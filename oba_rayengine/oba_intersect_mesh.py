import FreeCAD as App
import Part
import math
import time


import numpy as np


# Global cache för att slippa beräkna om, den överlever också mellan execute-anrop
_GLOBAL_MESH_CACHE = {}


# ============================================================
# Ray intersect med NumpyArray som ger ca 3x snabbare tracing istället för gamla loopen
# ============================================================


def ray_mesh_intersect_numpy(origin, direction, tri_array):
    """
    Vektoriserad Möller-Trumbore för en hel mesh.

    origin: (3,) numpy array [x, y, z]
    direction: (3,) numpy array [dx, dy, dz]
    tri_array: (N, 3, 3) numpy array [antal_trianglar, hörn_index, xyz]

    Returnerar:
        t: Array (N,) med avstånd till varje triangel (inf om ingen träff)
        u: Array (N,) barycentrisk koordinat u
        v: Array (N,) barycentrisk koordinat v
    """
    eps = 1e-9

    # Packa upp hörn (N, 3)
    v0 = tri_array[:, 0, :]
    v1 = tri_array[:, 1, :]
    v2 = tri_array[:, 2, :]

    # Kanter
    e1 = v1 - v0  # (N, 3)
    e2 = v2 - v0  # (N, 3)

    # h = direction x e2
    h = np.cross(direction, e2)  # (N, 3)

    # a = e1 . h (determinant)
    a = np.einsum("ij,ij->i", e1, h)  # Snabb dot-produkt rad för rad

    # Skapa resultat-arrays fyllda med oändlighet/nollor
    n = tri_array.shape[0]
    t_results = np.full(n, np.inf, dtype=np.float32)
    u_results = np.zeros(n, dtype=np.float32)
    v_results = np.zeros(n, dtype=np.float32)

    # Parallella trianglar (a nära 0)
    parallel_mask = np.abs(a) < eps

    # Undvik division med noll
    inv_a = 1.0 / np.where(parallel_mask, 1.0, a)

    s = origin - v0
    u = inv_a * np.einsum("ij,ij->i", s, h)

    # Maskera ut giltiga u
    mask = (~parallel_mask) & (u >= 0.0) & (u <= 1.0)

    if not np.any(mask):
        return t_results, u_results, v_results

    # q = s x e1
    q = np.cross(s, e1)
    v = inv_a * np.einsum("j,ij->i", direction, q)  # dot-produkt med direction

    # Uppdatera mask med v-villkor
    mask &= (v >= 0.0) & (u + v <= 1.0)

    if not np.any(mask):
        return t_results, u_results, v_results

    # t = e2 . q * inv_a
    t = inv_a * np.einsum("ij,ij->i", e2, q)

    # Slutgiltig mask för t > 0
    mask &= t > eps

    # Sätt värden för de trianglar som faktiskt träffades
    t_results[mask] = t[mask]
    u_results[mask] = u[mask]
    v_results[mask] = v[mask]

    return t_results, u_results, v_results


