# oba_component_mirror_builder.py
#
# OBA Component Mirror
#
# Geometry:
#   - One rectangular cube/body
#   - One ellipsoid centred in the cube
#   - The ellipsoid is the optical component mirror
#   - The ellipsoid is subtracted from the cube
#
# The ellipsoid uses the same convention as the White Cell:
#   A  = semi-major axis
#   B  = semi-minor radius
#   B2 = optional independent Y radius
#   C  = sqrt(A^2 - B^2)
#
# The ellipsoid centre is at the cube centre in X/Z and at the
# optical surface reference Y = 0.
#
# Shared boilerplate lives in oba_mirror_common.py.
#

import math
from re import split

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from oba_objects.oba_base import OBAElementProxy

from .oba_toolbox_base import (
    OBAToolboxDialogBase,
    OBAToolboxViewProviderBase,
    create_ellipsoid,
    ensure_debug_property,
    focus_distance,
    install_properties,
    make_calculated_length,
    make_centered_cube,
    make_optical_type,
    remove_objects,
    restore_view_provider,
)

COMPONENT_MIRROR_PROPERTIES = [
    {"name": "Width", "type": "App::PropertyLength", "group": "Component Mirror", "default": 100.0, "doc": "Width of the cube/body along X"},
    {"name": "Height", "type": "App::PropertyLength", "group": "Component Mirror", "default": 30.0, "doc": "Height of the cube/body along Z"},
    {"name": "A", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 40.0, "doc": "Ellipsoid semi-major axis"},
    {"name": "B", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 30.0, "doc": "Ellipsoid semi-minor radius"},
    {"name": "UseIndependentRadius3", "type": "App::PropertyBool", "group": "Ellipsoid", "default": False, "doc": "Use independent radius in Y direction"},
    {"name": "B2", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 20.0, "doc": "Independent ellipsoid Y radius"},
    {"name": "FocusDistance", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 26.4575131106, "doc": "Distance from ellipsoid centre to focus"},
]


