import FreeCAD as App
from PySide import QtCore, QtWidgets

from .oba_base import (
    OBABaseDialog,
    OBAElementProxy,
    OBAViewProviderBase,
    _trigger_ray_engine,
)
from . import oba_optical_shapes
from . import oba_optical_lens, oba_optical_mirror, oba_optical_none
from . import oba_mirror, oba_absorber, oba_emitter, oba_detector

ALL_OPTICAL_GROUPS = ["None", "Lens", "Mirror", "Absorber", "Emitter", "Detector"]


OPTICAL_MODULES = {
    "None": oba_optical_none,
    "Lens": oba_optical_lens,
    "Mirror": oba_optical_mirror,
}

OPTICAL_BEHAVIOUR = {
    "Mirror": oba_mirror,
    "Absorber": oba_absorber,
    "Emitter": oba_emitter,
    "Detector": oba_detector,
}


def add_prop(obj, ptype, name, group, default=None):
    if name not in obj.PropertiesList:
        obj.addProperty(ptype, name, group)
        if default is not None:
            setattr(obj, name, default)


def _world_axis_rotation(rot_x, rot_y, rot_z):
    rotation_x = App.Rotation(App.Vector(1, 0, 0), float(rot_x))
    rotation_y = App.Rotation(App.Vector(0, 1, 0), float(rot_y))
    rotation_z = App.Rotation(App.Vector(0, 0, 1), float(rot_z))
    # Multiplication applies rotations about global X, then Y, then Z.
    return rotation_z.multiply(rotation_y).multiply(rotation_x)


# def get_shape_obj(group):
#     shape_obj = getattr(group, "ShapeObj", None)
#     if shape_obj:
#         return shape_obj

#     doc = group.Document
#     if not doc:
#         return None

#     shape_obj = doc.addObject("Part::FeaturePython", group.Name + "_Shape")
#     OpticalShape(shape_obj, group)
#     group.addObject(shape_obj)
#     group.ShapeObj = shape_obj

#     if App.GuiUp:
#         OpticalShapeViewProvider(shape_obj.ViewObject)

#     return shape_obj


def get_shape_obj(group):
    return getattr(group, "ShapeObj", None)


