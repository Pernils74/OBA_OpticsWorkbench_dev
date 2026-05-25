# -*- coding: utf-8 -*-
# optimize_ray_collector.py — direkt collector från OBARayManager

import numpy as np
from collections import defaultdict
from oba_rayengine.oba_ray_core import OBARayManager

from .optimize_metrics import (
    density_score,
    roundness_score_from_cov,
)

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


def _target_match(name, targets):
    """
    targets:
        ["ALL"]
        ["Mirror_001"]
        ["Mirror_*"]
    """
    if not targets or "ALL" in targets:
        return True

    for t in targets:
        if t.endswith("*"):
            if name.startswith(t[:-1]):
                return True
        elif name == t:
            return True

    return False


# ------------------------------------------------------------
# MAIN COLLECTOR
# ------------------------------------------------------------


def collect_optimize_metrics(
    *,
    plane="XY",
    metric_targets=None,
    mode="final",
):
    """
    Returnerar metrics i exakt gamma-format som workern förväntar sig.
    """

    plane = plane.upper()
    if plane not in ("XY", "XZ", "YZ"):
        plane = "XY"

    metric_targets = metric_targets or {}

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

            obj = h.get("object_name")
            optical_type = h.get("optical_type")
            bounce = h.get("bounce_index", ray.bounce_count)

            key = (ray.path_id, bounce)

            buckets[key].append(
                {
                    "point": np.array(h["hit_point"], dtype=float),
                    "object": obj,
                    "optical_type": optical_type,
                    "power_out": h.get("extra", {}).get("power_out", ray.power),
                    "absorbed": h.get("extra", {}).get("absorbed_power", 0.0),
                }
            )

    # --------------------------------------------------------
    # 2) Compute metrics per bucket
    # --------------------------------------------------------

    metrics = {}
    cluster_index = 0

    for (path_id, bounce), hits in buckets.items():

        if len(hits) < 2:
            continue

        # ---------- target filtering (object-based) ----------
        objs = {h["object"] for h in hits}

        if not _target_match_any(
            objs,
            metric_targets.get("density"),
            metric_targets.get("roundness"),
            metric_targets.get("equal_distance"),
        ):
            continue

        pts = np.array([h["point"] for h in hits])
        n = len(pts)

        centroid_3d = pts.mean(axis=0)

        # ---------- 3D radius ----------
        d3 = np.linalg.norm(pts - centroid_3d, axis=1)
        radius_3d = float(np.max(d3))

        dens = density_score(n, radius_3d)

        # ---------- roundness via covariance ----------
        proj = _project_points(pts, plane)
        cov = np.cov(proj.T) if n >= 3 else None
        rnd = roundness_score_from_cov(cov) if cov is not None else 0.0

        key = f"{cluster_index}:{bounce}"
        cluster_index += 1

        metrics[key] = {
            "count": n,
            "density": float(dens),
            "roundness": float(rnd),
            "centroid": {
                "3D": tuple(centroid_3d),
                plane: tuple(proj.mean(axis=0)),
            },
            "spread": {
                "3D": {"radius": radius_3d},
                plane: {"cov": cov},
            },
        }

    return metrics


def _target_match_any(objects, *target_lists):
    for tlist in target_lists:
        if not tlist:
            continue
        for obj in objects:
            if _target_match(obj, tlist):
                return True
    return False
