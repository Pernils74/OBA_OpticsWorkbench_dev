import FreeCAD as App
from PySide import QtWidgets

from .oba_lens_materials import (
    get_material_list,
    get_refractive_index,
)

# ============================================================
# OPTICAL PROPERTIES (✅ endast optik)
# ============================================================

OPTICAL_PROPERTIES = [
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
]

# ============================================================
# INIT MATERIAL ENUM (helper)
# ============================================================


def init_material(obj):

    if hasattr(obj, "Material"):
        obj.Material = get_material_list()
        if not obj.Material:
            obj.Material = ["N-BK7"]
        obj.Material = obj.Material[0]


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


def calculate_focal_old(obj):

    n = get_refractive_index(
        getattr(obj, "Material", "N-BK7"),
        wavelength_nm=getattr(obj, "Wavelength", 550.0),
    )

    st = obj.ShapeType

    try:

        # ----------------------------------------------------
        # PLANO CONVEX
        # ----------------------------------------------------
        if st == "PlanoConvex":

            R = obj.Radius1

            if (n - 1.0) != 0:
                return R / (n - 1.0)

        # ----------------------------------------------------
        # BI CONVEX
        # ----------------------------------------------------
        elif st == "BiConvex":

            R1 = obj.Radius1
            R2 = obj.Radius2
            d = obj.Thickness

            inv_f = (n - 1.0) * ((1.0 / R1) - (1.0 / R2) + ((n - 1.0) * d) / (n * R1 * R2))

            if inv_f != 0:
                return 1.0 / inv_f

    except:
        return 0.0

    return 0.0


# ============================================================
# APPLY OPTICS → WRITE INTO SHAPE
# ============================================================


def update_calculated_properties(obj):

    if not hasattr(obj, "Focal"):
        return

    n = get_refractive_index(
        getattr(obj, "Material", "N-BK7"),
        wavelength_nm=getattr(obj, "Wavelength", 550.0),
    )

    if n <= 1.0:
        return

    f = obj.Focal
    st = obj.ShapeType

    try:

        # ----------------------------------------------------
        # PLANO CONVEX
        # ----------------------------------------------------
        if st == "PlanoConvex":

            if f == 0:
                return

            R = f * (n - 1.0)
            obj.Radius1 = R

        # ----------------------------------------------------
        # PLANO CONCAVE
        # ----------------------------------------------------
        elif st == "PlanoConcave":

            if f == 0:
                return

            R = -f * (n - 1.0)
            obj.Radius1 = abs(R)

        # ----------------------------------------------------
        # BI CONVEX
        # ----------------------------------------------------
        elif st == "BiConvex":

            if f == 0:
                return

            R = 2.0 * f * (n - 1.0)

            obj.Radius1 = R
            obj.Radius2 = -R

        # ----------------------------------------------------
        # BI CONCAVE
        # ----------------------------------------------------
        elif st == "BiConcave":

            if f == 0:
                return

            R = -2.0 * f * (n - 1.0)

            obj.Radius1 = R
            obj.Radius2 = -R

    except:
        pass


def update_calculated_properties_old(obj):

    if not hasattr(obj, "Focal"):
        return

    # ✅ Hämta brytningsindex
    n = get_refractive_index(
        getattr(obj, "Material", "N-BK7"),
        wavelength_nm=getattr(obj, "Wavelength", 550.0),
    )

    f = obj.Focal

    if n == 1.0:
        return

    # --------------------------------------------------------
    # PLANO CONVEX → R = f*(n-1)
    # --------------------------------------------------------
    if obj.ShapeType == "PlanoConvex":

        R = f * (n - 1.0)

        if hasattr(obj, "Radius1"):
            obj.Radius1 = R

    # --------------------------------------------------------
    # BI CONVEX → symmetrisk förenkling
    # --------------------------------------------------------
    elif obj.ShapeType == "BiConvex":

        R = f * (n - 1.0) * 2.0

        if hasattr(obj, "Radius1"):
            obj.Radius1 = R

        if hasattr(obj, "Radius2"):
            obj.Radius2 = -R


# ============================================================
# DIALOG (✅ endast optical UI)
# ============================================================


def build_dialog(dlg, obj, layout):

    # ✅ Material
    if hasattr(obj, "Material"):

        row = QtWidgets.QHBoxLayout()

        row.addWidget(QtWidgets.QLabel("Material"))

        cmb = QtWidgets.QComboBox()

        mats = get_material_list()
        cmb.addItems(mats)

        if obj.Material in mats:
            cmb.setCurrentText(obj.Material)

        def changed(v):
            obj.Material = v

        cmb.currentTextChanged.connect(changed)

        row.addWidget(cmb)
        layout.addLayout(row)

    # ✅ Focal
    dlg._spin(layout, "Focal", "Focal")

    # ✅ Wavelength
    dlg._spin(layout, "Wavelength", "Wavelength")


def build_dialog_old(dlg, obj, layout):

    # ✅ Material dropdown
    if hasattr(obj, "Material"):

        row = dlg._row(layout, "Material")

        cmb = dlg._combo(row)

        mats = get_material_list()
        cmb.addItems(mats)

        cmb.setCurrentText(obj.Material)

        def changed(v):
            obj.Material = v

        cmb.currentTextChanged.connect(changed)

    # ✅ Focal
    dlg._spin(layout, "Focal", "Focal")

    # ✅ Wavelength
    dlg._spin(layout, "Wavelength", "Wavelength")