def build_mesh_engine(ray_targets, tolerance, max_time_sec=20):
    """
    Bygger en högpresterande mesh-motor med Numpy-arrays för blixtsnabb ray-tracing.
    Vertex-normaler beräknas nu alltid som standard för mjuk interpolation.
    """
    global _GLOBAL_MESH_CACHE
    mesh_engine = []
    start_time = time.perf_counter()

    hits = 0
    new_builds = 0

    for target in ray_targets:
        # 1. Timeout-kontroll
        if time.perf_counter() - start_time > max_time_sec:
            App.Console.PrintError(f"[MeshEngine] Build aborted: timeout {max_time_sec}s\n")
            break

        face = target["face"]
        geo_hash = face.hashCode()

        # Unik nyckel för cachen (nu utan use_vertex_normals flaggan)
        cache_key = (geo_hash, round(tolerance, 7))

        if cache_key in _GLOBAL_MESH_CACHE:
            target.update(_GLOBAL_MESH_CACHE[cache_key])
            mesh_engine.append(target)
            hits += 1
            continue

        new_builds += 1

        # 2. Tessellera (generera trianglar från CAD-ytan)
        verts_raw, tris_idx = face.tessellate(tolerance * 0.001)

        # Konvertera till Numpy float32 för prestanda
        verts_np = np.array(verts_raw, dtype=np.float32)
        tris_idx_np = np.array(tris_idx, dtype=np.int32)

        # 3. Skapa Triangel-array (N, 3, 3)
        tri_array = verts_np[tris_idx_np]

        # 4. Beräkna Facett-normaler
        v0, v1, v2 = tri_array[:, 0], tri_array[:, 1], tri_array[:, 2]
        f_norms = np.cross(v1 - v0, v2 - v0)
        norms_len = np.linalg.norm(f_norms, axis=1, keepdims=True)
        f_norms = np.divide(f_norms, norms_len, out=np.zeros_like(f_norms), where=norms_len != 0)

        # 5. Kontrollera orientering mot CAD-ytan
        centers = np.mean(tri_array, axis=1)
        for i in range(min(5, len(centers))):
            c = centers[i]
            u, v = face.Surface.parameter(App.Vector(*c))
            occ_n = face.normalAt(u, v)
            if f_norms[i].dot(np.array([occ_n.x, occ_n.y, occ_n.z])) < 0:
                f_norms = -f_norms
                tri_array = tri_array[:, [0, 2, 1], :]  # Behåll winding order
                break

        # 6. Beräkna Vertex-normaler (Nu obligatoriskt)
        v_normals = np.zeros_like(verts_np)
        # Ackumulera normaler till varje vertex
        for i in range(len(tris_idx_np)):
            idx = tris_idx_np[i]
            v_normals[idx] += f_norms[i]

        # Normalisera vertex-normalerna
        v_norms_len = np.linalg.norm(v_normals, axis=1, keepdims=True)
        v_normals = np.divide(
            v_normals,
            v_norms_len,
            out=np.zeros_like(v_normals),
            where=v_norms_len != 0,
        )

        # Skapa den slutgiltiga norm_arrayen (N, 3, 3) för interpolation
        norm_array = v_normals[tris_idx_np]

        # 7. Spara Bounding Box och data
        bb = face.BoundBox
        bbox_tuple = (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax)

        cache_entry = {
            "tri_array": tri_array,
            "norm_array": norm_array,
            "bbox": bbox_tuple,
            "num_tris": len(tri_array),
        }

        _GLOBAL_MESH_CACHE[cache_key] = cache_entry
        target.update(cache_entry)
        mesh_engine.append(target)

    elapsed = time.perf_counter() - start_time
    App.Console.PrintLog(f"[MeshEngine] Built: {new_builds} new, {hits} cached. Time: {elapsed:.4f}s\n")

    return mesh_engine


