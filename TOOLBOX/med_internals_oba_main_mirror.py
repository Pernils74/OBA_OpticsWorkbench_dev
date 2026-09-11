# oba_main_mirror.py
#
# OBA Main Mirror / Split Mirror
#
# Geometry:
#   - One rectangular cube/body
#   - Two identical ellipsoids
#   - The ellipsoids are mirrored around the cube centre plane
#   - Both ellipsoids are subtracted from the cube
#
# The final geometry is:
#
#   Cube
#     -> Cut1: Cube - Left ellipsoid
#     -> Cut2: Cut1 - Right ellipsoid
#
# The construction objects are kept inside an internal App::Part.
#

import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from oba_objects.oba_base import OBAElementProxy

from .oba_toolbox_base import (
    OBAToolboxDialogBase,
    OBAToolboxViewProviderBase,
    focus_distance,
    install_properties,
    make_calculated_length,
    make_optical_type,
    restore_view_provider,
)

MAIN_MIRROR_PROPERTIES = [
    {"name": "Width", "type": "App::PropertyLength", "group": "Main Mirror", "default": 100.0, "doc": "Width of the cube/body along X"},
    {"name": "Height", "type": "App::PropertyLength", "group": "Main Mirror", "default": 30.0, "doc": "Height of the cube/body along Z"},
    {"name": "SplitOffset", "type": "App::PropertyLength", "group": "Main Mirror", "default": 40.0, "doc": "Distance between the two ellipsoid focal points"},
    {"name": "A", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 40.0, "doc": "Ellipsoid semi-major axis"},
    {"name": "B", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 30.0, "doc": "Ellipsoid semi-minor radius"},
    {"name": "UseIndependentRadius3", "type": "App::PropertyBool", "group": "Ellipsoid", "default": False, "doc": "Use independent radius in Y direction"},
    {"name": "B2", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 20.0, "doc": "Independent ellipsoid Y radius"},
    {"name": "FocusDistance", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 26.4575131106, "doc": "Distance from ellipsoid centre to focus"},
    {"name": "TiltAngle", "type": "App::PropertyAngle", "group": "Ellipsoid", "default": 0.0, "doc": "Tilt angle of the ellipsoids around the Z axis"},
    {"name": "DebugShowEllipsoids", "type": "App::PropertyBool", "group": "Debug", "default": False, "doc": "Show ellipsoids for debugging"},
]


