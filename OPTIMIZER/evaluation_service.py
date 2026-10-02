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


from .spreadsheet_utils import apply_cad_params, get_param_info, SPREADSHEET_NAME

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

            #
            # recompute_doc(doc, restore_view=False)
            App.Console.PrintMessage("[Eval] Applied best parameters.\n")

        except Exception as e:
            App.Console.PrintError(f"[Eval] applyBest failed: {e}\n")

    def _get_clusters(self, params):
        if self.use_ml:
            pass
            # return ml_predict_clusters(params)  # placeholder for machine leatning
        # _trigger_ray_engine(...)

        return aggregate_interaction_clusters(mode="final", min_hits=1)

    # -------------------------------------------------------
    # MAIN EVALUATION ENTRY
    # -------------------------------------------------------

    @QtCore.Slot(dict)
    def evaluate(self, payload):
        if self._busy:
            return
        self._busy = True

        try:
            doc = App.ActiveDocument
            if not doc:
                self.evaluationReady.emit({"_pruned": True, "error": "No active document"})
                return

            params = payload.get("params", {})
            unselected_params = payload.get("unselected_params", {})
            metrics = payload.get("metrics", [])
            trial_id = payload.get("trial_id", "?")
            # --------------------------------------------------
            # START CAD-LÄGE
            #
            # Detta sparas EN gång och används som bas vid
            # eventuell recheck.
            # --------------------------------------------------
            start_cad_params = payload.get("start_cad_params")
            if start_cad_params:
                self._start_cad_params = dict(start_cad_params)

            elif self._start_cad_params is None:
                self._start_cad_params = {}
                if isinstance(unselected_params, dict):
                    self._start_cad_params.update(unselected_params)

                if isinstance(params, dict):
                    self._start_cad_params.update(params)
            # --------------------------------------------------
            # 1. FÖRSTA EVALUERING
            # --------------------------------------------------
            result_1 = self._run_trial_evaluation(params=params, unselected_params=unselected_params, metrics=metrics, doc=doc, trial_id=trial_id)

            if result_1 is None:
                return

            if result_1.get("_pruned", False):
                self.evaluationReady.emit(result_1)
                return

            results_1 = dict(result_1.get("results", {}))
            debug_1 = dict(result_1.get("debug", {}))
            constraints_1 = dict(result_1.get("constraints", {}))

            # --------------------------------------------------
            # 2. DELA UPP METRICS
            #
            # Scanner är dyr och skall endast köras EN gång.
            # --------------------------------------------------
            normal_metrics = []
            scanner_metrics = []

            for m in metrics:
                if not m.get("active", True):
                    continue
                if m.get("base_metric") == "scanner":
                    scanner_metrics.append(m)
                else:
                    normal_metrics.append(m)
            # --------------------------------------------------
            # 3. SCORE FÖR ATT AVGÖRA RECHECK
            #
            # Scanner räknas med i första score eftersom det är
            # det faktiska trial-resultatet som Optuna annars
            # skulle ha fått.
            #
            # Detta score används ENDAST för att avgöra om en
            # extra körning skall göras.
            # --------------------------------------------------
            score_values_1 = []
            for m in metrics:
                name = m.get("name")
                direction = m.get("direction")
                value = results_1.get(name)
                if isinstance(value, (int, float, np.number)):
                    if direction == "minimize":  # tar hänsyn till riktning
                        score_values_1.append(-float(value))
                    else:
                        score_values_1.append(float(value))

            if score_values_1:
                score_1 = sum(score_values_1) / len(score_values_1)
            else:
                score_1 = 0.0

            # --------------------------------------------------
            # 4. AVGÖR OM RECHECK SKALL GÖRAS
            # --------------------------------------------------
            should_recheck = self._best_score is None or score_1 > self._best_score
            # --------------------------------------------------
            # DEFAULT:
            #
            # Om ingen recheck görs används resultat 1 direkt.
            # Scanner-resultatet ligger alltså kvar precis som
            # det beräknades.
            # --------------------------------------------------
            final_results = dict(results_1)
            final_constraints = dict(constraints_1)

            final_debug = dict(debug_1)
            score_2 = None
            # --------------------------------------------------
            # 5. RECHECK
            # --------------------------------------------------
            if should_recheck:
                # print(f"[RECHECK] " f"Trial {trial_id} " f"score={score_1:.8f} " f"best={self._best_score}")
                # --------------------------------------------------
                # 5A. ÅTERSTÄLL STARTLÄGET
                # --------------------------------------------------
                if self._start_cad_params:
                    apply_cad_params(self._start_cad_params)
                    doc.recompute()
                    # doc.recompute(None)
                # --------------------------------------------------
                # 5B. APPLICERA AKTUELL TRIAL
                # --------------------------------------------------
                apply_cad_params(params)
                doc.recompute()
                # doc.recompute(None)
                # --------------------------------------------------
                # 5C. RAYTRACE
                # --------------------------------------------------
                _trigger_ray_engine(reason="optuna_recheck", source=None, force=True)
                # --------------------------------------------------
                # 5D. HÄMTA CLUSTERS
                # --------------------------------------------------
                clusters_2 = aggregate_interaction_clusters(mode="final", min_hits=1)
                total_hits_2 = sum(c.get("hit_count", 0) for c in clusters_2.values())
                scene_hash_2 = OBARayManager().scene_hash()
                # --------------------------------------------------
                # 5E. KÖR ENDAST BILLIGA METRICS IGEN
                #
                # SCANNER SKALL INTE KÖRAS IGEN.
                # --------------------------------------------------
                recheck_results = {}
                recheck_constraints = {}
                recheck_pruned = False
                for m in normal_metrics:
                    metric_name = m.get("name", "?")
                    self.statusChanged.emit(f"Trial {trial_id} → " f"RECHECK {m.get('base_metric')} " f"({m.get('plane', '')})")
                    value, valid, constraint = self._evaluate_metric(clusters_2, m)
                    recheck_results[metric_name] = value
                    recheck_constraints[metric_name] = constraint

                    if constraint > 0:
                        # if not valid:
                        print(f"[RECHECK PRUNE] " f"metric='{metric_name}' " f"value={value}")
                        recheck_pruned = True
                        break
                # --------------------------------------------------
                # 5F. OM RECHECKENS VANLIGA METRIC MISSlyCKAS
                # --------------------------------------------------
                if recheck_pruned:
                    self.evaluationReady.emit(
                        {
                            "results": results_1,
                            "constraints": recheck_constraints,
                            "_pruned": True,
                            "unselected_params": unselected_params,
                            "debug": {
                                **debug_1,
                                "recheck": {
                                    "score_1": score_1,
                                    "recheck_pruned": True,
                                    "cluster_count": len(clusters_2),
                                    "total_hits": total_hits_2,
                                    "scene_hash": scene_hash_2,
                                },
                            },
                        }
                    )
                    return

                # --------------------------------------------------
                # 5G. MEDELVÄRDE PER METRIC
                #
                # Vanliga metrics:
                #
                #     (run1 + run2) / 2
                #
                # Scanner:
                #
                #     run1
                #
                # eftersom scanner endast körs en gång.
                # --------------------------------------------------

                for m in normal_metrics:
                    metric_name = m.get("name")
                    value_1 = results_1.get(metric_name)
                    value_2 = recheck_results.get(metric_name)

                    if isinstance(value_1, (int, float, np.number)) and isinstance(value_2, (int, float, np.number)):
                        final_results[metric_name] = (float(value_1) + float(value_2)) / 2.0
                # --------------------------------------------------
                # SCANNER:
                #
                # Behåll värdet från första körningen.
                # Ingen andra scanner-körning.
                # --------------------------------------------------
                for m in scanner_metrics:
                    metric_name = m.get("name")
                    if metric_name in results_1:
                        final_results[metric_name] = results_1[metric_name]
                # --------------------------------------------------
                # 5H. DEBUG
                # --------------------------------------------------

                final_debug["recheck"] = {
                    "score_1": score_1,
                    "cluster_count": len(clusters_2),
                    "total_hits": total_hits_2,
                    "scene_hash": scene_hash_2,
                    "normal_metrics_rechecked": [m.get("name") for m in normal_metrics],
                    "scanner_metrics_rechecked": [],
                }
                # --------------------------------------------------
                # 5I. FINAL SCORE
                #
                # Detta är endast för vår interna
                # "bättre än tidigare"-jämförelse.
                # --------------------------------------------------
                final_score_values = []
                for m in metrics:
                    metric_name = m.get("name")
                    value = final_results.get(metric_name)
                    if isinstance(
                        value,
                        (
                            int,
                            float,
                            np.number,
                        ),
                    ):
                        final_score_values.append(float(value))
                if final_score_values:
                    final_score = sum(final_score_values) / len(final_score_values)
                else:
                    final_score = 0.0
                final_debug["recheck"]["score_2"] = self._calculate_trial_score(recheck_results)
                final_debug["recheck"]["final_score"] = final_score
                # --------------------------------------------------
                # UPPDATERA BEST EFTER RECHECK
                # --------------------------------------------------
                self._best_score = final_score
                self._best_trial_params = dict(params)
                print(f"[RECHECK] " f"trial={trial_id} " f"score1={score_1:.8f} " f"score2={final_debug['recheck']['score_2']:.8f} " f"final={final_score:.8f} " f"clusters={len(clusters_2)} " f"hits={total_hits_2}")

                for name in final_constraints:
                    c1 = constraints_1.get(name, 0.0)
                    c2 = recheck_constraints.get(name, c1)
                    final_constraints[name] = max(float(c1), float(c2))
            else:
                # --------------------------------------------------
                # INGEN RECHECK
                # --------------------------------------------------
                # print(f"[NO RECHECK] " f"Trial {trial_id} " f"score={score_1:.8f} " f"best={self._best_score}")
                # --------------------------------------------------
                # Om detta är första trialen måste best sättas.
                # --------------------------------------------------
                if self._best_score is None:
                    self._best_score = score_1
                    self._best_trial_params = dict(params)

            # --------------------------------------------------
            # 6. RETURNERA RESULTAT TILL WORKER
            # --------------------------------------------------
            self.evaluationReady.emit(
                {"results": final_results, "constraints": final_constraints, "_pruned": False, "unselected_params": unselected_params, "debug": final_debug},
            )

        except Exception as e:
            App.Console.PrintError(f"[Eval] evaluate failed: {e}\n")
            import traceback

            App.Console.PrintError(traceback.format_exc() + "\n")
            self.evaluationReady.emit({"results": {}, "_pruned": True, "error": str(e)})
        finally:
            self._busy = False

    def _debug_threshold_info(self, metric):
        if not metric.get("use_threshold"):
            return "disabled"
        base = metric.get("base_metric")
        if base in ("power", "hit_count"):
            return f">= {metric.get('percent', 0.0):.3f}"
        if base == "target_cluster_count":
            return f"count≈{metric.get('value')} " f"filter>={metric.get('percent', 0.0):.3f}"
        return "enabled"

    def _run_trial_evaluation(self, params, unselected_params, metrics, doc, trial_id):

        # --------------------------------------------------
        # APPLY CAD PARAMS
        # --------------------------------------------------
        apply_cad_params(params)

        doc.recompute()

        # doc.recompute(None)
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
        constraints = {}
        # --------------------------------------------------
        # 1. VANLIGA METRICS
        # --------------------------------------------------
        for m in metrics:
            if not m.get("active", True):
                continue

            if m.get("base_metric") == "scanner":
                continue

            self.statusChanged.emit(f"Trial {trial_id} → " f"{m.get('base_metric')} " f"({m.get('plane', '')})")
            value, valid, constraint = self._evaluate_metric(clusters, m)
            results[m["name"]] = value
            constraints[m["name"]] = constraint

            # --------------------------------------------------
            # EARLY PRUNE
            # --------------------------------------------------
            if constraint > 0:
                # if not valid:
                print(f"[PRUNE] " f"metric='{m['name']}' " f"base={m.get('base_metric')} " f"value={value} " f"threshold=" f"{self._debug_threshold_info(m)}")
                return {
                    "results": results,
                    "constraints": constraints,
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
            constraints[m["name"]] = 0.0
            self.statusChanged.emit(f"Trial {trial_id} → " f"SCANNER score: " f"({value}) " f"Targets: " f"({targets}) " f"Step_id: " f"{m.get('step_id')}")

        return {"results": results, "constraints": constraints, "_pruned": False, "unselected_params": unselected_params, "debug": debug_info}

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
        # print("---- metric ----", metric)
        base = metric["base_metric"]
        plane = metric.get("plane")
        targets = metric.get("targets", [])

        label_map = self._build_label_to_name_map()
        target_names = [label_map.get(t, t) for t in targets]

        filtered = {k: c for k, c in clusters.items() if c.get("object") in target_names}
        # filtered = {k: c for k, c in clusters.items() if c.get("object") in targets}
        valid = True
        constraint = 0
        # ----------------------------------
        # DISPATCH + THRESHOLD (tillsammans)
        # ----------------------------------

        if base == "power":
            value, ratio = compute_power(filtered, target_names)
            constraint = 0.0
            if metric.get("use_threshold"):
                threshold = metric.get("percent", 0.0)
                # valid = ratio >= threshold  # 1 metric.get("percent", 0.0)
                # constraint = threshold - ratio
                constraint = threshold - ratio
                # print("power=", ratio, "threshold=", threshold, "constraint=", constraint)

        elif base == "target_cluster_count":
            value, diff = compute_target_cluster_count(filtered, target_names, metric.get("percent", 0.01), metric.get("value", 3))
            if metric.get("use_threshold"):
                # valid = diff == 0
                constraint = float(diff)

        elif base == "hit_count":
            value, ratio = compute_hit_count(filtered, target_names)
            if metric.get("use_threshold"):
                threshold = metric.get("percent", 0.0)
                # valid = ratio >= threshold  # metric.get("percent", 0.0)
                # constraint = threshold - ratio
                constraint = threshold - ratio

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

        elif base == "preserve_parameter":

            value = compute_preserve_parameter(
                metric.get("parameters", []),
                metric.get("tolerance", 0.10),
            )

        else:
            App.Console.PrintError(f"[evaluation_service] Unknown base metric: {base}\n")
            value = 0.0

        return value, valid, constraint


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
            # WX, WY, WZ, X, Y, Z, H, PIN, POUT, MOVE_OBJECT, MOVED_OBJECTS
            WX, WY, WZ, X, Y, Z, H, PIN, POUT, MOVE_OBJECT, MOVED_OBJECTS = db.read_grid(tgt, em, step_id)
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


def compute_preserve_parameter(parameters, tolerance):
    if not parameters:
        return 0.0

    doc = App.ActiveDocument
    if not doc:
        return 0.0
    ss = doc.getObject(SPREADSHEET_NAME)
    if not ss:
        return 0.0
    param_names = [p["name"] for p in parameters]
    current_info = get_param_info(ss, param_names)

    scores = []
    for p in parameters:
        name = p["name"]
        start_value = p["value"]

        current = current_info.get(name)
        if not current:
            continue
        current_value = current["value"]
        # print("[values]", current_value, start_value)
        if abs(start_value) < 1e-12:
            deviation = abs(current_value - start_value)
        else:
            deviation = abs(current_value - start_value) / abs(start_value)
        score = 1.0 / (1.0 + deviation / max(tolerance, 1e-9))
        scores.append(score)
    if not scores:
        return 0.0

    return sum(scores) / len(scores)
