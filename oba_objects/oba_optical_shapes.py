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
]

# ============================================================
# SHAPE PROPERTIES
# ============================================================
SHAPE_PROPERTIES_ol2 = {
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
    "Concave": [  # Menisklins (Tunnast i mitten, båda kurvorna åt samma håll)
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
            "default": 200.0,
        },
    ],
    "Convex": [  # Menisklins (Tjockast i mitten, båda kurvorna åt samma håll)
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
        {
            "type": "App::PropertyFloat",
            "name": "Radius2",
            "group": "Shape",
            "default": 100.0,
        },
    ],
    "Concave-D": [
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
        {
            "type": "App::PropertyFloat",
            "name": "FlatDistance",
            "group": "Shape",
            "default": 25.0,  # Matchar r (D/2) som standard = ingen kapning
        },
    ],
}


SHAPE_PROPERTIES = {
    "Plane": [
        {"type": "App::PropertyFloat", "name": "Width", "group": "Shape", "default": 10.0},
        {"type": "App::PropertyFloat", "name": "Height", "group": "Shape", "default": 10.0},
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


def build_shape_old(obj):
    # if not shape_is_ready(obj):
    #     return

    st = obj.ShapeType

    # Snabbretur för Plane eftersom den inte använder cylinderparametrar
    if st == "Plane":
        w = getattr(obj, "Width", 10.0)
        h = getattr(obj, "Height", 10.0)
        p1 = App.Vector(-w / 2, -h / 2, 0)
        p2 = App.Vector(w / 2, -h / 2, 0)
        p3 = App.Vector(w / 2, h / 2, 0)
        p4 = App.Vector(-w / 2, h / 2, 0)
        wire = Part.makePolygon([p1, p2, p3, p4, p1])
        return Part.Face(wire)

    # Standardparametrar för runda linser
    D = obj.Diameter
    T = obj.Thickness
    r = D / 2.0
    cyl = Part.makeCylinder(r, T)

    # --------------------------------------------------------
    # PLANO CONVEX
    # --------------------------------------------------------
    if st == "PlanoConvex":
        R = abs(obj.Radius1)
        if R <= r:
            App.Console.PrintWarning(f"Invalid geometry: Radius {R} <= aperture {r}\n")
            return cyl

        sag = R - math.sqrt(R * R - r * r)
        base = Part.makeCylinder(r, T - sag)

        sphere = Part.makeSphere(R)
        sphere.translate(App.Vector(0, 0, T - R))

        cap_cyl = Part.makeCylinder(r, sag + 0.001)
        cap_cyl.translate(App.Vector(0, 0, T - sag))

        cap = sphere.common(cap_cyl)
        return base.fuse(cap)

    # --------------------------------------------------------
    # PLANO CONCAVE
    # --------------------------------------------------------
    if st == "PlanoConcave":
        R = abs(obj.Radius1)
        if R <= r:
            App.Console.PrintWarning(f"Invalid geometry: Radius {R} <= aperture {r}\n")
            return cyl

        sag = R - math.sqrt(R * R - r * r)
        sphere = Part.makeSphere(R)
        sphere.translate(App.Vector(0, 0, T + R - sag))
        return cyl.cut(sphere)

    # --------------------------------------------------------
    # BI CONVEX
    # --------------------------------------------------------
    if st == "BiConvex":
        R1 = abs(obj.Radius1)
        R2 = abs(obj.Radius2)
        if R1 <= r or R2 <= r:
            App.Console.PrintWarning("Invalid geometry: Radius <= aperture\n")
            return cyl

        s1 = Part.makeSphere(R1)
        s2 = Part.makeSphere(R2)
        s1.translate(App.Vector(0, 0, T - R1))
        s2.translate(App.Vector(0, 0, R2))

        shape = cyl.common(s1)
        shape = shape.common(s2)
        return shape

    # --------------------------------------------------------
    # BI CONCAVE
    # --------------------------------------------------------
    if st == "BiConcave":
        R1 = abs(obj.Radius1)
        R2 = abs(obj.Radius2)
        if R1 <= r or R2 <= r:
            App.Console.PrintWarning("Invalid geometry: Radius <= aperture\n")
            return cyl

        sag1 = R1 - math.sqrt(R1 * R1 - r * r)
        sag2 = R2 - math.sqrt(R2 * R2 - r * r)

        if (sag1 + sag2) >= T:
            App.Console.PrintWarning("Invalid geometry: Sagitta sum exceeds thickness\n")
            return cyl

        s1 = Part.makeSphere(R1)
        s2 = Part.makeSphere(R2)
        s1.translate(App.Vector(0, 0, T + (R1 - sag1)))
        s2.translate(App.Vector(0, 0, -(R2 - sag2)))

        shape = cyl.cut(s1)
        shape = shape.cut(s2)
        return shape

    # --------------------------------------------------------
    # CONCAVE (Menisk - Tunnast i mitten)
    # --------------------------------------------------------
    if st == "Concave":
        R1 = abs(obj.Radius1)  # Insidan (mindre radie, brantare krökning)
        R2 = abs(obj.Radius2)  # Utsidan (större radie, flackare krökning)
        if R1 <= r or R2 <= r:
            return cyl

        sag1 = R1 - math.sqrt(R1 * R1 - r * r)
        sag2 = R2 - math.sqrt(R2 * R2 - r * r)

        # Skapa yttre konvexa formen först (snitt av cylinder och sfär 2)
        s2 = Part.makeSphere(R2)
        s2.translate(App.Vector(0, 0, T - R2 + sag2))
        shape = cyl.common(s2)

        # Skär bort sfär 1 från undersidan för att göra den konkav
        s1 = Part.makeSphere(R1)
        s1.translate(App.Vector(0, 0, R1 + (T - sag1) - T))  # Justerad för korrekt mittentjocklek
        shape = shape.cut(s1)
        return shape

    # --------------------------------------------------------
    # CONVEX (Menisk - Tjockast i mitten)

    # --------------------------------------------------------
    # CONVEX (Menisk - Tjockast i mitten)
    # --------------------------------------------------------
    if st == "Convex":
        R1 = abs(obj.Radius1)  # Utsidan (större radie)
        R2 = abs(obj.Radius2)  # Insidan (mindre radie)

        if R1 <= r or R2 <= r:
            App.Console.PrintWarning("Invalid geometry: Radius <= aperture\n")
            return cyl

        sag1 = R1 - math.sqrt(R1 * R1 - r * r)
        sag2 = R2 - math.sqrt(R2 * R2 - r * r)

        # Skapa den konvexa fronten
        s1 = Part.makeSphere(R1)
        s1.translate(App.Vector(0, 0, T - R1))
        shape = cyl.common(s1)

        # Skär bort den bakre sfären (krökt åt samma håll)
        s2 = Part.makeSphere(R2)
        s2.translate(App.Vector(0, 0, T - sag1 + sag2 - R2))
        shape = shape.cut(s2)
        return shape

    # --------------------------------------------------------
    # CONCAVE-D
    # --------------------------------------------------------
    if st == "Concave-D":
        R = abs(obj.Radius1)

        if R <= r:
            App.Console.PrintWarning("Invalid geometry: Radius <= aperture\n")
            return cyl

        sag = R - math.sqrt(R * R - r * r)

        # Skapa konkav lins
        sphere = Part.makeSphere(R)
        sphere.translate(App.Vector(0, 0, T + (R - sag)))
        concave = cyl.cut(sphere)

        # Hämta FlatDistance (standardvärde är radien = ingen kapning)
        flat_dist = getattr(obj, "FlatDistance", r)
        if flat_dist >= r:
            return concave

        # Kapa av sidan med en box
        box = Part.makeBox(D, D * 2.0, T * 2.0)
        box.translate(App.Vector(flat_dist, -D, -T))
        dshape = concave.cut(box)
        return dshape


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


SHAPE_PROPERTIES_old = {
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
    "Concave-D": [
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
        {
            "type": "App::PropertyFloat",
            "name": "FlatDistance",  # Mätt från centrum till platta kanten
            "group": "Shape",
            "default": 0.0,  # Samma som radien (ingen kapning som standard)
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