class OBAMainMirror:

    def _init_runtime_state(self):
        """
        Initialise all Python-only runtime references.

        These references are not persisted by FreeCAD and therefore must
        also be recreated when a document is restored.
        """
        self._initializing = False
        self._updating = False
        # self._restoring = False

        self._internal = None
        self._cube = None
        self._ellipsoid_Left = None
        self._ellipsoid_Right = None
        self._cut1 = None
        self._cut2 = None

    def __init__(self, obj):
        self._init_runtime_state()

        obj.Proxy = self
        self.Object = obj

        self._initializing = True

        obj.setEditorMode("Placement", 1)

        install_properties(obj, MAIN_MIRROR_PROPERTIES)
        if hasattr(obj, "FocusDistance"):
            obj.setEditorMode("FocusDistance", 1)
        make_calculated_length(obj, "Ellipsoid1FocusX", "X position of first ellipsoid focus")
        make_calculated_length(obj, "Ellipsoid2FocusX", "X position of second ellipsoid focus")
        make_calculated_length(obj, "MirrorPlaneX", "X coordinate of mirror symmetry plane")
        make_optical_type(obj, "MainMirror")
        self._initializing = False

    # ------------------------------------------------------------------
    # Runtime object handling
    # ------------------------------------------------------------------

    @staticmethod
    def _obj_exists(obj):
        if obj is None:
            return False
        try:
            return obj.Document is not None and obj.Document.getObject(obj.Name) is obj
        except Exception:
            return False

    def _ensure_features(self, obj):
        """
        Find existing construction objects or create them if missing.

        This is deliberately safe to call both during normal rebuilds and
        after a document has been restored.
        """
        doc = obj.Document

        if self._internal is None:
            self._internal = doc.getObject(f"{obj.Name}_Internal")
        if self._cube is None:
            self._cube = doc.getObject(f"{obj.Name}_Cube")
        if self._ellipsoid_Left is None:
            self._ellipsoid_Left = doc.getObject(f"{obj.Name}_Ellipsoid1")
        if self._ellipsoid_Right is None:
            self._ellipsoid_Right = doc.getObject(f"{obj.Name}_Ellipsoid2")
        if self._cut1 is None:
            self._cut1 = doc.getObject(f"{obj.Name}_Cut1")
        if self._cut2 is None:
            self._cut2 = doc.getObject(f"{obj.Name}_Cut2")

        if not self._obj_exists(self._internal):
            self._internal = None
        if not self._obj_exists(self._cube):
            self._cube = None
        if not self._obj_exists(self._ellipsoid_Left):
            self._ellipsoid_Left = None
        if not self._obj_exists(self._ellipsoid_Right):
            self._ellipsoid_Right = None
        if not self._obj_exists(self._cut1):
            self._cut1 = None
        if not self._obj_exists(self._cut2):
            self._cut2 = None

        if self._internal is None:
            self._internal = doc.addObject("App::Part", f"{obj.Name}_Internal")
            self._internal.Label = f"{obj.Label} Internal"

        if self._cube is None:
            self._cube = doc.addObject("Part::Box", f"{obj.Name}_Cube")

        if self._ellipsoid_Left is None:
            self._ellipsoid_Left = doc.addObject("Part::Ellipsoid", f"{obj.Name}_Ellipsoid1")
            self._ellipsoid_Left.ViewObject.ShapeColor = (1.0, 0.0, 0.0)  # röd

        if self._ellipsoid_Right is None:
            self._ellipsoid_Right = doc.addObject("Part::Ellipsoid", f"{obj.Name}_Ellipsoid2")
            self._ellipsoid_Right.ViewObject.ShapeColor = (0.0, 0.0, 1.0)  # blå

        children = set(self._internal.Group)

        if self._cube not in children:
            self._internal.addObject(self._cube)

        if self._ellipsoid_Left not in children:
            self._internal.addObject(self._ellipsoid_Left)

        if self._ellipsoid_Right not in children:
            self._internal.addObject(self._ellipsoid_Right)

        if self._cut1 is None:
            self._cut1 = doc.addObject("Part::Cut", f"{obj.Name}_Cut1")

        self._cut1.Base = self._cube
        self._cut1.Tool = self._ellipsoid_Left

        if self._cut2 is None:
            self._cut2 = doc.addObject("Part::Cut", f"{obj.Name}_Cut2")

        self._cut2.Base = self._cut1
        self._cut2.Tool = self._ellipsoid_Right

        if self._cut1 not in self._internal.Group:
            self._internal.addObject(self._cut1)

        if self._cut2 not in self._internal.Group:
            self._internal.addObject(self._cut2)

        # try:
        #     self._cube.ViewObject.Visibility = False
        #     self._ellipsoid_Left.ViewObject.Visibility = False
        #     self._ellipsoid_Right.ViewObject.Visibility = False
        #     self._cut1.ViewObject.Visibility = False
        #     self._cut2.ViewObject.Visibility = True
        # except Exception:
        #     pass

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _update_cube(self, obj):
        width = float(obj.Width)
        height = float(obj.Height)

        # Keep enough depth for the ellipsoid geometry.
        depth = 1.5 * float(obj.B)

        self._cube.Length = width
        self._cube.Width = depth
        self._cube.Height = height

        self._cube.Placement.Base = App.Vector(-width / 2.0, 0.0, -height / 2.0)

    def _update_ellipsoids(self, obj):
        split = float(obj.SplitOffset)

        a = float(obj.A)
        b = float(obj.B)

        if obj.UseIndependentRadius3:
            b2 = float(obj.B2)
        else:
            b2 = b

        tilt = float(obj.TiltAngle)

        left = self._ellipsoid_Left

        left.Radius1 = a
        left.Radius2 = b
        left.Radius3 = b2

        left_placement = App.Placement()

        left_placement.Base = App.Vector(-split / 2.0, 0.0, 0.0)
        rot1 = App.Rotation(App.Vector(1, 0, 0), 90)
        rot2 = App.Rotation(App.Vector(0, 0, 1), 270 + tilt)
        left_placement.Rotation = rot2.multiply(rot1)

        left.Placement = left_placement

        right = self._ellipsoid_Right

        right.Radius1 = a
        right.Radius2 = b
        right.Radius3 = b2

        right_placement = App.Placement()
        right_placement.Base = App.Vector(split / 2.0, 0.0, 0.0)
        rot1 = App.Rotation(App.Vector(1, 0, 0), 90)
        rot2 = App.Rotation(App.Vector(0, 0, 1), 270 - tilt)

        right_placement.Rotation = rot2.multiply(rot1)

        right.Placement = right_placement

    def _update_debug_visibility(self, obj):
        try:
            debug = bool(obj.DebugShowEllipsoids)

            self._cube.ViewObject.Visibility = False
            self._cut1.ViewObject.Visibility = False
            self._cut2.ViewObject.Visibility = True

            if debug:
                self._ellipsoid_Left.ViewObject.Visibility = True
                self._ellipsoid_Right.ViewObject.Visibility = True

                self._ellipsoid_Left.ViewObject.Transparency = 80
                self._ellipsoid_Right.ViewObject.Transparency = 80
            else:
                self._ellipsoid_Left.ViewObject.Visibility = False
                self._ellipsoid_Right.ViewObject.Visibility = False

        except Exception:
            pass

    # ------------------------------------------------------------------
    # Rebuild
    # ------------------------------------------------------------------

    def _rebuild(self, obj):
        """
        Rebuild the complete Main Mirror geometry immediately.
        """
        if self._updating:
            return

        self._updating = True

        if self._initializing:
            return

        required = ("Width", "Height", "SplitOffset", "A", "B")
        for name in required:
            if not hasattr(obj, name):
                return

        try:
            self._ensure_features(obj)

            self._internal.Placement = obj.Placement

            self._update_cube(obj)
            self._update_ellipsoids(obj)

            self._update_debug_visibility(obj)

            c = focus_distance(float(obj.A), float(obj.B))
            obj.FocusDistance = c
            obj.Ellipsoid1FocusX = -float(obj.SplitOffset) / 2.0
            obj.Ellipsoid2FocusX = float(obj.SplitOffset) / 2.0
            obj.MirrorPlaneX = 0.0

            obj.Document.recompute()

        finally:
            self._updating = False

    # ------------------------------------------------------------------
    # Property changes
    # ------------------------------------------------------------------

    def onChanged(self, obj, prop):
        if getattr(self, "_initializing", False):
            return

        if getattr(self, "_updating", False):
            return

        App.Console.PrintMessage(f"onChanged: {prop}\n")

        rebuild_properties = {
            "Width",
            "Height",
            "SplitOffset",
            "A",
            "B",
            "UseIndependentRadius3",
            "B2",
            "TiltAngle",
            "DebugShowEllipsoids",
        }

        if prop in rebuild_properties:
            try:
                self._rebuild(obj)
            except Exception as exc:
                App.Console.PrintError(f"[OBA] Main Mirror rebuild failed: {exc}\n")

        elif prop == "Placement":
            try:
                if self._obj_exists(self._internal):
                    self._internal.Placement = obj.Placement
                obj.Document.recompute()
            except Exception as exc:
                App.Console.PrintError(f"[OBA] Main Mirror placement update failed: {exc}\n")

        # super().onChanged(obj, prop)

    # ------------------------------------------------------------------
    # Document restore
    # ------------------------------------------------------------------

    def onDocumentRestored(self, obj):
        """
        Restore Python runtime state and reconnect to the existing
        FreeCAD construction objects.
        """
        self._init_runtime_state()

        self._initializing = True

        obj.Proxy = self
        self.Object = obj

        obj.setEditorMode("Placement", 1)
        try:
            install_properties(obj, MAIN_MIRROR_PROPERTIES)

            if hasattr(obj, "FocusDistance"):
                obj.setEditorMode("FocusDistance", 1)

            make_calculated_length(obj, "Ellipsoid1FocusX", "X position of first ellipsoid focus")
            make_calculated_length(obj, "Ellipsoid2FocusX", "X position of second ellipsoid focus")
            make_calculated_length(obj, "MirrorPlaneX", "X coordinate of mirror symmetry plane")
            make_optical_type(obj, "MainMirror")
            self._ensure_features(obj)

        finally:
            self._initializing = False

        try:
            self._rebuild(obj)
        except Exception as exc:
            App.Console.PrintError(f"[OBA] Main Mirror restore rebuild failed: {exc}\n")

        restore_view_provider(obj, MainMirrorViewProvider)

    def onDelete(self, obj, subelements):
        doc = obj.Document
        # 1. Hitta det interna objektets namn baserat på huvudobjektets interna namn
        internal_name = f"{obj.Name}_Internal"
        # 2. Ta bara bort det interna objektet.
        # Huvudobjektet (obj) tas bort automatiskt av FreeCAD direkt efter denna metod.
        try:
            if doc.getObject(internal_name):
                print("försöker ta bort ", internal_name)
                doc.removeObject(internal_name)
        except Exception as e:
            print(f"Kunde inte ta bort internal: {str(e)}")
            pass
        # 3. Returnera True för att ge FreeCAD grönt ljus att slutföra raderingen av huvudobjektet
        return True

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        self._init_runtime_state()


