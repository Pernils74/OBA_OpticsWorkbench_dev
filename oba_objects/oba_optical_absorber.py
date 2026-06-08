# oba_optical_mirror.py

from PySide import QtWidgets

from .oba_mirror import MIRROR_PROPERTIES as OPTICAL_PROPERTIES

# ============================================================
# OPTICAL PROPERTIES (✅ endast optik)
# ============================================================

# OPTICAL_PROPERTIES = [
#     {
#         "type": "App::PropertyFloat",
#         "name": "Focal",
#         "group": "Optical",
#         "default": 100.0,
#     }
# ]

SUPPORTED_SHAPES = [
    "Plane",
    "Concave",
    "Convex",
]


OPTICAL_PROPERTIES = [
    {
        "type": "App::PropertyFloat",
        "name": "Absorption",
        "group": "Absorber",
        "default": 1.0,
    },
    #     {
    #         "type": "App::PropertyFloat",
    #         "name": "Transmissivity",
    #         "group": "Optical",
    #         "default": 0.0,
    #     },
]

AFFECTS_GEOMETRY = False

# ============================================================
# CALCULATE (geometry → optics)
# ============================================================


# def update_calculated_properties(obj):
#     pass  # eller inget


# def calculate_focal(obj):

#     if hasattr(obj, "Radius1"):
#         return obj.Radius1 / 2.0

#     return 0.0


# ============================================================
# APPLY OPTICS → WRITE INTO SHAPE
# ============================================================


# def update_calculated_properties(obj):

#     if not hasattr(obj, "Focal"):
#         return

#     f = obj.Focal
#     if f == 0:
#         return
#     # --------------------------------------------------------
#     # SPHERICAL MIRROR RELATION
#     # R = 2f
#     # --------------------------------------------------------
#     R = 2.0 * f
#     if obj.ShapeType in ("Concave", "Convex"):
#         if hasattr(obj, "Radius1"):
#             # ✅ Concave → positiv radie
#             if obj.ShapeType == "Concave":
#                 obj.Radius1 = abs(R)

#             # ✅ Convex → negativ radie
#             elif obj.ShapeType == "Convex":
#                 obj.Radius1 = -abs(R)


# ============================================================
# DIALOG (✅ endast optical UI)
# ============================================================


# def build_dialog(dlg, obj, layout):
#     for p in OPTICAL_PROPERTIES:
#         dlg._spin(layout, p["name"], p["name"])

# dlg._spin(layout, "Reflectivity", "Reflectivity")
# dlg._spin(layout, "Transmissivity", "Transmissivity")
