import FreeCAD as App
import FreeCADGui as Gui
import Part
import json
import math


# ============================================================
#  U T I L I T I E T E R
# ============================================================


def clean(v):
    """Convert FreeCAD types → JSON serializable."""
    try:
        import FreeCAD

        if isinstance(v, FreeCAD.Units.Quantity):
            return float(v)
    except:
        pass

    if isinstance(v, App.Vector):
        return [v.x, v.y, v.z]

    if isinstance(v, tuple):
        return [clean(i) for i in v]

    if isinstance(v, list):
        return [clean(i) for i in v]

    if isinstance(v, dict):
        return {k: clean(val) for k, val in v.items()}

    if isinstance(v, (str, int, float, bool)) or v is None:
        return v

    return str(v)


def vec(p):
    return [p.x, p.y, p.z]


def to_global(sketch, p):
    return sketch.Placement.multVec(p)


# ============================================================
#  RESOLVERS
# ============================================================


def resolveShapeBinderSupport(binder):
    support = binder.Support
    if not support:
        return None, None

    obj, subs = support[0]
    if subs:
        return obj, subs[0]
    return None, None


def resolveProfileSketch(revolve):
    prof = revolve.Profile
    return prof[0] if isinstance(prof, tuple) else prof


def getRevolveAxis(revolve):
    axis_dir = revolve.Axis.normalize()

    try:
        obj, sub = revolve.ReferenceAxis
        edge = obj.Shape.getElement(sub)
        axis_pos = edge.Placement.Base
    except:
        axis_pos = App.Vector(0, 0, 0)

    return axis_pos, axis_dir


# ============================================================
#  S K E T C H   →   J S O N
# ============================================================


def sketch_to_json(sketch):

    data = {
        "SketchName": sketch.Name,
        "Geometry": [],
        "ExternalGeometry": [],
    }

    for i, geo in enumerate(sketch.Geometry):

        shape = geo.toShape()
        curve = getattr(shape, "Curve", None)

        # Skip unsupported geometry
        if curve is None:
            data["Geometry"].append({"index": i, "type": "Unknown"})
            continue

        # --------------------------------------------------
        # LINE  (Part.Line)
        # --------------------------------------------------
        if isinstance(curve, Part.Line):

            p1 = shape.Vertexes[0].Point
            p2 = shape.Vertexes[1].Point

            data["Geometry"].append(
                {
                    "index": i,
                    "type": "Line",
                    "p1": vec(p1),
                    "p2": vec(p2),
                    "dir": vec(p2 - p1),
                    "length": (p2 - p1).Length,
                }
            )

        # --------------------------------------------------
        # ARC / CIRCLE
        # --------------------------------------------------
        elif isinstance(curve, Part.Circle):

            center = curve.Center
            radius = curve.Radius
            start = shape.Vertexes[0].Point
            end = shape.Vertexes[-1].Point

            data["Geometry"].append(
                {
                    "index": i,
                    "type": "Arc",
                    "center": vec(center),
                    "radius": radius,
                    "start": vec(start),
                    "end": vec(end),
                }
            )

        # --------------------------------------------------
        # BSPLINE
        # --------------------------------------------------
        elif isinstance(curve, Part.BSplineCurve):

            poles = [vec(p) for p in curve.getPoles()]
            data["Geometry"].append(
                {
                    "index": i,
                    "type": "BSpline",
                    "poles": poles,
                    "degree": curve.Degree,
                    "knots": list(curve.getKnots()),
                    "weights": list(curve.getWeights()) if curve.isRational() else None,
                }
            )

        else:
            data["Geometry"].append({"index": i, "type": "Unsupported", "classname": str(type(curve))})

    # External Geometry
    for i, ext in enumerate(sketch.ExternalGeometry):

        obj, sub = ext

        try:
            element = obj.Shape.getElement(sub)
            pts = [vec(v.Point) for v in element.Vertexes]
        except:
            pts = None

        data["ExternalGeometry"].append(
            {
                "index": i,
                "object": obj.Name,
                "subelement": sub,
                "points": pts,
            }
        )

    return data


# ============================================================
#  R E V O L V E
# ============================================================


def revolve_to_json(revolve):

    axis_pos, axis_dir = getRevolveAxis(revolve)

    return {
        "StartAngle_deg": revolve.Angle2,
        "EndAngle_deg": revolve.Angle,
        "MidPlane": getattr(revolve, "Midplane", False),
        "Reversed": getattr(revolve, "Reversed", False),
        "AxisPosition": axis_pos,
        "AxisDirection": axis_dir,
    }


# ============================================================
#  M A I N
# ============================================================


def OBA_FeatureScan():

    doc = App.ActiveDocument
    if not doc:
        print("No active document!")
        return

    print("\n===================================================")
    print(" OBA FULL EXPORT (JSON)")
    print("===================================================\n")

    binders = [o for o in doc.Objects if o.TypeId == "PartDesign::SubShapeBinder"]

    if not binders:
        print("No SubShapeBinders found.")
        return

    for binder in binders:

        print("\n---------------------------------------------------")
        print("SubShapeBinder:", binder.Name)
        print("---------------------------------------------------")

        supObj, supSub = resolveShapeBinderSupport(binder)

        if not supObj:
            print("ERROR: No support")
            continue

        print("Support:", supObj.Name, supSub)

        if supObj.TypeId != "PartDesign::Revolution":
            print("Not a Revolve — skip")
            continue

        sketch = resolveProfileSketch(supObj)
        if not sketch:
            print("ERROR: No sketch")
            continue

        print("Sketch:", sketch.Name)

        data = {
            "SubShapeBinder": binder.Name,
            "Sketch": sketch_to_json(sketch),
            "Revolve": revolve_to_json(supObj),
        }

        print("\n===== JSON EXPORT =====")
        print(json.dumps(clean(data), indent=4))
        print("=======================\n")


# ============================================================
#  COMMAND
# ============================================================


class _CmdFeatureScan:

    def GetResources(self):
        return {
            "MenuText": "OBA Full Export",
            "ToolTip": "Export Sketch + Revolve metadata as JSON",
            "Pixmap": "",
        }

    def Activated(self):
        OBA_FeatureScan()


if "OBA_FeatureScan" not in Gui.listCommands():
    Gui.addCommand("OBA_FeatureScan", _CmdFeatureScan())
