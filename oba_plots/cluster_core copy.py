# -*- coding: utf-8 -*-
# cluster_core.py

from __future__ import annotations
from typing import List, Dict
from collections import defaultdict, Counter

import matplotlib.cm as cm
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon


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
# Draw: Blobs
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

        key = (h["object"], h["emitter_id"], h["bounce"])
        groups[key].append(h)

    for (_, _, bounce), entries in groups.items():
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
# Draw: Centroids
# -------------------------------------------------


# -------------------------------------------------
# Draw: Cluster centroids (YT-KLUSTER)
# -------------------------------------------------
def draw_cluster_centroids(ax, clusters, filter_spec, plane_key, flip2d):
    # Stabil markör per face_id
    face_markers = face_marker_map({c["face_id"] for c in clusters.values()})

    for c in clusters.values():
        if not _allow(c["object"], filter_spec.get("objects")):
            continue
        if not _allow(c["bounce"], filter_spec.get("bounces")):
            continue

        face = c["face_id"]
        marker = face_markers.get(face, "o")  # fallback säker

        cx, cy = c["centroid_plane"]
        if flip2d:
            cx, cy = cy, cx

        ax.scatter(
            [cx],
            [cy],
            s=120,
            facecolor="none",
            edgecolor="black",
            marker=marker,
            linewidths=1.6,
            zorder=20,
        )


def draw_centroids_old(
    ax,
    stats,
    filter_spec,
    plane_key,
    flip2d,
):
    """
    Rita EN centroid per (emitter, objekt, bounce)
    Samma klusterdefinition som blobs.
    """

    merged = defaultdict(list)

    for (emitter_id, path_signature), s in stats.items():
        if not _allow(emitter_id, filter_spec.get("emitters")):
            continue
        if not path_signature:
            continue

        last_obj, _last_face = path_signature[-1]
        if not _allow(last_obj, filter_spec.get("objects")):
            continue

        bounce = s.get("mean_bounce")  # eller min/max om du vill
        key = (emitter_id, last_obj, int(round(bounce)))

        merged[key].append(s["centroid"])

    # Rita EN centroid per interaction-kluster
    for (_emitter, _obj, _bounce), pts in merged.items():
        n = len(pts)
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
        cz = sum(p[2] for p in pts) / n

        cx, cy = _project((cx, cy, cz), plane_key)
        if flip2d:
            cx, cy = cy, cx

        ax.scatter(
            [cx],
            [cy],
            s=120,
            facecolor="none",
            edgecolor="black",
            linewidths=1.5,
            zorder=20,
        )


# -------------------------------------------------
# Legends (✅ MED HIT-COUNT PER BOUNCE)
# -------------------------------------------------


def face_marker_map(faces):
    """
    Tilldelar stabil markör per face_id.
    """
    markers = ["o", "s", "^", "D", "x", "+", "*", "P"]
    return {face: markers[i % len(markers)] for i, face in enumerate(sorted(faces))}