# ======================================================================
# Dialog
# ======================================================================


class MainMirrorDialog(OBAToolboxDialogBase):

    def __init__(self, obj, title="Main Mirror Main Mirror Settings", parent=None):
        super().__init__(obj, title=title, parent=parent)

        self._updating_widgets = False
        group = QtWidgets.QGroupBox("Main Mirror Main Mirror Parameters")
        form = QtWidgets.QFormLayout(group)

        self.width = self._add_spin("Width", "Width", 0, 1000, "mm", form)
        self.height = self._add_spin("Height", "Height", 0, 1000, "mm", form)
        self.split = self._add_spin("SplitOffset", "SplitOffset", 0, 1000, "mm", form)

        self.a = self._add_spin("A", "A", 0, 1000, "mm", form)
        self.b = self._add_spin("B", "B", 0, 1000, "mm", form)
        self.use_b2 = QtWidgets.QCheckBox("Use independent Radius3")
        form.addRow(self.use_b2)

        self.b2 = self._add_spin("B2", "B2", 0, 1000, "mm", form)
        self.tiltangle = self._add_spin("Tilt angle", "TiltAngle", -90, 90, "°", form)

        self.c = QtWidgets.QLabel()
        self.focus1 = QtWidgets.QLabel()
        self.focus2 = QtWidgets.QLabel()
        self.left_angle = QtWidgets.QLabel()
        self.right_angle = QtWidgets.QLabel()

        form.addRow("Focus distance C", self.c)
        form.addRow("Ellipsoid 1 focus X", self.focus1)
        form.addRow("Ellipsoid 2 focus X", self.focus2)
        form.addRow("Left ellipsoid angle", self.left_angle)
        form.addRow("Right ellipsoid angle", self.right_angle)

        self.debug_show = QtWidgets.QCheckBox("Show ellipsoids (debug)")
        form.addRow(self.debug_show)

        self.custom_layout.addWidget(group)

        self.add_placement_group()
        info = QtWidgets.QLabel("The two ellipsoids are mirrored around the centre " "plane of the Main Mirror.\n\n" "SplitOffset is the distance between the two " "ellipsoid focal points.\n\n" "TiltAngle is the symmetric tilt of the ellipsoids.")
        info.setWordWrap(True)
        self.custom_layout.addWidget(info)

        self.width.valueChanged.connect(lambda value: self._set_property("Width", value.Value))
        self.height.valueChanged.connect(lambda value: self._set_property("Height", value.Value))
        self.split.valueChanged.connect(lambda value: self._set_property("SplitOffset", value.Value))
        self.a.valueChanged.connect(lambda value: self._set_property("A", value.Value))
        self.b.valueChanged.connect(lambda value: self._set_property("B", value.Value))
        self.b2.valueChanged.connect(lambda value: self._set_property("B2", value.Value))
        self.tiltangle.valueChanged.connect(lambda value: self._set_property("TiltAngle", value.Value))
        self.use_b2.toggled.connect(self._use_b2_changed)
        self.debug_show.toggled.connect(lambda checked: self._set_property("DebugShowEllipsoids", checked))

        self.reload()

    # ------------------------------------------------------------------
    # Property editing
    # ------------------------------------------------------------------

    def _set_property(self, prop, value):
        if self._updating_widgets:
            return
        try:
            setattr(self.obj, prop, value)
            self._update_information()
        except Exception as exc:
            App.Console.PrintError(f"[OBA] Failed to update {prop}: {exc}\n")

    def _use_b2_changed(self, checked):
        if self._updating_widgets:
            return
        try:
            self.obj.UseIndependentRadius3 = checked
            self.b2.setEnabled(checked)
            self._update_information()
        except Exception as exc:
            App.Console.PrintError("[OBA] Failed to update UseIndependentRadius3: " f"{exc}\n")

    # ------------------------------------------------------------------
    # Dialog refresh
    # ------------------------------------------------------------------

    def reload(self):
        self._updating_widgets = True

        try:
            self.use_b2.setChecked(bool(self.obj.UseIndependentRadius3))
            self.b2.setEnabled(bool(self.obj.UseIndependentRadius3))
            self.reload_placement()
            self._update_information()
            self.debug_show.setChecked(bool(self.obj.DebugShowEllipsoids))
        finally:
            self._updating_widgets = False

    def _update_information(self):
        width = float(self.obj.Width)
        height = float(self.obj.Height)
        split = float(self.obj.SplitOffset)
        a = float(self.obj.A)
        b = float(self.obj.B)
        tilt = float(self.obj.TiltAngle)

        # --------------------------------------------------------------
        # Focus distance
        # --------------------------------------------------------------

        if a > 0 and b > 0 and a >= b:
            c = math.sqrt(max(0.0, a * a - b * b))
            self.c.setText(f"{c:.4f} mm")
        else:
            self.c.setText("Invalid A/B")

        # --------------------------------------------------------------
        # Focus positions
        # --------------------------------------------------------------
        self.focus1.setText(f"{-split / 2.0:.4f} mm")
        self.focus2.setText(f"{split / 2.0:.4f} mm")

        # --------------------------------------------------------------
        # Symmetric ellipsoid angles
        # --------------------------------------------------------------

        self.left_angle.setText(f"{90 - tilt:.3f}°")
        self.right_angle.setText(f"{90 + tilt:.3f}°")
        self.b2.setEnabled(bool(self.obj.UseIndependentRadius3))


