# -*- coding: utf-8 -*-
# evaluation_service.py — REINTRODUCED CLEAN PIPELINE


import time


import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore
from PySide import QtWidgets  # 🔥 FIX: Importera för att rensa Qt-kön

from oba_rayengine.oba_intersect_mesh import _GLOBAL_MESH_CACHE
from oba_rayengine.oba_ray_core import OBARayManager
from oba_rayengine.oba_ray_engine import OBARayEngine

# from vendor_optuna.numpy._core.strings import count


from .spreadsheet_utils import apply_cad_params
from oba_objects.oba_base import _trigger_ray_engine

import numpy as np
from collections import defaultdict
from oba_rayengine.oba_ray_analyser import aggregate_interaction_clusters, get_emitted_power

# ------------------------------------------------------------
# EVALUATION SERVICE
# ------------------------------------------------------------


class EvaluationService(QtCore.QObject):
    """
    Bridge mellan:
        CAD params → Ray engine → Cluster extraction → Optuna worker
    """

    evaluationReady = QtCore.Signal(dict)
    statusChanged = QtCore.Signal(str)  # lblStatus i optimzer_dialog.py

    def __init__(self):
        super().__init__()
        self._busy = False
        # Komplett CAD-läge från när optimeringen startade.
        self._start_cad_params = None

        # Bästa score som hittills har accepterats.
        self._best_score = None

        # Params för bästa trail.
        self._best_trial_params = None

        # Antal EXTRA evalueringar när en trial kvalificerar för recheck.
        # 0 = funktionen avstängd.
        # 1 = första körningen + 1 recheck.
        self._recheck_count = 1

    # -------------------------------------------------------
    # APPLY BEST PARAMS (UI BUTTON)
    # -------------------------------------------------------

    @QtCore.Slot(dict)
    def applyBest(self, params: dict):
        doc = App.ActiveDocument
        if not doc:
            App.Console.PrintError("[Eval] No active document\n")
            return
        try:
            apply_cad_params(params)
            # recompute_doc(doc, restore_view=False)
            App.Console.PrintMessage("[Eval] Applied best parameters.\n")

        except Exception as e:
            App.Console.PrintError(f"[Eval] applyBest failed: {e}\n")

    # -------------------------------------------------------
    # MAIN EVALUATION ENTRY
    # -------------------------------------------------------

    @QtCore.Slot(dict)
    def evaluate(self, payload):
        """
        Huvudflöde för en trial.

        Recheck-logik:
            recheck_count = 0
                -> ingen recheck, första körningen används direkt.

            recheck_count = n > 0
                -> första körningen görs alltid.
                -> om första score är bättre än tidigare best körs n rechecks.
                -> scanner körs bara på första körningen.
                -> vanliga metrics medelvärdesbildas över alla körningar.
        """
        if self._busy:
            return

        self._busy = True

        try:
            doc = App.ActiveDocument
            if not doc:
                self.evaluationReady.emit(
                    {
                        "_pruned": True,
                        "error": "No active document",
                    }
                )
                return

            params = payload.get("params", {})
            unselected_params = payload.get("unselected_params", {})
            metrics = payload.get("metrics", [])
            trial_id = payload.get("trial_id", "?")

            # Antal extra körningar.
            # Kan skickas i payload, annars används inställningen från __init__.
            if "recheck_count" in payload:
                try:
                    recheck_count = max(0, int(payload.get("recheck_count", 0)))
                except (TypeError, ValueError):
                    recheck_count = self._recheck_count
            else:
                recheck_count = self._recheck_count

            # --------------------------------------------------
            # START CAD-LÄGE
            # --------------------------------------------------
            self._capture_start_cad_params(
                payload.get("start_cad_params"),
                params,
                unselected_params,
            )

            # --------------------------------------------------
            # 1. FÖRSTA EVALUERING
            # --------------------------------------------------
            result_1 = self._run_trial_evaluation(
                params=params,
                unselected_params=unselected_params,
                metrics=metrics,
                doc=doc,
                trial_id=trial_id,
            )

            if result_1 is None:
                return

            if result_1.get("_pruned", False):
                self.evaluationReady.emit(result_1)
                return

            results_1 = dict(result_1.get("results", {}))
            debug_1 = dict(result_1.get("debug", {}))

            # --------------------------------------------------
            # 2. DELA UPP METRICS
            # --------------------------------------------------
            normal_metrics, scanner_metrics = self._split_metrics(metrics)

            # --------------------------------------------------
            # 3. SCORE FÖR ATT AVGÖRA RECHECK
            #
            # Scanner ingår i score eftersom första körningen är
            # det faktiska trial-resultatet.
            # --------------------------------------------------
            score_1 = self._calculate_trial_score(results_1, metrics)

            should_recheck = recheck_count > 0 and (self._best_score is None or score_1 > self._best_score)

            # --------------------------------------------------
            # 4. DEFAULT: INGEN RECHECK
            # --------------------------------------------------
            if not should_recheck:
                final_results = dict(results_1)
                final_debug = dict(debug_1)
                final_debug["recheck"] = {
                    "enabled": recheck_count > 0,
                    "requested_count": recheck_count,
                    "performed_count": 0,
                    "score_1": score_1,
                    "reason": ("recheck_disabled" if recheck_count == 0 else "trial_not_better_than_best"),
                }

                # Första trialen måste fortfarande etablera best.
                if self._best_score is None:
                    self._best_score = score_1
                    self._best_trial_params = dict(params)

                self.evaluationReady.emit(
                    {
                        "results": final_results,
                        "_pruned": False,
                        "unselected_params": unselected_params,
                        "debug": final_debug,
                    }
                )
                return

            # --------------------------------------------------
            # 5. RECHECKS
            # --------------------------------------------------
            final_results, final_debug = self._run_rechecks(
                params=params,
                unselected_params=unselected_params,
                metrics=metrics,
                normal_metrics=normal_metrics,
                scanner_metrics=scanner_metrics,
                doc=doc,
                trial_id=trial_id,
                results_1=results_1,
                debug_1=debug_1,
                score_1=score_1,
                recheck_count=recheck_count,
            )

            if final_results is None:
                # _run_rechecks har redan skickat evaluationReady vid prune.
                return

            # --------------------------------------------------
            # 6. FINAL SCORE / BEST
            # --------------------------------------------------
            final_score = self._calculate_trial_score(final_results, metrics)

            final_debug.setdefault("recheck", {})
            final_debug["recheck"]["final_score"] = final_score

            self._best_score = final_score
            self._best_trial_params = dict(params)

            self.evaluationReady.emit(
                {
                    "results": final_results,
                    "_pruned": False,
                    "unselected_params": unselected_params,
                    "debug": final_debug,
                }
            )

        except Exception as e:
            App.Console.PrintError(f"[Eval] evaluate failed: {e}\\n")

            import traceback

            App.Console.PrintError(traceback.format_exc() + "\\n")

            self.evaluationReady.emit(
                {
                    "results": {},
                    "_pruned": True,
                    "error": str(e),
                }
            )

        finally:
            self._busy = False

    # -------------------------------------------------------
    # RECHECK CONFIGURATION
    # -------------------------------------------------------

    def set_recheck_count(self, count):
        """
        Sätter antal EXTRA körningar.

        Exempel:
            0 -> ingen recheck
            1 -> totalt 2 körningar
            2 -> totalt 3 körningar
            5 -> totalt 6 körningar
        """
        try:
            self._recheck_count = max(0, int(count))
        except (TypeError, ValueError):
            raise ValueError("recheck_count måste vara ett heltal >= 0")

    # Qt/Python-konvention för eventuell UI-kod som vill använda camelCase.
    def setRecheckCount(self, count):
        self.set_recheck_count(count)

    # -------------------------------------------------------
    # EVALUATION HELPERS
    # -------------------------------------------------------

    def _capture_start_cad_params(
        self,
        start_cad_params,
        params,
        unselected_params,
    ):
        """
        Sparar CAD-läget som skall användas som bas före varje recheck.

        Om start_cad_params skickas in används det.
        Annars byggs startläget upp en gång från unselected_params + params.
        """
        if start_cad_params:
            self._start_cad_params = dict(start_cad_params)
            return

        if self._start_cad_params is not None:
            return

        self._start_cad_params = {}

        if isinstance(unselected_params, dict):
            self._start_cad_params.update(unselected_params)

        if isinstance(params, dict):
            self._start_cad_params.update(params)

    def _split_metrics(self, metrics):
        """
        Delar metrics i:
            normal_metrics
            scanner_metrics

        Scanner är dyr och körs bara under första evalueringen.
        """
        normal_metrics = []
        scanner_metrics = []

        for metric in metrics:
            if not metric.get("active", True):
                continue

            if metric.get("base_metric") == "scanner":
                scanner_metrics.append(metric)
            else:
                normal_metrics.append(metric)

        return normal_metrics, scanner_metrics

    def _calculate_trial_score(self, results, metrics=None):
        """
        Beräknar jämförelsescore.

        Om metrics skickas in används direction:
            minimize -> värdet inverteras
            maximize/övrigt -> värdet används direkt

        Om metrics saknas används ett enkelt medelvärde för numeriska
        resultat. Detta behåller kompatibilitet med äldre anrop.
        """
        if metrics is None:
            values = [float(value) for value in results.values() if isinstance(value, (int, float, np.number))]
            if not values:
                return 0.0
            return sum(values) / len(values)

        values = []

        for metric in metrics:
            name = metric.get("name")
            value = results.get(name)

            if not isinstance(value, (int, float, np.number)):
                continue

            value = float(value)

            if metric.get("direction") == "minimize":
                value = -value

            values.append(value)

        if not values:
            return 0.0

        return sum(values) / len(values)

    def _run_rechecks(
        self,
        params,
        unselected_params,
        metrics,
        normal_metrics,
        scanner_metrics,
        doc,
        trial_id,
        results_1,
        debug_1,
        score_1,
        recheck_count,
    ):
        """
        Kör n extra evalueringar.

        Viktigt:
            - Scanner körs aldrig här.
            - Varje recheck börjar från _start_cad_params.
            - Trial-parametrarna appliceras därefter.
            - Varje recheck får sitt eget metric-resultat.
            - Slutresultatet för vanliga metrics är medelvärdet av
              första körningen + alla lyckade rechecks.
        """
        all_normal_results = [dict(results_1)]
        recheck_debug = []

        for recheck_index in range(1, recheck_count + 1):
            # --------------------------------------------------
            # A. ÅTERSTÄLL STARTLÄGET
            # --------------------------------------------------
            if self._start_cad_params:
                apply_cad_params(self._start_cad_params)
                # doc.recompute(None)
                doc.recompute()

            # --------------------------------------------------
            # B. APPLICERA AKTUELL TRIAL
            # --------------------------------------------------
            apply_cad_params(params)
            # doc.recompute(None)
            doc.recompute()

            # --------------------------------------------------
            # C. RAYTRACE
            # --------------------------------------------------
            self.statusChanged.emit(f"Trial {trial_id} → RECHECK {recheck_index}/{recheck_count}")

            _trigger_ray_engine(
                reason=f"optuna_recheck_{recheck_index}",
                source=None,
                force=True,
            )

            # --------------------------------------------------
            # D. HÄMTA CLUSTERS
            # --------------------------------------------------
            clusters = aggregate_interaction_clusters(
                mode="final",
                min_hits=1,
            )

            total_hits = sum(c.get("hit_count", 0) for c in clusters.values())

            scene_hash = OBARayManager().scene_hash()

            # --------------------------------------------------
            # E. KÖR VANLIGA METRICS
            #
            # Scanner hoppas över helt.
            # --------------------------------------------------
            recheck_results = {}
            recheck_pruned = False
            prune_metric = None

            for metric in normal_metrics:
                metric_name = metric.get("name", "?")

                self.statusChanged.emit(f"Trial {trial_id} → " f"RECHECK {recheck_index}/{recheck_count} " f"{metric.get('base_metric')} " f"({metric.get('plane', '')})")

                value, valid = self._evaluate_metric(
                    clusters,
                    metric,
                )

                recheck_results[metric_name] = value

                if not valid:
                    prune_metric = metric
                    recheck_pruned = True
                    print(f"[RECHECK PRUNE] " f"recheck={recheck_index}/{recheck_count} " f"metric='{metric_name}' " f"value={value}")
                    break

            # --------------------------------------------------
            # F. RECHECK PRUNE
            # --------------------------------------------------
            if recheck_pruned:
                final_debug = dict(debug_1)
                final_debug["recheck"] = {
                    "enabled": True,
                    "requested_count": recheck_count,
                    "performed_count": recheck_index,
                    "score_1": score_1,
                    "recheck_pruned": True,
                    "pruned_recheck": recheck_index,
                    "pruned_metric": (prune_metric.get("name") if prune_metric else None),
                    "cluster_count": len(clusters),
                    "total_hits": total_hits,
                    "scene_hash": scene_hash,
                    "rechecks": recheck_debug,
                }

                self.evaluationReady.emit(
                    {
                        "results": results_1,
                        "_pruned": True,
                        "unselected_params": unselected_params,
                        "debug": final_debug,
                    }
                )

                return None, None

            # --------------------------------------------------
            # G. SPARA RESULTAT FÖR MEDELVÄRDE
            # --------------------------------------------------
            all_normal_results.append(recheck_results)

            recheck_score = self._calculate_trial_score(
                recheck_results,
                normal_metrics,
            )

            recheck_debug.append(
                {
                    "index": recheck_index,
                    "cluster_count": len(clusters),
                    "total_hits": total_hits,
                    "scene_hash": scene_hash,
                    "score": recheck_score,
                    "normal_metrics": list(recheck_results.keys()),
                }
            )

        # ------------------------------------------------------
        # H. BYGG FINAL RESULTS
        # ------------------------------------------------------
        final_results = dict(results_1)

        for metric in normal_metrics:
            metric_name = metric.get("name")

            values = []
            for result_set in all_normal_results:
                value = result_set.get(metric_name)

                if isinstance(value, (int, float, np.number)):
                    values.append(float(value))

            if values:
                final_results[metric_name] = sum(values) / len(values)

        # Scanner kördes bara första gången.
        for metric in scanner_metrics:
            metric_name = metric.get("name")

            if metric_name in results_1:
                final_results[metric_name] = results_1[metric_name]

        # ------------------------------------------------------
        # I. DEBUG
        # ------------------------------------------------------
        final_debug = dict(debug_1)
        final_debug["recheck"] = {
            "enabled": True,
            "requested_count": recheck_count,
            "performed_count": recheck_count,
            "recheck_pruned": False,
            "score_1": score_1,
            "normal_metrics_rechecked": [metric.get("name") for metric in normal_metrics],
            "scanner_metrics_rechecked": [],
            "rechecks": recheck_debug,
        }

        return final_results, final_debug

    def _run_trial_evaluation(self, params, unselected_params, metrics, doc, trial_id):

        # --------------------------------------------------
        # APPLY CAD PARAMS
        # --------------------------------------------------
        apply_cad_params(params)
        # doc.recompute(None)
        doc.recompute()
        # --------------------------------------------------
        # RAYTRACE
        # --------------------------------------------------
        _trigger_ray_engine(reason="optuna", source=None, force=True)
        # --------------------------------------------------
        # CLUSTERS
        # --------------------------------------------------
        clusters = aggregate_interaction_clusters(mode="final", min_hits=1)
        total_hits = sum(c.get("hit_count", 0) for c in clusters.values())
        scene_hash = OBARayManager().scene_hash()
        # --------------------------------------------------
        # DEBUG
        # --------------------------------------------------
        debug_info = {
            "cluster_count": len(clusters),
            "total_hits": total_hits,
            "scene_hash": scene_hash,
        }
        results = {}
        # --------------------------------------------------
        # 1. VANLIGA METRICS
        # --------------------------------------------------
        for m in metrics:
            if not m.get("active", True):
                continue

            if m.get("base_metric") == "scanner":
                continue

            self.statusChanged.emit(f"Trial {trial_id} → " f"{m.get('base_metric')} " f"({m.get('plane', '')})")
            value, valid = self._evaluate_metric(clusters, m)
            results[m["name"]] = value
            # --------------------------------------------------
            # EARLY PRUNE
            # --------------------------------------------------
            if not valid:
                print(f"[PRUNE] " f"metric='{m['name']}' " f"base={m.get('base_metric')} " f"value={value} " f"threshold=" f"{self._debug_threshold_info(m)}")
                return {
                    "results": results,
                    "_pruned": True,
                    "unselected_params": unselected_params,
                    "debug": debug_info,
                }

        # --------------------------------------------------
        # 2. SCANNER METRICS
        #
        # Scanner körs här EN gång.
        # Recheck-funktionen kör ALDRIG scanner igen.
        # --------------------------------------------------

        for m in metrics:
            if not m.get("active", True):
                continue

            if m.get("base_metric") != "scanner":
                continue

            targets = m.get("targets", [])
            label_map = self._build_label_to_name_map()
            target_names = [label_map.get(target, target) for target in targets]

            filtered = {key: cluster for key, cluster in clusters.items() if cluster.get("object") in target_names}

            value = metric_scanner(m, filtered, m.get("plane", "XY"), {"doc": doc})

            results[m["name"]] = value
            self.statusChanged.emit(f"Trial {trial_id} → " f"SCANNER score: " f"({value}) " f"Targets: " f"({targets}) " f"Step_id: " f"{m.get('step_id')}")

        # --------------------------------------------------
        # RETURN
        # --------------------------------------------------

        return {"results": results, "_pruned": False, "unselected_params": unselected_params, "debug": debug_info}

    # def _average_result_dicts(self, results_1, results_2):
    #     merged = {}
    #     for key, value_1 in results_1.items():
    #         value_2 = results_2.get(key, value_1)
    #         if isinstance(value_1, (int, float, np.number)) and isinstance(value_2, (int, float, np.number)):
    #             merged[key] = (float(value_1) + float(value_2)) / 2.0
    #         else:
    #             merged[key] = value_1
    #     return merged

    def _calculate_trial_score(self, results):
        values = [float(v) for v in results.values() if isinstance(v, (int, float, np.number))]
        if not values:
            return 0.0
        return sum(values) / len(values)

    # -------------------------------------------------------
    # PROJECTION HELPERS
    # -------------------------------------------------------

    def _project_points(self, points, plane):

        if plane == "XY":
            return points[:, [0, 1]]
        elif plane == "XZ":
            return points[:, [0, 2]]
        elif plane == "YZ":
            return points[:, [1, 2]]

        return points[:, [0, 1]]

    def _build_label_to_name_map(self):
        doc = App.ActiveDocument
        mapping = {}
        for obj in doc.Objects:
            if hasattr(obj, "OpticalType"):
                mapping[obj.Label] = obj.Name
        return mapping

    def _evaluate_metric(self, clusters, metric):

        base = metric["base_metric"]
        plane = metric.get("plane")
        targets = metric.get("targets", [])

        label_map = self._build_label_to_name_map()
        target_names = [label_map.get(t, t) for t in targets]

        filtered = {k: c for k, c in clusters.items() if c.get("object") in target_names}
        # filtered = {k: c for k, c in clusters.items() if c.get("object") in targets}
        valid = True

        # ----------------------------------
        # DISPATCH + THRESHOLD (tillsammans)
        # ----------------------------------

        if base == "power":
            value, ratio = compute_power(filtered, target_names)
            if metric.get("use_threshold"):
                valid = ratio >= metric.get("percent", 0.0)

        elif base == "target_cluster_count":
            value, diff = compute_target_cluster_count(filtered, target_names, metric.get("percent", 0.01), metric.get("value", 3))
            if metric.get("use_threshold"):
                valid = diff == 0

        elif base == "hit_count":
            value, ratio = compute_hit_count(filtered, target_names)
            if metric.get("use_threshold"):
                valid = ratio >= metric.get("percent", 0.0)

        elif base == "density":
            value = compute_density(filtered, plane, metric.get("bounce", 0))

        elif base == "roundness":
            value = compute_roundness(filtered, plane, metric.get("bounce", 0))

        elif base == "equal_distance":
            value = compute_distance(filtered, plane)

        elif base == "cluster_position_matching":
            value = compute_cluster_position_matching(filtered, metric.get("axis"))

        elif base == "cluster_origin_centering":
            value = compute_cluster_origin_centering(filtered, metric.get("axis"), metric.get("bounce", 1))

        elif base == "target_face_centering":
            value = compute_target_face_centering(filtered, metric.get("bounce", 0))

        else:
            App.Console.PrintError(f"[evaluation_service] Unknown base metric: {base}\n")
            value = 0.0

        return value, valid


