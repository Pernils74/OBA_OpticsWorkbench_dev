import FreeCAD as App
import Part

from PySide import QtCore, QtWidgets


from .oba_base import OBABaseDialog, OBAElementProxy, OBAViewProviderBase, _trigger_ray_engine


from . import oba_mirror
from . import oba_absorber
from . import oba_emitter
from . import oba_lens

OPTICAL_BEHAVIOUR = {
    # "Lens": oba_lens,  # sköts av oba_optical_lens
    "Mirror": oba_mirror,
    "Absorber": oba_absorber,
    "Emitter": oba_emitter,
}


from . import oba_optical_lens
from . import oba_optical_mirror
from . import oba_optical_shapes
from . import oba_optical_none

# ============================================================
# MODULE REGISTRY (OPTICAL ONLY)
# ============================================================

OPTICAL_MODULES = {
    "Lens": oba_optical_lens,
    "Mirror": oba_optical_mirror,
    "None": oba_optical_none,
}


# ============================================================
# OPTICAL OBJECT (SHAPE PROXY)
# ============================================================

ALL_OPTICAL_GROUPS = ["None", "Lens", "Mirror", "Absorber", "Emitter", "Detector"]  # OBS måste matchas med OpticalModel


class OBAOpticalObject(OBAElementProxy):

    def __init__(self, obj):
        super().__init__(obj, use_binders=False)

        self._updating = False
        self._init_done = False

        self.Object = obj

        if not hasattr(obj, "OpticalType"):
            obj.addProperty("App::PropertyString", "OpticalType", "Base", "Type of optical element")
        obj.OpticalType = "None"  # eller vad din sub‑klass ska sätta

        if not hasattr(obj, "Binders"):
            obj.addProperty("App::PropertyLinkList", "Binders", "Optics")

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

        if not hasattr(obj, "OpticalModel"):
            obj.addProperty("App::PropertyEnumeration", "OpticalModel", "Base")
            obj.OpticalModel = ALL_OPTICAL_GROUPS  # ["None", "Lens", "Mirror", "Absorber", "Detector"]
            obj.OpticalModel = "None"

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

    def _cleanup_optical_properties(self, obj):
        current = obj.OpticalModel
        for prop in list(obj.PropertiesList):
            try:
                group = obj.getGroupOfProperty(prop)
            except:
                continue
            if group in ALL_OPTICAL_GROUPS and group != current and group != "None":
                try:
                    print("🧹 REMOVE:", prop)
                    obj.removeProperty(prop)
                except Exception as e:
                    print("Failed removing:", prop, e)

    def _ensure_dynamic_properties(self):
        obj = self.Object

        # if getattr(self, "_updating", False):
        #     return

        try:
            self._updating = True  # ✅ BLOCK
            self._cleanup_optical_properties(obj)
            # =====================================================
            # OPTICAL MODULE
            # =====================================================
            mod = OPTICAL_MODULES.get(obj.OpticalModel, oba_optical_none)  # fallback till none
            # mod = OPTICAL_MODULES.get(obj.OpticalModel)  # fallback till none

            # =====================================================
            # SHAPE ENUM (styrs av optical!)
            # =====================================================
            if mod and hasattr(mod, "SUPPORTED_SHAPES"):
                allowed_shapes = mod.SUPPORTED_SHAPES
            else:
                allowed_shapes = oba_optical_shapes.SHAPES

            # ✅ sätt enum-lista
            obj.ShapeType = allowed_shapes

            # ✅ säkerställ giltigt värde
            if obj.ShapeType not in allowed_shapes:
                obj.ShapeType = allowed_shapes[0]

            # =====================================================
            # SHAPE PROPERTIES
            # =====================================================
            print("SHAPE:", obj.ShapeType)

            shape_props = oba_optical_shapes.SHAPE_PROPERTIES.get(
                obj.ShapeType,
                [],
            )
            print("PROPS:", [p["name"] for p in shape_props])
            # =====================================================
            # ADD SHAPE PROPERTIES
            # =====================================================
            for p in shape_props:
                if p["name"] not in obj.PropertiesList:
                    obj.addProperty(p["type"], p["name"], p["group"])

                    if "default" in p:
                        setattr(obj, p["name"], p["default"])

            # =====================================================
            # EXTRA OPTICAL PROPERTIES (oba_object_mirrror , oba_optical_lens etc.. )
            # =====================================================
            if hasattr(mod, "EXTRA_PROPERTIES"):
                for p in mod.EXTRA_PROPERTIES:
                    # if not hasattr(obj, p["name"]):
                    if p["name"] not in obj.PropertiesList:
                        obj.addProperty(p["type"], p["name"], p["group"])

                        if "default" in p:
                            setattr(obj, p["name"], p["default"])

            # =====================================================
            # BEHAVIOUR PROPERTIES (oba_mirror etc)
            # =====================================================
            beh = OPTICAL_BEHAVIOUR.get(obj.OpticalModel)

            # if beh and hasattr(beh, "OPTICAL_PROPERTIES"):
            if beh:
                for p in beh.OPTICAL_PROPERTIES:
                    # if not hasattr(obj, p["name"]):
                    if p["name"] not in obj.PropertiesList:
                        obj.addProperty(p["type"], p["name"], p["group"])

                        if "default" in p:
                            setattr(obj, p["name"], p["default"])

            # =====================================================
            # INIT MODULE
            # =====================================================
            if hasattr(mod, "ensure_initialized"):
                mod.ensure_initialized(obj)

            # =====================================================
            # INITIAL SYNC (optics → geometry)
            # =====================================================
            if getattr(mod, "AFFECTS_GEOMETRY", False):
                if hasattr(mod, "update_calculated_properties"):
                    mod.update_calculated_properties(obj)

                elif hasattr(mod, "calculate_focal"):
                    f = mod.calculate_focal(obj)
                    if hasattr(obj, "Focal") and f != 0:
                        obj.Focal = f

        finally:
            obj.OpticalType = obj.OpticalModel  #  ✅ behåll OpticlaType i sync med OpticalModel
            self._updating = False  # ✅ UNBLOCK

    # ========================================================
    # BUILD
    # ========================================================

    def _do_build(self):
        self.build_shape()

    def build_shape(self):
        obj = self.Object

        mod = OPTICAL_MODULES.get(obj.OpticalModel)

        print("build:", obj.Name, obj.OpticalModel, obj.ShapeType)

        if mod and getattr(mod, "AFFECTS_GEOMETRY", False):
            if hasattr(mod, "update_calculated_properties"):
                mod.update_calculated_properties(obj)

        pl = obj.Placement.copy() if hasattr(obj, "Placement") else App.Placement()

        shape = oba_optical_shapes.build_shape(obj)

        obj.Shape = shape
        obj.touch()
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

    def onChanged_new(self, obj, prop):

        # ----------------------------------------
        # 1. SKYDD (init + recursion)
        # ----------------------------------------
        if not getattr(self, "_init_done", False):
            return

        if getattr(self, "_updating", False):
            return

        # ----------------------------------------
        # 2. HÄMTA MODUL / BEHAVIOUR
        # ----------------------------------------
        mod = OPTICAL_MODULES.get(obj.OpticalModel)
        beh = OPTICAL_BEHAVIOUR.get(obj.OpticalModel)

        try:
            self._updating = True

            # ----------------------------------------
            # 3. STRUCTURE CHANGE (model / shape)
            # ----------------------------------------
            if prop in ("OpticalModel", "ShapeType"):

                # ✅ 1: skapa ALLA properties först
                self._ensure_dynamic_properties()

                print("[AFTER___]:", obj.PropertiesList)

                # ✅ 2: uppdatera optics → radius
                if mod and getattr(mod, "AFFECTS_GEOMETRY", False):
                    if hasattr(mod, "update_calculated_properties"):
                        mod.update_calculated_properties(obj)

                # ✅ 3: bygg shape sist
                self.build_shape()

                # ✅ rebuild GUI
                vobj = getattr(obj, "ViewObject", None)
                if vobj and getattr(vobj, "Proxy", None):
                    dlg = getattr(vobj.Proxy, "dialog", None)
                    if dlg:
                        QtCore.QTimer.singleShot(0, dlg.build_ui)

                return

            # ----------------------------------------
            # 4. OPTICAL TRIGGERS (Focal, Material etc)
            # ----------------------------------------
            if mod:

                triggers = getattr(mod, "TRIGGER_PROPS", set())

                if prop in triggers:

                    # ✅ säkerställ att shape props finns
                    self._ensure_dynamic_properties()

                    # ✅ DESIGN MODE → påverkar geometri
                    if getattr(mod, "AFFECTS_GEOMETRY", False):

                        if hasattr(mod, "update_calculated_properties"):
                            mod.update_calculated_properties(obj)

                    # ✅ bygg shape
                    self.build_shape()

            # ----------------------------------------
            # 5. (OPTIONAL) BEHAVIOUR TRIGGERS
            # ----------------------------------------
            # framtida:
            # if beh and hasattr(beh, "TRIGGER_PROPS") ...

        finally:
            self._updating = False

        # ----------------------------------------
        # 6. FREECAD INFORM
        # ----------------------------------------
        obj.touch()

    def onChanged(self, obj, prop):
        # ----------------------------------------
        # 1. SKYDD (init + recursion)
        # ----------------------------------------
        if not getattr(self, "_init_done", False):
            return

        if getattr(self, "_updating", False):
            return

        # ----------------------------------------
        # 2. HÄMTA MODUL / BEHAVIOUR
        # ----------------------------------------
        mod = OPTICAL_MODULES.get(obj.OpticalModel)
        beh = OPTICAL_BEHAVIOUR.get(obj.OpticalModel)
        try:
            self._updating = True
            # ----------------------------------------
            # 3. STRUCTURE CHANGE (model / shape)
            # ----------------------------------------
            if prop in ("OpticalModel", "ShapeType"):
                self._ensure_dynamic_properties()
                print("[AFTER___]:", obj.PropertiesList)
                # rebuild GUI
                vobj = getattr(obj, "ViewObject", None)
                if vobj and getattr(vobj, "Proxy", None):
                    dlg = getattr(vobj.Proxy, "dialog", None)
                    if dlg:
                        QtCore.QTimer.singleShot(0, dlg.build_ui)

                # rebuild shape
                self.build_shape()
                return
            # ----------------------------------------
            # 4. OPTICAL TRIGGERS (Focal, Material etc)
            # ----------------------------------------
            if mod:
                triggers = getattr(mod, "TRIGGER_PROPS", set())
                if prop in triggers:
                    # ✅ DESIGN MODE → påverkar geometri
                    if getattr(mod, "AFFECTS_GEOMETRY", False):

                        if hasattr(mod, "update_calculated_properties"):
                            mod.update_calculated_properties(obj)

                    # rebuild shape efter ändring
                    self.build_shape()
                    self._update_dialog(obj, prop)

            # ----------------------------------------
            # 5. (OPTIONAL) BEHAVIOUR TRIGGERS
            # ----------------------------------------
            # här kan du senare lägga:
            # if beh and hasattr(beh, "TRIGGER_PROPS") ...
        finally:
            self._updating = False
        # ----------------------------------------
        # 6. FREECAD INFORM
        # ----------------------------------------
        obj.touch()

    def _update_dialog(self, obj, prop):
        vobj = getattr(obj, "ViewObject", None)

        if vobj and getattr(vobj, "Proxy", None):
            dlg = getattr(vobj.Proxy, "dialog", None)
            if dlg:
                if prop in ("ShapeType", "OpticalModel"):
                    QtCore.QTimer.singleShot(0, dlg.build_ui)  # ✅ FIX
                else:
                    dlg.update_ui_from_object()

    def execute(self, obj):

        if not getattr(self, "_updating", False):
            self.build_shape()

    def onDocumentRestored(self, obj):
        self._init_done = True
        self._updating = False


