# ray_tracer.py

import FreeCAD as App
import FreeCADGui as Gui
import math
import random
import Part
import time
from logger import get_logger

# log = get_logger()

import numpy as np


from PySide import QtWidgets
from .oba_ray_core import OBARay, OBARayManager

from oba_objects.oba_lens_materials import get_refractive_index

# from .oba_rays_phys import find_nearest_intersection, reflect


# -------------------------------------------------------------
# EMITTER TRACE
# -------------------------------------------------------------


def run_normalized_ray_trace(source_obj, ray_gen, engine, max_bounce, max_length, trace_mode, mode):

    rays = list(ray_gen)
    if not rays:
        return 0

    total_weight = sum(w for _, _, w in rays)
    total_power = getattr(source_obj, "Power", 1.0)

    scale = total_power / total_weight

    emitter_name = source_obj.Name
    wavelength = getattr(source_obj, "Wavelength", 550.0)

    start_medium = getattr(source_obj, "StartMedium", "Air")
    n0 = get_refractive_index(start_medium, wavelength_nm=wavelength)

    for p, direction, w in rays:
        power = w * scale
        ray = OBARay(start_point=p, direction=direction, wavelength=wavelength, power=power, emitter_id=emitter_name, mode=mode, medium_stack=[n0])

        # ray.current_n = n0
        # ray.medium_stack = [n0]

        if trace_mode == "OCC":
            propagate_occ(ray, engine, max_bounce, max_length)
        else:
            propagate_mesh(ray, engine, max_bounce, max_length)

    return len(rays)


def trace_emitter(emitter, engine, max_bounce, max_length, trace_mode="OCC", ray_multiplier=1, mode="final"):
    """Hanterar strålar från ytor (Binders)."""
    max_rays = int(getattr(emitter, "MaxRays", 100) * ray_multiplier)
    use_lambert = getattr(emitter, "Lambertian", True)
    spread_angle = float(getattr(emitter, "SpreadAngle", 5.0))
    flip_normal = getattr(emitter, "FlipNormal", False)

    total_traced = 0
    emitter_binders = getattr(emitter, "Binders", [])

    for binder in emitter_binders:
        if not binder.Shape or binder.Shape.isNull():
            continue

        # ✅ FIX: Loopa igenom varje face i listan binder.Shape.Faces
        for f in binder.Shape.Faces:
            # Nu skickar vi en enskild face 'f' istället för hela listan
            ray_gen = populate_emitter_rays(f, max_rays, use_lambert, spread_angle, flip_normal)
            total_traced += run_normalized_ray_trace(emitter, ray_gen, engine, max_bounce, max_length, trace_mode, mode)

    return total_traced


def trace_beam(beam, engine, max_bounce, max_length, trace_mode="OCC", ray_multiplier=1, mode="final"):
    """Hanterar strålar från punktkällor (Beam)."""
    # from raytracer.oba_ray_tracer import populate_beam_rays

    max_rays = int(beam.MaxRays * ray_multiplier)
    ray_gen = populate_beam_rays(beam, max_rays, beam.SpreadAngle, lambert=getattr(beam, "Lambertian", False))

    return run_normalized_ray_trace(beam, ray_gen, engine, max_bounce, max_length, trace_mode, mode)


# -------------------------------------------------------------
# EMITTER SAMPLING
# -------------------------------------------------------------


