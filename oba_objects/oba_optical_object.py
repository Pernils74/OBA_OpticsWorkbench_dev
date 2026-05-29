import math

import FreeCAD as App
import FreeCADGui as Gui
import Part

from PySide import QtWidgets

from .oba_base import (
    OBABaseDialog,
    OBAElementProxy,
    OBAViewProviderBase,
)

from .oba_lens_materials import (
    get_material_list,
    get_refractive_index,
    MATERIAL_DATA,
)

# ============================================================
#  O P T I C A L   O B J E C T
# ============================================================


class OBAOpticalObject(OBAElementProxy):

    def __init__(self, obj):
        super().__init__(obj)

        # =====================================================
        # BASE
        # =====================================================

        self._add_prop(obj, "App::PropertyBool", "IsOptical", "Base", True)
        self._add_prop(obj, "App::PropertyString", "OpticalType", "Base", "OpticalObject")

        # =====================================================
        # SHAPE
        # =====================================================

        if not hasattr(obj, "ShapeType"):
            obj.addProperty("App::PropertyEnumeration", "ShapeType", "Shape")
            obj.ShapeType = ["Lens", "Mirror"]
            obj.ShapeType = "Lens"

        # =====================================================
        # GEOMETRY
        # =====================================================

        self._add_prop(obj, "App::PropertyFloat", "Diameter", "Geometry", 50.0)
        self._add_prop(obj, "App::PropertyFloat", "Thickness", "Geometry", 10.0)

        # Lens radii
        self._add_prop(obj, "App::PropertyFloat", "Radius1", "Lens", 100.0)
        self._add_prop(obj, "App::PropertyFloat", "Radius2", "Lens", -100.0)

        self._add_prop(obj, "App::PropertyFloat", "Focal", "Lens", 100.0)

        # Mirror
        self._add_prop(obj, "App::PropertyFloat", "MirrorRadius", "Mirror", 200.0)

        # =====================================================
        # MATERIAL
        # =====================================================

        if not hasattr(obj, "Material"):
            obj.addProperty("App::PropertyEnumeration", "Material", "Material")
            obj.Material = get_material_list()

        obj.Material = "N-BK7"

        self._add_prop(obj, "App::PropertyFloat", "RefractiveIndex", "Material", 1.5168)
        self._add_prop(obj, "App::PropertyFloat", "AbbeNumber", "Material", 64.17)
        self._add_prop(obj, "App::PropertyFloat", "Wavelength", "Material", 550.0)

        # =====================================================
        # OPTICS
        # =====================================================

        self._add_prop(obj, "App::PropertyBool", "UseFresnel", "Optics", False)
        self._add_prop(obj, "App::PropertyFloat", "Reflectivity", "Optics", 1.0)

        # =====================================================
        # BODY
        # =====================================================

        body = App.ActiveDocument.addObject("Part::Feature", "OpticalShape")
        obj.addObject(body)

        self.body = body
        self.Object = obj

        self._init_done = True

        self.build_shape()

    # =========================================================
    # PROPERTY HELPER
    # =========================================================

    def _add_prop(self, obj, ptype, name, group, value):

        if not hasattr(obj, name):
            obj.addProperty(ptype, name, group)

        setattr(obj, name, value)

    # =========================================================
    # BUILD
    # =========================================================

    def build_shape(self):

        obj = self.Object

        if obj.ShapeType == "Lens":
            shape = self._build_lens()

        elif obj.ShapeType == "Mirror":
            shape = self._build_mirror()

        else:
            return

        pl = self.body.Placement

        self.body.Shape = shape
        self.body.Placement = pl

        self._rebuild_binders()

    # =========================================================
    # LENS
    # =========================================================

    def _build_lens(self):

        obj = self.Object

        D = obj.Diameter
        T = obj.Thickness

        R1 = obj.Radius1
        R2 = obj.Radius2

        cyl = Part.makeCylinder(D / 2.0, T)

        shape = cyl

        # FRONT
        if abs(R1) > 0.001:

            s1 = Part.makeSphere(abs(R1))

            if R1 > 0:
                s1.translate(App.Vector(0, 0, -(abs(R1) - T)))
                shape = shape.common(s1)

            else:
                s1.translate(App.Vector(0, 0, abs(R1)))
                shape = shape.cut(s1)

        # BACK
        if abs(R2) > 0.001:

            s2 = Part.makeSphere(abs(R2))

            if R2 > 0:
                s2.translate(App.Vector(0, 0, T + abs(R2)))
                shape = shape.cut(s2)

            else:
                s2.translate(App.Vector(0, 0, T - abs(R2)))
                shape = shape.common(s2)

        return shape

    # =========================================================
    # MIRROR
    # =========================================================

    def _build_mirror(self):

        obj = self.Object

        D = obj.Diameter
        T = obj.Thickness
        R = abs(obj.MirrorRadius)

        cyl = Part.makeCylinder(D / 2.0, T)

        sphere = Part.makeSphere(R)

        sagitta = R - math.sqrt(R * R - (D / 2.0) ** 2)

        sphere.translate(App.Vector(0, 0, T + (R - sagitta)))

        shape = cyl.cut(sphere)

        return shape

    # =========================================================
    # FOCAL
    # =========================================================

    def calculate_focal(self):

        obj = self.Object

        n = get_refractive_index(
            obj.Material,
            wavelength_nm=obj.Wavelength,
            override_n=obj.RefractiveIndex if obj.Material == "Custom" else None,
        )

        R1 = obj.Radius1
        R2 = obj.Radius2
        d = obj.Thickness

        try:

            inv_f = (n - 1.0) * ((1.0 / R1) - (1.0 / R2) + (((n - 1.0) * d) / (n * R1 * R2)))

            if abs(inv_f) < 1e-9:
                return 1e9

            return 1.0 / inv_f

        except:
            return 1e9

    # =========================================================
    # BINDERS
    # =========================================================

    def _rebuild_binders(self):

        obj = self.Object

        if not hasattr(self.body, "Shape"):
            return

        self.clear_binders(obj)

        faces = [f"Face{i+1}" for i in range(len(self.body.Shape.Faces))]

        self.add_binders(obj, self.body, faces)

    # =========================================================
    # CHANGED
    # =========================================================

    def onChanged(self, obj, prop):

        if not getattr(self, "_init_done", False):
            return

        rebuild = (
            "ShapeType",
            "Diameter",
            "Thickness",
            "Radius1",
            "Radius2",
            "MirrorRadius",
        )

        if prop in rebuild:
            self.build_shape()

        if prop in (
            "Radius1",
            "Radius2",
            "Thickness",
            "Material",
            "RefractiveIndex",
        ):
            obj.Focal = self.calculate_focal()