class OBAComponentMirror(OBAElementProxy):
    def __init__(self, obj):
        self._initializing = True
        self._updating = False
        self._ellipsoid = None

        super().__init__(obj, use_binders=False)
        install_properties(obj, COMPONENT_MIRROR_PROPERTIES)
        ensure_debug_property(obj)

        obj.setEditorMode("FocusDistance", 1)
        make_calculated_length(obj, "MirrorCentreX", "X coordinate of ellipsoid centre")
        make_calculated_length(obj, "MirrorCentreZ", "Z coordinate of ellipsoid centre")
        make_optical_type(obj, "ComponentMirror")

        self._initializing = False

    def _rebuild(self, obj):
        old_placement = obj.Placement.copy()

        width = float(obj.Width)
        height = float(obj.Height)
        a = float(obj.A)
        b = float(obj.B)
        b2 = float(obj.B2) if obj.UseIndependentRadius3 else b

        if width <= 0 or height <= 0:
            raise ValueError("Width and Height must be greater than zero.")
        if a <= 0 or b <= 0:
            raise ValueError("A and B must be greater than zero.")
        if a < b:
            raise ValueError("A must be greater than or equal to B.")
        if b2 <= 0:
            raise ValueError("B2 must be greater than zero.")

        c = focus_distance(a, b)

        # Same cube convention as the White Cell:
        # X = -Width/2 ... +Width/2
        # Y = 0 ... depth
        # Z = -Height/2 ... +Height/2
        depth = 1.5 * b
        cube = make_centered_cube(width, depth, height)

        doc = obj.Document
        tmp, ellipsoid = create_ellipsoid(
            doc,
            a,
            b,
            b2,
            "_OBA_ComponentMirror_EllipsoidTmp",
            "_OBA Component Mirror temporary ellipsoid",
        )

        try:

            # First orient the ellipsoid exactly as the optical component
            # convention used by the existing White Cell geometry.
            ellipsoid.rotate(
                App.Vector(0.0, 0.0, 0.0),
                App.Vector(1.0, 0.0, 0.0),
                -90.0,
            )
            ellipsoid.rotate(
                App.Vector(0.0, 0.0, 0.0),
                App.Vector(0.0, 0.0, 1.0),
                -90.0,
            )

            ellipsoid.translate(App.Vector(0.0, b, 0.0))

            # The component mirror is centred in X/Z. Its optical reference
            # point is Y = 0, i.e. the front face of the cube coordinate
            # system.
            self._ellipsoid = ellipsoid.copy()

            try:
                shape = cube.cut(ellipsoid)
            except Exception:
                shape = cube.cut(ellipsoid.copy())

            try:
                shape = shape.removeSplitter()
            except Exception:
                pass

            obj.Shape = shape
            obj.FocusDistance = c
            obj.MirrorCentreX = 0.0
            obj.MirrorCentreZ = 0.0

            was_updating = self._updating
            self._updating = True
            try:
                obj.Placement = old_placement
            finally:
                self._updating = was_updating
        finally:
            remove_objects(doc, [tmp.Name])

        self._update_debug(obj)

    def _update_debug(self, obj):
        name = f"{obj.Name}_DebugEllipsoid"
        if not obj.ShowDebugEllipsoid:
            remove_objects(obj.Document, [name])
            return

        if self._ellipsoid is None:
            return

        dbg = obj.Document.getObject(name)
        if dbg is None:
            dbg = obj.Document.addObject("Part::Feature", name)
            # spara lokal offset
            dbg.addProperty("App::PropertyVector", "DebugOffset", "Debug", "Local debug offset")
            # dbg.DebugOffset = self._ellipsoid.Placement.Base.copy()

        dbg.Label = f"{obj.Label} debug ellipsoid"
        dbg.Shape = self._ellipsoid.copy()
        dbg.ViewObject.Transparency = 80
        dbg.ViewObject.ShapeColor = (1.0, 0.0, 0.0)

        b = float(obj.B)
        dbg.Placement.Base = obj.Placement.Base + App.Vector(0, b, 0)

    def onChanged(self, obj, prop):
        if getattr(self, "_initializing", False):
            return
        if prop == "Placement":
            self._update_debug(obj)
        elif prop == "ShowDebugEllipsoid":
            self._update_debug(obj)
        elif prop in (
            "Width",
            "Height",
            "A",
            "B",
            "UseIndependentRadius3",
            "B2",
        ):
            try:
                self._rebuild(obj)
            except Exception as exc:
                App.Console.PrintError(f"[OBA] Component Mirror rebuild failed: {exc}\n")
                return

        super().onChanged(obj, prop)

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self.Object = obj
        install_properties(obj, COMPONENT_MIRROR_PROPERTIES)
        ensure_debug_property(obj)
        obj.setEditorMode("FocusDistance", 1)
        make_calculated_length(obj, "MirrorCentreX", "X coordinate of ellipsoid centre")
        make_calculated_length(obj, "MirrorCentreZ", "Z coordinate of ellipsoid centre")
        make_optical_type(obj, "ComponentMirror")

        restore_view_provider(obj, ComponentMirrorViewProvider)

    def onDelete(self, obj, subelements):
        remove_objects(obj.Document, [f"{obj.Name}_DebugEllipsoid"])
        return True

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class ComponentMirrorDialog(OBAToolboxDialogBase):
    def __init__(
        self,
        obj,
        title="Component Mirror Settings",
        parent=None,
    ):
        super().__init__(obj, title=title, parent=parent)

        group = QtWidgets.QGroupBox("Component Mirror")
        form = QtWidgets.QFormLayout(group)

        self.width = self._add_spin("Width", "Width", 0, 1000, "mm", form)
        self.height = self._add_spin("Height", "Height", 0, 1000, "mm", form)
        self.a = self._add_spin("A", "A", 0, 1000, "mm", form)
        self.b = self._add_spin("B", "B", 0, 1000, "mm", form)

        self.use_b2 = QtWidgets.QCheckBox("Use independent Radius3")
        form.addWidget(self.use_b2)

        self.b2 = self._add_spin("B2", "B2", 0, 1000, "mm", form)

        self.c = QtWidgets.QLabel()
        self.centre_x = QtWidgets.QLabel()
        self.centre_z = QtWidgets.QLabel()

        form.addRow("Focus distance C", self.c)
        form.addRow("Ellipsoid centre X", self.centre_x)
        form.addRow("Ellipsoid centre Z", self.centre_z)

        self.custom_layout.addWidget(group)
        self.add_debug_checkbox()
        self.add_placement_group()

        info = QtWidgets.QLabel("The component mirror consists of one ellipsoid centred in " "the cube. The ellipsoid is subtracted from the cube.")
        info.setWordWrap(True)
        self.custom_layout.addWidget(info)

        for w in (
            self.width,
            self.height,
            self.a,
            self.b,
            self.b2,
        ):
            w.valueChanged.connect(self._preview)
        self.use_b2.toggled.connect(self._use_b2_changed)

        self.reload()

    def _use_b2_changed(self, checked):
        self.obj.UseIndependentRadius3 = checked
        self._preview()

    def reload(self):
        self.use_b2.setChecked(bool(self.obj.UseIndependentRadius3))
        self.reload_placement()
        self._preview()

    def _preview(self):
        width = float(self.obj.Width)
        height = float(self.obj.Height)
        a = float(self.obj.A)
        b = float(self.obj.B)

        valid = width > 0 and height > 0 and a > 0 and b > 0 and a >= b

        if a > 0 and b > 0 and a >= b:
            self.c.setText(f"{math.sqrt(max(0.0, a*a-b*b)):.4f} mm")
        else:
            self.c.setText("Invalid A/B")
            valid = False

        self.centre_x.setText("0.0000 mm")
        self.centre_z.setText("0.0000 mm")

        self.b2.setEnabled(self.use_b2.isChecked())
        if self.use_b2.isChecked() and float(self.obj.B2) <= 0:
            valid = False

        return valid


