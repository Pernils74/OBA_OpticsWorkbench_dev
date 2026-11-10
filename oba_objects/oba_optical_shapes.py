import math
import Part
import FreeCAD as App

SHAPES = [
    "Plane",
    "Prism",
    "Box",
    "PlanoConvex",
    "PlanoConcave",
    "BiConvex",
    "BiConcave",
]

SHAPE_PROPERTIES = {
    "Plane": [
        {"type": "App::PropertyLength", "name": "Width", "group": "Geometry", "default": 10.0},
        {"type": "App::PropertyLength", "name": "Height", "group": "Geometry", "default": 10.0},
    ],
    "Prism": [
        {"type": "App::PropertyLength", "name": "Width", "group": "Geometry", "default": 20.0},
        {"type": "App::PropertyLength", "name": "Height", "group": "Geometry", "default": 20.0},
        {"type": "App::PropertyLength", "name": "Length", "group": "Geometry", "default": 40.0},
    ],
    "Box": [
        {"type": "App::PropertyLength", "name": "Width", "group": "Geometry", "default": 20.0},
        {"type": "App::PropertyLength", "name": "Height", "group": "Geometry", "default": 20.0},
        {"type": "App::PropertyLength", "name": "Length", "group": "Geometry", "default": 20.0},
    ],
    "PlanoConvex": [
        {"type": "App::PropertyLength", "name": "Diameter", "group": "Geometry", "default": 50.0},
        {"type": "App::PropertyLength", "name": "Thickness", "group": "Geometry", "default": 10.0},
        {"type": "App::PropertyLength", "name": "Radius1", "group": "Geometry", "default": 100.0},
        {"type": "App::PropertyBool", "name": "UseDShape", "group": "Aperture", "default": False},
        {"type": "App::PropertyLength", "name": "FlatDistance", "group": "Aperture", "default": 0.0},
    ],
    "PlanoConcave": [
        {"type": "App::PropertyLength", "name": "Diameter", "group": "Geometry", "default": 50.0},
        {"type": "App::PropertyLength", "name": "Thickness", "group": "Geometry", "default": 10.0},
        {"type": "App::PropertyLength", "name": "Radius1", "group": "Geometry", "default": 100.0},
        {"type": "App::PropertyBool", "name": "UseDShape", "group": "Aperture", "default": False},
        {"type": "App::PropertyFloat", "name": "FlatDistance", "group": "Aperture", "default": 0.0},
    ],
    "BiConvex": [
        {"type": "App::PropertyLength", "name": "Diameter", "group": "Geometry", "default": 50.0},
        {"type": "App::PropertyLength", "name": "Thickness", "group": "Geometry", "default": 10.0},
        {"type": "App::PropertyFloat", "name": "Radius1", "group": "Geometry", "default": 100.0},
        {"type": "App::PropertyFloat", "name": "Radius2", "group": "Geometry", "default": -100.0},
        {"type": "App::PropertyBool", "name": "UseDShape", "group": "Aperture", "default": False},
        {"type": "App::PropertyFloat", "name": "FlatDistance", "group": "Aperture", "default": 0.0},
    ],
    "BiConcave": [
        {"type": "App::PropertyLength", "name": "Diameter", "group": "Geometry", "default": 50.0},
        {"type": "App::PropertyLength", "name": "Thickness", "group": "Geometry", "default": 10.0},
        {"type": "App::PropertyFloat", "name": "Radius1", "group": "Geometry", "default": -100.0},
        {"type": "App::PropertyFloat", "name": "Radius2", "group": "Geometry", "default": 100.0},
        {"type": "App::PropertyBool", "name": "UseDShape", "group": "Aperture", "default": False},
        {"type": "App::PropertyFloat", "name": "FlatDistance", "group": "Aperture", "default": 0.0},
    ],
}


def _num(obj, name, default=0.0):
    value = getattr(obj, name, default)
    return float(value.Value if hasattr(value, "Value") else value)


def shape_is_ready(obj):
    return all(p["name"] in obj.PropertiesList for p in SHAPE_PROPERTIES.get(str(obj.ShapeType), []))


def apply_dshape(shape, obj, diameter, thickness):
    radius = diameter / 2.0
    if not getattr(obj, "UseDShape", False):
        return shape

    flat = _num(obj, "FlatDistance", radius)
    if flat < 0 or flat >= radius:
        return shape

    cutter = Part.makeBox(diameter, diameter * 2.0, thickness * 2.0)
    cutter.translate(App.Vector(flat, -diameter, -thickness))
    return shape.cut(cutter)


def _plane(obj):
    width = _num(obj, "Width", 10.0)
    height = _num(obj, "Height", 10.0)
    points = [
        App.Vector(-width / 2, -height / 2, 0),
        App.Vector(width / 2, -height / 2, 0),
        App.Vector(width / 2, height / 2, 0),
        App.Vector(-width / 2, height / 2, 0),
    ]
    points.append(points[0])
    return Part.Face(Part.makePolygon(points))


