import FreeCAD as App
import Part

from PySide import QtWidgets, QtCore

from .oba_base import OBABaseDialog, OBAElementProxy, OBAViewProviderBase, _trigger_ray_engine

from . import oba_optical_lens
from . import oba_optical_mirror
from . import oba_optical_shapes

# ============================================================
# MODULE REGISTRY
# ============================================================

OPTICAL_MODULES = {
    "Lens": oba_optical_lens,
    "Mirror": oba_optical_mirror,
}


# ============================================================
# OPTICAL OBJECT (SHAPE PROXY)
# ============================================================


class OBAOpticalObject(OBAElementProxy):

    def __init__(self, obj):
        super().__init__(obj, use_binders=False)

        self._updating = False
        self._init_done = False

        self.Object = obj

        # ✅ debounce timer
        self._recompute_timer = QtCore.QTimer()
        self._recompute_timer.setSingleShot(True)
        self._recompute_timer.timeout.connect(self._do_build)

        self._add_base_properties(obj)

        self._init_done = True
        self._ensure_dynamic_properties()

    # ========================================================
    # PROPERTIES
    # ========================================================

    def _add_base_properties(self, obj):
        self._add_prop(obj, "App::PropertyBool", "IsOptical", "Base", True)

        if not hasattr(obj, "OpticalType"):
            obj.addProperty("App::PropertyEnumeration", "OpticalType", "Base")
            obj.OpticalType = ["None", "Lens", "Mirror", "Absorber", "Detector"]
            obj.OpticalType = "None"

        if not hasattr(obj, "ShapeType"):
            obj.addProperty("App::PropertyEnumeration", "ShapeType", "Shape")

        self._add_prop(obj, "App::PropertyFloat", "Diameter", "Geometry", 50.0)
        self._add_prop(obj, "App::PropertyFloat", "Thickness", "Geometry", 10.0)

    def _add_prop(self, obj, ptype, name, group, value):
        if not hasattr(obj, name):
            obj.addProperty(ptype, name, group)
        setattr(obj, name, value)

    # ========================================================
    # DYNAMIC PROPS
    # ========================================================
    def _ensure_dynamic_properties(self):
        obj = self.Object

        if getattr(self, "_updating", False):
            return

        try:
            self._updating = True  # ✅ BLOCK

            obj.ShapeType = oba_optical_shapes.SHAPES

            if obj.ShapeType not in oba_optical_shapes.SHAPES:
                obj.ShapeType = oba_optical_shapes.SHAPES[0]

            shape_props = oba_optical_shapes.SHAPE_PROPERTIES.get(obj.ShapeType, [])

            if obj.ShapeType == "Plane":
                if not hasattr(obj, "Width"):
                    obj.addProperty("App::PropertyFloat", "Width", "Shape")
                    obj.Width = obj.Diameter

                if not hasattr(obj, "Height"):
                    obj.addProperty("App::PropertyFloat", "Height", "Shape")
                    obj.Height = obj.Diameter

            for p in shape_props:
                if not hasattr(obj, p["name"]):
                    obj.addProperty(p["type"], p["name"], p["group"])
                    if "default" in p:
                        setattr(obj, p["name"], p["default"])

            mod = OPTICAL_MODULES.get(obj.OpticalType)
            if not mod:
                return

            if hasattr(mod, "OPTICAL_PROPERTIES"):
                for p in mod.OPTICAL_PROPERTIES:
                    if not hasattr(obj, p["name"]):
                        obj.addProperty(p["type"], p["name"], p["group"])
                        if "default" in p:
                            setattr(obj, p["name"], p["default"])

        finally:
            self._updating = False  # ✅ UNBLOCK

    # ========================================================
    # BUILD
    # ========================================================

    def _do_build(self):
        self.build_shape()

    def build_shape(self):
        obj = self.Object

        mod = OPTICAL_MODULES.get(obj.OpticalType)

        print("build:", obj.Name, obj.OpticalType, obj.ShapeType)

        if mod and getattr(mod, "AFFECTS_GEOMETRY", False):
            if hasattr(mod, "update_calculated_properties"):
                mod.update_calculated_properties(obj)

        pl = obj.Placement.copy() if hasattr(obj, "Placement") else App.Placement()

        shape = oba_optical_shapes.build_shape(obj)

        obj.Shape = shape
        obj.Placement = pl

        self._rebuild_binders()

        _trigger_ray_engine("Shape rebuilt", obj)

    # ========================================================
    # BINDERS (ON GROUP)
    # ========================================================

    def _rebuild_binders(self):
        obj = self.Object

        if not hasattr(obj, "Shape") or not obj.Shape:
            return

        group = obj.InList[0] if obj.InList else None
        if not group:
            return

        self.clear_binders(group)

        faces = [f"Face{i+1}" for i in range(len(obj.Shape.Faces))]
        self.add_binders(group, obj, faces)

    # ========================================================
    # CHANGED
    # ========================================================

    def onChanged(self, obj, prop):
        if not getattr(self, "_init_done", False) or getattr(self, "_updating", False):
            return

        try:
            self._updating = True

            if prop in ("ShapeType", "OpticalType"):
                self._ensure_dynamic_properties()

            # ✅ debounce istället för direkt rebuild
            if not self._updating:  # prevent rebuilds during dynamic prop changes
                self._recompute_timer.start(50)
        finally:
            self._updating = False
        self._update_dialog(obj, prop)

    def _update_dialog(self, obj, prop):
        vobj = getattr(obj, "ViewObject", None)

        if vobj and getattr(vobj, "Proxy", None):
            dlg = getattr(vobj.Proxy, "dialog", None)
            if dlg:
                if prop in ("ShapeType", "OpticalType"):
                    dlg.build_ui()
                else:
                    dlg.update_ui_from_object()

    def execute(self, obj):
        return
        if not getattr(self, "_updating", False):
            self.build_shape()

    def onDocumentRestored(self, obj):
        self._init_done = True
        self._updating = False