class ComponentMirrorViewProvider(OBAToolboxViewProviderBase):
    dialog_class = ComponentMirrorDialog

    def __init__(self, vobj):
        super().__init__(vobj, ComponentMirrorDialog)


def OBA_CreateComponentMirror(
    doc=None,
    label="Component_Mirror",
    width=100.0,
    height=30.0,
    a=40.0,
    b=30.0,
    x=0.0,
    y=0.0,
    z=0.0,
    placement=None,
    show_dialog=True,
):
    doc = doc or App.ActiveDocument or App.newDocument()

    if width <= 0 or height <= 0:
        raise ValueError("Width and Height must be greater than zero.")
    if a <= 0 or b <= 0:
        raise ValueError("A and B must be greater than zero.")
    if a < b:
        raise ValueError("A must be greater than or equal to B.")

    obj = doc.addObject("Part::FeaturePython", "OBAComponentMirror")
    obj.Label = label
    OBAComponentMirror(obj)

    obj.Width = App.Units.Quantity(f"{width} mm")
    obj.Height = App.Units.Quantity(f"{height} mm")
    obj.A = App.Units.Quantity(f"{a} mm")
    obj.B = App.Units.Quantity(f"{b} mm")

    if placement is None:
        placement = App.Placement(App.Vector(x, y, z), App.Rotation())
    obj.Placement = placement

    if App.GuiUp:
        ComponentMirrorViewProvider(obj.ViewObject)

    doc.recompute()

    if show_dialog:
        ComponentMirrorDialog(obj).show()
    return obj


def create(doc=None, label="Component_Mirror", width=100.0, height=30.0, a=40.0, b=30.0, x=0, y=0, z=0):
    return OBA_CreateComponentMirror(
        doc=doc,
        label=label,
        width=width,
        height=height,
        a=a,
        b=b,
        x=x,
        y=y,
        z=z,
        show_dialog=False,
    )
