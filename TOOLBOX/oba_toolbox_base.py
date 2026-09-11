# oba_toolbox_base.py
#
# Shared boilerplate for OBA cube + ellipsoid optical components.
#

import math
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtWidgets

from oba_objects.oba_base import (
    OBABaseDialog,
    OBAElementProxy,
    OBAViewProviderBase,
)

BASE_PATH = os.path.dirname(__file__)


def focus_distance(a, b):
    """Return C = sqrt(A² - B²), the centre-to-focus distance."""
    if a <= 0 or b <= 0:
        raise ValueError("A and B must be greater than zero.")
    if a < b:
        raise ValueError("A must be greater than or equal to B.")
    return math.sqrt(max(0.0, a * a - b * b))


def validate_cube(width, height):
    if width <= 0:
        raise ValueError("Width must be greater than zero.")
    if height <= 0:
        raise ValueError("Height must be greater than zero.")


def validate_ellipsoid(a, b, b2=None):
    if a <= 0 or b <= 0:
        raise ValueError("A and B must be greater than zero.")
    if a < b:
        raise ValueError("A must be greater than or equal to B.")
    if b2 is not None and b2 <= 0:
        raise ValueError("B2 must be greater than zero.")


def create_ellipsoid(doc, a, b, b2, tmp_name="_OBA_EllipsoidTmp", label="_OBA temporary ellipsoid"):
    """
    Create a temporary Part::Ellipsoid and return (object, copied shape).

    FreeCAD convention used here:
        Radius1 = Z
        Radius2 = X
        Radius3 = Y
    """
    old = doc.getObject(tmp_name)
    if old is not None:
        doc.removeObject(old.Name)

        # doc.recompute()

    tmp = doc.addObject("Part::Ellipsoid", tmp_name)
    tmp.Label = label
    tmp.Radius1 = a
    tmp.Radius2 = b
    tmp.Radius3 = b2
    tmp.Angle1 = -90.0
    tmp.Angle2 = 90.0
    tmp.Angle3 = 360.0

    # doc.recompute()
    return tmp, tmp.Shape.copy()


def cut_shapes(base_shape, tool_shapes):
    """Fuse tool shapes and subtract them from the base shape."""
    if not tool_shapes:
        return base_shape

    try:
        tools = tool_shapes[0].fuse(tool_shapes[1:])
    except Exception:
        tools = tool_shapes[0].multiFuse(tool_shapes[1:])

    try:
        shape = base_shape.cut(tools)
    except Exception:
        shape = base_shape.cut(tool_shapes[0])
        for tool in tool_shapes[1:]:
            shape = shape.cut(tool)

    try:
        shape = shape.removeSplitter()
    except Exception:
        pass

    return shape


def make_centered_cube(width, depth, height, x=0.0, y=0.0, z=0.0):
    """
    Cube centred around (x, y, z)

        X = x - Width/2  ... x + Width/2
        Y = y - Depth/2  ... y + Depth/2
        Z = z - Height/2 ... z + Height/2
    """

    return Part.makeBox(
        width,
        depth,
        height,
        App.Vector(
            x - width / 2.0,
            y - depth / 2.0,
            z - height / 2.0,
        ),
    )


def install_properties(obj, specs):
    for spec in specs:

        # 1. Guard: Skapa bara egenskapen om den inte redan finns
        if not hasattr(obj, spec["name"]):
            obj.addProperty(spec["type"], spec["name"], spec["group"], spec.get("doc", ""))

        # 2. Guard: Sätt standardvärde ENDAST om 'default' finns i spec
        # OCH om egenskapen är tom/nollställd (så du inte skriver över sparad data)
        if "default" in spec:
            current_value = getattr(obj, spec["name"])

            # Kollar om värdet är oanvänt (t.ex. 0.0, None eller tom sträng) innan default sätts
            if not current_value or current_value == 0.0:
                setattr(obj, spec["name"], spec["default"])


def install_properties_old(obj, specs):
    for spec in specs:

        if hasattr(obj, spec["name"]):
            continue

        obj.addProperty(spec["type"], spec["name"], spec["group"], spec.get("doc", ""))

        setattr(obj, spec["name"], spec["default"])


