# -*- coding: utf-8 -*-
# oba_ray_analyser.py

"""
Ray analysis built on OBARayManager singleton.

- En hit = en faktisk geometrisk träff
- power_out = kvarvarande transportenergi efter interaktionen
- power_in = inkommande energi till ytan
- absorbed_power = energi som absorberades i träffen
"""

import math
import numpy as np

from OPTIMIZER.optimize_scoring import roundness_score_from_cov
from .oba_ray_core import OBARayManager
from collections import defaultdict

# Huvudgruppering: object_name
# Inom objektet: separera per bounce_count
# Inom samma bounce: separera per prev_hit_label
# last_hit_label är beskrivande metadata, inte kluster-nyckel.

# ⚠️ Viktigt:

# last_hit_label ska INTE orsaka nya kluster
# Om ett objekt har flera ytor och användaren bryr sig om det → användaren får filtrera / tolka själv
# Kluster = “alla ray‑träffar på detta objekt, vid detta bounce, som kommer från samma tidigare yta”


def aggregate_interaction_clusters(
    *,
    mode="final",
    min_hits=2,
):
    """
    Aggregate spatial clusters per optisk interaktion.

    ✅ Precomputes:
        - density
        - roundness per plane (XY, XZ, YZ)
        - basic power efficiency

    ✅ Retains:
        - centroid
        - covariance
        - spread

    ✅ Backward compatible (mostly)
    """

    import numpy as np
    import math

    # --- local helpers (avoid circular imports) ---
    def density_score(hit_count, radius):
        if hit_count <= 0:
            return 0.0
        density = hit_count / (radius * radius + 1e-6)
        return 1.0 - math.exp(-0.02 * density)

    def radius_2d(points_2d, centroid_2d):
        d = np.linalg.norm(points_2d - centroid_2d, axis=1)
        return float(np.sqrt(np.mean(d**2)))

    def roundness_score_from_cov(cov):
        if cov is None:
            return 0.0
        try:
            A = np.array(cov, dtype=float)
            vals = np.linalg.eigvals(A)
            lam_max = float(np.max(vals).real)
            lam_min = float(np.min(vals).real)

            if lam_max <= 0:
                return 0.0

            return float(np.clip(lam_min / lam_max, 0.0, 1.0))
        except Exception:
            return 0.0

    # ---------------------------------------------------
    # 0) LOAD RAYS
    # ---------------------------------------------------
    rm = OBARayManager()
    rays = [r for r in rm.get_all_rays() if r.mode == mode]

    buckets = defaultdict(list)

    # ---------------------------------------------------
    # 1) BUCKET
    # ---------------------------------------------------
    for ray in rays:
        for h in ray.history:
            if not isinstance(h, dict):
                continue
            if "hit_point" not in h:
                continue

            obj = h.get("object_name")
            bounce = h.get("bounce_index")
            prev = h.get("prev_hit_label")
            last = h.get("last_hit_label")

            if obj is None or bounce is None:
                continue

            extra = h.get("extra", {})

            buckets[(obj, bounce, prev)].append(
                (
                    last,
                    h["hit_point"],
                    extra.get("power_in", 0.0),
                    extra.get("power_out", 0.0),
                    extra.get("absorbed_power", 0.0),
                )
            )

    # ---------------------------------------------------
    # 2) BUILD CLUSTERS
    # ---------------------------------------------------
    clusters = {}
    idx = 0

    for (obj, bounce, prev_hit_label), items in buckets.items():
        if len(items) < min_hits:
            continue

        pts = np.array([p for _, p, *_ in items], dtype=float)

        # --- power ---
        power_in = sum(pin for _, _, pin, _, _ in items)
        power_out = sum(pout for _, _, _, pout, _ in items)
        power_abs = sum(pabs for _, _, _, _, pabs in items)

        power_efficiency = power_out / (power_in + 1e-9)

        # --- labels ---
        last_hit_labels = sorted({l for l, *_ in items})

        # --- centroid ---
        centroid_3d = pts.mean(axis=0)

        # ---------- PROJECTIONS ----------
        proj = {
            "XY": pts[:, [0, 1]],
            "XZ": pts[:, [0, 2]],
            "YZ": pts[:, [1, 2]],
        }

        centroid_plane = {k: proj[k].mean(axis=0) for k in proj}

        # ---------- COV ----------
        cov_plane = {k: np.cov(proj[k].T).tolist() if len(proj[k]) >= 3 else None for k in proj}

        cov_3d = np.cov(pts.T).tolist() if len(pts) >= 3 else None

        # ---------- RADIER ----------
        radius_3d_max = float(np.max(np.linalg.norm(pts - centroid_3d, axis=1)))
        radius_3d_rms = float(np.sqrt(np.mean(np.sum((pts - centroid_3d) ** 2, axis=1))))

        # ---------------------------------------------------
        # ✅ PRECOMPUTED METRICS
        # ---------------------------------------------------
        hit_count = len(pts)

        # --- density (kan vara samma men dupliceras per plan för enkelhet)
        density_3d = density_score(hit_count, radius_3d_rms)

        # ---------- RADIER ----------
        radius_3d_rms = float(np.sqrt(np.mean(np.sum((pts - centroid_3d) ** 2, axis=1))))

        radius_xy = radius_2d(proj["XY"], centroid_plane["XY"])
        radius_xz = radius_2d(proj["XZ"], centroid_plane["XZ"])
        radius_yz = radius_2d(proj["YZ"], centroid_plane["YZ"])

        # ---------- RAW DENSITY ----------
        raw_3d = hit_count / (radius_3d_rms**3 + 1e-9)
        raw_xy = hit_count / (radius_xy**2 + 1e-9)
        raw_xz = hit_count / (radius_xz**2 + 1e-9)
        raw_yz = hit_count / (radius_yz**2 + 1e-9)

        # ---------- NORMALISERA ----------
        def norm(x):
            return 1.0 - math.exp(-0.01 * x)

        # --- roundness
        roundness_3d = roundness_score_from_cov(cov_3d)

        # dämpa brus
        # scale = scale ** 0.5   # mindre aggressivt
        scale = min(1.0, hit_count / 20.0)

        roundness_3d *= scale

        roundness_vals = {
            "3D": roundness_score_from_cov(cov_3d),
            "XY": roundness_score_from_cov(cov_plane["XY"]),
            "XZ": roundness_score_from_cov(cov_plane["XZ"]),
            "YZ": roundness_score_from_cov(cov_plane["YZ"]),
        }

        roundness_vals = {k: v * scale for k, v in roundness_vals.items()}

        # ---------------------------------------------------
        cluster_id = f"{idx}:{obj}:B{bounce}:P{prev_hit_label}"
        idx += 1

        clusters[cluster_id] = {
            # --------------------------------------------------
            # CORE DATA
            # --------------------------------------------------
            "object": obj,
            "bounce": bounce,
            "prev_hit_label": prev_hit_label,
            "last_hit_labels": last_hit_labels,
            "hit_count": hit_count,
            "points": pts,
            "power": {
                "in": float(power_in),
                "out": float(power_out),
                "absorbed": float(power_abs),
                "efficiency": float(power_efficiency),
            },
            # --------------------------------------------------
            # POSITION
            # --------------------------------------------------
            "centroid": {
                "3D": tuple(map(float, centroid_3d)),
                "XY": tuple(map(float, centroid_plane["XY"])),
                "XZ": tuple(map(float, centroid_plane["XZ"])),
                "YZ": tuple(map(float, centroid_plane["YZ"])),
            },
            # --------------------------------------------------
            # SPREAD
            # --------------------------------------------------
            "spread": {
                "3D": {
                    "radius": float(radius_3d_rms),
                    "radius_max": float(radius_3d_max),
                    "cov": cov_3d,
                },
                "XY": {"cov": cov_plane["XY"]},
                "XZ": {"cov": cov_plane["XZ"]},
                "YZ": {"cov": cov_plane["YZ"]},
            },
            # --------------------------------------------------
            # ✅ NEW: PRECOMPUTED METRICS
            # --------------------------------------------------
            # "density": {
            #     "3D": norm(raw_3d),
            #     "XY": norm(raw_xy),
            #     "XZ": norm(raw_xz),
            #     "YZ": norm(raw_yz),
            # },
            "density": {
                "3D": raw_3d,
                "XY": raw_xy,
                "XZ": raw_xz,
                "YZ": raw_yz,
            },
            "roundness": {
                "3D": float(roundness_vals["3D"]),
                "XY": float(roundness_vals["XY"]),
                "XZ": float(roundness_vals["XZ"]),
                "YZ": float(roundness_vals["YZ"]),
            },
        }

    return clusters


