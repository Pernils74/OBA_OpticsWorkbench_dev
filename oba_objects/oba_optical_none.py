from . import oba_optical_shapes

# ============================================================
# SUPPORTED SHAPES
# ============================================================

SUPPORTED_SHAPES = [
    "Plane",
    "PlanoConvex",
    "PlanoConcave",
    "BiConvex",
    "BiConcave",
    "Concave",
    "Convex",
]

# ============================================================
# FLAGS
# ============================================================

AFFECTS_GEOMETRY = False
TRIGGER_PROPS = ()

# ============================================================
# OPTICAL PROPERTIES
# ============================================================

OPTICAL_PROPERTIES = []


# ============================================================
# INIT
# ============================================================


def ensure_initialized(obj):
    pass


# ============================================================
# CALC
# ============================================================


def update_calculated_properties(obj):
    pass


def calculate_focal(obj):
    return 0.0


# ============================================================
# ✅ SHAPE UI (det du efterfrågade)
# ============================================================


def build_shape_dialog(dlg, obj, layout):

    props = oba_optical_shapes.SHAPE_PROPERTIES.get(
        obj.ShapeType,
        [],
    )

    for p in props:
        dlg._spin(
            layout,
            p["name"],
            p["name"],
        )


# ============================================================
# OPTICAL UI (None = inget)
# ============================================================


def build_dialog(dlg, obj, layout):
    pass
