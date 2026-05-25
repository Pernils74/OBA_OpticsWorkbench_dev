# -*- coding: utf-8 -*-
# optimize_metrics.py
from __future__ import annotations
from typing import Sequence, Tuple, List
import math
import numpy as np


# -------------------------------
# ROUNDNESS
# -------------------------------


def roundness_score_from_cov(cov_matrix: Sequence[Sequence[float]]) -> float:
    try:
        A = np.array(cov_matrix, dtype=float)
        vals = np.linalg.eigvals(A)
        lam_max = float(np.max(vals).real)
        lam_min = float(np.min(vals).real)
        if lam_max <= 0.0:
            return 0.0
        return max(0.0, min(1.0, lam_min / lam_max))
    except Exception:
        return 0.0


# -------------------------------
# DENSITY
# -------------------------------


def density_score(hit_count: int, radius: float) -> float:
    if hit_count <= 0:
        return 0.0
    r2 = max(0.0, float(radius)) ** 2
    d_raw = float(hit_count) / (1.0 + r2)
    return float(math.log1p(d_raw) / math.log1p(d_raw + 1.0))


# -------------------------------
# EQUAL DISTANCE — 3D
# -------------------------------


def equal_distance_score_3d(centroids: Sequence[Tuple[float, float, float]]) -> float:
    n = len(centroids)
    if n < 2:
        return 1.0
    dists = []
    for i in range(n):
        x1, y1, z1 = centroids[i]
        for j in range(i + 1, n):
            x2, y2, z2 = centroids[j]
            dij = math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2)
            dists.append(dij)
    if not dists:
        return 1.0
    mean_d = np.mean(dists)
    if mean_d <= 0:
        return 0.0
    cv = np.std(dists) / mean_d
    return float(1.0 / (1.0 + cv))


# -------------------------------
# EQUAL DISTANCE — 2D
# -------------------------------


def equal_distance_score_2d(centroids: Sequence[Tuple[float, float, float]], plane: str = "XY") -> float:

    plane = plane.upper()
    if plane not in ("XY", "XZ", "YZ"):
        plane = "XY"

    pts2 = []
    for x, y, z in centroids:
        if plane == "XY":
            pts2.append((x, y))
        elif plane == "XZ":
            pts2.append((x, z))
        else:  # YZ
            pts2.append((y, z))

    n = len(pts2)
    if n < 2:
        return 1.0

    dists = []
    for i in range(n):
        xi, yi = pts2[i]
        for j in range(i + 1, n):
            xj, yj = pts2[j]
            dij = math.hypot(xi - xj, yi - yj)
            dists.append(dij)

    if not dists:
        return 1.0
    mean_d = np.mean(dists)
    if mean_d <= 0:
        return 0.0
    cv = np.std(dists) / mean_d
    return float(1.0 / (1.0 + cv))


# -------------------------------
# GLOBAL METRICS (utan equal-distance)
# -------------------------------


def aggregate_from_metrics_dict(metrics: dict, plane_for_roundness: str = "XY") -> Tuple[float, float, List[Tuple[float, float, float]]]:

    plane = plane_for_roundness.upper().strip()
    if plane not in ("XY", "XZ", "YZ"):
        plane = "XY"

    dens_scores = []
    round_scores = []
    centroids = []

    for _, m in metrics.items():

        # densitet från (count, 3D-radius)
        cnt = int(m.get("count", 0) or 0)
        radius3d = float(m.get("spread", {}).get("3D", {}).get("radius", 0.0) or 0.0)
        dens_scores.append(density_score(cnt, radius3d))

        # projicerad rundhet
        cov = m.get("spread", {}).get(plane, {}).get("cov")
        round_scores.append(roundness_score_from_cov(cov) if cov is not None else 0.0)

        # centroid 3D
        c3d = m.get("centroid", {}).get("3D")
        if c3d and len(c3d) >= 3:
            try:
                centroids.append((float(c3d[0]), float(c3d[1]), float(c3d[2])))
            except Exception:
                pass

    density_global = float(np.mean(dens_scores)) if dens_scores else 0.0
    roundness_global = float(np.mean(round_scores)) if round_scores else 0.0

    # equal-distance gör vi separat i worker
    return density_global, roundness_global, centroids
