# -*- coding: utf-8 -*-
# cluster_core.py

from __future__ import annotations
from typing import List, Dict
from collections import defaultdict, Counter

import matplotlib.cm as cm
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon
from numpy import cov


# -------------------------------------------------
# Helpers
# -------------------------------------------------
def _allow(val, allowed):
    return (allowed is None) or (val in allowed)


def _project(point, plane_key):
    x, y, z = point
    if plane_key == "XY":
        return x, y
    if plane_key == "XZ":
        return x, z
    if plane_key == "YZ":
        return y, z
    raise ValueError(plane_key)


# -------------------------------------------------
# Geometry
# -------------------------------------------------
def convex_hull_2d(xs, ys):
    pts = sorted(set(zip(xs, ys)))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def smooth_polygon(points, iterations=2):
    pts = points
    for _ in range(iterations):
        new = []
        for i in range(len(pts)):
            p0 = pts[i]
            p1 = pts[(i + 1) % len(pts)]
            new.append((0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]))
            new.append((0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]))
        pts = new
    return pts


# -------------------------------------------------
# Color
# -------------------------------------------------
class ColorMixer:
    def __init__(self, bounces: List[int]):
        self.index = {b: i for i, b in enumerate(sorted(set(bounces)))}
        self.max_i = max(len(self.index) - 1, 1)
        self.cmap = cm.get_cmap("plasma")

    def color(self, bounce: int, alpha=0.9):
        t = self.index.get(bounce, 0) / self.max_i
        r, g, b, _ = self.cmap(t)
        return (r, g, b, alpha)


# -------------------------------------------------
# Draw: Points
# -------------------------------------------------
def draw_points(
    ax,
    hits,
    filter_spec,
    plane_key,
    flip2d,
    mixer: ColorMixer,
    marker_map,
    size=40,
):
    for h in hits:
        if not _allow(h["emitter_id"], filter_spec.get("emitters")):
            continue
        if not _allow(h["object"], filter_spec.get("objects")):
            continue

        x, y = _project(h["point"], plane_key)
        if flip2d:
            x, y = y, x

        sc = ax.scatter(
            [x],
            [y],
            s=size,
            marker=marker_map.get(h["emitter_id"], "o"),
            color=mixer.color(h["bounce"]),
            picker=True,
        )
        sc._pointinfo = [h]


# -------------------------------------------------
# Draw: Blobs (surface clusters)
# -------------------------------------------------
def draw_blobs_2d(
    ax,
    hits,
    filter_spec,
    plane_key,
    flip2d,
    mixer: ColorMixer,
    smooth: bool = True,
):
    groups = defaultdict(list)

    for h in hits:
        if not _allow(h["emitter_id"], filter_spec.get("emitters")):
            continue
        if not _allow(h["object"], filter_spec.get("objects")):
            continue

        key = (h["object"], h["bounce"], h["prev_hit_label"])
        groups[key].append(h)

    for (_, bounce, _), entries in groups.items():
        if len(entries) < 3:
            continue

        xs, ys = zip(*(_project(e["point"], plane_key) for e in entries))
        if flip2d:
            xs, ys = ys, xs

        hull = convex_hull_2d(xs, ys)
        if len(hull) < 3:
            continue

        pts = smooth_polygon(hull) if smooth else hull
        col = mixer.color(bounce, 1.0)

        ax.add_patch(
            Polygon(
                pts,
                closed=True,
                facecolor=(col[0], col[1], col[2], 0.2),
                edgecolor=(col[0], col[1], col[2], 0.4),
                linewidth=1.2,
            )
        )


# -------------------------------------------------
# Draw: Cluster centroids
# -------------------------------------------------
def draw_cluster_centroids(ax, clusters, filter_spec, plane_key, flip2d):
    for c in clusters.values():
        if not _allow(c["object"], filter_spec.get("objects")):
            continue
        if not _allow(c["bounce"], filter_spec.get("bounces")):
            continue

        cx, cy = c["centroid"][plane_key]
        if flip2d:
            cx, cy = cy, cx

        cov = c["spread"][plane_key]["cov"]  # olika punkt storlek baserat på spridning i planet (covariansmatris)
        if cov is not None:
            import numpy as np

            size = 200 / max(np.linalg.det(cov), 1e-6)
        else:
            size = 140

        ax.scatter(
            [cx],
            [cy],
            s=size,
            facecolor="none",
            edgecolor="black",
            linewidths=1.8,
            zorder=20,
        )


# -------------------------------------------------
# Legends
# -------------------------------------------------
def label_marker_map(labels):
    markers = ["o", "s", "^", "D", "x", "+", "*", "P"]
    return {label: markers[i % len(markers)] for i, label in enumerate(sorted(labels))}


def build_bounce_flow_legend(ax, clusters, mixer):
    combo = {}

    for c in clusters.values():
        key = (c["bounce"], c["prev_hit_label"])
        p = c.get("power", {}).get("out", 0.0)

        if key not in combo:
            combo[key] = {"hits": 0, "power": 0.0}

        combo[key]["hits"] += c["hit_count"]
        combo[key]["power"] += p

    total_hits = sum(d["hits"] for d in combo.values())
    total_power = sum(d["power"] for d in combo.values())

    handles = []
    labels = []

    def sort_key(item):
        (bounce, prev), _ = item
        prev_key = "" if prev is None else str(prev)
        return (bounce, prev_key)

    for (bounce, prev), data in sorted(combo.items(), key=sort_key):
        hits = data["hits"]
        power = data["power"]

        hits_pct = 100.0 * hits / total_hits if total_hits > 0 else 0.0
        power_pct = 100.0 * power / total_power if total_power > 0 else 0.0

        prev_str = prev if prev is not None else "∅"

        handles.append(
            Line2D(
                [0],
                [0],
                marker="o",
                linestyle="None",
                markerfacecolor="none",
                markeredgecolor=mixer.color(bounce)[0:3],
                markersize=10,
            )
        )

        labels.append(f"B{bounce} |  " f"({hits} hits, {hits_pct:.1f}%, " f"P={power:.2f}, {power_pct:.1f}%)")

    ax.legend(
        handles,
        labels,
        title="Bounce | Incoming surface",
        loc="upper right",
    )


def build_emitter_legend(ax, emitters, marker_map):
    handles = [
        Line2D(
            [0],
            [0],
            marker=marker_map[e],
            linestyle="None",
            color="black",
            label=e,
        )
        for e in emitters
    ]
    leg = ax.legend(handles=handles, title="Emitter", loc="upper left")
    ax.add_artist(leg)


# -------------------------------------------------
# Domains
# -------------------------------------------------
def compute_domains_for_legend(hits, filter_spec):
    emitters = set()
    objects = set()
    bounces = set()

    for h in hits:
        if not _allow(h["emitter_id"], filter_spec.get("emitters")):
            continue
        if not _allow(h["object"], filter_spec.get("objects")):
            continue

        emitters.add(h["emitter_id"])
        objects.add(h["object"])
        bounces.add(h["bounce"])

    return sorted(emitters), sorted(objects), sorted(bounces)
