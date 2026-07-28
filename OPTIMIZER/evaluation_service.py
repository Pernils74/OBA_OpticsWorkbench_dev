# -*- coding: utf-8 -*-
# evaluation_service.py — REINTRODUCED CLEAN PIPELINE

from pydoc import doc

import FreeCAD as App
from PySide import QtCore
from .spreadsheet_utils import apply_cad_params
from oba_objects.oba_base import _trigger_ray_engine

import numpy as np
from collections import defaultdict
from oba_rayengine.oba_ray_analyser import aggregate_interaction_clusters

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
        if self._busy:
            return
        self._busy = True

        doc = App.ActiveDocument
        if not doc:
            self.evaluationReady.emit({"_pruned": True})
            return

        params = payload.get("params", {})
        metrics = payload.get("metrics", [])
        baseline = payload.get("baseline", None)
        if baseline is None:
            print("[WARN] baseline is None")

        # -------------------------
        # APPLY CAD
        # -------------------------
        if params:
            # print(f"[evaluation_service] DEBUG: Applying params: {params}")
            apply_cad_params(params)
            doc.recompute()
            _trigger_ray_engine(reason="optuna", source=None, force=True)

        # -------------------------
        # CLUSTERS
        # -------------------------
        clusters = aggregate_interaction_clusters(mode="final", min_hits=1)
        # print(f"[evaluation_service] DEBUG: Collected {len(clusters)} clusters")

        results = {}
        pruned = False

        # -------------------------
        # FAST METRICS (NO SCANNER)
        # -------------------------
        trial_id = payload.get("trial_id", "?")
        for m in metrics:
            self.statusChanged.emit(f"Trial {trial_id} → {m['base_metric']} ({m['plane']})")  # set lblStaus in optimizer_dialog.py

            if m["base_metric"] == "scanner":
                continue  # kör senare

            value, valid = self._evaluate_metric(clusters, m, baseline)

            results[m["name"]] = value
            # print(f"[METRIC] {m['name']} " f"value={value} " f"valid={valid}")

            # ✅ early pruning
            if not valid:
                print(f"[PRUNE] metric='{m['name']}' " f"base={m['base_metric']} " f"value={value} " f"threshold={self._debug_threshold_info(m)}")
                pruned = True
                break

        # -------------------------
        # EARLY EXIT
        # -------------------------
        if pruned:
            # results["_prune_info"] = {"metric": m["name"], "base": m["base_metric"], "value": value}
            self.evaluationReady.emit({"results": results, "_pruned": True})
            return

        # -------------------------
        # SCANNER METRICS (EXPENSIVE)
        # -------------------------
        for m in metrics:
            if m["base_metric"] != "scanner":
                continue
            targets = m.get("targets", [])
            # filtered = {k: c for k, c in clusters.items() if c.get("object") in targets}

            label_map = self._build_label_to_name_map()
            target_names = [label_map.get(t, t) for t in targets]

            filtered = {k: c for k, c in clusters.items() if c.get("object") in target_names}
            value = metric_scanner(m, filtered, m["plane"], {"doc": doc})

            results[m["name"]] = value

            self.statusChanged.emit(f"Trial {trial_id} → SCANNER score: ({value})    Targets: ({targets})   Step_id: {m.get('step_id')}")  # set lblStaus in optimizer_dialog.py

        # -------------------------
        # FINAL RETURN
        # -------------------------
        self.evaluationReady.emit({"results": results, "_pruned": False})

        self._busy = False

    def evaluate_old(self, payload):
        # print("🔥[evaluation_service] evaluate received in EvalService")
        # print(f"DEBUG: Payload: {payload}")

        doc = App.ActiveDocument
        if not doc:
            print("[evaluation_service] DEBUG: No active document in evaluate")
            self.evaluationReady.emit({"clusters": {}})
            return

        params = payload.get("params", {})
        metrics = payload.get("metrics", [])

        # 1. APPLY PARAMS
        if params:
            print(f"[evaluation_service] DEBUG: Applying params: {params}")
            apply_cad_params(params)
            # ✅ Tvinga modelluppdatering
            doc.recompute()
            _trigger_ray_engine(reason="optuna_optimization", source=None, force=True)
            # print("[evaluation_service] DEBUG: Applied CAD parameters for evaluation.")

        # 2. NOTE:
        # Ray engine är reaktiv → ingen explicit recompute behövs
        # recompute_doc(doc, restore_view=False)

        # 3. COLLECT RAY CLUSTERS
        # print("[evaluation_service] DEBUG: Collecting clusters")

        # clusters = aggregate_interaction_clusters(plane=plane, mode="final", min_hits=1)
        clusters = aggregate_interaction_clusters(mode="final", min_hits=1)
        print(f"[evaluation_service] DEBUG: Collected {len(clusters)} clusters")

        # 4. RETURN TO WORKER
        self.evaluationReady.emit({"clusters": clusters})

        scanner_results = {}

        for m in metrics:
            if m["base_metric"] == "scanner":
                scanner_results[m["name"]] = metric_scanner(
                    m,
                    clusters,
                    m["plane"],
                    {"doc": doc},
                )

        self.evaluationReady.emit(
            {
                "clusters": clusters,
                "scanner": scanner_results,
            }
        )

        # -------------------------------------------------------
        # CLUSTER COLLECTION (CORE LOGIC)
        # -------------------------------------------------------

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

    def _evaluate_metric(self, clusters, metric, baseline):

        base = metric["base_metric"]
        plane = metric["plane"]
        targets = metric.get("targets", [])

        targets = metric["targets"]

        label_map = self._build_label_to_name_map()
        target_names = [label_map.get(t, t) for t in targets]
        filtered = {k: c for k, c in clusters.items() if c.get("object") in target_names}

        # filtered = {k: c for k, c in clusters.items() if c.get("object") in targets}

        valid = True

        # ----------------------------------
        # DISPATCH + THRESHOLD (tillsammans)
        # ----------------------------------

        if base == "power":
            value, _ = compute_power(filtered, target_names, baseline)

            if metric.get("use_threshold"):
                margin = metric.get("percent", 0.0)
                valid = value >= (1.0 + margin)

        elif base == "preserve_cluster_count":
            value = compute_preserve_cluster_count(filtered, target_names, baseline, metric.get("percent", 0.01))

            if metric.get("use_threshold"):
                tol = metric.get("percent_tolerance", 0.1)
                valid = abs(value - 1.0) <= tol

        elif base == "target_cluster_count":
            value, diff = compute_target_cluster_count(filtered, target_names, baseline, metric.get("percent", 0.01), metric.get("value", 1))

            if metric.get("use_threshold"):
                tol = metric.get("percent_tol", 0.2)
                valid = diff <= tol

        elif base == "density":
            value = compute_density(filtered, plane, baseline)

        elif base == "roundness":
            value = compute_roundness(filtered, plane, baseline)

        elif base == "equal_distance":
            value = compute_distance(filtered, plane, baseline)

        elif base == "equal_ray_hits_count":
            value = compute_equal_ray_hits_count(filtered, plane, baseline)

        elif base == "cluster_axis_alignment":
            value = compute_cluster_axis_alignment(filtered, metric.get("axis"), plane, baseline)

        else:
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


