import FreeCAD as App
import Part

from PySide import QtWidgets

from .oba_base import (
    OBABaseDialog,
    OBAElementProxy,
    OBAViewProviderBase,
)

from . import oba_optical_lens
from . import oba_optical_mirror
from . import oba_optical_shapes

# ============================================================
# MODULE REGISTRY (OPTICAL ONLY)
# ============================================================

OPTICAL_MODULES = {
    "Lens": oba_optical_lens,
    "Mirror": oba_optical_mirror,
}


# ============================================================
# OPTICAL OBJECT
# ============================================================


class OBAOpticalObject(OBAElementProxy):

    def __init__(self, obj):
        super().__init__(obj)

        self._updating = False

        self._add_base_properties(obj)

        body = App.ActiveDocument.addObject("Part::Feature", "OpticalShape")
        obj.addObject(body)

        self.body = body
        self.Object = obj

        self._init_done = True

        self._ensure_dynamic_properties()
        self.build_shape()

    # ========================================================
    # BASE PROPERTIES
    # ========================================================

    def _add_base_properties(self, obj):
        self._add_prop(obj, "App::PropertyBool", "IsOptical", "Base", True)

        if not hasattr(obj, "OpticalType"):
            obj.addProperty("App::PropertyEnumeration", "OpticalType", "Optics")
            obj.OpticalType = ["None", "Lens", "Mirror"]
            obj.OpticalType = "None"

        if not hasattr(obj, "ShapeType"):
            obj.addProperty("App::PropertyEnumeration", "ShapeType", "Shape")

        self._add_prop(obj, "App::PropertyFloat", "Diameter", "Geometry", 50.0)
        self._add_prop(obj, "App::PropertyFloat", "Thickness", "Geometry", 10.0)

    # ========================================================
    # DYNAMIC PROPS (SHAPE FIRST!)
    # ========================================================

    def _ensure_dynamic_properties(self):
        obj = self.Object
        # =====================================================
        # SHAPE ENUM (ALLTID)
        # =====================================================
        obj.ShapeType = oba_optical_shapes.SHAPES

        if obj.ShapeType not in oba_optical_shapes.SHAPES:
            obj.ShapeType = oba_optical_shapes.SHAPES[0]
        # =====================================================
        # SHAPE PROPERTIES (från module)
        # =====================================================
        shape_props = oba_optical_shapes.SHAPE_PROPERTIES.get(obj.ShapeType, [])
        # Collect valid property names

        # =====================================================
        # SPECIAL CASE: PLANE
        # =====================================================
        if obj.ShapeType == "Plane":
            # ✅ Width
            if not hasattr(obj, "Width"):
                obj.addProperty("App::PropertyFloat", "Width", "Shape")
                obj.Width = getattr(obj, "Diameter", 50.0)
            # ✅ Height
            if not hasattr(obj, "Height"):
                obj.addProperty("App::PropertyFloat", "Height", "Shape")
                obj.Height = getattr(obj, "Diameter", 50.0)

        # =====================================================
        # ADD SHAPE PROPS
        # =====================================================
        for p in shape_props:
            if not hasattr(obj, p["name"]):
                obj.addProperty(p["type"], p["name"], p["group"])

                if "default" in p:
                    setattr(obj, p["name"], p["default"])

                # setattr(obj, p["name"], p["default"])

        # =====================================================
        # OPTICAL PROPERTIES
        # =====================================================
        mod = OPTICAL_MODULES.get(obj.OpticalType)
        if mod and hasattr(mod, "OPTICAL_PROPERTIES"):
            for p in mod.OPTICAL_PROPERTIES:
                if not hasattr(obj, p["name"]):
                    obj.addProperty(p["type"], p["name"], p["group"])

                    if "default" in p:
                        setattr(obj, p["name"], p["default"])

                    # setattr(obj, p["name"], p["default"])

    # ========================================================
    # PROP HELPER
    # ========================================================

    def _add_prop(self, obj, ptype, name, group, value):

        if not hasattr(obj, name):
            obj.addProperty(ptype, name, group)

        setattr(obj, name, value)

    # ========================================================
    # BUILD
    # ========================================================

    def build_shape(self):
        obj = self.Object
        # ✅ OPTICAL först → skriver t.ex Radius1/Radius2
        mod = OPTICAL_MODULES.get(obj.OpticalType)

        if mod and hasattr(mod, "update_calculated_properties"):
            mod.update_calculated_properties(obj)

        # ✅ SHAPE bygger med uppdaterade värden
        shape = oba_optical_shapes.build_shape(obj)
        self.body.Shape = shape
        self._rebuild_binders()

    def build_shape_old(self):
        obj = self.Object
        # ✅ SHAPE bygger geometri
        shape = oba_optical_shapes.build_shape(obj)
        # ✅ OPTICAL påverkar parametrar
        mod = OPTICAL_MODULES.get(obj.OpticalType)
        if mod and hasattr(mod, "update_calculated_properties"):
            mod.update_calculated_properties(obj)
        self.body.Shape = shape
        self._rebuild_binders()

    # ========================================================
    # BINDERS
    # ========================================================

    def _rebuild_binders(self):
        obj = self.Object
        if not hasattr(self.body, "Shape"):
            return
        self.clear_binders(obj)
        faces = [f"Face{i+1}" for i in range(len(self.body.Shape.Faces))]
        self.add_binders(obj, self.body, faces)

    # ========================================================
    # CHANGED
    # ========================================================

    def onChanged(self, obj, prop):
        if not getattr(self, "_init_done", False):
            return

        if self._updating:
            return
        try:
            self._updating = True

            if prop in ("OpticalType", "ShapeType"):
                self._ensure_dynamic_properties()

            if prop in (
                "ShapeType",
                "OpticalType",
                "Diameter",
                "Thickness",
                "Radius1",
                "Radius2",
                "Width",
                "Height",
                "Focal",  # ✅
                "Material",  # ✅
                "Wavelength",
            ):
                self.build_shape()

        finally:
            self._updating = False