# ============================================================
# DIALOG
# ============================================================
class OpticalObjectDialog(OBABaseDialog):
    ALLOW_SURFACE_SELECTION = False  # Beam har inga binders

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

        # ✅ combos
        self._combo_optical(layout)
        self._combo_shape(layout)

        # ✅ modules
        mod = OPTICAL_MODULES.get(self.obj.OpticalModel)
        beh = OPTICAL_BEHAVIOUR.get(self.obj.OpticalModel)

        # ===============================================
        # 1. SHAPE UI
        # ===============================================
        if mod and hasattr(mod, "build_shape_dialog"):
            mod.build_shape_dialog(self, self.obj, layout)
        else:
            oba_optical_shapes.build_dialog(self, self.obj, layout)

        # ===============================================
        # 2. OPTICAL ADAPTER UI (optional in oba_optical_lens etc ...)
        # ===============================================
        if mod and hasattr(mod, "EXTRA_PROPERTIES"):
            box = QtWidgets.QGroupBox("Optical")
            box_layout = QtWidgets.QVBoxLayout(box)

            for p in mod.EXTRA_PROPERTIES:
                self._create_widget(box_layout, p["name"])

            layout.addWidget(box)

        # ===============================================
        # 3. OPTICAL CORE UI (oba_mirror etc)
        # ===============================================

        if beh and hasattr(beh, "OPTICAL_PROPERTIES"):

            box = QtWidgets.QGroupBox(self.obj.OpticalModel)
            box_layout = QtWidgets.QVBoxLayout(box)

            for p in beh.OPTICAL_PROPERTIES:
                # self._spin(box_layout, p["name"], p["name"])
                self._create_widget(box_layout, p["name"])

            layout.addWidget(box)

        self.custom_layout.addWidget(self.dynamic_widget)

    # ========================================================

    def _get_shapes_for_optical(self, opt):
        mod = OPTICAL_MODULES.get(opt)
        if mod and hasattr(mod, "SUPPORTED_SHAPES"):
            return mod.SUPPORTED_SHAPES
        return oba_optical_shapes.SHAPES

    # ========================================================

    def _combo_shape(self, layout):
        shapes = self._get_shapes_for_optical(self.obj.OpticalModel)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Shape"))

        cmb = QtWidgets.QComboBox()
        cmb.addItems(shapes)

        if self.obj.ShapeType not in shapes:
            self.obj.ShapeType = shapes[0]

        cmb.setCurrentText(self.obj.ShapeType)

        cmb.currentTextChanged.connect(lambda v: self._on_change("ShapeType", v))

        row.addWidget(cmb)
        layout.addLayout(row)

    # ========================================================

    def _combo_optical(self, layout):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Optical"))

        cmb = QtWidgets.QComboBox()
        cmb.addItems(["None", "Lens", "Mirror", "Absorber", "Detector"])
        cmb.setCurrentText(self.obj.OpticalModel)

        def changed(v):
            self.obj.OpticalModel = v

            # ✅ säkerställ shape fortfarande giltig
            valid = self._get_shapes_for_optical(v)
            if self.obj.ShapeType not in valid:
                self.obj.ShapeType = valid[0]

            # QtCore.QTimer.singleShot(0, self.build_ui)
            # self.build_ui()

        cmb.currentTextChanged.connect(changed)

        row.addWidget(cmb)
        layout.addLayout(row)

    # ========================================================

    def _on_change(self, prop, value):
        setattr(self.obj, prop, value)

        if self.obj.Document:
            self.obj.Document.recompute()

    # ========================================================

    def _create_widget(self, layout, prop):

        if prop not in self.obj.PropertiesList:
            return

        ptype = self.obj.getTypeIdOfProperty(prop)
        val = getattr(self.obj, prop)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(prop))

        # ------------------------
        # FLOAT
        # ------------------------
        if "Float" in ptype:
            w = QtWidgets.QDoubleSpinBox()
            w.setRange(-1e9, 1e9)
            w.setValue(float(val))
            w.valueChanged.connect(lambda v: self._on_change(prop, v))

        # ------------------------
        # BOOL
        # ------------------------
        elif "Bool" in ptype:
            w = QtWidgets.QCheckBox()
            w.setChecked(bool(val))
            w.toggled.connect(lambda v: self._on_change(prop, v))

        # ------------------------
        # STRING (tex Material)
        # ------------------------
        elif "String" in ptype:
            w = QtWidgets.QLineEdit()
            w.setText(str(val))
            w.textChanged.connect(lambda v: self._on_change(prop, v))

        # ------------------------
        # ENUM
        # ------------------------
        elif "Enumeration" in ptype:
            w = QtWidgets.QComboBox()
            enum = self.obj.getEnumerationsOfProperty(prop)
            w.addItems(enum)
            w.setCurrentText(val)
            w.currentTextChanged.connect(lambda v: self._on_change(prop, v))

        else:
            print("Unknown property type:", prop, ptype)
            return

        row.addWidget(w)
        layout.addLayout(row)

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

    # ========================================================

    def update_ui_from_object(self):
        dead = []

        for prop, w in list(self._spinboxes.items()):
            try:
                if hasattr(self.obj, prop):
                    w.blockSignals(True)
                    w.setValue(getattr(self.obj, prop))
                    w.blockSignals(False)
            except RuntimeError:
                # ✅ widget död → markera
                dead.append(prop)

        # ✅ ta bort efter iteration
        for prop in dead:
            self._spinboxes.pop(prop, None)


# ============================================================
# VIEW PROVIDER
# ============================================================


class OpticalObjectViewProvider(OBAViewProviderBase):
    def __init__(self, vobj):
        super().__init__(vobj)
        self.dialog_class = OpticalObjectDialog

    def updateData(self, obj, prop):

        if prop == "OpticalModel":

            if obj.OpticalModel == "Lens":
                obj.ViewObject.Transparency = 90
            else:
                obj.ViewObject.Transparency = 10


# ============================================================
# CREATE
# ============================================================


def OBA_CreateOpticalObject(show_dialog=True):
    doc = App.ActiveDocument or App.newDocument()

    obj = doc.addObject("Part::FeaturePython", "OpticalObject")

    OBAOpticalObject(obj)

    if App.GuiUp:
        OpticalObjectViewProvider(obj.ViewObject)

    doc.recompute()

    if show_dialog:
        OpticalObjectDialog(obj).show()

    return obj