def _box(obj):
    width = _num(obj, "Width", 20.0)
    height = _num(obj, "Height", 20.0)
    length = _num(obj, "Length", 20.0)
    result = Part.makeBox(width, height, length)
    result.translate(App.Vector(-width / 2, -height / 2, 0))
    return result


def _prism(obj):
    width = _num(obj, "Width", 20.0)
    height = _num(obj, "Height", 20.0)
    length = _num(obj, "Length", 40.0)
    points = [
        App.Vector(-width / 2, 0, 0),
        App.Vector(width / 2, 0, 0),
        App.Vector(0, height, 0),
    ]
    points.append(points[0])
    face = Part.Face(Part.makePolygon(points))
    return face.extrude(App.Vector(0, 0, length))


def _lens(obj):
    diameter = _num(obj, "Diameter", 50.0)
    thickness = _num(obj, "Thickness", 10.0)
    radius = diameter / 2.0

    if diameter <= 0 or thickness <= 0:
        return Part.Shape()

    cylinder = Part.makeCylinder(radius, thickness)
    st = str(obj.ShapeType)
    if st not in ("PlanoConvex", "PlanoConcave", "BiConvex", "BiConcave"):
        return cylinder

    r1 = abs(_num(obj, "Radius1", 100.0))
    r2 = abs(_num(obj, "Radius2", 100.0))

    if r1 <= radius:
        return cylinder

    sag1 = r1 - math.sqrt(max(0.0, r1 * r1 - radius * radius))

    if st == "PlanoConvex":
        base = Part.makeCylinder(radius, max(0.001, thickness - sag1))
        sphere = Part.makeSphere(r1)
        sphere.translate(App.Vector(0, 0, thickness - r1))
        cap_cyl = Part.makeCylinder(radius, sag1 + 0.001)
        cap_cyl.translate(App.Vector(0, 0, thickness - sag1))
        result = base.fuse(sphere.common(cap_cyl))

    elif st == "PlanoConcave":
        sphere = Part.makeSphere(r1)
        sphere.translate(App.Vector(0, 0, thickness + r1 - sag1))
        result = cylinder.cut(sphere)

    elif st == "BiConvex":
        if r1 <= radius or r2 <= radius:
            return cylinder

        # Beräkna sagitta (bukthöjd) för båda sidor
        sag1 = r1 - math.sqrt(max(0.0, r1 * r1 - radius * radius))
        sag2 = r2 - math.sqrt(max(0.0, r2 * r2 - radius * radius))

        # För en bikonvex lins är 'thickness' oftast scentrumtjockleken (max tjocklek).
        # Vi skapar en cylinder som täcker hela linsens höjd.
        lens_cylinder = Part.makeCylinder(radius, thickness)

        # Övre sfären: Flyttas så att dess nederkant skär cylindern vid (thickness - sag1)
        sphere1 = Part.makeSphere(r1)
        sphere1.translate(App.Vector(0, 0, thickness - r1))

        # Undre sfären: Centrum flyttas UNDER Z=0 så att dess överkant sticker upp exakt 'sag2'
        sphere2 = Part.makeSphere(r2)
        sphere2.translate(App.Vector(0, 0, -(r2 - sag2)))

        # Resultatet är där alla tre kroppar överlappar
        result = lens_cylinder.common(sphere1).common(sphere2)

    elif st == "BiConcave":
        if r1 <= radius or r2 <= radius:
            return cylinder

        # Beräkna sagitta för båda sidor
        sag1 = r1 - math.sqrt(max(0.0, r1 * r1 - radius * radius))
        sag2 = r2 - math.sqrt(max(0.0, r2 * r2 - radius * radius))

        # 'thickness' är centrumtjockleken (smalaste punkten).
        # Cylinderns totala höjd måste därför vara centrum + båda kanternas höjd.
        total_height = thickness + sag1 + sag2
        lens_cylinder = Part.makeCylinder(radius, total_height)

        # Övre sfären: Placeras så att den klipper ner i cylinderns topp
        sphere1 = Part.makeSphere(r1)
        sphere1.translate(App.Vector(0, 0, total_height + r1 - sag1))

        # Undre sfären: Placeras så att den klipper upp i cylinderns botten
        sphere2 = Part.makeSphere(r2)
        sphere2.translate(App.Vector(0, 0, -r2 + sag2))

        # Klipp ut sfärerna ur den höga cylindern
        result = lens_cylinder.cut(sphere1).cut(sphere2)

        # Valfritt: Flytta linsen nedåt så att dess geometriska centrum hamnar vid Z=0
        # result.translate(App.Vector(0, 0, -sag2))

    return apply_dshape(result, obj, diameter, thickness)


def build_shape(obj):
    st = str(obj.ShapeType)
    if st == "Plane":
        return _plane(obj)
    if st == "Box":
        return _box(obj)
    if st == "Prism":
        return _prism(obj)
    return _lens(obj)