def aggregate_interaction_clusters_old(
    *,
    mode="final",
    min_hits=2,
):
    """
    Aggregate spatial clusters per optisk interaktion.

    ✅ Alla plan räknas ut (XY, XZ, YZ)
    ✅ Backward compatible (delvis)
    """

    rm = OBARayManager()
    rays = [r for r in rm.get_all_rays() if r.mode == mode]

    buckets = defaultdict(list)

    # ---------------------------------------------------
    # 1) BUCKET
    # ---------------------------------------------------
    for ray in rays:
        for h in ray.history:
            if not isinstance(h, dict):
                continue
            if "hit_point" not in h:
                continue

            obj = h.get("object_name")
            bounce = h.get("bounce_index")
            prev = h.get("prev_hit_label")
            last = h.get("last_hit_label")

            if obj is None or bounce is None:
                continue
            # buckets[(obj, bounce, prev)].append((last, h["hit_point"]))
            extra = h.get("extra", {})
            buckets[(obj, bounce, prev)].append(
                (
                    last,
                    h["hit_point"],
                    extra.get("power_in", 0.0),
                    extra.get("power_out", 0.0),
                    extra.get("absorbed_power", 0.0),
                )
            )

    # ---------------------------------------------------
    # 2) BUILD CLUSTERS
    # ---------------------------------------------------
    clusters = {}
    idx = 0

    for (obj, bounce, prev_hit_label), items in buckets.items():
        if len(items) < min_hits:
            continue

        # pts = np.array([p for _, p in items], dtype=float)
        pts = np.array([p for _, p, *_ in items], dtype=float)
        power_in = sum(pin for _, _, pin, _, _ in items)
        power_out = sum(pout for _, _, _, pout, _ in items)
        power_abs = sum(pabs for _, _, _, _, pabs in items)

        last_hit_labels = sorted({l for l, *_ in items})

        centroid_3d = pts.mean(axis=0)

        # ---------- ALL PLANES ----------
        proj = {
            "XY": pts[:, [0, 1]],
            "XZ": pts[:, [0, 2]],
            "YZ": pts[:, [1, 2]],
        }

        centroid_plane = {k: proj[k].mean(axis=0) for k in proj}

        cov_plane = {k: np.cov(proj[k].T).tolist() if len(proj[k]) >= 3 else None for k in proj}

        # ---------- RADIER ----------
        radius_3d_max = float(np.max(np.linalg.norm(pts - centroid_3d, axis=1)))
        radius_3d_rms = float(np.sqrt(np.mean(np.sum((pts - centroid_3d) ** 2, axis=1))))

        cov_3d = np.cov(pts.T) if len(pts) >= 3 else None

        cluster_id = f"{idx}:{obj}:B{bounce}:P{prev_hit_label}"
        idx += 1

        clusters[cluster_id] = {
            # --------------------------------------------------
            # GAMLA
            # --------------------------------------------------
            "object": obj,
            "bounce": bounce,
            "prev_hit_label": prev_hit_label,
            "last_hit_labels": last_hit_labels,
            "hit_count": len(pts),
            "points": pts,
            "power": {
                "in": float(power_in),
                "out": float(power_out),
                "absorbed": float(power_abs),
            },
            # --------------------------------------------------
            # SCORING STRUCTURE
            # --------------------------------------------------
            # ✅ POSITION
            "centroid": {
                "3D": tuple(map(float, centroid_3d)),
                "XY": tuple(map(float, centroid_plane["XY"])),
                "XZ": tuple(map(float, centroid_plane["XZ"])),
                "YZ": tuple(map(float, centroid_plane["YZ"])),
            },
            # ✅ SPRIDNING  cov = covariance matrix (kovariansmatris)
            "spread": {
                "3D": {
                    "radius": float(radius_3d_rms),
                    "radius_max": float(radius_3d_max),
                    "cov": cov_3d.tolist() if cov_3d is not None else None,
                },
                "XY": {
                    "cov": cov_plane["XY"],
                },
                "XZ": {
                    "cov": cov_plane["XZ"],
                },
                "YZ": {
                    "cov": cov_plane["YZ"],
                },
            },
        }

    return clusters