def compute_baseline():
    clusters = aggregate_interaction_clusters(mode="final", min_hits=1)

    baseline = {}

    baseline["cluster_count"] = len(clusters)
    baseline["total_hits"] = sum(c.get("hit_count", 0) for c in clusters.values())
    baseline["max_hits"] = max(c.get("hit_count", 0) for c in clusters.values())  # Max hits

    # ✅ power per object
    object_power = {}
    object_hits = {}

    for c in clusters.values():
        obj = c.get("object")

        object_power[obj] = object_power.get(obj, 0.0) + c.get("power", {}).get("in", 0.0)
        object_hits[obj] = object_hits.get(obj, 0) + c.get("hit_count", 0)

    baseline["object_power"] = object_power
    baseline["object_hits"] = object_hits

    # density
    for plane in ("3D", "XY", "XZ", "YZ"):
        vals = [c.get("density", {}).get(plane) for c in clusters.values() if c.get("density", {}).get(plane) is not None]
        baseline[f"density_{plane}"] = sum(vals) / len(vals) if vals else 0.0

    cluster_count_per_object = {}
    for c in clusters.values():
        obj = c.get("object")
        cluster_count_per_object[obj] = cluster_count_per_object.get(obj, 0) + 1

    baseline["cluster_count_per_object"] = cluster_count_per_object

    return baseline


