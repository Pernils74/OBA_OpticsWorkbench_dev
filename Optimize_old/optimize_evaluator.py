# -*- coding: utf-8 -*-
# evaluation_service.py — ANALYSER-BASERAD, GAMMA-KOMPATIBEL

import FreeCAD as App
from PySide import QtCore

from .spreadsheet_utils import apply_cad_params
from .cad_refresh import recompute_doc

from oba_rayengine.oba_ray_analyser import collect_ray_hits_and_stats
from oba_rayengine.oba_ray_core import OBARayManager


from .optimize_ray_collector import collect_optimize_metrics


from .optimize_metrics import (
    roundness_score_from_cov,
    density_score,
)


class EvaluationService(QtCore.QObject):
    """
    EvaluationService baserad direkt på ray-engine-analys.

    Pipeline:
        CAD params → recompute →
        collect_ray_hits_and_stats →
        gamma-metrics → Optuna
    """

    evaluationReady = QtCore.Signal(dict)

    # -------------------------------------------------------
    # Publika slots
    # -------------------------------------------------------

    @QtCore.Slot(dict)
    def applyBest(self, params: dict):
        doc = App.ActiveDocument
        if not doc:
            App.Console.PrintError("[Eval] No active document\n")
            return
        try:
            apply_cad_params(params)
            recompute_doc(doc, restore_view=False)
            App.Console.PrintMessage("[Eval] Applied best parameters.\n")
        except Exception as e:
            App.Console.PrintError(f"[Eval] applyBest failed: {e}\n")

    @QtCore.Slot(dict)
    def evaluate(self, payload):

        doc = App.ActiveDocument
        if not doc:
            self.evaluationReady.emit({"metrics": {}})
            return

        params = payload.get("params", {})
        plane = payload.get("plane", "XY")

        if params:
            apply_cad_params(params)
        # recompute_doc(doc, restore_view=False) # Ray tracing är numera reaktiv, dvs vi behöver inte manuellt trigga en recompute här

        # metrics = collect_optimize_metrics(
        #     plane=plane,
        #     metric_targets=self.parent().state.metric_targets,  # ✅ UI → collector
        # )
        # self.evaluationReady.emit({"metrics": metrics})

        # samlar rådata
        clusters = collect_clusters(
            plane=plane,
        )

        self.evaluationReady.emit({"clusters": clusters})


import numpy as np
from collections import defaultdict
from oba_rayengine.oba_ray_core import OBARayManager

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------


def _project_points(points, plane):
    if plane == "XY":
        return points[:, [0, 1]]
    elif plane == "XZ":
        return points[:, [0, 2]]
    elif plane == "YZ":
        return points[:, [1, 2]]
    raise ValueError(f"Invalid plane: {plane}")


# ------------------------------------------------------------
# MAIN COLLECTOR
# ------------------------------------------------------------


def collect_clusters(
    *,
    plane="XY",
    mode="final",
):
    """
    Samlar och returnerar kluster som RÅDATA.

    Returnerar:
        clusters: dict[cluster_id, ClusterData]
    """

    plane = plane.upper()
    if plane not in ("XY", "XZ", "YZ"):
        plane = "XY"

    rm = OBARayManager()
    rays = [r for r in rm.get_all_rays() if r.mode == mode]

    # --------------------------------------------------------
    # 1) Bucket: (path_id, bounce) → list[hit]
    # --------------------------------------------------------

    buckets = defaultdict(list)

    for ray in rays:
        for h in ray.history:
            if not isinstance(h, dict):
                continue
            if "hit_point" not in h:
                continue

            key = (ray.path_id, h.get("bounce_index", ray.bounce_count))

            buckets[key].append(
                {
                    "point": np.array(h["hit_point"], dtype=float),
                    "object": h.get("object_name"),
                    "optical_type": h.get("optical_type"),
                    "power_out": h.get("extra", {}).get("power_out", ray.power),
                    "absorbed": h.get("extra", {}).get("absorbed_power", 0.0),
                }
            )

    # --------------------------------------------------------
    # 2) Bygg ClusterData (INGA METRICS)
    # --------------------------------------------------------

    clusters = {}
    cluster_index = 0

    for (path_id, bounce), hits in buckets.items():

        if len(hits) < 2:
            continue

        pts = np.array([h["point"] for h in hits])
        objects = {h["object"] for h in hits}

        centroid_3d = pts.mean(axis=0)
        proj = _project_points(pts, plane)

        d3 = np.linalg.norm(pts - centroid_3d, axis=1)
        radius_3d = float(np.max(d3))

        cluster_id = f"{cluster_index}:{bounce}"
        cluster_index += 1

        clusters[cluster_id] = {
            "path_id": path_id,
            "bounce": bounce,
            # rå geometri
            "points": pts,
            "centroid_3d": centroid_3d,
            "centroid_plane": proj.mean(axis=0),
            "radius_3d": radius_3d,
            # metadata
            "objects": objects,
            "hit_count": len(pts),
            # ev. framtida metrics
            "extras": {
                "plane": plane,
            },
        }

    return clusters