def debug_print_surface_clusters(
    *,
    plane="XY",
    mode="final",
    min_hits=2,
    max_points_preview=3,
):
    """
    Skriver ut ett ASCII-träd över surface-clusters i konsolen.

    ✅ KORREKT HIERARKI:
        object → bounce → prev_hit_label → cluster

    last_hit_labels visas som metadata (inte struktur).
    """

    clusters = aggregate_interaction_clusters(
        plane=plane,
        mode=mode,
        min_hits=min_hits,
    )

    if not clusters:
        print("[DEBUG] No clusters found.")
        return

    # --------------------------------------------------
    # 1. Bygg hierarkisk struktur
    # --------------------------------------------------
    tree = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))  # object  # bounce  # prev_hit_label → clusters

    for cid, c in clusters.items():
        obj = c["object"]
        bounce = c["bounce"]
        prev_hit = c.get("prev_hit_label")

        tree[obj][bounce][prev_hit].append((cid, c))

    # --------------------------------------------------
    # 2. Skriv ASCII-träd
    # --------------------------------------------------
    print("\n" + "=" * 60)
    print("DEBUG: SURFACE CLUSTER TREE")
    print(f"Plane={plane}, Mode={mode}, min_hits={min_hits}")
    print("=" * 60)

    for obj in sorted(tree):
        print(f"\nObject: {obj}")
        print("│")

        for bounce in sorted(tree[obj]):
            print(f"├─ Bounce {bounce}")
            print("│")

            for prev_hit in sorted(tree[obj][bounce], key=lambda x: str(x)):
                prev_str = prev_hit if prev_hit is not None else "∅"
                print(f"│  ├─ Prev surface: {prev_str}")

                for cid, c in tree[obj][bounce][prev_hit]:
                    hits = c["hit_count"]
                    radius = c["radius_3d"]
                    cx, cy = c["centroid_plane"]

                    last_labels = c.get("last_hit_labels", [])
                    last_str = ", ".join(last_labels) if last_labels else "∅"

                    print(f"│  │  ├─ Cluster {cid}" f" | surfaces=[{last_str}]" f" | hits={hits}" f" | radius={radius:.3g}" f" | centroid=({cx:.3g}, {cy:.3g})")

                    pts = c["points"]
                    preview = pts[:max_points_preview]

                    for i, p in enumerate(preview):
                        print(f"│  │  │   p{i}: ({p[0]:.3g}, {p[1]:.3g}, {p[2]:.3g})")

                    if len(pts) > max_points_preview:
                        print(f"│  │  │   … ({len(pts) - max_points_preview} more points)")

    print("\n" + "=" * 60)
    print(f"[DEBUG] Total clusters: {len(clusters)}")
    print("=" * 60 + "\n")