def compute_power(clusters, targets, baseline=None):
    if not clusters:
        return 0.0, False
    current = sum(c.get("power", {}).get("in", 0.0) for c in clusters.values() if c.get("object") in targets)
    if current <= 1e-12:
        return 0.0, False
    if baseline:
        base = sum(baseline.get("object_power", {}).get(obj, 0.0) for obj in targets)
        if base <= 1e-12:
            return 0.0, False
        value = current / base
        return value, True  # ✅ INGEN constraint här
    return current, True


def compute_filtered_baseline_clusters(baseline, min_percent):
    max_hits = baseline.get("max_hits", 1e-6)
    object_hits = baseline.get("object_hits", {})
    count = 0
    for obj, hits in object_hits.items():
        ratio = hits / (max_hits + 1e-6)
        # ✅ samma logik som runtime
        score = 1 / (1 + np.exp(-20 * (ratio - min_percent)))
        count += score
    return count


def compute_preserve_cluster_count(clusters, targets, baseline, min_percent):

    if not clusters or not baseline:
        return 0.0, False  # ❗ invalid direkt
    max_hits = baseline.get("max_hits", 1e-6)
    current = 0
    for c in clusters.values():
        if c.get("object") not in targets:
            continue
        ratio = c.get("hit_count", 0) / max_hits
        # ✅ soft count
        score = 1 / (1 + np.exp(-10 * (ratio - min_percent)))
        current += score

    baseline_count = compute_filtered_baseline_clusters(baseline, min_percent)
    if baseline_count is None:
        baseline_count = 1  # safety
    diff = abs(current - baseline_count)
    value = 1.0 / (1.0 + diff)
    # ✅ HARD constraint (du bestämmer tolerans)
    # tolerance = 0.5
    # valid = diff < tolerance
    return value  # , valid


def compute_target_cluster_count(clusters, targets, baseline, min_percent, target):

    if not clusters:
        return 0.0, False  # ❗ invalid

    max_hits = baseline.get("max_hits", 1e-6) if baseline else 1e-6
    current = 0
    for c in clusters.values():
        if c.get("object") not in targets:
            continue
        ratio = c.get("hit_count", 0) / max_hits
        score = 1 / (1 + np.exp(-20 * (ratio - min_percent)))
        current += score
    diff = abs(current - target)
    value = 1.0 / (1.0 + diff)

    return value, diff