def populate_emitter_rays(face, max_rays, use_lambert, spread_angle, flip_normal):
    import math

    u1, u2, v1, v2 = face.ParameterRange
    grid_n = max(1, int(math.sqrt(max_rays)))

    du = (u2 - u1) / grid_n
    dv = (v2 - v1) / grid_n

    center = face.CenterOfMass
    u0, v0 = face.Surface.parameter(center)
    center_normal = face.normalAt(u0, v0).normalize()
    if flip_normal:
        center_normal = -center_normal

    max_dist = max((vtx.Point - center).Length for vtx in face.Vertexes)

    count = 0
    for i in range(grid_n):
        for j in range(grid_n):
            if count >= max_rays:
                return

            u = u1 + (i + 0.5) * du
            v = v1 + (j + 0.5) * dv
            p = face.valueAt(u, v)

            if not face.isInside(p, 1e-6, True):
                continue

            direction = get_emitter_cone_surface_dir(
                center=center,
                center_normal=center_normal,
                p=p,
                max_angle_deg=spread_angle,
                max_dist=max_dist,
            )

            if use_lambert:
                theta = center_normal.getAngle(direction)
                weight = max(0.0, math.cos(theta))
            else:
                weight = 1.0

            yield (p, direction, weight)
            count += 1


def populate_beam_rays(obj, max_rays, spread_angle, lambert=False):
    """
    Deterministisk beam-sampling:
    - Samma spridning som populate_beam_rays_old
    - Lambert-vikt = cos(theta) relativt beam-axeln
    """

    import math
    import FreeCAD as App

    rot = obj.Placement.Rotation
    origin = obj.Placement.Base

    # Beam-axel i världssystem
    axis = rot.multVec(App.Vector(0, 0, 1)).normalize()

    # --- 1 stråle ---
    if spread_angle <= 0 or max_rays <= 1:
        direction = axis
        weight = 1.0
        yield origin, direction, weight
        return

    theta_max = math.radians(spread_angle)

    # -------------------------------------------------
    # 2 strålar
    # -------------------------------------------------
    if max_rays == 2:
        # center
        yield origin, axis, 1.0

        # kant
        d_local = App.Vector(
            math.sin(theta_max),
            0,
            math.cos(theta_max),
        )
        direction = rot.multVec(d_local).normalize()
        w = direction.dot(axis) if lambert else 1.0
        yield origin, direction, max(w, 0.0)
        return

    # -------------------------------------------------
    # 3 strålar
    # -------------------------------------------------
    if max_rays == 3:
        for i in range(3):
            phi = 2 * math.pi * i / 3
            d_local = App.Vector(
                math.sin(theta_max) * math.cos(phi),
                math.sin(theta_max) * math.sin(phi),
                math.cos(theta_max),
            )
            direction = rot.multVec(d_local).normalize()
            w = direction.dot(axis) if lambert else 1.0
            yield origin, direction, max(w, 0.0)
        return

    # -------------------------------------------------
    # GENERISK RING-SAMPLING (som gamla)
    # -------------------------------------------------
    # center-ray
    yield origin, axis, 1.0

    n_remaining = max_rays - 1
    num_rings = int(math.sqrt(n_remaining / 3.0))
    if num_rings < 1:
        num_rings = 1

    total_weight = (num_rings * (num_rings + 1)) / 2
    rays_placed = 0

    for r in range(1, num_rings + 1):
        if r == num_rings:
            n_ring = n_remaining - rays_placed
        else:
            n_ring = int(round((r / total_weight) * n_remaining))

        if n_ring <= 0:
            continue

        theta = (r / num_rings) * theta_max

        for i in range(n_ring):
            phi_offset = r * 0.5
            phi = (2 * math.pi * i / n_ring) + phi_offset

            d_local = App.Vector(
                math.sin(theta) * math.cos(phi),
                math.sin(theta) * math.sin(phi),
                math.cos(theta),
            )

            direction = rot.multVec(d_local).normalize()

            if lambert:
                w = direction.dot(axis)
                if w <= 0:
                    continue
            else:
                w = 1.0

            yield origin, direction, w

        rays_placed += n_ring


def get_emitter_cone_surface_dir(center, center_normal, p, max_angle_deg, max_dist):
    offset = p - center
    dist = offset.Length

    if dist < 1e-9:
        return center_normal

    # tangentkomponenten
    offset_tangent = offset - center_normal * offset.dot(center_normal)
    if offset_tangent.Length < 1e-9:
        return center_normal
    offset_tangent.normalize()

    relative = dist / max_dist
    max_angle_rad = math.radians(max_angle_deg)
    local_angle = relative * max_angle_rad

    # axis*cos + tangent*sin
    dir_vec = center_normal * math.cos(local_angle) + offset_tangent * math.sin(local_angle)
    return dir_vec.normalize()