def build_mesh_engine_old(ray_targets, tolerance, use_vertex_normals=True, max_time_sec=20):
    """
    Bygger en högpresterande mesh-motor med Numpy-arrays för blixtsnabb ray-tracing.
    Returnerar targets berikade med 'tri_array' (N, 3, 3) och 'norm_array' (N, 3, 3).
    """
    global _GLOBAL_MESH_CACHE
    mesh_engine = []
    start_time = time.perf_counter()

    hits = 0
    new_builds = 0

    for target in ray_targets:
        # 1. Timeout-kontroll
        if time.perf_counter() - start_time > max_time_sec:
            App.Console.PrintError(f"[MeshEngine] Build aborted: timeout {max_time_sec}s\n")
            break

        face = target["face"]
        geo_hash = face.hashCode()

        # Unik nyckel för cachen
        cache_key = (geo_hash, round(tolerance, 7), use_vertex_normals)

        if cache_key in _GLOBAL_MESH_CACHE:
            target.update(_GLOBAL_MESH_CACHE[cache_key])
            mesh_engine.append(target)
            hits += 1
            continue

        new_builds += 1

        # 2. Tessellera (generera trianglar från CAD-ytan)
        # tolerance * 0.001 för att matcha din tidigare skala
        verts_raw, tris_idx = face.tessellate(tolerance * 0.001)

        # Konvertera till Numpy float32 för prestanda
        verts_np = np.array(verts_raw, dtype=np.float32)
        tris_idx_np = np.array(tris_idx, dtype=np.int32)

        # 3. Skapa Triangel-array (N, 3, 3) -> [triangel_index, vertex_index, xyz]
        # Detta är den primära datan för ray-intersection
        tri_array = verts_np[tris_idx_np]

        # 4. Beräkna Normaler
        # Beräkna facett-normaler via kryssprodukt: (v1-v0) x (v2-v0)
        v0, v1, v2 = tri_array[:, 0], tri_array[:, 1], tri_array[:, 2]
        f_norms = np.cross(v1 - v0, v2 - v0)

        # Normalisera facett-normaler
        norms_len = np.linalg.norm(f_norms, axis=1, keepdims=True)
        f_norms = np.divide(f_norms, norms_len, out=np.zeros_like(f_norms), where=norms_len != 0)

        # Kontrollera orientering mot CAD-ytans faktiska normal (viktigt för solid-modeller)
        # Vi testar i triangelns centrum
        centers = np.mean(tri_array, axis=1)
        for i in range(min(5, len(centers))):  # Stickprov räcker oftast om meshen är sammanhängande
            c = centers[i]
            u, v = face.Surface.parameter(App.Vector(*c))
            occ_n = face.normalAt(u, v)
            # Om Numpy-normalen pekar fel väg, vänd hela arrayen
            if f_norms[i].dot(np.array([occ_n.x, occ_n.y, occ_n.z])) < 0:
                f_norms = -f_norms
                # Vi vänder även ordningen på vertexarna för att behålla högerhandsregeln
                tri_array = tri_array[:, [0, 2, 1], :]
                break

        # 5. Hantera Vertex-normaler för snygg interpolation
        if use_vertex_normals:
            # Skapa en mappning från vertex-index till ackumulerad normal
            v_normals = np.zeros_like(verts_np)
            for i in range(len(tris_idx_np)):
                idx = tris_idx_np[i]
                v_normals[idx] += f_norms[i]

            # Normalisera vertex-normalerna
            v_norms_len = np.linalg.norm(v_normals, axis=1, keepdims=True)
            v_normals = np.divide(
                v_normals,
                v_norms_len,
                out=np.zeros_like(v_normals),
                where=v_norms_len != 0,
            )

            # Skapa den slutgiltiga norm_arrayen (N, 3, 3)
            norm_array = v_normals[tris_idx_np]
        else:
            # Använd samma facett-normal för alla tre hörn
            norm_array = np.stack([f_norms, f_norms, f_norms], axis=1)

        # 6. Spara och returnera
        # I build_mesh_engine, vid skapandet av cache_entry:
        bb = face.BoundBox
        bbox_tuple = (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax)

        cache_entry = {
            "tri_array": tri_array,  # Skickas till ray_mesh_intersect_numpy
            "norm_array": norm_array,  # Används för interpolation vid träff
            # "bbox": face.BoundBox,  # För snabb utgallring i loopen
            "bbox": bbox_tuple,  # Nu är den en tuple och kan subscriptas med [0], [1]...
            "num_tris": len(tri_array),
        }

        _GLOBAL_MESH_CACHE[cache_key] = cache_entry
        target.update(cache_entry)
        mesh_engine.append(target)

    elapsed = time.perf_counter() - start_time
    App.Console.PrintLog(f"[MeshEngine] Built: {new_builds} new, {hits} cached. Time: {elapsed:.4f}s\n")

    return mesh_engine
