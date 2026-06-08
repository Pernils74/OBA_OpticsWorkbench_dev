import FreeCAD as App
from PySide import QtWidgets

from .oba_lens_materials import (
    get_material_list,
    get_refractive_index,
)

# ============================================================
# OPTICAL PROPERTIES (✅ endast optik)
# ============================================================

EXTRA_PROPERTIES = [
    {
        "type": "App::PropertyFloat",
        "name": "Focal",
        "group": "Optical",
        "default": 100.0,
    },
    {
        "type": "App::PropertyEnumeration",
        "name": "Material",
        "group": "Optical",
    },
    {
        "type": "App::PropertyFloat",
        "name": "Wavelength",
        "group": "Optical",
        "default": 550.0,
    },
    {
        "type": "App::PropertyBool",
        "name": "UseFresnel",
        "group": "Optical",
        "default": False,
    },
]


SUPPORTED_SHAPES = ["Plane", "PlanoConvex", "PlanoConcave", "BiConvex", "BiConcave"]


TRIGGER_PROPS = {
    "Material",
    "Focal",
    "Wavelength",
    "UseFresnel",
}

AFFECTS_GEOMETRY = True

# ============================================================
# INIT MATERIAL ENUM (helper)
# ============================================================


def init_material(obj):
    if not hasattr(obj, "Material"):
        return

    mats = [m for m in get_material_list() if m != "Air"]

    # # ✅ Sätt enum-lista
    obj.Material = mats

    # # ✅ Sätt värde SOM FINNS I LISTAN
    if obj.Material not in mats:
        obj.Material = mats[0]


def ensure_initialized(obj):
    if not hasattr(obj, "_init_done"):
        obj.addProperty("App::PropertyBool", "_init_done", "Internal")
        obj._init_done = False

    if obj._init_done:
        return
    init_material(obj)

    if obj.ShapeType == "Plane":
        return

    if getattr(obj, "Focal", 0.0) != 0:
        update_calculated_properties(obj)
    obj._init_done = True


# ============================================================
# CALCULATE FOCAL FROM GEOMETRY
# ============================================================


def calculate_focal(obj):
    n = get_refractive_index(
        getattr(obj, "Material", "N-BK7"),
        wavelength_nm=getattr(obj, "Wavelength", 550.0),
    )

    st = obj.ShapeType
    r = getattr(obj, "Radius1", 0.0)
    r2 = getattr(obj, "Radius2", 0.0)
    d = getattr(obj, "Thickness", 0.0)

    if n <= 1.0:
        return 0.0

    try:
        # ----------------------------------------------------
        # PLANO CONVEX
        # ----------------------------------------------------
        if st == "PlanoConvex":
            if r == 0:
                return 0.0
            return r / (n - 1.0)
        # ----------------------------------------------------
        # PLANO CONCAVE
        # ----------------------------------------------------
        if st == "PlanoConcave":
            if r == 0:
                return 0.0
            return -r / (n - 1.0)
        # ----------------------------------------------------
        # BI CONVEX / BI CONCAVE (LENSMAKER)
        # ----------------------------------------------------
        if st in ("BiConvex", "BiConcave"):
            inv_f = (n - 1.0) * ((1.0 / r if r != 0 else 0.0) - (1.0 / r2 if r2 != 0 else 0.0) + ((n - 1.0) * d) / (n * r * r2 if r * r2 != 0 else 1e9))
            if inv_f == 0:
                return 0.0
            return 1.0 / inv_f
    except:
        return 0.0
    return 0.0


# ============================================================
# APPLY OPTICS → WRITE INTO SHAPE
# ============================================================


def update_calculated_properties(obj):
    updated = []

    material = getattr(obj, "Material", "N-BK7")

    n = get_refractive_index(material, wavelength_nm=getattr(obj, "Wavelength", 550.0))

    if n <= 1.0:
        return updated

    f = obj.Focal
    st = obj.ShapeType

    try:
        if st == "PlanoConvex":
            if f == 0:
                return updated

            R = f * (n - 1.0)

            if obj.Radius1 != R:
                obj.Radius1 = R
                updated.append("Radius1")

        elif st == "PlanoConcave":
            if f == 0:
                return updated

            R = -f * (n - 1.0)
            R = abs(R)

            if obj.Radius1 != R:
                obj.Radius1 = R
                updated.append("Radius1")

        elif st == "BiConvex":
            if f == 0:
                return updated

            R = 2.0 * f * (n - 1.0)

            if obj.Radius1 != R:
                obj.Radius1 = R
                updated.append("Radius1")

            if obj.Radius2 != -R:
                obj.Radius2 = -R
                updated.append("Radius2")

        elif st == "BiConcave":
            if f == 0:
                return updated

            R = -2.0 * f * (n - 1.0)

            if obj.Radius1 != R:
                obj.Radius1 = R
                updated.append("Radius1")

            if obj.Radius2 != -R:
                obj.Radius2 = -R
                updated.append("Radius2")

    except:
        pass

    return updated


# ============================================================
# DIALOG (✅ endast optical UI)
# ============================================================


def build_dialog(dlg, obj, layout):
    from .oba_optical_dialog_builder import create_widget

    from PySide import QtWidgets

    box = QtWidgets.QGroupBox("Lens")
    lay = QtWidgets.QVBoxLayout(box)

    # -------------------------
    # Material (special-case)
    # -------------------------
    if hasattr(obj, "Material"):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Material"))

        cmb = QtWidgets.QComboBox()
        mats = [m for m in get_material_list() if m != "Air"]
        cmb.addItems(mats)

        if obj.Material in mats:
            cmb.setCurrentText(obj.Material)

        def changed(v, p="Material"):
            obj.Material = mats
            if v in mats:
                obj.Material = v

        cmb.currentTextChanged.connect(changed)
        row.addWidget(cmb)
        lay.addLayout(row)

    # -------------------------
    # Standard properties
    # -------------------------
    for prop in ["Focal", "Wavelength", "UseFresnel"]:
        w = create_widget(dlg, obj, prop)
        if w:
            lay.addLayout(w)

    layout.addWidget(box)


def build_dialog_old(dlg, obj, layout):

    # ✅ Material
    if hasattr(obj, "Material"):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Material"))
        cmb = QtWidgets.QComboBox()
        mats = [m for m in get_material_list() if m != "Air"]
        cmb.addItems(mats)

        if obj.Material in mats:
            cmb.setCurrentText(obj.Material)

        def changed(v):
            mats = [m for m in get_material_list() if m != "Air"]
            print("Materials", mats)
            # ✅ säkerställ att enum är korrekt innan set
            obj.Material = mats

            if v in mats:
                obj.Material = v

        cmb.currentTextChanged.connect(changed)

        row.addWidget(cmb)
        layout.addLayout(row)

    print("objjj", obj)
    if obj.ShapeModel != "Plane":
        # ✅ Focal
        dlg._create_widget(layout, "Focal")
        # ✅ Wavelength
        dlg._create_widget(layout, "Wavelength")

        dlg._create_widget(layout, "UseFresnel")