# ============================================================
# DIALOG
# ============================================================


class OpticalObjectDialog(OBABaseDialog):

    ALLOW_SURFACE_SELECTION = False

    def __init__(self, obj):
        super().__init__(obj, title="Optical Object")

        self.obj = obj
        self.dynamic_widget = None

        vobj = getattr(self.obj, "ViewObject", None)
        if vobj and getattr(vobj, "Proxy", None):
            vobj.Proxy.dialog = self

        self._recompute_timer = QtCore.QTimer()
        self._recompute_timer.setSingleShot(True)
        self._recompute_timer.timeout.connect(self._do_recompute)

        self.build_ui()

    def _do_recompute(self):
        if self.obj.Document:
            self.obj.Document.recompute()

    # --------------------------------------------------------

    def build_ui(self):
        self._spinboxes = {}

        if self.dynamic_widget:
            self.custom_layout.removeWidget(self.dynamic_widget)
            self.dynamic_widget.deleteLater()

        self.dynamic_widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.dynamic_widget)

        self._combo_optical(layout)
        self._combo_shape(layout)

        if self.obj.ShapeType == "Plane":
            self._spin(layout, "Width", "Width")
            self._spin(layout, "Height", "Height")
        else:
            self._spin(layout, "Diameter", "Diameter")
            self._spin(layout, "Thickness", "Thickness")

        oba_optical_shapes.build_dialog(self, self.obj, layout)

        mod = OPTICAL_MODULES.get(self.obj.OpticalType)
        if mod and hasattr(mod, "build_dialog"):
            mod.build_dialog(self, self.obj, layout)

        self.custom_layout.addWidget(self.dynamic_widget)

    # --------------------------------------------------------

    def _get_shapes_for_optical(self, opt):
        mod = OPTICAL_MODULES.get(opt)
        if mod and hasattr(mod, "SUPPORTED_SHAPES"):
            return mod.SUPPORTED_SHAPES
        return oba_optical_shapes.SHAPES

    def _combo_shape(self, layout):
        shapes = self._get_shapes_for_optical(self.obj.OpticalType)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Shape"))

        cmb = QtWidgets.QComboBox()
        cmb.addItems(shapes)
        cmb.setCurrentText(self.obj.ShapeType)

        cmb.currentTextChanged.connect(lambda v: self._on_change("ShapeType", v))

        row.addWidget(cmb)
        layout.addLayout(row)

    def _combo_optical(self, layout):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Optical"))

        cmb = QtWidgets.QComboBox()
        cmb.addItems(["None", "Lens", "Mirror", "Absorber", "Detector"])
        cmb.setCurrentText(self.obj.OpticalType)

        def changed(v):
            self.obj.OpticalType = v
            valid = self._get_shapes_for_optical(v)
            if self.obj.ShapeType not in valid:
                self.obj.ShapeType = valid[0]
            self.build_ui()

        cmb.currentTextChanged.connect(changed)

        row.addWidget(cmb)
        layout.addLayout(row)

    def _on_change(self, prop, value):
        setattr(self.obj, prop, value)
        self._recompute_timer.start(50)

    def _spin(self, layout, label, prop):
        if not hasattr(self.obj, prop):
            return

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))

        w = QtWidgets.QDoubleSpinBox()
        w.setRange(-1e9, 1e9)
        w.setValue(getattr(self.obj, prop))

        w.valueChanged.connect(lambda v: self._on_change(prop, v))

        row.addWidget(w)
        layout.addLayout(row)

        self._spinboxes[prop] = w

    def update_ui_from_object(self):
        for prop, w in self._spinboxes.items():
            if hasattr(self.obj, prop):
                w.blockSignals(True)
                w.setValue(getattr(self.obj, prop))
                w.blockSignals(False)


# ============================================================
# VIEW PROVIDER
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

    group = doc.addObject("App::DocumentObjectGroupPython", "OpticalObject")

    shape = doc.addObject("Part::FeaturePython", "OpticalShape")
    group.addObject(shape)

    OBAOpticalObject(shape)

    if App.GuiUp:
        OpticalObjectViewProvider(group.ViewObject)
        OpticalObjectViewProvider(shape.ViewObject)

    doc.recompute()

    if show_dialog:
        OpticalObjectDialog(shape).show()

    return group