def _is_model_valid(doc):
    for obj in doc.Objects:
        # 1. Kontrollera skisser
        if obj.TypeId == "Sketcher::SketchObject":
            # obj.solve()
            # Hämtar DoF (standard 0 om det mot förmodan saknas)
            dof = getattr(obj, "DoF", 0)
            if dof < 0:
                print("[FAIL] negative DOF (over-constrained):", obj.Name)
                return False
            # Hämtar externa referenser säkert
            ext_geo = getattr(obj, "ExternalGeometry", [])
            for ext in ext_geo:
                if ext is None:
                    print("[FAIL] missing external ref:", obj.Name)
                    return False
        # 2. Kontrollera geometri (endast objekt som faktiskt har en Shape)
        # if hasattr(obj, "Shape"):
        if obj.TypeId.startswith("PartDesign::"):
            shape = obj.Shape
            if not shape or shape.isNull():
                print("[FAIL] null shape:", obj.Name)
                return False
            if shape.ShapeType == "Solid" and len(shape.Faces) == 0:
                print("[FAIL] no faces:", obj.Name)
                return False
        # 3. Kontrollera FreeCADs inbyggda felsignaler
        if "Invalid" in obj.State:
            print("[FAIL] state:", obj.Name, obj.State)
            return False
        # Hämtar ErrorStatus säkert (returnerar tom sträng om attributet saknas)
        if hasattr(obj, "ErrorStatus"):
            try:
                error_status = obj.ErrorStatus
            except Exception as e:
                print("[API WARN] ErrorStatus access failed:", obj.Name, e)
                error_status = None
            if error_status and error_status != "OK":
                print("[FAIL] error status:", obj.Name, error_status)
                return False
    return True