# -------------------------------------------------------------
# PROPAGATION
# -------------------------------------------------------------


def reflect(direction, normal):
    """Standard reflektionsvektor: r = d - 2*(d·n)*n"""
    return (direction - 2.0 * direction.dot(normal) * normal).normalize()


def refract(incident, normal, n1, n2):
    """
    Beräknar brytningsriktning enligt Snells lag.
    Returnerar None vid total internal reflection (TIR).

    incident, normal: NORMALISERADE vektorer
    n1: brytningsindex i inkommande medium
    n2: brytningsindex i utgående medium
    """
    # cos(theta_i)
    cos_i = -incident.dot(normal)
    # Förhållande av brytningsindex
    eta = n1 / n2
    # Snells lag: k = 1 - eta^2 (1 - cos_i^2)
    k = 1.0 - eta * eta * (1.0 - cos_i * cos_i)
    if k < 0.0:
        # Total intern reflektion
        return None
    # Refrakterad riktning
    refracted = incident * eta + normal * (eta * cos_i - (k**0.5))
    # return refracted.normalized()
    return refracted.normalize()


def ray_intersects_bbox_fast(origin, inv_dir, bbox):
    """
    Kollar om en stråle skär en AABB (Bounding Box).
    bbox = (xmin, xmax, ymin, ymax, zmin, zmax)
    inv_dir = (1/dx, 1/dy, 1/dz)
    """
    # X-axeln
    t1 = (bbox[0] - origin.x) * inv_dir[0]
    t2 = (bbox[1] - origin.x) * inv_dir[0]
    tmin = min(t1, t2)
    tmax = max(t1, t2)

    # Y-axeln
    t1 = (bbox[2] - origin.y) * inv_dir[1]
    t2 = (bbox[3] - origin.y) * inv_dir[1]
    tmin = max(tmin, min(t1, t2))
    tmax = min(tmax, max(t1, t2))

    # Z-axeln
    t1 = (bbox[4] - origin.z) * inv_dir[2]
    t2 = (bbox[5] - origin.z) * inv_dir[2]
    tmin = max(tmin, min(t1, t2))
    tmax = min(tmax, max(t1, t2))

    return tmax >= max(0.0, tmin)


