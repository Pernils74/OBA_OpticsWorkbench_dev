# -*- coding: utf-8 -*-
# optimize_scoring.py — samlad objektivfunktion

from __future__ import annotations
from typing import Sequence, Tuple, List
import math
import numpy as np

# from .optimize_metrics import (
#     aggregate_from_metrics_dict,
#     equal_distance_score_2d,
#     equal_distance_score_3d,
#     cluster_count_score,
#     density_score,
#     roundness_score_from_cov,
# )


# --------------------------------------------------
# ROUNDNESS (redan normaliserad)
# --------------------------------------------------


def roundness_score_from_cov(cov_matrix: Sequence[Sequence[float]]) -> float:
    """
    Isotropi = min(eigenvärde) / max(eigenvärde)
    ∈ [0, 1]
    """
    try:
        A = np.array(cov_matrix, dtype=float)
        vals = np.linalg.eigvals(A)

        lam_max = float(np.max(vals).real)
        lam_min = float(np.min(vals).real)

        if lam_max <= 0.0:
            return 0.0

        return float(np.clip(lam_min / lam_max, 0.0, 1.0))
    except Exception:
        return 0.0


# --------------------------------------------------
# DENSITY (log‑normaliserad)
# --------------------------------------------------


def density_score(hit_count, radius):
    if hit_count <= 0:
        return 0.0

    density = hit_count / (radius * radius + 1e-6)

    return 1.0 - math.exp(-0.02 * density)


# --------------------------------------------------
# EQUAL DISTANCE — GEMENSAM NORMALISERING
# --------------------------------------------------


def _equal_distance_from_points(
    distances: Sequence[float],
) -> float:
    """
    CV‑baserad likformighet:
        cv = std / mean
        score = 1 / (1 + cv)
    ∈ (0, 1]
    """
    if not distances:
        return 1.0

    mean_d = float(np.mean(distances))
    if mean_d <= 0.0:
        return 0.0

    cv = float(np.std(distances) / mean_d)
    return float(1.0 / (1.0 + cv))


# --------------------------------------------------
# EQUAL DISTANCE — 3D
# --------------------------------------------------


def equal_distance_score_3d(centroids: Sequence[Tuple[float, float, float]]) -> float:
    if len(centroids) < 2:
        return 1.0

    dists = []
    for i in range(len(centroids)):
        x1, y1, z1 = centroids[i]
        for j in range(i + 1, len(centroids)):
            x2, y2, z2 = centroids[j]
            dists.append(math.dist((x1, y1, z1), (x2, y2, z2)))

    return _equal_distance_from_points(dists)


# --------------------------------------------------
# EQUAL DISTANCE — 2D
# --------------------------------------------------


def equal_distance_score_2d(
    centroids: Sequence[Tuple[float, float, float]],
    plane: str = "XY",
) -> float:

    plane = plane.upper()
    if plane not in ("XY", "XZ", "YZ"):
        plane = "XY"

    pts = []
    for x, y, z in centroids:
        if plane == "XY":
            pts.append((x, y))
        elif plane == "XZ":
            pts.append((x, z))
        else:
            pts.append((y, z))

    if len(pts) < 2:
        return 1.0

    dists = []
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            dists.append(
                math.hypot(
                    pts[i][0] - pts[j][0],
                    pts[i][1] - pts[j][1],
                )
            )

    return _equal_distance_from_points(dists)


def cluster_count_score(
    actual: int,
    target: int | None,
) -> float:
    """
    White-cell-anpassad cluster count score.

    - Exakt rätt antal studs → 1.0
    - Fel antal studs straffas exponentiellt
    """

    if target is None or target <= 0:
        return 1.0

    diff = abs(actual - target)
    return float(math.exp(-diff))


# Mycket hård score för fel antal
# def cluster_count_score(actual, target):
#     if target is None:
#         return 1.0
#     return 1.0 if actual == target else 0.0
# --------------------------------------------------
# AGGREGERING (alla resultat ∈ [0,1])
# --------------------------------------------------


