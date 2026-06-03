# oba_optical_base_old.py

import FreeCAD as App
import Part

from PySide import QtWidgets

from .oba_base import OBABaseDialog, OBAElementProxy, OBAViewProviderBase, _trigger_ray_engine

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
        self._init_done = False  # ✅ sätt direkt

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
            obj.addProperty("App::PropertyEnumeration", "OpticalType", "Base")
            obj.OpticalType = ["None", "Lens", "Mirror", "Absorber", "Detector"]
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

        # =====================================================
        # SPECIAL CASE: PLANE
        # =====================================================
        if obj.ShapeType == "Plane":

            if not hasattr(obj, "Width"):
                obj.addProperty("App::PropertyFloat", "Width", "Shape")
                obj.Width = getattr(obj, "Diameter", 50.0)

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

        # =====================================================
        # OPTICAL MODULE
        # =====================================================
        mod = OPTICAL_MODULES.get(obj.OpticalType)

        if not mod:
            return

        created_props = False

        # =====================================================
        # ADD OPTICAL PROPERTIES
        # =====================================================

        if hasattr(mod, "OPTICAL_PROPERTIES"):  # and obj.ShapeType != "Plane":
            for p in mod.OPTICAL_PROPERTIES:

                if not hasattr(obj, p["name"]):
                    obj.addProperty(p["type"], p["name"], p["group"])
                    created_props = True

                    if "default" in p:
                        setattr(obj, p["name"], p["default"])

        # =====================================================
        # INIT MODULE (material etc)
        # =====================================================
        if hasattr(mod, "ensure_initialized"):
            mod.ensure_initialized(obj)

        # if hasattr(mod, "init_properties"):
        #     mod.init_properties(obj)

        # # Fallback om bara init_material finns
        # elif hasattr(mod, "init_material"):
        #     mod.init_material(obj)

        # =====================================================
        # INITIAL SYNC (Focal → Radius)
        # =====================================================
        if getattr(mod, "AFFECTS_GEOMETRY", False):

            if hasattr(mod, "update_calculated_properties"):

                # ✅ kör alltid en initial sync när properties finns
                mod.update_calculated_properties(obj)

            elif hasattr(mod, "calculate_focal"):

                # fallback: räkna focal från radius
                f = mod.calculate_focal(obj)
                if hasattr(obj, "Focal") and f != 0:
                    obj.Focal = f

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

        mod = OPTICAL_MODULES.get(obj.OpticalType)

        # ✅ endast om optical påverkar geometri
        if mod and getattr(mod, "AFFECTS_GEOMETRY", False):
            if hasattr(mod, "update_calculated_properties"):
                mod.update_calculated_properties(obj)

        pl = self.body.Placement.copy() if self.body.Shape else App.Placement()

        self.clear_binders(obj)

        shape = oba_optical_shapes.build_shape(obj)

        self.body.Shape = shape
        self.body.Placement = pl

        self.body.touch()
        self._rebuild_binders()
        _trigger_ray_engine("Shape rebuilt", obj)

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
        # ✅ alltid safe
        if not hasattr(self, "_init_done"):
            return

        if not self._init_done or getattr(self, "_updating", False):
            return

        try:
            self._updating = True

            mod = OPTICAL_MODULES.get(obj.OpticalType)

            if prop in ("OpticalType", "ShapeType"):
                self._ensure_dynamic_properties()

            # ✅ OPTICAL update separat
            # if mod and getattr(mod, "AFFECTS_GEOMETRY", False):
            #     mod.update_calculated_properties(obj)

            trigger_props = getattr(mod, "TRIGGER_PROPS", ())
            if prop in trigger_props and getattr(mod, "AFFECTS_GEOMETRY", False):
                mod.update_calculated_properties(obj)
                # ✅ FORCE rebuild direkt
                self.build_shape()

                # return

            # ✅ ENDAST geometry rebuild triggar shape
            if prop in (
                "ShapeType",
                "OpticalType",
                "Diameter",
                "Thickness",
                "Radius1",
                "Radius2",
                "Width",
                "Height",
            ):
                self.build_shape()

            vp = getattr(obj.ViewObject, "Proxy", None)
            if vp and hasattr(vp, "dialog") and vp.dialog:
                vp.dialog.update_ui_from_object()

        finally:
            self._updating = False

        if prop == "OpticalType":
            self.update_icon(obj)

    def execute(self, obj):
        self.build_shape()

    def onDocumentRestored(self, obj):
        self._init_done = True


# ============================================================
# DIALOG
# ============================================================


class OpticalObjectDialog(OBABaseDialog):

    def __init__(self, obj):
        super().__init__(obj, title="Optical Object")

        self.obj = obj
        self.dynamic_widget = None

        self.obj.ViewObject.Proxy.dialog = self
        self.build_ui()

    # ========================================================

    def build_ui(self):
        self._spinboxes = {}

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
        cmb.addItems(["None", "Lens", "Mirror", "Absorber", "Detector"])
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
        self._spinboxes = getattr(self, "_spinboxes", {})
        row = QtWidgets.QHBoxLayout()  # ❌ saknas just nu
        row.addWidget(QtWidgets.QLabel(label))  # ❌ saknas

        w = QtWidgets.QDoubleSpinBox()
        w.setRange(-1e9, 1e9)
        w.setValue(getattr(self.obj, prop))

        w.valueChanged.connect(lambda v: setattr(self.obj, prop, v))

        self._spinboxes[prop] = w  # ✅ spara

        row.addWidget(w)
        layout.addLayout(row)

    def _spin(self, layout, label, prop):
        if not hasattr(self.obj, prop):
            return

        self._spinboxes = getattr(self, "_spinboxes", {})

        row = QtWidgets.QHBoxLayout()  # ❌ saknas just nu
        row.addWidget(QtWidgets.QLabel(label))  # ❌ saknas

        w = QtWidgets.QDoubleSpinBox()
        w.setRange(-1e9, 1e9)
        w.setValue(getattr(self.obj, prop))

        w.valueChanged.connect(lambda v: setattr(self.obj, prop, v))

        self._spinboxes[prop] = w  # ✅ spara

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

    def update_ui_from_object(self):
        for prop, w in list(self._spinboxes.items()):
            try:
                if hasattr(self.obj, prop):
                    w.blockSignals(True)
                    w.setValue(getattr(self.obj, prop))
                    w.blockSignals(False)
            except RuntimeError:
                # widget borttagen → ta bort referens
                del self._spinboxes[prop]


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