def compute_power(clusters, targets=None):

    if not clusters:
        return 0.0, 0.0
    current = sum(c.get("power", {}).get("in", 0.0) for c in clusters.values())
    emitted_power, emitted_rays = get_emitted_power()
    if emitted_power <= 1e-12:
        return 0.0, 0.0

    ratio = current / emitted_power
    return ratio, ratio


def compute_hit_count(clusters, targets=None):
    if not clusters:
        return 0.0, 0.0

    current = sum(c.get("hit_count", 0) for c in clusters.values())
    emitted_power, emitted_rays = get_emitted_power()
    if emitted_rays <= 0:
        return float(current), 0.0
    ratio = current / emitted_rays
    return float(current), ratio


def compute_target_face_centering(clusters, bounce_count=0):
    if not clusters:
        return 0.0
    scores = []
    weights = []
    for c in clusters.values():
        if bounce_count > 0 and c.get("bounce") != bounce_count:
            continue
        centroid = c.get("centroid", {}).get("3D")
        target_center = c.get("target_center")
        if centroid is None or target_center is None:
            continue

        cx, cy, cz = centroid
        tx, ty, tz = target_center

        d = np.sqrt((cx - tx) ** 2 + (cy - ty) ** 2 + (cz - tz) ** 2)
        hit_count = c.get("hit_count", 1)
        # score = 1.0 / (1.0 + d)

        radius = c["spread"]["3D"]["radius"]
        score = 1.0 / (1.0 + d / (radius + 1e-6))  # mjukare score : hur långt från target-centret klustret ligger relativt sin egen storlek

        scores.append(score * hit_count)
        weights.append(hit_count)
    if not weights:
        return 0.0
    return sum(scores) / sum(weights)


