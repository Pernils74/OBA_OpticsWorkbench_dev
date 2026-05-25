# oba_ray_scene.py
# oba_ray_scene.py
import FreeCAD as App
import Part


# -------------------------------------------------------------
# SCENE COLLECTION  nya
# -------------------------------------------------------------
def collect_scene(doc):
    beams = []
    emitters = []
    ray_targets = []

    for obj in doc.Objects:
        if App.GuiUp and obj.ViewObject and not obj.ViewObject.Visibility:
            continue

        o_type = getattr(obj, "OpticalType", None)
        if not o_type:
            continue

        if o_type == "Beam":
            beams.append(obj)
            continue

        if o_type == "Emitter":
            emitters.append(obj)
            continue

        # Dynamisk cache: Hämta alla egenskaper som inte börjar med underscore
        # Detta gör att du slipper uppdatera koden när du lägger till nya fält i FreeCAD
        obj_props = {p: getattr(obj, p) for p in obj.PropertiesList if not p.startswith("_")}
        obj_props["Name"] = obj.Name  # Se till att namnet finns med
        # obj_props["obj"] = obj # lägger ref till sig själv.

        binders = getattr(obj, "Binders", [])
        for b in binders:
            if not b.Shape or b.Shape.isNull():
                continue

            for i, face in enumerate(b.Shape.Faces):
                bb = face.BoundBox

                # ✅ Tyngdpunkt
                center = face.CenterOfMass

                # ✅ Normal i tyngdpunkten
                try:
                    u, v = face.Surface.parameter(center)
                    normal = face.normalAt(u, v)
                    if normal.Length > 0:
                        normal.normalize()
                except Exception:
                    normal = None

                ray_targets.append(
                    {"face": face, "bbox": (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax), "obj_ref": obj, "props": obj_props, "label": f"{obj.Name}_{b.Name}_F{i}", "surface_center": center, "surface_normal": normal}
                )  # För loggning

    return beams, emitters, ray_targets


# -------------------------------------------------------------
# AABB RAY TEST
# -------------------------------------------------------------
def ray_intersects_bbox_fast(origin, inv_dir, bbox):
    # bbox = (xmin, xmax, ymin, ymax, zmin, zmax)
    # inv_dir = (1/dx, 1/dy, 1/dz) - Beräknas en gång per stråle!

    t1 = (bbox[0] - origin.x) * inv_dir[0]
    t2 = (bbox[1] - origin.x) * inv_dir[0]
    tmin = min(t1, t2)
    tmax = max(t1, t2)

    for i in range(1, 3):
        t1 = (bbox[i * 2] - origin[i]) * inv_dir[i]
        t2 = (bbox[i * 2 + 1] - origin[i]) * inv_dir[i]
        tmin = max(tmin, min(t1, t2))
        tmax = min(tmax, max(t1, t2))

    return tmax >= max(0.0, tmin)


# -------------------------------------------------------------
# -------------------------------------------------------------
# -------------------------------------------------------------
# -------------------------------------------------------------
# -------------------------------------------------------------
# -------------------------------------------------------------
# -------------------------------------------------------------
# -------------------------------------------------------------
#