def aggregate_from_metrics_dict(
    metrics: dict,
    plane_for_roundness: str = "XY",
) -> Tuple[float, float, List[Tuple[float, float, float]]]:

    plane = plane_for_roundness.upper()
    if plane not in ("XY", "XZ", "YZ"):
        plane = "XY"

    density_scores = []
    roundness_scores = []
    centroids = []

    for _, m in metrics.items():

        # ---- Density
        hits = int(m.get("hit_count", 0) or 0)
        r3d = float(m.get("spread", {}).get("3D", {}).get("radius", 0.0))
        dens = density_score(hits, r3d)
        density_scores.append(dens)

        # ---- Roundness (viktad mot hit_count för att minska brus)
        cov = m.get("spread", {}).get(plane, {}).get("cov")
        rnd = roundness_score_from_cov(cov) if cov is not None else 0.0

        # dämpa små, brusiga kluster
        rnd *= min(1.0, hits / 20.0)
        roundness_scores.append(rnd)

        # ---- Centroid
        c3d = m.get("centroid", {}).get("3D")
        if c3d and len(c3d) >= 3:
            centroids.append((float(c3d[0]), float(c3d[1]), float(c3d[2])))

    if not density_scores:
        return 0.0, 0.0, centroids

    # ✅ Bottleneck / low‑percentile aggregation
    density_g = float(np.percentile(density_scores, 40))
    roundness_g = float(np.percentile(roundness_scores, 40))

    # density_g = float(np.mean(density_scores))
    # roundness_g = float(np.mean(roundness_scores))

    return density_g, roundness_g, centroids


# --------------------------------------------------
# Aggregating Scoring for evalutae
# --------------------------------------------------


def _filter_clusters(metrics, targets):
    if targets == ["ALL"]:
        return metrics

    return {k: c for k, c in metrics.items() if c.get("object") in targets}


def compute_density(clusters, plane):
    vals = [c["density"][plane] for c in clusters.values()]
    if not vals:
        return 0.0
    return float(np.percentile(vals, 40))


def compute_roundness(clusters, plane):
    vals = [c["roundness"][plane] for c in clusters.values()]
    if not vals:
        return 0.0
    return float(np.percentile(vals, 40))


def compute_equal_distance(clusters, plane):
    centroids = [c["centroid"]["3D"] for c in clusters.values()]
    if len(centroids) < 2:
        return 1.0

    if plane == "3D":
        return equal_distance_score_3d(centroids)
    else:
        return equal_distance_score_2d(centroids, plane)


def compute_metric(metric, clusters, plane, target_count):

    if not clusters:
        return 0.0

    if metric == "density":
        return compute_density(clusters, plane)

    elif metric == "roundness":
        return compute_roundness(clusters, plane)

    elif metric == "equal_distance":
        return compute_equal_distance(clusters, plane)

    elif metric == "cluster_count":
        return cluster_count_score(len(clusters), target_count)

    return 0.0


def score_clusters(*, metrics, metric_config, target_cluster_count_map):

    # metric_config = {
    #     "density": {...},
    #     "roundness": {...},
    #     "cluster_count": {...},
    # }

    if not metrics:
        return {"score": 0.0}

    total_score = 0.0
    total_weight = 0.0

    debug_components = {}

    for metric_name, cfg in metric_config.items():

        weight = float(cfg.get("normalized", 0.0))
        targets = cfg.get("targets", ["ALL"])
        plane = cfg.get("plane", "XY")

        # --- filtrera ---
        sub = _filter_clusters(metrics, targets)

        # --- target count key ---
        key = tuple(sorted(targets))
        target_count = target_cluster_count_map.get(key)

        # --- compute metric ---
        val = compute_metric(metric_name, sub, plane, target_count)

        total_score += weight * val
        total_weight += weight

        debug_components[metric_name] = val

    if total_weight <= 1e-9:
        final_score = 0.0
    else:
        final_score = total_score / total_weight

    return {
        "score": float(final_score),
        "components": debug_components,
    }