def handle_optical_interaction(
    ray,
    hit_p,
    normal,
    incoming_dir,
    props,
    # target_label,
    # previous_face,
):
    """
    Utför optisk interaktion på 'ray'.
    Returnerar en lista med nya strålar (0..N) som ska propagras vidare.
    """
    # target_label = ray.last_hit_label  # last_hit_face_label är satt via add_segment

    last_hit_label = ray.last_hit_label
    prev_hit_label = ray.prev_hit_label

    spawned_rays = []
    o_type = props.get("OpticalType", "Absorber")

    # ==================================================
    # 0. Effektiv normal (fysik)
    # ==================================================
    normal_eff = normal
    if props.get("FlipNormal", False):
        normal_eff = -normal_eff

    if o_type in ("Mirror", "MirrorBuilder"):
        P_in = ray.power
        R = props.get("Reflectivity", 1.0)
        T = props.get("Transmissivity", 0.0)
        # --- Reflektion ger ALLTID ny ray ---
        if R > 1e-6:
            reflect_dir = reflect(incoming_dir, normal_eff)
            spawned_rays.append(
                ray.spawn_child(
                    direction=reflect_dir,
                    power=P_in * R,
                    offset=normal_eff * 1e-4,
                    extra={
                        "type": "mirror_reflection",
                        "power_in": P_in,
                        "power_out": P_in * R,
                        "reflectivity": R,
                    },
                )
            )
        # --- Transmission (om halvgenomskinlig spegel) ---
        if T > 1e-6:
            spawned_rays.append(
                ray.spawn_child(
                    direction=incoming_dir,
                    power=P_in * T,
                    offset=-normal_eff * 1e-4,
                    extra={
                        "type": "mirror_transmission",
                        "power_in": P_in,
                        "power_out": P_in * T,
                    },
                )
            )
        # ✅ Parent-rayen är klar
        ray.power = 0.0

        ray.log_bounce(
            props["Name"],
            o_type,
            last_hit_label,  # gamla target_label
            prev_hit_label,
            hit_p,
            normal_eff,
            incoming_dir,
            None,
            extra={
                "power_in": P_in,
                "power_out": P_in * (R + T),
                "absorbed_power": P_in * (1.0 - R - T),
                "reflected_power": P_in * R,
                "transmitted_power": P_in * T,
            },
        )
    # ==================================================
    # LENSE
    # ==================================================

    elif o_type in ("Lens", "LensBuilder"):

        P_in = ray.power
        surface_n = props.get("RefractiveIndex", 1.5)
        use_fresnel = props.get("UseFresnel", False)

        # 1. Bestäm om vi går IN eller UT baserat på strålens nuvarande medium
        # Om strålen redan befinner sig i detta medium (eller linsen), är den på väg UT.
        if abs(ray.current_n - surface_n) < 1e-5:
            entering = False
        else:
            entering = True

        # 2. Hantera normalen så att den ALLTID pekar MOT den inkommande strålen.
        # Detta krävs för att standardfunktioner för brytning (refract) och reflektion (reflect) ska fungera.
        dot = incoming_dir.dot(normal_eff)
        if dot < 0:
            normal_l = normal_eff
        else:
            normal_l = -normal_eff

        # n1 är mediet strålen kommer FRÅN
        n1 = ray.current_n

        # 3. Bestäm n2 (mediet strålen går TILL)
        if entering:
            n2 = surface_n
        else:
            # Vid utgång: Hämta föregående medium i stacken (oftast luft/vakuum = 1.0)
            n2 = ray.medium_stack[-2] if len(ray.medium_stack) > 1 else 1.0

        # Beräkna brytningsvinkeln (refract förväntar sig normalen vänd MOT strålen)
        refract_dir = refract(incoming_dir, normal_l, n1, n2)

        def fresnel_schlick(incident, normal, n1, n2):
            # abs() säkrar att cosinus alltid blir positiv (mellan 0 och 1) oavsett normalriktning
            cosi = max(0.0, min(1.0, -incident.dot(normal)))
            r0 = ((n1 - n2) / (n1 + n2)) ** 2
            return r0 + (1 - r0) * (1 - cosi) ** 5

        # 4. Beräkna reflektion (R) och transmission (T)
        if not refract_dir:
            R = 1.0  # Totalreflektion (händer oftast vid utgång i skarpa vinklar)
        elif use_fresnel:
            R = fresnel_schlick(incoming_dir, normal_l, n1, n2)
        else:
            R = 0.0

        T = 1.0 - R

        # --- Logga träffen på parent-rayen ---
        ray.log_bounce(
            props["Name"],
            o_type,
            last_hit_label,
            prev_hit_label,
            hit_p,
            normal_l,
            incoming_dir,
            None,
            extra={
                "power_in": P_in,
                "power_out": P_in * T,
                "absorbed_power": P_in * (1.0 - R - T),
                "R": R,
                "T": T,
            },
        )

        # --- Fresnel-reflektion (NY bounce) ---
        if R > 1e-6:
            # Reflektion studsar TILLBAKA till mediet vi kom ifrån.
            # Eftersom normal_l pekar mot strålen, knuffar vi positions-offset LÄNGS normal_l.
            spawned_rays.append(
                ray.spawn_child(
                    direction=reflect(incoming_dir, normal_l),
                    power=P_in * R,
                    offset=normal_l * 1e-4,
                    extra={"type": "lens_reflection"},
                )
            )

        # --- Refraktion (NY bounce) ---
        if refract_dir and T > 1e-6:
            # Brytning fortsätter FRAMÅT in i nästa medium.
            # Vi knuffar positions-offset MOTSATT normal_l för att trycka igenom strålen till andra sidan ytan.
            child = ray.spawn_child(
                direction=refract_dir,
                power=P_in * T,
                offset=-normal_l * 1e-4,
                extra={"type": "lens_refraction"},
            )

            # ✅ Hantera medium-stacken för den brutna strålen
            if entering:
                child.enter_medium(n2)
            else:
                child.exit_medium()

            spawned_rays.append(child)

        # ✅ Parent-rayen är färdig
        ray.power = 0.0

    # ==================================================
    # GRATING
    # ==================================================
    elif o_type == "Grating":
        import math

        P_in = ray.power
        lines_per_mm = props.get("LinesPerMM", 600.0)
        num_spectral_rays = int(props.get("SpectrumRays", 5))
        m = 1  # diffraktionsordning

        # Gitterperiod i nm
        d_nm = 1_000_000.0 / lines_per_mm

        # Synligt spektrum
        lambda_min, lambda_max = 400.0, 700.0
        step = (lambda_max - lambda_min) / max(1, num_spectral_rays - 1)

        # Lokala axlar på ytan
        up = App.Vector(0, 0, 1)
        if abs(normal_eff.dot(up)) > 0.99:
            up = App.Vector(1, 0, 0)

        grating_dir = normal_eff.cross(up).normalize()
        dispersion_dir = normal_eff.cross(grating_dir).normalize()

        per_ray_power = P_in / max(1, num_spectral_rays)

        num_children = 0

        # --- Skapa diffrakterade barn-rays (NY bounce) ---
        for i in range(num_spectral_rays):
            wl = lambda_min + i * step

            # Gitterekvationen
            sin_in = incoming_dir.dot(dispersion_dir)
            sin_out = sin_in + (m * wl) / d_nm

            if abs(sin_out) > 1.0:
                continue  # ingen fysisk lösning

            cos_out = math.sqrt(1.0 - sin_out**2)
            sign = 1.0 if incoming_dir.dot(normal_eff) > 0 else -1.0

            comp_grating = incoming_dir.dot(grating_dir)

            refract_dir = (dispersion_dir * sin_out + grating_dir * comp_grating + normal_eff * (sign * cos_out)).normalize()

            spawned_rays.append(
                ray.spawn_child(
                    direction=refract_dir,
                    power=per_ray_power,
                    offset=normal_eff * (sign * 1e-4),
                    wavelength=wl,
                    extra={
                        "type": "grating_order",
                        "order": m,
                        "wavelength": wl,
                        "lines_per_mm": lines_per_mm,
                    },
                )
            )

            num_children += 1

        # --- Logga träffen på parent-rayen ---

        ray.log_bounce(
            props["Name"],
            o_type,
            last_hit_label,
            prev_hit_label,
            hit_p,
            normal_eff,
            incoming_dir,
            None,  # ✅ parent-rayen dör här
            extra={
                "power_in": P_in,
                "power_out": P_in,  # ✅ all effekt lämnar via diffrakterade ordningar
                "absorbed_power": 0.0,  # ✅ ingen absorption antagen
                "num_children": num_children,
                "lines_per_mm": lines_per_mm,
            },
        )

        # ✅ Parent-rayen är färdig
        ray.power = 0.0

    # ==================================================
    # ABSORBER
    # ==================================================

    else:
        absorption = props.get("Absorption", 1.0)

        P_in = ray.power
        P_abs = P_in * absorption
        P_out = P_in - P_abs

        # --- Ev. transmission (child) ---
        if P_out > 1e-12:
            spawned_rays.append(
                ray.spawn_child(
                    direction=incoming_dir,
                    power=P_out,
                    offset=-normal_eff * 1e-4,
                    extra={
                        "type": "absorber_transmission",
                        "power_in": P_in,
                        "power_out": P_out,
                        "absorption": absorption,
                    },
                )
            )

        # --- Parent-ray är alltid klar ---
        ray.power = 0.0

        ray.log_bounce(
            props["Name"],
            o_type,
            last_hit_label,
            prev_hit_label,
            hit_p,
            normal_eff,
            incoming_dir,
            None,
            extra={
                "power_in": P_in,
                "absorbed_power": P_abs,
                "transmitted_power": P_out,
            },
        )

    return spawned_rays