def compute_target_cluster_count(clusters, targets, min_percent, target):
    """
    min_percent:
        Minsta andel av emitterade rays som ett kluster
        måste innehålla för att räknas.

    target:
        Önskat antal kluster.
    """

    if not clusters:
        return 0.0, float(target)

    emitted_power, emitted_rays = get_emitted_power()

    if emitted_rays <= 0:
        return 0.0, float(target)

    cluster_count = 0

    for c in clusters.values():
        if c.get("object") not in targets:
            continue
        hits = c.get("hit_count", 0)
        ratio = hits / float(emitted_rays)
        if ratio >= min_percent:
            cluster_count += 1

    diff = abs(cluster_count - target)
    score = 1.0 / (1.0 + diff)
    return score, diff


def compute_distance(clusters, plane):

    if not clusters:
        return 0.0

    vals = []

    for c in clusters.values():

        if plane == "3D":
            r = c.get("spread", {}).get("3D", {}).get("radius")
        else:
            cov = c.get("spread", {}).get(plane, {}).get("cov")
            if cov is None:
                continue

            try:
                import numpy as np

                eig = np.linalg.eigvals(cov)
                r = float(max(eig)) ** 0.5
            except:
                continue

        if r is None:
            continue

        # ✅ bättre scaling
        score = 1.0 / (1.0 + r * 10.0)
        vals.append(score)

    if not vals:
        return 0.0

    return sum(vals) / len(vals)