class OBAOpticalObject(OBAElementProxy):
    """Group proxy. Owns optical parameters and links to OpticalShape."""

    def __init__(self, obj):
        super().__init__(obj, use_binders=False)
        obj.Proxy = self
        self.Object = obj
        self._updating = False
        self._init_done = False
        self.dialog = None
        self._placement_update_pending = False

        add_prop(obj, "App::PropertyBool", "IsOptical", "Base", True)
        add_prop(obj, "App::PropertyString", "OpticalType", "Base", "None")
        # add_prop(obj, "App::PropertyString", "OpticalModel", "Base", "None")
        add_prop(obj, "App::PropertyEnumeration", "OpticalModel", "Optics")
        obj.OpticalModel = ALL_OPTICAL_GROUPS

        add_prop(obj, "App::PropertyLink", "ShapeObj", "Geometry")
        add_prop(obj, "App::PropertyLinkList", "Binders", "Optics")
        add_prop(obj, "App::PropertyString", "GeomHash", "Internal", "")
        self._ensure_placement_properties(obj)

        self._ensure_optical_properties(obj)
        self._init_done = True
        get_shape_obj(obj)

    def _ensure_placement_properties(self, obj, shape_obj=None, existing=None):
        existing = set(obj.PropertiesList) if existing is None else existing
        for name in ("WorldX", "WorldY", "WorldZ"):
            add_prop(obj, "App::PropertyFloat", name, "Placement", 0.0)
            if name not in existing and shape_obj and name in shape_obj.PropertiesList:
                setattr(obj, name, float(getattr(shape_obj, name)))
        for name in ("RotX", "RotY", "RotZ"):
            add_prop(obj, "App::PropertyAngle", name, "Placement", 0.0)
            if name not in existing and shape_obj and name in shape_obj.PropertiesList:
                setattr(obj, name, float(getattr(shape_obj, name)))

    def _set_shape_placement_from_properties(self, obj):
        shape_obj = get_shape_obj(obj)
        if not shape_obj:
            return False

        required = ("WorldX", "WorldY", "WorldZ", "RotX", "RotY", "RotZ")
        if not all(name in obj.PropertiesList for name in required):
            return False

        rotation = _world_axis_rotation(obj.RotX, obj.RotY, obj.RotZ)
        placement = App.Placement(
            App.Vector(float(obj.WorldX), float(obj.WorldY), float(obj.WorldZ)),
            rotation,
        )
        if shape_obj.Placement.isSame(placement):
            return False

        shape_obj.Placement = placement
        return True

    def _schedule_shape_placement_update(self, obj):
        if self._placement_update_pending:
            return

        self._placement_update_pending = True
        QtCore.QTimer.singleShot(
            0,
            lambda target=obj: self._apply_deferred_shape_placement(target),
        )

    def _apply_deferred_shape_placement(self, obj):
        self._placement_update_pending = False
        doc = getattr(obj, "Document", None)
        if not doc:
            return

        self._updating = True
        try:
            placement_changed = self._set_shape_placement_from_properties(obj)
        finally:
            self._updating = False

        if placement_changed:
            doc.recompute()

    def _ensure_optical_properties(self, obj):
        model = str(obj.OpticalModel)
        mod = OPTICAL_MODULES.get(model, oba_optical_none)
        behaviour = OPTICAL_BEHAVIOUR.get(model)
        obj.OpticalType = model

        for p in getattr(mod, "EXTRA_PROPERTIES", []):
            add_prop(obj, p["type"], p["name"], p.get("group", "Optics"), p.get("default"))

        for p in getattr(behaviour, "OPTICAL_PROPERTIES", []):
            add_prop(obj, p["type"], p["name"], p.get("group", "Optics"), p.get("default"))

        for module in (mod, behaviour):
            initialize = getattr(module, "ensure_initialized", None)
            if initialize:
                initialize(obj)

        if model == "Lens":
            oba_optical_lens.init_material(obj)

    def _clear_optical_binders(self):
        obj = self.Object
        doc = obj.Document
        if not doc:
            return

        binders = list(getattr(obj, "Binders", []))
        obj.Binders = []
        for binder in binders:
            if not binder or not doc.getObject(binder.Name):
                continue
            try:
                doc.removeObject(binder.Name)
            except Exception as exc:
                App.Console.PrintError(
                    "[OBA] Could not remove optical binder {}: {}\n".format(
                        binder.Name, exc
                    )
                )

    def _build_optical_binders(self):
        obj = self.Object
        doc = obj.Document
        shape_obj = getattr(obj, "ShapeObj", None)
        if not doc or not shape_obj:
            return
        if str(obj.OpticalModel) == "None":
            return

        shape = shape_obj.Shape
        if not shape or shape.isNull():
            return

        self._clear_optical_binders()
        new_binders = []
        for i, _face in enumerate(shape.Faces):
            name = f"{obj.Name}_Face_{i+1}"
            if doc.getObject(name):
                name = f"{name}_{i}"

            try:
                b = doc.addObject("PartDesign::ShapeBinder", name)
            except Exception as e:
                App.Console.PrintError(
                    "[OBA] Could not create optical binder {}: {}\n".format(name, e)
                )
                continue

            b.Support = [(shape_obj, (f"Face{i+1}",))]
            b.TraceSupport = True
            b.ViewObject.Visibility = False
            obj.addObject(b)
            new_binders.append(b)

        obj.Binders = new_binders

    def onChanged(self, obj, prop):
        if not getattr(self, "_init_done", False):
            return

        if getattr(self, "_updating", False):
            return

        if getattr(self, "_initializing", False):
            return

        if getattr(self, "_updating", False):
            return

        placement_props = {
            "WorldX",
            "WorldY",
            "WorldZ",
            "RotX",
            "RotY",
            "RotZ",
        }

        if prop in placement_props:
            self._schedule_shape_placement_update(obj)
            return

        # if not self._init_done or self._updating:
        #     return

        if prop == "OpticalModel":
            self._updating = True
            try:
                self._ensure_optical_properties(obj)
                shape_obj = get_shape_obj(obj)
                if shape_obj:
                    shape_obj.Proxy.set_model(shape_obj, str(obj.OpticalModel))
                    shape_obj.touch()
                if self.dialog:
                    QtCore.QTimer.singleShot(0, self.dialog.build_ui)
            finally:
                self._updating = False
            if obj.Document:
                obj.Document.recompute()
            return

        if prop == "ShapeObj":
            shape_obj = getattr(obj, "ShapeObj", None)
            if shape_obj and getattr(shape_obj, "Proxy", None):
                shape_obj.Proxy.Group = obj
            self._schedule_shape_placement_update(obj)
            return

        mod = OPTICAL_MODULES.get(str(obj.OpticalModel))
        triggers = getattr(mod, "TRIGGER_PROPS", set())

        # if prop in triggers:
        #     shape_obj = get_shape_obj(obj)
        #     if shape_obj and getattr(mod, "AFFECTS_GEOMETRY", False):
        #         oba_optical_lens.update_calculated_properties(obj, shape_obj)
        #         shape_obj.touch()

        if prop in triggers:
            shape_obj = get_shape_obj(obj)
            if shape_obj and getattr(mod, "AFFECTS_GEOMETRY", False) and hasattr(mod, "update_calculated_properties"):
                mod.update_calculated_properties(obj, shape_obj)
                shape_obj.touch()

        if prop not in ("Binders", "GeomHash"):
            try:
                _trigger_ray_engine("Optical property changed", obj)
            except Exception:
                pass

        # Behåll här eventuell befintlig hantering av övriga egenskaper.

    def execute(self, obj):
        if not getattr(self, "_init_done", False):
            return

        if not self._init_done:
            return

        shape_obj = get_shape_obj(obj)

        if shape_obj:
            shape_obj.Proxy.Group = obj

    def onDocumentRestored(self, obj):
        self.Object = obj
        obj.Proxy = self
        self._updating = False
        self._init_done = True
        self._placement_update_pending = False

        add_prop(obj, "App::PropertyLinkList", "Binders", "Optics")
        add_prop(obj, "App::PropertyString", "GeomHash", "Internal", "")
        shape_obj = getattr(obj, "ShapeObj", None)
        existing_properties = set(obj.PropertiesList)
        self._updating = True
        try:
            self._ensure_placement_properties(
                obj,
                shape_obj=shape_obj,
                existing=existing_properties,
            )
        finally:
            self._updating = False
        # print(type(shape_obj))
        # print(shape_obj.TypeId)
        # print(hasattr(shape_obj, "Proxy"))

        self._ensure_optical_properties(obj)

        if shape_obj:
            if not getattr(shape_obj, "Proxy", None):
                OpticalShape(shape_obj, obj)
            else:
                shape_obj.Proxy.Group = obj
            self._set_shape_placement_from_properties(obj)

        if App.GuiUp and obj.ViewObject:
            OpticalObjectViewProvider(obj.ViewObject)

        print(type(obj.ViewObject.Proxy))
        print(hasattr(obj.ViewObject.Proxy, "dialog_class"))

        # if App.GuiUp and obj.ViewObject:
        #     if not getattr(obj.ViewObject, "Proxy", None):
        #         OpticalObjectViewProvider(obj.ViewObject)

    def __getstate__(self):
        return {}

    def __setstate__(self, state):
        self.Object = None
        self._updating = False
        self._init_done = False
        self.dialog = None
        self._placement_update_pending = False