def build_bounce_face_legend(ax, clusters, mixer):
    """
    Legend baserad på (bounce, face_id).
    """

    from matplotlib.lines import Line2D

    # Samla statistik
    combo = Counter()
    faces = set()

    for c in clusters.values():
        key = (c["bounce"], c["face_id"])
        combo[key] += c["hit_count"]
        faces.add(c["face_id"])

    marker_by_face = face_marker_map(faces)

    handles = []
    labels = []

    for (bounce, face), hit_count in sorted(combo.items()):
        handles.append(
            Line2D(
                [0],
                [0],
                marker=marker_by_face[face],
                linestyle="None",
                markerfacecolor="none",
                markeredgecolor=mixer.color(bounce)[0:3],
                markersize=10,
            )
        )
        labels.append(f"B{bounce} | F{face} ({hit_count} hits)")

    ax.legend(
        handles,
        labels,
        title="Bounce | Face",
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


# def build_legends(ax, emitters, bounces, marker_map, mixer, hits):
#     # -------------------------------------------------
#     # Emitters legend
#     # -------------------------------------------------
#     h_emit = [
#         Line2D(
#             [0],
#             [0],
#             marker=marker_map[e],
#             linestyle="None",
#             color="black",
#             label=e,
#         )
#         for e in emitters
#     ]

#     leg1 = ax.legend(handles=h_emit, title="Emitter", loc="upper left")
#     ax.add_artist(leg1)

#     # -------------------------------------------------
#     # Bounce statistics
#     # -------------------------------------------------
#     bounce_hit_count = Counter()
#     bounce_power_sum = defaultdict(float)

#     for h in hits:
#         b = h["bounce"]
#         bounce_hit_count[b] += 1
#         bounce_power_sum[b] += h.get("power", 0.0)

#     total_hits = sum(bounce_hit_count.values())

#     # -------------------------------------------------
#     # Bounce legend (hits | % | power)
#     # -------------------------------------------------
#     h_bounce = []
#     labels = []

#     for b in sorted(bounces):
#         hits_b = bounce_hit_count.get(b, 0)
#         pct = 100.0 * hits_b / total_hits if total_hits > 0 else 0.0
#         power = bounce_power_sum.get(b, 0.0)

#         h_bounce.append(
#             Line2D(
#                 [0],
#                 [0],
#                 marker="o",
#                 linestyle="None",
#                 color=mixer.color(b),
#             )
#         )

#         labels.append(f"B{b} ({hits_b} | {pct:.0f}% | {power:.3f})")

#     ax.legend(
#         h_bounce,
#         labels,
#         title="Bounce (hits | % | power)",
#         loc="upper right",
#     )


# -*- coding: utf-8 -*-
# cluster_core.py

from __future__ import annotations
from typing import List, Dict
from collections import defaultdict, Counter

import matplotlib.cm as cm
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon


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

        key = (h["object"], h["last_hit_label"], h["bounce"])
        groups[key].append(h)

    for (_, _, bounce), entries in groups.items():
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
    # Stabil markör per last_hit_label
    label_markers = label_marker_map({c["last_hit_label"] for c in clusters.values()})

    for c in clusters.values():
        if not _allow(c["object"], filter_spec.get("objects")):
            continue
        if not _allow(c["bounce"], filter_spec.get("bounces")):
            continue

        label = c["last_hit_label"]
        marker = label_markers.get(label, "o")

        cx, cy = c["centroid_plane"]
        if flip2d:
            cx, cy = cy, cx

        ax.scatter(
            [cx],
            [cy],
            s=120,
            facecolor="none",
            edgecolor="black",
            marker=marker,
            linewidths=1.6,
            zorder=20,
        )


# -------------------------------------------------
# Legends
# -------------------------------------------------
def label_marker_map(labels):
    markers = ["o", "s", "^", "D", "x", "+", "*", "P"]
    return {label: markers[i % len(markers)] for i, label in enumerate(sorted(labels))}


def build_bounce_surface_legend(ax, clusters, mixer):
    combo = Counter()
    labels = set()

    for c in clusters.values():
        key = (c["bounce"], c["last_hit_label"])
        combo[key] += c["hit_count"]
        labels.add(c["last_hit_label"])

    marker_by_label = label_marker_map(labels)

    handles = []
    legend_labels = []

    for (bounce, label), hit_count in sorted(combo.items()):
        handles.append(
            Line2D(
                [0],
                [0],
                marker=marker_by_label[label],
                linestyle="None",
                markerfacecolor="none",
                markeredgecolor=mixer.color(bounce)[0:3],
                markersize=10,
            )
        )
        legend_labels.append(f"B{bounce} | {label} ({hit_count} hits)")

    ax.legend(
        handles,
        legend_labels,
        title="Bounce | Surface",
        loc="upper right",
    )