def make_calculated_length(obj, name, doc):
    if not hasattr(obj, name):
        obj.addProperty("App::PropertyLength", name, "Calculated", doc)
    obj.setEditorMode(name, 1)


def make_optical_type(obj, value):
    if not hasattr(obj, "OpticalType"):
        obj.addProperty(
            "App::PropertyString",
            "OpticalType",
            "Base",
            "Type of optical element",
        )
    obj.OpticalType = value


def remove_objects(doc, names):
    for name in names:
        obj = doc.getObject(name)
        if obj is not None:
            try:
                doc.removeObject(obj.Name)
            except Exception:
                pass
    try:
        doc.recompute()
    except Exception:
        pass


class OBAToolboxViewProviderBase(OBAViewProviderBase):
    """Shared view-provider boilerplate for mirror components."""

    dialog_class = None

    def __init__(self, vobj, dialog_class):
        self.dialog_class = dialog_class
        super().__init__(vobj)
        self.dialog_class = dialog_class
        try:
            vobj.DisplayMode = "Flat Lines"
        except Exception:
            pass

    def doubleClicked(self, vobj):
        try:
            print("[OBA] doubleClicked:", vobj.Object.Name)

            if hasattr(self, "dialog_class") and self.dialog_class:
                dlg = self.dialog_class(vobj.Object)
                dlg.show()
            else:
                print("[OBA] missing dialog_class")
            return True  # ✅ ALLTID TRUE

        except Exception as e:
            App.Console.PrintError(f"[OBA] doubleClick error: {e}\n")
            return True  # ✅ stoppa fallback

    def getIcon(self):
        try:
            obj = self.Object
            ot = getattr(obj, "OpticalType", "").lower()
            if not ot:
                return ""

            # print("ikooon", ot)
            path = os.path.join(BASE_PATH, "..", "icons", f"oba_{ot}.svg")
            if os.path.exists(path):
                return path
        except Exception:
            pass
        return ""

    def onDocumentRestored(self, vobj):
        super().onDocumentRestored(vobj)
        self.dialog_class = type(self).dialog_class
        # restore_view_provider(obj, WhiteCellMainMirrorViewProvider, WhiteCellMainMirrorDialog)


