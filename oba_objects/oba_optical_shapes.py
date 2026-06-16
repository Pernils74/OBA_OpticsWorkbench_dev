# oba_optical_shapes.py
import math

import Part
import FreeCAD as App

# ============================================================
# SHAPES
# ============================================================

SHAPES = [
    "Plane",
    "Prism",  # ✅ ny
    "Box",  # ✅ ny
    "PlanoConvex",
    "PlanoConcave",
    "BiConvex",
    "BiConcave",
]

# ============================================================
# SHAPE PROPERTIES
# ============================================================


SHAPE_PROPERTIES = {
    "Plane": [
        {"type": "App::PropertyFloat", "name": "Width", "group": "Shape", "default": 10.0},
        {"type": "App::PropertyFloat", "name": "Height", "group": "Shape", "default": 10.0},
    ],
    "Prism": [
        {"type": "App::PropertyFloat", "name": "Width", "group": "Geometry", "default": 20.0},
        {"type": "App::PropertyFloat", "name": "Height", "group": "Geometry", "default": 20.0},
        {"type": "App::PropertyFloat", "name": "Length", "group": "Geometry", "default": 40.0},
    ],
    "Box": [
        {"type": "App::PropertyFloat", "name": "Width", "group": "Geometry", "default": 20.0},
        {"type": "App::PropertyFloat", "name": "Height", "group": "Geometry", "default": 20.0},
        {"type": "App::PropertyFloat", "name": "Length", "group": "Geometry", "default": 20.0},
    ],
    "PlanoConvex": [
        {"type": "App::PropertyFloat", "name": "Diameter", "group": "Geometry", "default": 50.0},
        {"type": "App::PropertyFloat", "name": "Thickness", "group": "Geometry", "default": 10.0},
        {"type": "App::PropertyFloat", "name": "Radius1", "group": "Shape", "default": 100.0},
        {"type": "App::PropertyBool", "name": "UseDShape", "group": "Aperture", "default": False},
        {"type": "App::PropertyFloat", "name": "FlatDistance", "group": "Aperture", "default": 0.0},
    ],
    "PlanoConcave": [
        {"type": "App::PropertyFloat", "name": "Diameter", "group": "Geometry", "default": 50.0},
        {"type": "App::PropertyFloat", "name": "Thickness", "group": "Geometry", "default": 10.0},
        {"type": "App::PropertyFloat", "name": "Radius1", "group": "Shape", "default": 100.0},
        {"type": "App::PropertyBool", "name": "UseDShape", "group": "Aperture", "default": False},
        {"type": "App::PropertyFloat", "name": "FlatDistance", "group": "Aperture", "default": 0.0},
    ],
    "BiConvex": [
        {"type": "App::PropertyFloat", "name": "Diameter", "group": "Geometry", "default": 50.0},
        {"type": "App::PropertyFloat", "name": "Thickness", "group": "Geometry", "default": 10.0},
        {"type": "App::PropertyFloat", "name": "Radius1", "group": "Shape", "default": 100.0},
        {"type": "App::PropertyFloat", "name": "Radius2", "group": "Shape", "default": -100.0},
        {"type": "App::PropertyBool", "name": "UseDShape", "group": "Aperture", "default": False},
        {"type": "App::PropertyFloat", "name": "FlatDistance", "group": "Aperture", "default": 0.0},
    ],
    "BiConcave": [
        {"type": "App::PropertyFloat", "name": "Diameter", "group": "Geometry", "default": 50.0},
        {"type": "App::PropertyFloat", "name": "Thickness", "group": "Geometry", "default": 10.0},
        {"type": "App::PropertyFloat", "name": "Radius1", "group": "Shape", "default": -100.0},
        {"type": "App::PropertyFloat", "name": "Radius2", "group": "Shape", "default": 100.0},
        {"type": "App::PropertyBool", "name": "UseDShape", "group": "Aperture", "default": False},
        {"type": "App::PropertyFloat", "name": "FlatDistance", "group": "Aperture", "default": 0.0},
    ],
}

# ============================================================
# BUILD
# ============================================================


def shape_is_ready(obj):
    props = SHAPE_PROPERTIES.get(obj.ShapeType, [])
    for p in props:
        if p["name"] not in obj.PropertiesList:
            return False
    return True


def apply_dshape(shape, obj, D, T):
    r = D / 2.0
    use_d = getattr(obj, "UseDShape", False)

    if not use_d:
        return shape

    flat = getattr(obj, "FlatDistance", r)

    if flat >= r:
        return shape

    box = Part.makeBox(D, D * 2.0, T * 2.0)
    box.translate(App.Vector(flat, -D, -T))

    return shape.cut(box)