def metric_scanner(metric, filtered_clusters, plane, context):
    from oba_scanner.scan_db import HitsDB
    from oba_scanner.batch_runner import run_steps_for_batch, find_batch_object, find_step_by_id
    from oba_rayengine.oba_ray_analyser import get_emitted_power
    import numpy as np

    doc = context["doc"]
    step_id = metric.get("step_id")
    radius = metric.get("radius", 0.2)

    if not step_id:
        return 0.0

    emitted_power, emitted_rays = get_emitted_power()

    # print("[SCANNER]", "emitted_power=", emitted_power, "emitted_rays=", emitted_rays)

    if emitted_power <= 1e-12:
        print("[SCANNER]", "No emitted rays found, returning 0.0. Total emitted_power=", emitted_power, "and emitted_rays=", emitted_rays)
        return 0.0

    db = HitsDB()

    targets = list({c.get("object") for c in filtered_clusters.values()})
    if not targets:
        return 0.0

    batch = find_batch_object(doc)
    if not batch:
        return 0.0

    step = find_step_by_id(doc, step_id)
    if not step:
        return 0.0

    class Dummy:
        def setValue(self, v):
            pass

        def setRange(self, a, b):
            pass

        def setText(self, t):
            pass

    # --------------------------------------------------
    # Kör scanner
    # --------------------------------------------------

    db.clear_step(step_id)

    run_steps_for_batch(
        batch=batch,
        prog_bar=Dummy(),
        status_lbl=Dummy(),
        pump_events_func=lambda: None,
        stop_flag_func=lambda: False,
        only_step_id=step_id,
    )

    QtCore.QCoreApplication.processEvents()

    # --------------------------------------------------
    # Läs scanner-grid
    # --------------------------------------------------

    X_all = []
    Y_all = []
    Z_all = []
    V_all = []

    for tgt in targets:

        for em in db.list_emitters(tgt):
            X, Y, Z, H, PIN, _, _ = db.read_grid(tgt, em, step_id)
            if not X:
                continue

            X_all.extend(X)
            Y_all.extend(Y)
            Z_all.extend(Z)

            # power på målobjektet
            V_all.extend(PIN)

    if not V_all:
        return 0.0

    X = np.asarray(X_all, dtype=float)
    Y = np.asarray(Y_all, dtype=float)
    Z = np.asarray(Z_all, dtype=float)
    V = np.asarray(V_all, dtype=float)

    # --------------------------------------------------
    # Välj projektionsplan
    # --------------------------------------------------

    if plane == "XY":
        A = X
        B = Y

    elif plane == "XZ":
        A = X
        B = Z

    elif plane == "YZ":
        A = Y
        B = Z

    else:
        A = X
        B = Y

    # --------------------------------------------------
    # Mätområde runt origo
    # --------------------------------------------------

    dist = np.sqrt(A * A + B * B)

    inside = dist <= radius

    if not np.any(inside):
        return 0.0

    # --------------------------------------------------
    # Effekt inom mätområdet
    # --------------------------------------------------

    power_inside = float(np.sum(V[inside]))

    # --------------------------------------------------
    # Normalisera mot emitterad effekt
    # --------------------------------------------------

    # print("GRID POWER =", np.sum(V))
    # print("EMITTED POWER =", emitted_power)

    score = power_inside / emitted_power

    # print(
    #     "[SCANNER]",
    #     "power_inside=",
    #     power_inside,
    #     "emitted_power=",
    #     emitted_power,
    #     "score=",
    #     score,
    # )
    # print("radius=", radius)
    # print("inside cells=", np.count_nonzero(inside))
    # print("all cells=", len(V))

    # print("avg power per cell =", np.sum(V) / len(V))

    return score


