# -*- coding: utf-8 -*-
# optimize_metrics.py

from __future__ import annotations
from typing import Sequence, Tuple, List
import math
import numpy as np

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


def density_score(
    hit_count: int,
    radius: float,
) -> float:
    """
    Rå densitet = hit_count / (1 + r²)
    Log‑komprimerad till [0, 1]
    """
    if hit_count <= 0:
        return 0.0

    r2 = max(0.0, float(radius)) ** 2
    raw = float(hit_count) / (1.0 + r2)

    # strikt [0, 1], mjukt växande
    return float(math.log1p(raw) / math.log1p(raw + 1.0))


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
        cnt = int(m.get("count", 0) or 0)
        r3d = float(m.get("spread", {}).get("3D", {}).get("radius", 0.0))
        density_scores.append(density_score(cnt, r3d))

        # ---- Roundness
        cov = m.get("spread", {}).get(plane, {}).get("cov")
        roundness_scores.append(roundness_score_from_cov(cov) if cov is not None else 0.0)

        # ---- Centroid
        c3d = m.get("centroid", {}).get("3D")
        if c3d and len(c3d) >= 3:
            centroids.append((float(c3d[0]), float(c3d[1]), float(c3d[2])))

    density_g = float(np.mean(density_scores)) if density_scores else 0.0
    roundness_g = float(np.mean(roundness_scores)) if roundness_scores else 0.0

    return density_g, roundness_g, centroids