class OpticalShape:
    """Part::FeaturePython proxy. Owns geometry and expression-driven placement."""

    def __init__(self, obj, group=None):
        self.Object = obj
        self.Group = group
        self._updating = False
        self._geometry_dirty = True
        self._placement_sync_pending = False
        obj.Proxy = self
        self._initializing = True

        add_prop(obj, "App::PropertyLinkHidden", "OpticalObject", "Internal")
        # add_prop(obj, "App::PropertyLink", "OpticalObject", "Optics", group)

        add_prop(obj, "App::PropertyEnumeration", "ShapeType", "Geometry")

        self.set_model(obj, str(getattr(group, "OpticalModel", "None")))
        self._initializing = False

    def set_model(self, obj, model):
        mod = OPTICAL_MODULES.get(model, oba_optical_none)
        shapes = getattr(mod, "SUPPORTED_SHAPES", oba_optical_shapes.SHAPES)
        current = str(getattr(obj, "ShapeType", "Plane"))
        obj.ShapeType = list(shapes)
        if current not in shapes:
            obj.ShapeType = shapes[0]
        self._ensure_shape_properties(obj)
        self.mark_geometry_dirty()

    def mark_geometry_dirty(self):
        self._geometry_dirty = True

    def _ensure_shape_properties(self, obj):
        for p in oba_optical_shapes.SHAPE_PROPERTIES.get(str(obj.ShapeType), []):
            add_prop(obj, p["type"], p["name"], p.get("group", "Geometry"), p.get("default"))

    def _set_placement_from_properties(self, obj):
        required = (
            "WorldX",
            "WorldY",
            "WorldZ",
            "RotX",
            "RotY",
            "RotZ",
        )
        if not all(name in obj.PropertiesList for name in required):
            return

        rotation = _world_axis_rotation(obj.RotX, obj.RotY, obj.RotZ)

        obj.Placement = App.Placement(
            App.Vector(float(obj.WorldX), float(obj.WorldY), float(obj.WorldZ)),
            rotation,
        )

    def _sync_group_placement_from_properties(self, obj):
        group = self.Group or getattr(obj, "OpticalObject", None)
        if not group:
            self._set_placement_from_properties(obj)
            return

        placement_props = ("WorldX", "WorldY", "WorldZ", "RotX", "RotY", "RotZ")
        if not all(name in obj.PropertiesList for name in placement_props):
            return
        if not all(name in group.PropertiesList for name in placement_props):
            self._set_placement_from_properties(obj)
            return

        group_proxy = getattr(group, "Proxy", None)
        if not group_proxy or not hasattr(
            group_proxy, "_set_shape_placement_from_properties"
        ):
            self._set_placement_from_properties(obj)
            return

        if self._placement_sync_pending:
            return

        self._placement_sync_pending = True
        QtCore.QTimer.singleShot(
            0,
            lambda source=obj, target=group: self._apply_deferred_group_placement(
                source, target
            ),
        )

    def _apply_deferred_group_placement(self, obj, group):
        self._placement_sync_pending = False
        doc = getattr(obj, "Document", None)
        if not doc or getattr(group, "Document", None) is not doc:
            return

        group_proxy = getattr(group, "Proxy", None)
        if not group_proxy or not hasattr(
            group_proxy, "_set_shape_placement_from_properties"
        ):
            return

        placement_props = ("WorldX", "WorldY", "WorldZ", "RotX", "RotY", "RotZ")
        group_proxy._updating = True
        try:
            for name in placement_props:
                setattr(group, name, float(getattr(obj, name)))
        finally:
            group_proxy._updating = False

        if group_proxy._set_shape_placement_from_properties(group):
            doc.recompute()

    def _set_placement_from_properties_fel(self, obj):
        required = (
            "WorldX",
            "WorldY",
            "WorldZ",
            "RotX",
            "RotY",
            "RotZ",
        )

        if not all(name in obj.PropertiesList for name in required):
            return

        self._updating = True
        try:
            rotation = App.Rotation(
                float(obj.RotZ),
                float(obj.RotY),
                float(obj.RotX),
            )

            obj.Placement = App.Placement(
                App.Vector(
                    float(obj.WorldX),
                    float(obj.WorldY),
                    float(obj.WorldZ),
                ),
                rotation,
            )
        finally:
            self._updating = False

    def onChanged(self, obj, prop):
        if getattr(self, "_updating", False):
            return

        if getattr(self, "_initializing", False):
            return

        # if self._updating:
        #     return

        if prop in {"WorldX", "WorldY", "WorldZ", "RotX", "RotY", "RotZ"}:
            self._updating = True
            try:
                self._sync_group_placement_from_properties(obj)
            finally:
                self._updating = False
            return

        if prop == "ShapeType":
            self._updating = True
            try:
                self._ensure_shape_properties(obj)
            finally:
                self._updating = False
            self.mark_geometry_dirty()
            return

        shape_properties = {
            p["name"]
            for properties in oba_optical_shapes.SHAPE_PROPERTIES.values()
            for p in properties
        }
        if prop in shape_properties:
            self.mark_geometry_dirty()

    def execute(self, obj):
        if getattr(self, "_updating", False):
            return

        if not getattr(self, "_geometry_dirty", True):
            return
        self._updating = True

        try:
            # group = self.Group or getattr(obj, "OpticalObject", None)

            # group = self.Group
            group = getattr(self, "Group", None)

            self.Group = group

            # self._set_placement_from_properties(obj)

            if not group:
                return

            mod = OPTICAL_MODULES.get(str(group.OpticalModel))
            # if mod and getattr(mod, "AFFECTS_GEOMETRY", False):
            #     oba_optical_lens.update_calculated_properties(group, obj)
            if mod and getattr(mod, "AFFECTS_GEOMETRY", False) and hasattr(mod, "update_calculated_properties"):
                mod.update_calculated_properties(group, obj)

            shape = oba_optical_shapes.build_shape(obj)
            if shape and not shape.isNull():
                obj.Shape = shape

                group_proxy = getattr(group, "Proxy", None)
                if group_proxy:
                    geometry_hash = self._geometry_hash(shape)
                    geometry_changed = geometry_hash != str(
                        getattr(group, "GeomHash", "")
                    )
                    if geometry_changed:
                        group.GeomHash = geometry_hash

                    binders = getattr(group, "Binders", [])
                    if str(group.OpticalModel) == "None":
                        if binders:
                            group_proxy._clear_optical_binders()
                    elif geometry_changed or len(binders) != len(shape.Faces):
                        group_proxy._build_optical_binders()
                self._geometry_dirty = False

            try:
                _trigger_ray_engine("OpticalShape rebuilt", group)
            except Exception:
                pass
        except Exception as exc:
            App.Console.PrintError("[OBA] OpticalShape: {}\n".format(exc))
        finally:
            self._updating = False

    @staticmethod
    def _geometry_hash(shape):
        try:
            return str(shape.BoundBox) + str(shape.Volume)
        except Exception:
            return ""

    def onDocumentRestored_old(self, obj):
        self.Object = obj
        obj.Proxy = self
        self._updating = False
        self._ensure_shape_properties(obj)
        # self.Group = getattr(obj, "OpticalObject", None)
        self.Group = None

    def onDocumentRestored(self, obj):
        self.Object = obj
        obj.Proxy = self
        self._updating = False
        self._geometry_dirty = True
        self._placement_sync_pending = False
        self._initializing = False
        self._ensure_shape_properties(obj)

        # Återställ gruppreferensen från FreeCAD-länken.
        self.Group = getattr(obj, "OpticalObject", None)

    def __getstate__(self):
        # Spara inte FeaturePython-referenser i proxytillståndet.
        return {}

    def __setstate__(self, state):
        # FreeCAD återkopplar objektet via onDocumentRestored().
        self.Object = None
        self.Group = None
        self._updating = False
        self._geometry_dirty = True
        self._placement_sync_pending = False
        self._initializing = False