def compute_cluster_position_matching(clusters, axis):

    if not clusters or not axis:
        return 0.0
    vals = []
    for c in clusters.values():
        centroid = c.get("centroid", {}).get("3D")
        if centroid is None:
            continue
        x, y, z = centroid
        if axis == "X":
            vals.append(x)
        elif axis == "Y":
            vals.append(y)
        elif axis == "Z":
            vals.append(z)
        elif axis == "XY":
            vals.append(np.sqrt(x * x + y * y))
        elif axis == "XZ":
            vals.append(np.sqrt(x * x + z * z))
        elif axis == "YZ":
            vals.append(np.sqrt(y * y + z * z))
        elif axis == "XYZ":
            vals.append(np.sqrt(x * x + y * y + z * z))
    if len(vals) < 2:
        return 0.0
    # låg spridning = klustren ligger på samma position
    std = np.std(vals)
    score = 1.0 / (1.0 + std)
    return score


def compute_cluster_origin_centering(clusters, axis, bounce_index=1):

    selected = [c for c in clusters.values() if c.get("bounce") == bounce_index]

    if not clusters or not axis:
        return 0.0

    if not selected:
        return 0.0

    scores = []
    weights = []

    for c in selected:

        centroid = c.get("centroid", {}).get("3D")
        if centroid is None:
            continue

        x, y, z = centroid

        if axis == "X":
            d = abs(x)

        elif axis == "Y":
            d = abs(y)

        elif axis == "Z":
            d = abs(z)

        elif axis == "XY":
            d = np.sqrt(x * x + y * y)

        elif axis == "XZ":
            d = np.sqrt(x * x + z * z)

        elif axis == "YZ":
            d = np.sqrt(y * y + z * z)

        elif axis == "XYZ":
            d = np.sqrt(x * x + y * y + z * z)

        else:
            continue

        hit_count = c.get("hit_count", 1)

        score = 1.0 / (1.0 + d)

        scores.append(score * hit_count)
        weights.append(hit_count)

    if not weights:
        return 0.0

    return sum(scores) / sum(weights)


def compute_density(clusters, plane, bounce_count=0):
    if not clusters:
        return 0.0
    vals = []
    weights = []
    for c in clusters.values():
        if bounce_count > 0 and c.get("bounce") != bounce_count:
            continue
        raw = c.get("density", {}).get(plane)
        w = c.get("hit_count", 1)

        if raw is not None:
            vals.append(raw * w)
            weights.append(w)

    if not vals:
        return 0.0

    return sum(vals) / sum(weights)


def compute_roundness(clusters, plane, bounce_count=0):
    if not clusters:
        return 0.0
    vals = []
    for c in clusters.values():
        if bounce_count > 0 and c.get("bounce") != bounce_count:
            continue
        r = c.get("roundness", {}).get(plane)
        if r is not None:
            vals.append(r)
    if not vals:
        return 0.0
    return sum(vals) / len(vals)