# ======================================================================
# View Provider
# ======================================================================


class MainMirrorViewProvider(OBAToolboxViewProviderBase):
    # class MainMirrorViewProvider:

    dialog_class = MainMirrorDialog

    def __init__(self, vobj):
        super().__init__(vobj, MainMirrorDialog)
        pass

    def attach(self, vobj):

        self.ViewObject = vobj
        self.Object = vobj.Object

    def canTransform(self):
        """
        Disable the standard Transform/Gizmo action for the main object.
        """
        return False

    def claimChildren(self):
        """
        Show the internal construction container underneath the main
        Main Mirror object in the tree.
        """
        obj = getattr(self, "Object", None)
        if obj is None:
            return []
        proxy = getattr(obj, "Proxy", None)
        if proxy is None:
            return []
        internal = getattr(proxy, "_internal", None)
        if internal is not None:
            return [internal]
        return []

    def doubleClicked(self, vobj):
        """
        Open the Main Mirror settings dialog when the object is
        double-clicked in the tree.
        """
        obj = getattr(vobj, "Object", None)

        if obj is None:
            return False

        try:
            dialog = MainMirrorDialog(obj)
            # Keep a reference so the dialog cannot be garbage-collected
            # while it is still open.
            self._dialog = dialog

            dialog.show()
            dialog.raise_()
            dialog.activateWindow()

            return True

        except Exception as exc:
            App.Console.PrintError(f"[OBA] Failed to open Main Mirror dialog: {exc}\n")
            return False