class OBAToolboxDialogBase(OBABaseDialog):
    """Shared placement/debug helpers used by mirror dialogs."""

    ALLOW_SURFACE_SELECTION = False

    def __init__(self, obj, title, parent=None):
        super().__init__(obj, title=title, parent=parent)
        self._closing = False

    @staticmethod
    def _create_spinbox(
        suffix="",
        minimum=-1_000_000.0,
        maximum=1_000_000.0,
        decimals=4,
        step=1.0,
        changed=None,
    ):
        spin = QtWidgets.QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        if changed:
            spin.valueChanged.connect(changed)
        return spin

    def _add_spin_old(self, label, prop, mn, mx, unit, layout):
        w = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        w.setProperty("minimum", mn)
        w.setProperty("maximum", mx)
        w.setProperty("unit", unit)
        w.setProperty("rawValue", float(getattr(self.obj, prop)))
        w.setProperty("binding", f"{self.obj.Name}.{prop}")
        w.valueChanged.connect(lambda v, p=prop: setattr(self.obj, p, v.Value))
        layout.addRow(label, w)
        return w

    def _add_spin(self, label, prop, mn, mx, unit, layout):
        w = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        w.setProperty("minimum", mn)
        w.setProperty("maximum", mx)
        w.setProperty("unit", unit)
        w.setProperty("rawValue", float(getattr(self.obj, prop)))
        w.setProperty("binding", f"{self.obj.Name}.{prop}")
        layout.addRow(label, w)
        return w

    def add_placement_group_med_spinn(self):
        group = QtWidgets.QGroupBox("Placement")
        form = QtWidgets.QFormLayout(group)

        self.pos_x = self._add_spin("X", "PlacementX", -1_000_000, 1_000_000, "mm", form)
        self.pos_y = self._add_spin("Y", "PlacementY", -1_000_000, 1_000_000, "mm", form)
        self.pos_z = self._add_spin("Z", "PlacementZ", -1_000_000, 1_000_000, "mm", form)
        self.custom_layout.addWidget(group)

    def add_placement_group(self):
        group = QtWidgets.QGroupBox("Placement")
        form = QtWidgets.QFormLayout(group)

        self.pos_x = self._create_spinbox(" mm", changed=self._placement_changed)
        self.pos_y = self._create_spinbox(" mm", changed=self._placement_changed)
        self.pos_z = self._create_spinbox(" mm", changed=self._placement_changed)

        form.addRow("X", self.pos_x)
        form.addRow("Y", self.pos_y)
        form.addRow("Z", self.pos_z)
        self.custom_layout.addWidget(group)

    def _placement_changed(self):
        placement = self.obj.Placement.copy()
        placement.Base = App.Vector(
            self.pos_x.value(),
            self.pos_y.value(),
            self.pos_z.value(),
        )
        self.obj.Placement = placement

    def reload_placement(self):
        placement = self.obj.Placement.Base
        self.pos_x.setValue(placement.x)
        self.pos_y.setValue(placement.y)
        self.pos_z.setValue(placement.z)

    def add_debug_checkbox(self, text="Show debug ellipsoid"):
        self.show_debug = QtWidgets.QCheckBox(text)
        self.show_debug.setChecked(bool(self.obj.ShowDebugEllipsoid))
        self.show_debug.toggled.connect(lambda v: setattr(self.obj, "ShowDebugEllipsoid", v))
        self.custom_layout.addWidget(self.show_debug)

    def closeEvent(self, event):
        try:
            if hasattr(self.obj, "ShowDebugEllipsoid"):
                self.obj.ShowDebugEllipsoid = False
        except Exception:
            pass

        if self._closing:
            event.accept()
            return
        self._closing = True
        self.obj.Document.recompute()
        Gui.updateGui()
        super().closeEvent(event)


def ensure_debug_property(obj):
    if not hasattr(obj, "ShowDebugEllipsoid"):
        obj.addProperty(
            "App::PropertyBool",
            "ShowDebugEllipsoid",
            "Debug",
            "Show debug ellipsoid",
        )
        obj.ShowDebugEllipsoid = False


def update_debug_ellipsoid(obj, shape, visible):
    name = f"{obj.Name}_DebugEllipsoid"
    if not visible:
        remove_objects(obj.Document, [name])
        return

    dbg = obj.Document.getObject(name)
    if dbg is None:
        dbg = obj.Document.addObject("Part::Feature", name)
    dbg.Label = f"{obj.Label} debug ellipsoid"
    dbg.Shape = shape.copy()
    dbg.ViewObject.Transparency = 80
    dbg.ViewObject.ShapeColor = (1.0, 0.0, 0.0)

    try:
        dbg.Placement = obj.Placement
    except Exception:
        pass


def restore_view_provider(obj, view_provider_cls):
    if not (App.GuiUp and obj.ViewObject):
        return
    if not hasattr(obj.ViewObject, "Proxy") or obj.ViewObject.Proxy is None:
        view_provider_cls(obj.ViewObject)
    else:
        obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)
    obj.ViewObject.update()


# class OBADeleteObserver:
#     def slotDeletedObject(self, document, object_name):
#         if not object_name.endswith("_CompMirror"):
#             return

#         internal_name = f"{object_name}_Internal"
#         internal = document.getObject(internal_name)

#         if internal is not None:
#             App.Console.PrintMessage(f"[OBA] Delete cleanup: {internal_name}\n")
#             document.removeObject(internal_name)


# _delete_observer = None


# def _install_delete_observer():
#     global _delete_observer

#     if _delete_observer is None:
#         _delete_observer = OBADeleteObserver()
#         App.addDocumentObserver(_delete_observer)

# _install_delete_observer()

# _delete_observer = OBADeleteObserver()
# App.addDocumentObserver(_delete_observer)
