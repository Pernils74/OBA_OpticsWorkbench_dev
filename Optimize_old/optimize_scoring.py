# -*- coding: utf-8 -*-
# optimize_scoring.py — samlad objektivfunktion

from .optimize_metrics import (
    aggregate_from_metrics_dict,
    equal_distance_score_2d,
    equal_distance_score_3d,
    cluster_count_score,
)


def score_clusters(
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
        equal_dist_g = equal_distance_score_2d(
            centroids,
            plane=plane,
        )
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
    # 5) Global score (viktad summa)
    # --------------------------------------------------
    score = w_d * density_g + w_r * roundness_g + w_e * equal_dist_g + w_c * cluster_count_g

    return {
        "score": float(score),
        "components": {
            "density": float(density_g),
            "roundness": float(roundness_g),
            "equal_distance": float(equal_dist_g),
            "cluster_count": float(cluster_count_g),
        },
        "cluster_count": cluster_count,
        "centroids": centroids,
    }