# ===============================================


def aggregate_path_statistics(
    *,
    mode="final",
    min_bounce=None,
    max_bounce=None,
    hit_selection="all",  # "all" | "incoming" | "outgoing"
):
    """
    Aggregate path-based statistics from OBARayManager.

    Grouping key:
        (emitter_id, path_signature)

    path_signature = sekvens av:
        (object_name, last_hit_label)

    Detta är INTE kluster-analys.
    Detta beskriver hela optiska strålgångar (paths).
    """

    rm = OBARayManager()

    hit_records = []
    groups = {}

    for ray in rm.get_all_rays():

        if mode and ray.mode != mode:
            continue

        # --------------------------------------------------
        # Path-signatur: exakt optisk bana (label-baserad)
        # --------------------------------------------------
        path_signature = tuple((h.get("object_name"), h.get("last_hit_label")) for h in ray.history if isinstance(h, dict) and "hit_point" in h)

        ray_points = []
        ray_bounces = []
        power_in_sum = 0.0
        power_out_sum = 0.0
        absorbed_power_sum = 0.0

        for h in ray.history:

            if not isinstance(h, dict):
                continue
            if "hit_point" not in h:
                continue

            bounce = h.get("bounce_index", 0)

            if min_bounce is not None and bounce < min_bounce:
                continue
            if max_bounce is not None and bounce > max_bounce:
                continue

            extra = h.get("extra", {})

            hit = {
                "ray_id": h.get("ray_id"),
                "parent_id": h.get("parent_id"),
                "path_id": h.get("path_id"),
                "path_signature": path_signature,
                "emitter_id": ray.emitter_id,
                # optisk/topologisk info
                "object": h.get("object_name"),
                "last_hit_label": h.get("last_hit_label"),
                "prev_hit_label": h.get("prev_hit_label"),
                # geometri
                "bounce": bounce,
                "point": h.get("hit_point"),
                # energi
                "power_out": h.get("power_out", 0.0),
                "power_in": extra.get("power_in", 0.0),
                "absorbed_power": extra.get("absorbed_power", 0.0),
            }

            hit_records.append(hit)
            ray_points.append(hit["point"])
            ray_bounces.append(bounce)

            power_out_sum += hit["power_out"]
            power_in_sum += hit["power_in"]
            absorbed_power_sum += hit["absorbed_power"]

        if not ray_points:
            continue

        # --------------------------------------------------
        # REPRESENTATIVA PUNKTER PER PATH
        # --------------------------------------------------
        if hit_selection == "incoming":
            selected_points = [ray_points[0]]
        elif hit_selection == "outgoing":
            selected_points = [ray_points[-1]]
        else:  # "all"
            selected_points = [ray_points[0], ray_points[-1]] if len(ray_points) > 1 else [ray_points[0]]

        key = (ray.emitter_id, path_signature)

        g = groups.setdefault(
            key,
            {
                "points": [],
                "bounces": [],
                "power_in": 0.0,
                "power_out": 0.0,
                "absorbed_power": 0.0,
            },
        )

        g["points"].extend(selected_points)
        g["bounces"].extend(ray_bounces)
        g["power_in"] += power_in_sum
        g["power_out"] += power_out_sum
        g["absorbed_power"] += absorbed_power_sum

    # --------------------------------------------------
    # FINALIZE PATH STATS
    # --------------------------------------------------
    path_stats = {}

    for key, g in groups.items():
        pts = g["points"]
        if not pts:
            continue

        n = len(pts)
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
        cz = sum(p[2] for p in pts) / n

        path_stats[key] = {
            "centroid": (cx, cy, cz),
            "count": n,
            "power_in": g["power_in"],
            "power_out": g["power_out"],
            "absorbed_power": g["absorbed_power"],
            "min_bounce": min(g["bounces"]),
            "max_bounce": max(g["bounces"]),
            "mean_bounce": sum(g["bounces"]) / len(g["bounces"]),
            "points": pts,
        }

    return hit_records, path_stats