def compute_distance(clusters, plane, baseline=None):

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

    doc = context["doc"]

    step_id = metric.get("step_id")
    min_percent = metric.get("percent", 0.8)

    # print("[metric_scanner] SCANNER METRIC CALLED with step_id:", step_id)
    # print(metric)

    if not step_id:
        # print("EXIT: no step_id")
        return 0.0

    db = HitsDB()

    # ✅ använd samma targets som resten av metrics
    targets = list({c.get("object") for c in filtered_clusters.values()})
    if not targets:
        # print("EXIT: no targets")
        return 0.0

    batch = find_batch_object(doc)
    if not batch:
        # print("EXIT: no batch")
        return 0.0

    step = find_step_by_id(doc, step_id)
    if not step:
        # print("EXIT: no step")
        return 0.0

    # --------------------------------------------------
    # 🔥 ALLTID kör scanner
    # --------------------------------------------------

    class Dummy:
        def setValue(self, v):
            pass

        def setRange(self, a, b):
            pass

        def setText(self, t):
            pass

    # print("TARGETS =", targets)
    # print("BATCH =", batch)
    # print("STEP =", step)
    # print("RUNNING BATCH NOW")

    # ta bort gamla scannerdata för denna step
    db.clear_step(step_id)
    run_steps_for_batch(
        batch=batch,
        prog_bar=Dummy(),
        status_lbl=Dummy(),
        pump_events_func=lambda: None,
        stop_flag_func=lambda: False,
        only_step_id=step_id,
    )

    # --------------------------------------------------
    # ✅ Läs resultat från DB
    # --------------------------------------------------

    import numpy as np

    X_all, Y_all, Z_all, V_all = [], [], [], []

    for tgt in targets:
        for em in db.list_emitters(tgt):
            X, Y, Z, H, PIN, _, _ = db.read_grid(tgt, em, step_id)

            if not X:
                continue

            X_all.extend(X)
            Y_all.extend(Y)
            Z_all.extend(Z)
            V_all.extend(PIN)

    if not V_all:
        return 0.0

    X = np.asarray(X_all)
    Y = np.asarray(Y_all)
    Z = np.asarray(Z_all)
    V = np.asarray(V_all)

    # --------------------------------------------------
    # ✅ NORMALISERA
    # --------------------------------------------------

    vmax = np.max(V)
    if vmax <= 0:
        return 0.0

    Vn = V / vmax

    # --------------------------------------------------
    # ✅ THRESHOLD REGION
    # --------------------------------------------------

    mask = Vn >= min_percent
    if not np.any(mask):
        return 0.0

    Xg = X[mask]
    Yg = Y[mask]
    Zg = Z[mask]

    # --------------------------------------------------
    # ✅ SCORING
    # --------------------------------------------------

    if plane == "XY":
        A, B = Xg, Yg
    elif plane == "XZ":
        A, B = Xg, Zg
    elif plane == "YZ":
        A, B = Yg, Zg
    else:
        dx = Xg.max() - Xg.min()
        dy = Yg.max() - Yg.min()
        dz = Zg.max() - Zg.min()
        return (dx + dy + dz) / 3.0

    # ✅ robust center
    ca = np.median(A)
    cb = np.median(B)

    dist = np.sqrt((A - ca) ** 2 + (B - cb) ** 2)

    return np.mean(dist)


# def run_scanner_blocking(metric, filtered_clusters, plane, context):
#     QtCore.QCoreApplication.processEvents()
#     result = metric_scanner(metric, filtered_clusters, plane, context)
#     QtCore.QCoreApplication.processEvents()
#     return result


def compute_cluster_axis_alignment(clusters, axis, plane=None, baseline=None):
    if not clusters or not axis:
        return 0.0

    vals = []

    for c in clusters.values():

        centroid = c.get("centroid", {}).get("3D")

        if centroid is None:
            continue

        if axis == "X":
            vals.append(centroid[0])
        elif axis == "Y":
            vals.append(centroid[1])
        elif axis == "Z":
            vals.append(centroid[2])

    if len(vals) < 2:
        return 0.0

    std = np.std(vals)

    # ✅ låg spridning = bra
    score = 1.0 / (1.0 + std)

    return score


def compute_equal_ray_hits_count(clusters, plane, baseline=None):
    # ✅ behålla rays
    # ✅ fördela dem jämnt
    # ✅ inte skapa döda kluster

    import numpy as np

    hits = np.array([c.get("hit_count", 0) for c in clusters.values()])

    if len(hits) == 0:
        return 0.0

    total = hits.sum()
    mean = hits.mean()
    std = hits.std()

    if total == 0:
        return 0.0

    # ✅ jämnhet
    uniformity = 1.0 / (1.0 + std / (mean + 1e-6))

    # ✅ total effekt
    if baseline:
        base_total = baseline.get("total_hits", 1e-6)
        efficiency = total / (base_total + 1e-6)
    else:
        efficiency = total

    return uniformity * efficiency


def compute_density(clusters, plane, baseline=None):
    if not clusters:
        return 0.0

    vals = []
    weights = []

    for c in clusters.values():
        raw = c.get("density", {}).get(plane)
        w = c.get("hit_count", 1)

        if raw is not None:
            vals.append(raw * w)
            weights.append(w)

    if not vals:
        return 0.0

    # ✅ INGEN normalisering
    return sum(vals) / sum(weights)


def compute_roundness(clusters, plane, baseline=None):
    if not clusters:
        return 0.0

    vals = []
    for c in clusters.values():
        r = c.get("roundness", {}).get(plane)
        if r is not None:
            vals.append(r)

    if not vals:
        return 0.0

    return sum(vals) / len(vals)