class OpticalShapeViewProvider(OBAViewProviderBase):
    def __init__(self, vobj):
        super().__init__(vobj)

    def onDocumentRestored(self, vobj):
        self.Object = vobj.Object


class OpticalObjectViewProvider(OBAViewProviderBase):
    def __init__(self, vobj):
        super().__init__(vobj)
        self.dialog_class = OpticalObjectDialog


class OpticalObjectDialog(OBABaseDialog):
    ALLOW_SURFACE_SELECTION = False

    def __init__(self, obj):
        super().__init__(obj, title="Optical Object")
        self.obj = obj
        self.obj.Proxy.dialog = self
        self.dynamic_widget = None
        self._spinboxes = {}
        self.build_ui()

    def build_ui(self):
        from .oba_optical_dialog_builder import OBADialogBuilder

        if self.dynamic_widget:
            self.custom_layout.removeWidget(self.dynamic_widget)
            self.dynamic_widget.deleteLater()

        self._spinboxes = {}
        self.dynamic_widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.dynamic_widget)

        self._combo_optical(layout)
        shape_obj = get_shape_obj(self.obj)

        if shape_obj:
            builder = OBADialogBuilder(self, shape_obj, layout)
            self._combo_shape(layout, shape_obj)
            builder.build_shape()

        placement_builder = OBADialogBuilder(self, self.obj, layout)
        placement_builder.build_placement()

        mod = OPTICAL_MODULES.get(str(self.obj.OpticalModel))
        beh = OPTICAL_BEHAVIOUR.get(str(self.obj.OpticalModel))
        builder = OBADialogBuilder(self, self.obj, layout)
        builder.build_module(mod)
        builder.build_behaviour(beh)

        layout.addStretch()
        self.custom_layout.addWidget(self.dynamic_widget)

    def _combo_optical(self, layout):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Optical model"))
        combo = QtWidgets.QComboBox()
        combo.addItems(ALL_OPTICAL_GROUPS)
        combo.setCurrentText(str(self.obj.OpticalModel))
        combo.currentTextChanged.connect(lambda value: setattr(self.obj, "OpticalModel", value))
        row.addWidget(combo)
        layout.addLayout(row)

    def _combo_shape(self, layout, shape_obj):
        mod = OPTICAL_MODULES.get(str(self.obj.OpticalModel), oba_optical_none)
        shapes = getattr(mod, "SUPPORTED_SHAPES", oba_optical_shapes.SHAPES)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Shape"))
        combo = QtWidgets.QComboBox()
        combo.addItems(shapes)
        combo.setCurrentText(str(shape_obj.ShapeType))

        # combo.currentTextChanged.connect(lambda value: setattr(shape_obj, "ShapeType", value))

        row.addWidget(combo)
        layout.addLayout(row)

        def changed(value):
            shape_obj.ShapeType = value
            if shape_obj.Document:
                shape_obj.Document.recompute()
            QtCore.QTimer.singleShot(
                0,
                self.build_ui,
            )

        combo.currentTextChanged.connect(changed)

    def _on_change(self, prop, value):
        target = self.obj

        if prop in ("ShapeType", "Diameter", "Thickness", "Radius1", "Radius2", "Width", "Height", "Length", "UseDShape", "FlatDistance"):
            target = get_shape_obj(self.obj) or self.obj
        if prop in target.PropertiesList:
            setattr(target, prop, value)
            if target.Document:
                target.Document.recompute()

    def update_ui_from_object(self):
        pass


def OBA_CreateOpticalObject(show_dialog=True):
    doc = App.ActiveDocument or App.newDocument()

    # ----------------------------------
    # Container
    # ----------------------------------
    group = doc.addObject(
        "App::DocumentObjectGroupPython",
        "OpticalObject",
    )

    OBAOpticalObject(group)

    # ----------------------------------
    # Shape
    # ----------------------------------
    shape_obj = doc.addObject(
        "Part::FeaturePython",
        f"{group.Name}_Shape",
    )

    OpticalShape(shape_obj, group)

    # länka
    group.ShapeObj = shape_obj

    shape_obj.OpticalObject = group

    group.addObject(shape_obj)

    # ----------------------------------
    # View providers
    # ----------------------------------
    if App.GuiUp:
        OpticalObjectViewProvider(group.ViewObject)
        OpticalShapeViewProvider(shape_obj.ViewObject)

    # ----------------------------------
    # Initial shape setup
    # ----------------------------------
    shape_obj.Proxy.set_model(
        shape_obj,
        str(group.OpticalModel),
    )

    doc.recompute()

    # ----------------------------------
    # Dialog
    # ----------------------------------
    if show_dialog:
        OpticalObjectDialog(group).show()

    return group