# ============================================================
# 1. CORE: collect hits + groups
# ============================================================


def collect_ray_hits_and_stats(
    mode="final",
    *,
    min_bounce=None,
    max_bounce=None,
    hit_selection="all",  # "all" | "incoming" | "outgoing"
):
    """
    Returnerar hit-data och path/statistik.

    hit_selection:
        "incoming"  -> endast första träffen per ray
        "outgoing"  -> endast sista träffen per ray
        "all"       -> första + sista träffen per ray (DEFAULT, rekommenderat)
    """

    rm = OBARayManager()
    hits = []
    groups = {}

    for ray in rm.get_all_rays():
        if mode and ray.mode != mode:
            continue

        # --------------------------------------------------
        # Exakt strålgång (label-baserad path-signatur)
        # --------------------------------------------------
        path_signature = tuple((h.get("object_name"), h.get("last_hit_label")) for h in ray.history if isinstance(h, dict) and "hit_point" in h)

        ray_points = []
        ray_bounces = []
        ray_power_out = 0.0
        ray_power_in = 0.0
        ray_absorbed = 0.0

        for h in ray.history:
            if not isinstance(h, dict):
                continue
            if "hit_point" not in h:
                continue

            bounce = h.get("bounce_index", 0)

            if min_bounce is not None and bounce < min_bounce:
                continue
            if max_bounce is not None and bounce > max_bounce:
                continue

            extra = h.get("extra", {})

            hit = {
                # identitet
                "ray_id": h.get("ray_id"),
                "parent_id": h.get("parent_id"),
                "path_id": h.get("path_id"),
                "path_signature": path_signature,
                "emitter_id": ray.emitter_id,
                # optik / topologi
                "object": h.get("object_name"),
                "last_hit_label": h.get("last_hit_label"),
                "prev_hit_label": h.get("prev_hit_label"),
                # geometri
                "bounce": bounce,
                "point": h.get("hit_point"),
                # energi
                "power_out": h.get("power_out", 0.0),
                "power_in": extra.get("power_in", 0.0),
                "absorbed_power": extra.get("absorbed_power", 0.0),
            }

            hits.append(hit)

            ray_points.append(hit["point"])
            ray_bounces.append(bounce)

            ray_power_out += hit["power_out"]
            ray_power_in += hit["power_in"]
            ray_absorbed += hit["absorbed_power"]

        if not ray_points:
            continue

        # --------------------------------------------------
        # Välj REPRESENTATIVA punkter per ray
        # --------------------------------------------------
        if hit_selection == "incoming":
            selected_points = [ray_points[0]]
        elif hit_selection == "outgoing":
            selected_points = [ray_points[-1]]
        else:  # "all"
            selected_points = [ray_points[0], ray_points[-1]] if len(ray_points) > 1 else [ray_points[0]]

        key = (ray.emitter_id, path_signature)

        g = groups.setdefault(
            key,
            {
                "points": [],
                "bounces": [],
                "power_in_sum": 0.0,
                "power_out_sum": 0.0,
                "absorbed_power_sum": 0.0,
            },
        )

        g["points"].extend(selected_points)
        g["bounces"].extend(ray_bounces)
        g["power_out_sum"] += ray_power_out
        g["power_in_sum"] += ray_power_in
        g["absorbed_power_sum"] += ray_absorbed

    # --------------------------------------------------
    # FINALIZE STATISTIK
    # --------------------------------------------------
    stats = {}

    for key, g in groups.items():
        pts = g["points"]
        if not pts:
            continue

        n = len(pts)
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
        cz = sum(p[2] for p in pts) / n

        stats[key] = {
            "centroid": (cx, cy, cz),
            "count": n,
            "power_in": g["power_in_sum"],
            "power_out": g["power_out_sum"],
            "absorbed_power": g["absorbed_power_sum"],
            "min_bounce": min(g["bounces"]),
            "max_bounce": max(g["bounces"]),
            "mean_bounce": sum(g["bounces"]) / len(g["bounces"]),
            "hit_points": pts,
        }

    return hits, stats


# ============================================================
# 3. BACKWARD-FRIENDLY WRAPPER
# ============================================================


def analyze_rays(mode="final"):
    """
    Enkel wrapper som matchar gamla analyzers API-stil.

    :return: dict med:
        {
            "hits":  platt lista av träffar,
            "stats": grupperad statistik
        }
    """
    hits, stats = collect_ray_hits_and_stats(mode=mode)
    return {
        "hits": hits,
        "stats": stats,
    }


# ============================================================
# 4. DEBUG / CLI
# ============================================================

if __name__ == "__main__":
    result = analyze_rays(mode="final")

    print("Top clusters by hit count:\n")
    for gid, s in sorted(
        result["stats"].items(),
        key=lambda kv: kv[1]["count"],
        reverse=True,
    )[:10]:
        print(
            gid,
            "hits:",
            s["count"],
            "centroid:",
            tuple(round(c, 3) for c in s["centroid"]),
            "radius:",
            f"{s['radius_3d']:.3g}",
        )