# ============================================================
# DIALOG
# ============================================================


class OpticalObjectDialog(OBABaseDialog):

    def __init__(self, obj):
        super().__init__(obj, title="Optical Object")

        self.obj = obj
        self.dynamic_widget = None

        self.build_ui()

    # ========================================================

    def build_ui(self):

        if self.dynamic_widget:
            self.custom_layout.removeWidget(self.dynamic_widget)
            self.dynamic_widget.deleteLater()

        self.dynamic_widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.dynamic_widget)

        # ✅ SHAPE FIRST
        self._combo_shape(layout)

        # ✅ THEN optical
        self._combo_optical(layout)

        if self.obj.ShapeType == "Plane":
            self._spin(layout, "Width", "Width")
            self._spin(layout, "Height", "Height")

        else:
            self._spin(layout, "Diameter", "Diameter")
            self._spin(layout, "Thickness", "Thickness")

        # ✅ shape UI
        oba_optical_shapes.build_dialog(self, self.obj, layout)

        # ✅ optical UI
        mod = OPTICAL_MODULES.get(self.obj.OpticalType)

        if mod and hasattr(mod, "build_dialog"):
            mod.build_dialog(self, self.obj, layout)

        self.custom_layout.addWidget(self.dynamic_widget)

    # ========================================================

    def _combo_shape(self, layout):
        opt = self.obj.OpticalType

        if opt == "Lens":
            shapes = ["Plane", "PlanoConvex", "PlanoConcave", "BiConvex", "BiConcave"]

        elif opt == "Mirror":
            shapes = ["Plane", "Concave", "Convex"]

        else:
            shapes = oba_optical_shapes.SHAPES

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Shape"))

        cmb = QtWidgets.QComboBox()
        # cmb.addItems(oba_optical_shapes.SHAPES)
        cmb.addItems(shapes)

        cmb.setCurrentText(self.obj.ShapeType)

        def changed(v):
            self.obj.ShapeType = v
            self.build_ui()

        cmb.currentTextChanged.connect(changed)

        row.addWidget(cmb)
        layout.addLayout(row)

    # ========================================================

    def _combo_optical(self, layout):

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Optical"))

        cmb = QtWidgets.QComboBox()
        cmb.addItems(["None", "Lens", "Mirror"])
        cmb.setCurrentText(self.obj.OpticalType)

        def changed(v):
            self.obj.OpticalType = v
            self.build_ui()

        cmb.currentTextChanged.connect(changed)

        row.addWidget(cmb)
        layout.addLayout(row)

    # ========================================================

    def _spin(self, layout, label, prop):

        if not hasattr(self.obj, prop):
            return

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))

        w = QtWidgets.QDoubleSpinBox()
        w.setRange(-1e9, 1e9)
        w.setValue(getattr(self.obj, prop))

        w.valueChanged.connect(lambda v: setattr(self.obj, prop, v))

        row.addWidget(w)
        layout.addLayout(row)

    def _check(self, layout, label, prop):

        if not hasattr(self.obj, prop):
            return

        row = QtWidgets.QHBoxLayout()

        chk = QtWidgets.QCheckBox(label)
        chk.setChecked(getattr(self.obj, prop))

        def changed(v):
            setattr(self.obj, prop, bool(v))

        chk.stateChanged.connect(changed)

        row.addWidget(chk)
        layout.addLayout(row)


# ============================================================
# VIEW
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