def propagate_occ(ray, ray_targets, max_bounce, max_length):
    from Part import LineSegment

    for _ in range(max_bounce):

        if ray.bounce_count >= max_bounce:
            break

        origin = ray.last_point
        direction = ray.direction

        inv_dir = (
            1.0 / direction.x if direction.x != 0 else 1e12,
            1.0 / direction.y if direction.y != 0 else 1e12,
            1.0 / direction.z if direction.z != 0 else 1e12,
        )

        best_dist = max_length
        hit_data = None

        ray_line = LineSegment(
            origin,
            origin + direction * max_length,
        ).toShape()

        # --------------------------------------------------
        # HIT DETECTION
        # --------------------------------------------------

        for target in ray_targets:

            if not ray_intersects_bbox_fast(
                origin,
                inv_dir,
                target["bbox"],
            ):
                continue

            dist, points, _ = target["face"].distToShape(ray_line)

            if dist < 1e-6:

                p = points[0][0]
                d = (p - origin).Length

                if 1e-6 < d < best_dist:

                    best_dist = d
                    hit_data = (target, p)

        # --------------------------------------------------
        # NO HIT
        # --------------------------------------------------

        if not hit_data:
            ray.add_segment(
                origin + direction * max_length,
                interaction_type="Void",
            )
            break

        target, hit_p = hit_data

        props = target["props"]
        face = target["face"]

        # --------------------------------------------------
        # NORMAL
        # --------------------------------------------------

        u, v = face.Surface.parameter(hit_p)

        normal = face.normalAt(u, v).normalize()
        raw_normal = normal

        if normal.dot(direction) > 0:
            normal = -normal
        incoming_dir = direction

        # ==================================================
        # DETECTOR = OBSERVER
        # ==================================================

        if props.get("OpticalType") == "Detector":
            mode = props.get("HitMode")  # , "Both")
            if isinstance(mode, int):
                mode = ["Both", "Front", "Back"][mode]
            dot = incoming_dir.dot(raw_normal)
            if mode == "Front" and dot > 0:
                continue

            if mode == "Back" and dot < 0:
                continue

            P_in = ray.power
            detector_label = target["label"]
            ray.log_bounce(
                props["Name"],
                "Detector",
                detector_label,
                ray.prev_hit_label,
                hit_p,
                normal,
                incoming_dir,
                incoming_dir,
                extra={
                    "power_in": P_in,
                    "power_out": P_in,
                    "detected_power": P_in,
                    "wavelength": ray.wavelength,
                },
            )

            # Silent detector: record the hit but do not treat the detector as an optical bounce.
            ray.add_segment(hit_p, interaction_type="Detector")

            child = ray.spawn_child(
                direction=incoming_dir,
                power=P_in,
                offset=incoming_dir * 1e-4,
            )
            child.last_facet = None
            child.last_target_id = None
            ray = child
            continue

        # ==================================================
        # VANLIG OPTIK
        # ==================================================

        ray.add_segment(
            hit_p,
            hit_face_label=target["label"],
        )

        ray.bounce_count += 1

        spawned = handle_optical_interaction(
            ray,
            hit_p,
            normal,
            incoming_dir,
            props,
        )

        for child in spawned:
            propagate_occ(
                child,
                ray_targets,
                max_bounce,
                max_length,
            )

        if ray.power < 1e-12:
            break