def score_clusters_old(
    *,
    metrics: dict,
    plane: str,
    weights: dict,
    equal_distance_mode: str,
    target_cluster_count: int | None = None,
):
    """
    Alla komponenter ∈ [0, 1]
    Global score ∈ [0, 1]
    """

    if not metrics:
        return None

    # --------------------------------------------------
    # Canonical slot order (stabil ordning)
    # --------------------------------------------------
    slot_keys = sorted(metrics.keys())

    # --------------------------------------------------
    # 1) Per-cluster → globala metrics
    # --------------------------------------------------
    density_g, roundness_g, centroids = aggregate_from_metrics_dict(
        metrics,
        plane_for_roundness=plane,
    )

    # --------------------------------------------------
    # 2) Global equal-distance
    # --------------------------------------------------
    if equal_distance_mode == "2D":
        equal_dist_g = equal_distance_score_2d(centroids, plane=plane)
    else:
        equal_dist_g = equal_distance_score_3d(centroids)

    # --------------------------------------------------
    # 3) Klusterantal-metric
    # --------------------------------------------------
    cluster_count = len(metrics)

    cluster_count_g = cluster_count_score(
        actual=cluster_count,
        target=target_cluster_count,
    )

    # --------------------------------------------------
    # 4) Vikter
    # --------------------------------------------------
    w_d = float(weights.get("density", 0.0))
    w_r = float(weights.get("roundness", 0.0))
    w_e = float(weights.get("equal_distance", 0.0))
    w_c = float(weights.get("cluster_count", 0.0))

    # --------------------------------------------------
    # 5) Global score  tar det sämsta
    # --------------------------------------------------
    # score = w_d * density_g + w_r * roundness_g + w_e * equal_dist_g + w_c * cluster_count_g
    score = (w_d * density_g + w_r * roundness_g + w_e * equal_dist_g + w_c * cluster_count_g) / (w_d + w_r + w_e + w_c)
    # score = min(
    #     w_d * density_g,
    #     w_r * roundness_g,
    #     w_e * equal_dist_g,
    # )

    # --------------------------------------------------
    # 6) Per-cluster metrics (för plot + debug)
    # --------------------------------------------------
    cluster_metrics = {}
    slot_scores = []

    for k in slot_keys:
        m = metrics[k]
        dens = density_score(m.get("hit_count", 0), m.get("spread", {}).get("3D", {}).get("radius", 0.0))
        rnd = roundness_score_from_cov(m.get("spread", {}).get(plane, {}).get("cov"))

        cluster_metrics[k] = {
            "density": float(dens),
            "roundness": float(rnd),
            "radius3d": float(m.get("spread", {}).get("3D", {}).get("radius", 0.0)),
        }

        # Slot-score = density + roundness (enkelt, stabilt)
        slot_scores.append((dens + rnd) * 0.5)

    # --------------------------------------------------
    # 7) Returnera ALLT
    # --------------------------------------------------

    import FreeCAD as App

    App.Console.PrintWarning(f"[Scoring] dens={density_g:.4f} | " f"round={roundness_g:.4f} | " f"eq={equal_dist_g:.4f} | " f"cc={cluster_count_g:.4f}\n")
    # print(f"[DEBUG] dens_g={density_g:.4f}, " f"round_g={roundness_g:.4f}, " f"eq={equal_dist_g:.4f}, " f"cc={cluster_count_g:.4f}")

    return {
        "score": float(score),
        "slot_keys": slot_keys,
        "slot_scores": slot_scores,
        "cluster_metrics": cluster_metrics,
        "components": {
            "density": float(density_g),
            "roundness": float(roundness_g),
            "equal_distance": float(equal_dist_g),
            "cluster_count": float(cluster_count_g),
        },
        "centroids": centroids,
    }