# ============================================================
#  D I A L O G
# ============================================================


class OpticalObjectDialog(OBABaseDialog):

    def __init__(self, obj):

        super().__init__(obj, title="Optical Object")

        self.obj = obj

        self._spin("Diameter", "Diameter")
        self._spin("Thickness", "Thickness")

        self._combo_shape()

        self._spin("Radius1", "Radius1")
        self._spin("Radius2", "Radius2")

        self._spin("Mirror Radius", "MirrorRadius")

        self._spin("Focal", "Focal")

    # =====================================================

    def _spin(self, label, prop):

        row = QtWidgets.QHBoxLayout()

        row.addWidget(QtWidgets.QLabel(label))

        w = QtWidgets.QDoubleSpinBox()

        w.setRange(-1e6, 1e6)
        w.setDecimals(4)

        w.setValue(getattr(self.obj, prop))

        w.valueChanged.connect(lambda v, p=prop: setattr(self.obj, p, v))

        row.addWidget(w)

        self.custom_layout.addLayout(row)

    # =====================================================

    def _combo_shape(self):

        row = QtWidgets.QHBoxLayout()

        row.addWidget(QtWidgets.QLabel("Shape"))

        cmb = QtWidgets.QComboBox()

        cmb.addItems(["Lens", "Mirror"])

        cmb.setCurrentText(self.obj.ShapeType)

        cmb.currentTextChanged.connect(lambda t: setattr(self.obj, "ShapeType", t))

        row.addWidget(cmb)

        self.custom_layout.addLayout(row)


# ============================================================
#  VIEW
# ============================================================


class OpticalObjectViewProvider(OBAViewProviderBase):

    def __init__(self, vobj):

        super().__init__(vobj)

        self.dialog_class = OpticalObjectDialog


# ============================================================
# CREATE
# ============================================================


def OBA_CreateOpticalObject(show_dialog=True):

    doc = App.ActiveDocument or App.newDocument()

    obj = doc.addObject(
        "App::DocumentObjectGroupPython",
        "OpticalObject",
    )

    OBAOpticalObject(obj)

    if App.GuiUp:
        OpticalObjectViewProvider(obj.ViewObject)

    doc.recompute()

    if show_dialog:
        OpticalObjectDialog(obj).show()

    return obj