def propagate_mesh(ray, mesh_targets, max_bounce, max_length):

    from .oba_intersect_mesh import ray_mesh_intersect_numpy

    for _ in range(max_bounce):

        if ray.bounce_count >= max_bounce:
            break

        origin = ray.last_point
        direction = ray.direction

        origin_np = np.array(
            [origin.x, origin.y, origin.z],
            dtype=np.float32,
        )

        direction_np = np.array(
            [direction.x, direction.y, direction.z],
            dtype=np.float32,
        )

        inv_dir = (
            1.0 / direction.x if direction.x != 0 else 1e12,
            1.0 / direction.y if direction.y != 0 else 1e12,
            1.0 / direction.z if direction.z != 0 else 1e12,
        )

        best_dist = max_length
        best_hit = None
        for target in mesh_targets:
            if not ray_intersects_bbox_fast(
                origin,
                inv_dir,
                target["bbox"],
            ):
                continue
            ts, us, vs = ray_mesh_intersect_numpy(
                origin_np,
                direction_np,
                target["tri_array"],
            )
            if ray.last_facet is not None and id(target) == ray.last_target_id:
                ts[ray.last_facet] = np.inf
            min_idx = np.argmin(ts)
            min_t = ts[min_idx]
            if 1e-6 < min_t < best_dist:
                best_dist = float(min_t)
                hit_point = origin + direction * best_dist
                best_hit = (
                    target,
                    int(min_idx),
                    float(us[min_idx]),
                    float(vs[min_idx]),
                    hit_point,
                )
        # --------------------------------------------------
        # NO HIT
        # --------------------------------------------------

        if not best_hit:
            ray.add_segment(
                origin + direction * max_length,
                interaction_type="Void",
            )
            break
        target, tid, u, v, hit_p = best_hit
        props = target["props"]
        ray.last_facet = tid
        ray.last_target_id = id(target)

        # --------------------------------------------------
        # NORMAL
        # --------------------------------------------------

        n_tri = target["norm_array"][tid]

        n0, n1, n2 = n_tri

        w = 1.0 - u - v

        res_n = n0 * w + n1 * u + n2 * v

        normal = App.Vector(*res_n).normalize()

        raw_normal = normal
        if normal.dot(direction) > 0:
            normal = -normal
        incoming_dir = direction

        # ==================================================
        # DETECTOR = OBSERVER
        # ==================================================

        # if props.get("OpticalType") == "Detector":
        #     print("[DETECTOR HIT] wl =", ray.wavelength)
        #     print("[target]", target, target["label"])

        if props.get("OpticalType") == "Detector":
            mode = props.get("HitMode")  # , "Both")

            if isinstance(mode, int):
                mode = ["Both", "Front", "Back"][mode]
            dot = incoming_dir.dot(raw_normal)
            if mode == "Front" and dot > 0:
                continue
            if mode == "Back" and dot < 0:
                continue

            P_in = ray.power
            detector_label = target["label"]

            ray.log_bounce(
                props["Name"],
                "Detector",
                detector_label,
                ray.prev_hit_label,
                hit_p,
                normal,
                incoming_dir,
                incoming_dir,
                extra={
                    "power_in": P_in,
                    "power_out": P_in,
                    "detected_power": P_in,
                    "wavelength": ray.wavelength,
                },
            )

            # Silent detector: record the hit but keep the ray optical state unchanged.
            ray.add_segment(hit_p, interaction_type="Detector")

            child = ray.spawn_child(
                direction=incoming_dir,
                power=P_in,
                offset=incoming_dir * 1e-4,
            )
            child.last_facet = None
            child.last_target_id = None
            ray = child

            continue

        # ==================================================
        # VANLIG OPTIK
        # ==================================================

        ray.add_segment(
            hit_p,
            hit_face_label=target["label"],
        )

        ray.bounce_count += 1
        spawned = handle_optical_interaction(
            ray,
            hit_p,
            normal,
            incoming_dir,
            props,
        )
        for child in spawned:
            propagate_mesh(
                child,
                mesh_targets,
                max_bounce,
                max_length,
            )

        if ray.power < 1e-12:
            break


# -------------------------------------
# -------------------------------------
# -------------------------------------
