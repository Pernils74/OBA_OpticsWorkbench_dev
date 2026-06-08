# oba_optical_mirror.py

from PySide import QtWidgets

from .oba_mirror import OPTICAL_PROPERTIES

# ============================================================
# OPTICAL PROPERTIES (✅ endast optik)
# ============================================================


SUPPORTED_SHAPES = [
    "Plane",
    "PlanoConvex",
    "PlanoConcave",
]


OPTICAL_PROPERTIES = [
    {
        "type": "App::PropertyFloat",
        "name": "Reflectivity",
        "group": "Optical",
        "default": 0.95,
    },
    {
        "type": "App::PropertyFloat",
        "name": "Transmissivity",
        "group": "Optical",
        "default": 0.0,
    },
]

AFFECTS_GEOMETRY = False

# ============================================================
# CALCULATE (geometry → optics)
# ============================================================


def update_calculated_properties(obj):
    pass  # eller inget


def calculate_focal(obj):
    return


# ============================================================
# APPLY OPTICS → WRITE INTO SHAPE
# ============================================================


def update_calculated_properties(obj):
    return


# ============================================================
# DIALOG (✅ endast optical UI)
# ============================================================


def build_dialog(dlg, obj, layout):
    return