def build_shape(obj):

    st = obj.ShapeType

    # -------------------------
    # PLANE
    # -------------------------
    if st == "Plane":
        w = getattr(obj, "Width", 10.0)
        h = getattr(obj, "Height", 10.0)

        p1 = App.Vector(-w / 2, -h / 2, 0)
        p2 = App.Vector(w / 2, -h / 2, 0)
        p3 = App.Vector(w / 2, h / 2, 0)
        p4 = App.Vector(-w / 2, h / 2, 0)

        return Part.Face(Part.makePolygon([p1, p2, p3, p4, p1]))

    # -------------------------
    # BOX
    # -------------------------

    if st == "Box":
        w = getattr(obj, "Width", 10.0)
        h = getattr(obj, "Height", 10.0)
        l = getattr(obj, "Length", 10.0)

        box = Part.makeBox(w, h, l)
        box.translate(App.Vector(-w / 2, -h / 2, 0))

        return box

    # -------------------------
    # PRISM
    # -------------------------

    if st == "Prism":
        w = getattr(obj, "Width", 10.0)
        h = getattr(obj, "Height", 10.0)
        l = getattr(obj, "Length", 10.0)

        # triangel i XY-plan
        p1 = App.Vector(-w / 2, 0, 0)
        p2 = App.Vector(w / 2, 0, 0)
        p3 = App.Vector(0, h, 0)

        wire = Part.makePolygon([p1, p2, p3, p1])
        face = Part.Face(wire)

        prism = face.extrude(App.Vector(0, 0, l))

        return prism
    # -------------------------
    # COMMON
    # -------------------------
    D = obj.Diameter
    T = obj.Thickness
    r = D / 2.0

    cyl = Part.makeCylinder(r, T)

    # -------------------------
    # PLANO CONVEX
    # -------------------------
    if st == "PlanoConvex":
        R = abs(obj.Radius1)
        if R <= r:
            return cyl

        sag = R - math.sqrt(R * R - r * r)

        base = Part.makeCylinder(r, T - sag)

        sphere = Part.makeSphere(R)
        sphere.translate(App.Vector(0, 0, T - R))

        cap_cyl = Part.makeCylinder(r, sag + 0.001)
        cap_cyl.translate(App.Vector(0, 0, T - sag))

        cap = sphere.common(cap_cyl)
        shape = base.fuse(cap)

        return apply_dshape(shape, obj, D, T)

    # -------------------------
    # PLANO CONCAVE
    # -------------------------
    if st == "PlanoConcave":
        R = abs(obj.Radius1)
        if R <= r:
            return cyl

        sag = R - math.sqrt(R * R - r * r)

        sphere = Part.makeSphere(R)
        sphere.translate(App.Vector(0, 0, T + R - sag))

        shape = cyl.cut(sphere)
        return apply_dshape(shape, obj, D, T)

    # -------------------------
    # BI CONVEX
    # -------------------------
    if st == "BiConvex":
        R1 = abs(obj.Radius1)
        R2 = abs(obj.Radius2)

        s1 = Part.makeSphere(R1)
        s2 = Part.makeSphere(R2)

        s1.translate(App.Vector(0, 0, T - R1))
        s2.translate(App.Vector(0, 0, R2))

        shape = cyl.common(s1)
        shape = shape.common(s2)

        return apply_dshape(shape, obj, D, T)

    # -------------------------
    # BI CONCAVE
    # -------------------------
    if st == "BiConcave":
        R1 = abs(obj.Radius1)
        R2 = abs(obj.Radius2)

        sag1 = R1 - math.sqrt(R1 * R1 - r * r)
        sag2 = R2 - math.sqrt(R2 * R2 - r * r)

        s1 = Part.makeSphere(R1)
        s2 = Part.makeSphere(R2)

        s1.translate(App.Vector(0, 0, T + (R1 - sag1)))
        s2.translate(App.Vector(0, 0, -(R2 - sag2)))

        shape = cyl.cut(s1)
        shape = shape.cut(s2)

        return apply_dshape(shape, obj, D, T)

    return cyl


# ============================================================
# DIALOG
# ============================================================


def build_dialog(dlg, obj, layout):

    props = SHAPE_PROPERTIES.get(
        obj.ShapeType,
        [],
    )

    for p in props:

        dlg._spin(
            layout,
            p["name"],
            p["name"],
        )
