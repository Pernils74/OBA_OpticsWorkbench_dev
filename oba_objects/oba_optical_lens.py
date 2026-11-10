from .oba_lens_materials import get_material_list, get_refractive_index

EXTRA_PROPERTIES = [
    {"type": "App::PropertyFloat", "name": "Focal", "group": "Optics", "default": 100.0},
    {"type": "App::PropertyEnumeration", "name": "Material", "group": "Optics"},
    {"type": "App::PropertyFloat", "name": "Wavelength", "group": "Optics", "default": 550.0},
    {"type": "App::PropertyBool", "name": "UseFresnel", "group": "Optics", "default": False},
]

SUPPORTED_SHAPES = ["Plane", "PlanoConvex", "PlanoConcave", "BiConvex", "BiConcave"]

TRIGGER_PROPS = {"Focal", "Material", "Wavelength"}
AFFECTS_GEOMETRY = True


def ensure_initialized(obj):
    if "OpticalType" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "OpticalType", "Base")
    obj.OpticalType = "Lens"


def init_material(obj):
    if "Material" not in obj.PropertiesList:
        return
    materials = [m for m in get_material_list() if m != "Air"]
    if materials:
        obj.Material = materials
        if str(obj.Material) not in materials:
            obj.Material = materials[0]


def _number(obj, name, default=0.0):
    value = getattr(obj, name, default)
    return float(value.Value if hasattr(value, "Value") else value)


def _has_expression(obj, prop):
    try:
        return bool(obj.getExpression(prop))
    except Exception:
        return False


def calculate_focal(group, shape_obj=None):
    shape_obj = shape_obj or getattr(group, "ShapeObj", None)
    if not shape_obj:
        return 0.0

    n = get_refractive_index(
        str(group.Material),
        wavelength_nm=_number(group, "Wavelength", 550.0),
    )
    if n <= 1.0:
        return 0.0

    r1 = _number(shape_obj, "Radius1")
    r2 = _number(shape_obj, "Radius2")
    thickness = _number(shape_obj, "Thickness")
    st = str(shape_obj.ShapeType)

    try:
        if st == "PlanoConvex":
            return r1 / (n - 1.0) if r1 else 0.0
        if st == "PlanoConcave":
            return -abs(r1) / (n - 1.0) if r1 else 0.0
        if st in ("BiConvex", "BiConcave"):
            if not r1 or not r2:
                return 0.0
            inv_f = (n - 1.0) * (1.0 / r1 - 1.0 / r2 + ((n - 1.0) * thickness) / (n * r1 * r2))
            return 1.0 / inv_f if inv_f else 0.0
    except (ValueError, ZeroDivisionError, TypeError):
        return 0.0
    return 0.0


def update_calculated_properties(group, shape_obj=None):
    """Apply Focal to radii unless the radii are expression-driven."""
    shape_obj = shape_obj or getattr(group, "ShapeObj", None)
    if not shape_obj:
        return []

    n = get_refractive_index(
        str(group.Material),
        wavelength_nm=_number(group, "Wavelength", 550.0),
    )
    focal = _number(group, "Focal")
    if n <= 1.0 or focal == 0:
        return []

    st = str(shape_obj.ShapeType)
    if st == "PlanoConvex":
        targets = {"Radius1": focal * (n - 1.0)}
    elif st == "PlanoConcave":
        targets = {"Radius1": abs(focal * (n - 1.0))}
    elif st == "BiConvex":
        radius = 2.0 * focal * (n - 1.0)
        targets = {"Radius1": radius, "Radius2": -radius}
    elif st == "BiConcave":
        radius = -2.0 * focal * (n - 1.0)
        targets = {"Radius1": radius, "Radius2": -radius}
    else:
        return []

    updated = []
    for prop, value in targets.items():
        if prop not in shape_obj.PropertiesList or _has_expression(shape_obj, prop):
            continue
        if abs(_number(shape_obj, prop) - value) > 1e-9:
            setattr(shape_obj, prop, value)
            updated.append(prop)
    return updated


def build_dialog(dlg, obj, layout):
    from PySide import QtWidgets
    from .oba_optical_dialog_builder import create_widget

    box = QtWidgets.QGroupBox("Lens")
    lay = QtWidgets.QVBoxLayout(box)

    if "Material" in obj.PropertiesList:
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Material"))
        combo = QtWidgets.QComboBox()
        materials = [m for m in get_material_list() if m != "Air"]
        combo.addItems(materials)
        combo.setCurrentText(str(obj.Material))
        combo.currentTextChanged.connect(lambda value: setattr(obj, "Material", value))
        row.addWidget(combo)
        lay.addLayout(row)

    for prop in ("Focal", "Wavelength", "UseFresnel"):
        row = create_widget(dlg, obj, prop)
        if row:
            lay.addLayout(row)

    layout.addWidget(box)
