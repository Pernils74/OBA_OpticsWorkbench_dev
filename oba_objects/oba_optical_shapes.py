# oba_optical_shapes.py
import math

import Part
import FreeCAD as App

# ============================================================
# SHAPES
# ============================================================

SHAPES = [
    "Plane",
    "PlanoConvex",
    "PlanoConcave",
    "BiConvex",
    "BiConcave",
    "Concave",
    "Convex",
]

# ============================================================
# SHAPE PROPERTIES
# ============================================================
SHAPE_PROPERTIES = {
    "Plane": [
        {
            "type": "App::PropertyFloat",
            "name": "Width",
            "group": "Shape",
            "default": 10.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Height",
            "group": "Shape",
            "default": 10.0,
        },
    ],
    "PlanoConvex": [
        {
            "type": "App::PropertyFloat",
            "name": "Diameter",
            "group": "Geometry",
            "default": 50.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Thickness",
            "group": "Geometry",
            "default": 10.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Radius1",
            "group": "Shape",
            "default": 100.0,
        },
    ],
    "PlanoConcave": [
        {
            "type": "App::PropertyFloat",
            "name": "Diameter",
            "group": "Geometry",
            "default": 50.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Thickness",
            "group": "Geometry",
            "default": 10.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Radius1",
            "group": "Shape",
            "default": 100.0,
        },
    ],
    "BiConvex": [
        {
            "type": "App::PropertyFloat",
            "name": "Diameter",
            "group": "Geometry",
            "default": 50.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Thickness",
            "group": "Geometry",
            "default": 10.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Radius1",
            "group": "Shape",
            "default": 100.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Radius2",
            "group": "Shape",
            "default": -100.0,
        },
    ],
    "BiConcave": [
        {
            "type": "App::PropertyFloat",
            "name": "Diameter",
            "group": "Geometry",
            "default": 50.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Thickness",
            "group": "Geometry",
            "default": 10.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Radius1",
            "group": "Shape",
            "default": -100.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Radius2",
            "group": "Shape",
            "default": 100.0,
        },
    ],
    "Concave": [
        {
            "type": "App::PropertyFloat",
            "name": "Diameter",
            "group": "Geometry",
            "default": 50.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Thickness",
            "group": "Geometry",
            "default": 10.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Radius1",
            "group": "Shape",
            "default": 200.0,
        },
    ],
    "Convex": [
        {
            "type": "App::PropertyFloat",
            "name": "Diameter",
            "group": "Geometry",
            "default": 50.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Thickness",
            "group": "Geometry",
            "default": 10.0,
        },
        {
            "type": "App::PropertyFloat",
            "name": "Radius1",
            "group": "Shape",
            "default": 200.0,
        },
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


def build_shape(obj):

    # if not shape_is_ready(obj):
    #     return

    D = obj.Diameter
    T = obj.Thickness

    st = obj.ShapeType

    cyl = Part.makeCylinder(
        D / 2.0,
        T,
    )

    # --------------------------------------------------------
    # PLANE
    # --------------------------------------------------------

    if st == "Plane":

        w = getattr(obj, "Width", obj.Diameter)
        h = getattr(obj, "Height", obj.Diameter)

        p1 = App.Vector(-w / 2, -h / 2, 0)
        p2 = App.Vector(w / 2, -h / 2, 0)
        p3 = App.Vector(w / 2, h / 2, 0)
        p4 = App.Vector(-w / 2, h / 2, 0)

        wire = Part.makePolygon([p1, p2, p3, p4, p1])
        plane = Part.Face(wire)
        return plane

        plane = Part.makePlane(w, h)
        # ✅ CENTERA
        plane.translate(App.Vector(-w / 2.0, -h / 2.0, 0))
        return plane

    # --------------------------------------------------------
    # PLANO CONVEX
    # --------------------------------------------------------

    # if st == "PlanoConvex":
    #     R = abs(obj.Radius1)
    #     sphere = Part.makeSphere(R)
    #     sphere.translate(App.Vector(0, 0, T - R))
    #     return cyl.common(sphere)

    if st == "PlanoConvex_old":
        R = abs(obj.Radius1)
        r = D / 2.0
        sag = R - math.sqrt(R * R - r * r)
        # ----------------------------------------------------
        # bascylinder
        # ----------------------------------------------------
        base = Part.makeCylinder(r, T - sag)
        # ----------------------------------------------------
        # sfär
        # ----------------------------------------------------
        sphere = Part.makeSphere(R)
        # centrum så att topp hamnar vid T
        sphere.translate(App.Vector(0, 0, T - R))
        # ----------------------------------------------------
        # kapa ut cap
        # ----------------------------------------------------
        cap_cyl = Part.makeCylinder(r, sag + 0.001)
        cap_cyl.translate(App.Vector(0, 0, T - sag))
        cap = sphere.common(cap_cyl)
        return base.fuse(cap)

    # --------------------------------------------------------
    # PLANO CONCAVE
    # --------------------------------------------------------

    if st == "PlanoConvex":
        R = abs(obj.Radius1)
        r = D / 2.0
        if R <= r:
            App.Console.PrintWarning(f"Invalid geometry: Radius {R} < aperture {r}, fallback used\n")
            return cyl  # ✅ skydd

        sag = R - math.sqrt(R * R - r * r)
        # ----------------------------------------------------
        # full cylinder
        # ----------------------------------------------------
        base = Part.makeCylinder(r, T - sag)
        # ----------------------------------------------------
        # sphere
        # ----------------------------------------------------
        sphere = Part.makeSphere(R)
        sphere.translate(App.Vector(0, 0, T - R))

        cap_cyl = Part.makeCylinder(r, sag + 0.001)
        cap_cyl.translate(App.Vector(0, 0, T - sag))

        cap = sphere.common(cap_cyl)
        return base.fuse(cap)

    if st == "PlanoConcave":
        R = abs(obj.Radius1)
        r = D / 2.0
        if R <= r:
            App.Console.PrintWarning(f"Invalid geometry: Radius {R} < aperture {r}, fallback used\n")
            return cyl

        sag = R - math.sqrt(R * R - r * r)
        # ----------------------------------------------------
        # full cylinder
        # ----------------------------------------------------
        base = Part.makeCylinder(r, T)
        # ----------------------------------------------------
        # sphere
        # ----------------------------------------------------
        sphere = Part.makeSphere(R)
        # placera för konkav front
        sphere.translate(App.Vector(0, 0, T + R - sag))
        # ----------------------------------------------------
        # cut
        # ----------------------------------------------------        return base.cut(sphere)

    # --------------------------------------------------------
    # BICONVEX
    # --------------------------------------------------------

    if st == "BiConvex":
        R1 = abs(obj.Radius1)
        R2 = abs(obj.Radius2)

        s1 = Part.makeSphere(R1)
        s2 = Part.makeSphere(R2)

        s1.translate(App.Vector(0, 0, T - R1))

        s2.translate(App.Vector(0, 0, R2))
        shape = cyl.common(s1)
        shape = shape.common(s2)
        return shape

    # --------------------------------------------------------
    # CONCAVE MIRROR
    # --------------------------------------------------------

    if st == "Concave":
        R = abs(obj.Radius1)
        sphere = Part.makeSphere(R)
        sagitta = R - math.sqrt(R * R - (D / 2.0) ** 2)
        sphere.translate(App.Vector(0, 0, T + (R - sagitta)))
        return cyl.cut(sphere)

    # --------------------------------------------------------
    # CONVEX MIRROR
    # --------------------------------------------------------

    if st == "Convex":
        R = abs(obj.Radius1)
        sphere = Part.makeSphere(R)
        sphere.translate(App.Vector(0, 0, T - R))
        return cyl.common(sphere)
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