# ======================================================================
# Factory
# ======================================================================


def OBA_CreateMainMirror(
    doc=None,
    label="Main_Mirror",
    width=100.0,
    height=30.0,
    split_offset=40.0,
    a=40.0,
    b=30.0,
    tiltangle=0.0,
    x=0.0,
    y=30.0,
    z=0.0,
    placement=None,
    show_dialog=True,
):
    doc = doc or App.ActiveDocument or App.newDocument()

    # --------------------------------------------------------------
    # Validate input
    # --------------------------------------------------------------

    if width <= 0:
        raise ValueError("Width must be greater than zero.")
    if height <= 0:
        raise ValueError("Height must be greater than zero.")
    if split_offset < 0 or split_offset > width:
        raise ValueError("SplitOffset must be between zero and Width.")
    if a <= 0:
        raise ValueError("A must be greater than zero.")
    if b <= 0:
        raise ValueError("B must be greater than zero.")
    if a < b:
        raise ValueError("A must be greater than or equal to B.")
    if b > height:
        raise ValueError("B must be less than or equal to Height.")

    # --------------------------------------------------------------
    # Main FeaturePython object
    # --------------------------------------------------------------

    obj = doc.addObject("Part::FeaturePython", "OBA_MainMirror")

    obj.Label = label
    OBAMainMirror(obj)

    obj.Width = App.Units.Quantity(f"{width} mm")
    obj.Height = App.Units.Quantity(f"{height} mm")
    obj.SplitOffset = App.Units.Quantity(f"{split_offset} mm")
    obj.A = App.Units.Quantity(f"{a} mm")
    obj.B = App.Units.Quantity(f"{b} mm")
    obj.TiltAngle = App.Units.Quantity(f"{tiltangle} deg")

    if placement is None:
        placement = App.Placement(App.Vector(x, y, z), App.Rotation())

    obj.Placement = placement
    if App.GuiUp:
        MainMirrorViewProvider(obj.ViewObject)
    doc.recompute()

    if show_dialog:
        dialog = MainMirrorDialog(obj)
        dialog.show()

    return obj


# ======================================================================
# Public create() entry point
# ======================================================================


def create(doc=None, label="Main_Mirror", width=100.0, height=30.0, split_offset=40.0, a=40.0, b=30.0, tiltangle=0.0, x=0.0, y=30.0, z=0.0):
    return OBA_CreateMainMirror(
        doc=doc,
        label=label,
        width=width,
        height=height,
        split_offset=split_offset,
        a=a,
        b=b,
        tiltangle=tiltangle,
        x=x,
        y=y,
        z=z,
        show_dialog=False,
    )
