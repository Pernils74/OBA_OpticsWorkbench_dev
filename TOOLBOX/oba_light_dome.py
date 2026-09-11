# oba_light_dome.py
#
# OBA Light Dome / Component Mirror
#
# Geometry:
#   - One rectangular Part::Box
#   - One Part::Ellipsoid centred in the cube
#   - The ellipsoid is the optical component mirror
#   - The ellipsoid is subtracted from the cube
#
# The final geometry is:
#
#   Cube
#     -> Cut: Cube - Ellipsoid
#
# Construction objects are created directly in the document.
# The ViewProvider claims them as children of the main FeaturePython
# object.
#
# Ellipsoid convention:
#   A  = semi-major axis
#   B  = semi-minor radius
#   B2 = optional independent Radius3
#   C  = sqrt(A^2 - B^2)
#
# The ellipsoid centre is at the cube centre in X/Z and at the
# optical surface reference Y = 0.
#

import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from oba_objects.oba_base import OBAElementProxy

from .oba_toolbox_base import (
    OBAToolboxDialogBase,
    OBAToolboxViewProviderBase,
    ensure_debug_property,
    focus_distance,
    install_properties,
    make_calculated_length,
    make_optical_type,
    restore_view_provider,
)

LIGHT_DOME_PROPERTIES = [
    {"name": "Width", "type": "App::PropertyLength", "group": "Light Dome", "default": 100.0, "doc": "Width of the cube/body along X"},
    {"name": "Height", "type": "App::PropertyLength", "group": "Light Dome", "default": 30.0, "doc": "Height of the cube/body along Z"},
    {"name": "A", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 40.0, "doc": "Ellipsoid semi-major axis"},
    {"name": "B", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 30.0, "doc": "Ellipsoid semi-minor radius"},
    {"name": "UseIndependentRadius3", "type": "App::PropertyBool", "group": "Ellipsoid", "default": False, "doc": "Use independent radius in Y direction"},
    {"name": "B2", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 20.0, "doc": "Independent ellipsoid Y radius"},
    {"name": "FocusDistance", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 26.4575131106, "doc": "Distance from ellipsoid centre to focus"},
    {"name": "DirectionX", "type": "App::PropertyFloat", "group": "Orientation", "default": 1.0, "doc": "Optical axis X direction"},
    {"name": "DirectionY", "type": "App::PropertyFloat", "group": "Orientation", "default": 0.0, "doc": "Optical axis Y direction"},
    {"name": "DirectionZ", "type": "App::PropertyFloat", "group": "Orientation", "default": 0.0, "doc": "Optical axis Z direction"},
]


class OBALightDome:
    # ------------------------------------------------------------------
    # Construction objects belonging to this FeaturePython object
    # ------------------------------------------------------------------
    CHILD_OBJECTS = ("_cube", "_ellipsoid", "_cut")

    def _init_runtime_state(self):
        """
        Initialise all Python-only runtime references.
        """
        self._initializing = False
        self._updating = False

        self._cube = None
        self._ellipsoid = None
        self._cut = None

    def __init__(self, obj):
        self._init_runtime_state()
        obj.Proxy = self
        self.Object = obj

        self._initializing = True
        install_properties(obj, LIGHT_DOME_PROPERTIES)
        ensure_debug_property(obj)

        obj.setEditorMode("FocusDistance", 1)
        make_calculated_length(obj, "MirrorCentreX", "X coordinate of ellipsoid centre")
        make_calculated_length(obj, "MirrorCentreZ", "Z coordinate of ellipsoid centre")
        make_optical_type(obj, "ComponentMirror")

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

        All construction objects live directly in the document.
        There is no internal App::Part and no temporary Shape geometry.
        """
        doc = obj.Document
        # --------------------------------------------------------------
        # Find existing objects
        # --------------------------------------------------------------
        if self._cube is None:
            self._cube = doc.getObject(f"{obj.Name}_Cube")
        if self._ellipsoid is None:
            self._ellipsoid = doc.getObject(f"{obj.Name}_Ellipsoid")
        if self._cut is None:
            self._cut = doc.getObject(f"{obj.Name}_Cut")
        # --------------------------------------------------------------
        # Validate references
        # --------------------------------------------------------------
        if not self._obj_exists(self._cube):
            self._cube = None
        if not self._obj_exists(self._ellipsoid):
            self._ellipsoid = None
        if not self._obj_exists(self._cut):
            self._cut = None
        # --------------------------------------------------------------
        # Create missing objects
        # --------------------------------------------------------------
        if self._cube is None:
            self._cube = doc.addObject("Part::Box", f"{obj.Name}_Cube")
            self._cube.Label = f"{obj.Label} Cube"
        if self._ellipsoid is None:
            self._ellipsoid = doc.addObject("Part::Ellipsoid", f"{obj.Name}_Ellipsoid")
            self._ellipsoid.Label = f"{obj.Label} Ellipsoid"
            self._ellipsoid.ViewObject.ShapeColor = (1.0, 0.0, 0.0)
        if self._cut is None:
            self._cut = doc.addObject("Part::Cut", f"{obj.Name}_Cut")
            self._cut.Label = f"{obj.Label} Cut"
        # --------------------------------------------------------------
        # Boolean relationship
        # --------------------------------------------------------------
        self._cut.Base = self._cube
        self._cut.Tool = self._ellipsoid

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _update_cube(self, obj):
        """
        Update the real Part::Box.

        Local cube coordinates:

            X = -Width/2 ... +Width/2
            Y = 0 ... depth
            Z = -Height/2 ... +Height/2

        The local placement is then transformed by obj.Placement.
        """
        width = float(obj.Width)
        height = float(obj.Height)
        b = float(obj.B)
        a = float(obj.A)

        depth = 1.4 * a

        self._cube.Length = width
        self._cube.Width = depth
        self._cube.Height = height
        cube_local = App.Placement(App.Vector(-width / 2.0, -depth * 0.5, -height / 2.0), App.Rotation())

        self._cube.Placement = obj.Placement.multiply(cube_local)

    def _update_ellipsoid(self, obj):
        """
        Update the real Part::Ellipsoid.

        The ellipsoid follows the same orientation convention as the
        previous Light Dome implementation.

        The geometry is created at the local Main Mirror coordinate
        system and the final placement is:

            obj.Placement * local_placement
        """
        a = float(obj.A)
        b = float(obj.B)
        height = float(obj.Height)

        if obj.UseIndependentRadius3:
            b2 = float(obj.B2)
        else:
            b2 = b

        ellipsoid = self._ellipsoid

        ellipsoid.Radius1 = a
        ellipsoid.Radius2 = b
        ellipsoid.Radius3 = b2

        # rot_z = App.Rotation(App.Vector(0.0, 0.0, 1.0), -90.0)
        # rot_x = App.Rotation(App.Vector(1.0, 0.0, 0.0), 270.0)
        # rot = rot_x.multiply(rot_z)

        rot = App.Rotation(App.Vector(-1.0, 1.0, 1.0), 120.0)

        rot = rot + tillskotten ifrån direction

        start_placement = App.Placement(App.Vector(0.0, b, -height / 2), rot)

        final_placement = start_placement + extra förflyttning som är en transformerad kvot ifrån den extra rotering ifrån direction


        ellipsoid.Placement = obj.Placement.multiply(final_placement)

    # ------------------------------------------------------------------
    # Debug visibility
    # ------------------------------------------------------------------

    def _update_debug(self, obj):
        """
        Show the real construction ellipsoid when debugging is enabled.

        The final Cut remains the normal visible result.
        """
        try:
            debug = bool(obj.ShowDebugEllipsoid)
        except Exception:
            debug = False
        try:
            self._cube.ViewObject.Visibility = False
            self._cut.ViewObject.Visibility = True
            if debug:
                self._ellipsoid.ViewObject.Visibility = True
                self._ellipsoid.ViewObject.Transparency = 80
            else:
                self._ellipsoid.ViewObject.Visibility = False
                self._ellipsoid.ViewObject.Transparency = 0
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Rebuild
    # ------------------------------------------------------------------

    def _rebuild(self, obj):
        """
        Rebuild the complete Light Dome geometry immediately.
        """
        if self._updating:
            return
        self._updating = True
        try:
            if self._initializing:
                return
            required = ("Width", "Height", "A", "B")
            for name in required:
                if not hasattr(obj, name):
                    return
            width = float(obj.Width)
            height = float(obj.Height)
            a = float(obj.A)
            b = float(obj.B)
            if width <= 0 or height <= 0:
                raise ValueError("Width and Height must be greater than zero.")
            if a <= 0 or b <= 0:
                raise ValueError("A and B must be greater than zero.")
            if a < b:
                raise ValueError("A must be greater than or equal to B.")
            if obj.UseIndependentRadius3:
                b2 = float(obj.B2)
                if b2 <= 0:
                    raise ValueError("B2 must be greater than zero.")

            # ----------------------------------------------------------
            # Ensure real Part objects exist
            # ----------------------------------------------------------
            self._ensure_features(obj)
            # ----------------------------------------------------------
            # Update geometry
            # ----------------------------------------------------------
            self._update_cube(obj)
            self._update_ellipsoid(obj)
            # ----------------------------------------------------------
            # Calculated values
            # ----------------------------------------------------------
            c = focus_distance(a, b)
            obj.FocusDistance = c
            obj.MirrorCentreX = 0.0
            obj.MirrorCentreZ = 0.0

            # ----------------------------------------------------------
            # Visibility
            # ----------------------------------------------------------
            self._update_debug(obj)
            # ----------------------------------------------------------
            # Recompute real Part::Box / Part::Ellipsoid / Part::Cut
            # ----------------------------------------------------------
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
        if prop in (
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
                App.Console.PrintError("[OBA] Light Dome rebuild failed: " f"{exc}\n")
                return
        elif prop == "Placement":
            try:
                self._ensure_features(obj)
                self._update_cube(obj)
                self._update_ellipsoid(obj)
                self._update_debug(obj)
                obj.Document.recompute()
            except Exception as exc:
                App.Console.PrintError("[OBA] Light Dome placement update failed: " f"{exc}\n")
                return
        elif prop == "ShowDebugEllipsoid":
            self._update_debug(obj)

    # ------------------------------------------------------------------
    # Document restore
    # ------------------------------------------------------------------

    def onDocumentRestored(self, obj):
        """
        Restore Python runtime state and reconnect to existing
        construction objects.
        """
        self._init_runtime_state()

        self._initializing = True

        obj.Proxy = self
        self.Object = obj

        try:
            install_properties(obj, LIGHT_DOME_PROPERTIES)
            ensure_debug_property(obj)
            obj.setEditorMode("FocusDistance", 1)
            make_calculated_length(obj, "MirrorCentreX", "X coordinate of ellipsoid centre")
            make_calculated_length(obj, "MirrorCentreZ", "Z coordinate of ellipsoid centre")
            make_optical_type(obj, "ComponentMirror")
            self._ensure_features(obj)
        finally:
            self._initializing = False
        try:
            self._rebuild(obj)
        except Exception as exc:
            App.Console.PrintError("[OBA] Light Dome restore rebuild failed: " f"{exc}\n")

        restore_view_provider(obj, LightDomeViewProvider)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    def onDelete(self, obj, subelements):
        """
        Remove all construction objects when the main object is deleted.

        This is kept here as a fallback as well as in the ViewProvider.
        """
        doc = obj.Document

        for attr_name in reversed(self.CHILD_OBJECTS):
            child = getattr(self, attr_name, None)
            if child is None:
                continue
            try:
                if doc.getObject(child.Name):
                    doc.removeObject(child.Name)
            except Exception as exc:
                App.Console.PrintError("[OBA] Could not remove Light Dome child " f"{child.Name}: {exc}\n")
        return True

    # ------------------------------------------------------------------
    # Python serialization
    # ------------------------------------------------------------------

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        self._init_runtime_state()


# ======================================================================
# Dialog
# ======================================================================


class LightDomeDialog(OBAToolboxDialogBase):

    def __init__(self, obj, title="Component Mirror Settings", parent=None):
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
        self.direction_x = self._add_spin("Direction X", "DirectionX", -10, 10, "mm", form)
        self.direction_y = self._add_spin("Direction Y", "DirectionY", -10, 10, "mm", form)
        self.direction_z = self._add_spin("Direction Z", "DirectionZ", -10, 10, "mm", form)
        self.c = QtWidgets.QLabel()
        self.centre_x = QtWidgets.QLabel()
        self.centre_z = QtWidgets.QLabel()
        form.addRow("Focus distance C", self.c)
        form.addRow("Ellipsoid centre X", self.centre_x)
        form.addRow("Ellipsoid centre Z", self.centre_z)
        self.custom_layout.addWidget(group)
        self.add_debug_checkbox()
        self.add_placement_group()
        info = QtWidgets.QLabel("The light dome consists of one ellipsoid " "centred in the cube. The ellipsoid is " "subtracted from the cube.")
        info.setWordWrap(True)
        self.custom_layout.addWidget(info)
        for widget in (self.width, self.height, self.a, self.b, self.b2):
            widget.valueChanged.connect(self._preview)
        self.use_b2.toggled.connect(self._use_b2_changed)
        self.reload()

    # ------------------------------------------------------------------
    # B2
    # ------------------------------------------------------------------

    def _use_b2_changed(self, checked):
        self.obj.UseIndependentRadius3 = checked
        self._preview()

    # ------------------------------------------------------------------
    # Reload
    # ------------------------------------------------------------------

    def reload(self):
        self.use_b2.setChecked(bool(self.obj.UseIndependentRadius3))

        self.reload_placement()
        self._preview()

    # ------------------------------------------------------------------
    # Preview information
    # ------------------------------------------------------------------

    def _preview(self):
        width = float(self.obj.Width)
        height = float(self.obj.Height)
        a = float(self.obj.A)
        b = float(self.obj.B)
        valid = width > 0 and height > 0 and a > 0 and b > 0 and a >= b
        if a > 0 and b > 0 and a >= b:
            self.c.setText(f"{math.sqrt(max(0.0, a * a - b * b)):.4f} mm")
        else:
            self.c.setText("Invalid A/B")
            valid = False
        self.centre_x.setText("0.0000 mm")
        self.centre_z.setText("0.0000 mm")
        self.b2.setEnabled(self.use_b2.isChecked())
        if self.use_b2.isChecked() and float(self.obj.B2) <= 0:
            valid = False
        return valid


# ======================================================================
# View Provider
# ======================================================================


class LightDomeViewProvider(OBAToolboxViewProviderBase):
    dialog_class = LightDomeDialog

    def __init__(self, vobj):
        super().__init__(vobj, LightDomeDialog)

    def claimChildren(self):
        """
        Show the real construction objects directly underneath the
        main Light Dome object in the tree.
        """
        obj = getattr(self, "Object", None)
        if obj is None:
            return []
        proxy = getattr(obj, "Proxy", None)
        if proxy is None:
            return []
        children = []
        for attr_name in getattr(proxy, "CHILD_OBJECTS", ()):
            child = getattr(proxy, attr_name, None)
            if child is not None:
                children.append(child)
        return children

    def onDelete(self, vobj, subelements):
        """
        Remove all construction objects when the main object is deleted.
        """
        obj = getattr(self, "Object", None)
        if obj is None:
            return True

        proxy = getattr(obj, "Proxy", None)
        if proxy is None:
            return True

        doc = obj.Document
        child_names = getattr(proxy, "CHILD_OBJECTS", ())

        # Remove Cut first, then ellipsoid and cube.
        for attr_name in reversed(child_names):
            child = getattr(proxy, attr_name, None)
            if child is None:
                continue
            try:
                if doc.getObject(child.Name):
                    doc.removeObject(child.Name)
            except Exception as exc:
                App.Console.PrintError("[OBA] Could not remove Light Dome child " f"{child.Name}: {exc}\n")

        return True


# ======================================================================
# Factory
# ======================================================================


def OBA_CreateLightDome(
    doc=None,
    label="Light Dome",
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

    # --------------------------------------------------------------
    # Validate input
    # --------------------------------------------------------------

    if width <= 0 or height <= 0:
        raise ValueError("Width and Height must be greater than zero.")
    if a <= 0 or b <= 0:
        raise ValueError("A and B must be greater than zero.")
    if a < b:
        raise ValueError("A must be greater than or equal to B.")
    # --------------------------------------------------------------
    # Main FeaturePython object
    # --------------------------------------------------------------

    obj = doc.addObject("Part::FeaturePython", "OBALightDome")
    obj.Label = label
    OBALightDome(obj)
    obj.Width = App.Units.Quantity(f"{width} mm")
    obj.Height = App.Units.Quantity(f"{height} mm")
    obj.A = App.Units.Quantity(f"{a} mm")
    obj.B = App.Units.Quantity(f"{b} mm")
    # --------------------------------------------------------------
    # Placement
    # --------------------------------------------------------------

    if placement is None:
        placement = App.Placement(App.Vector(x, y, z), App.Rotation())
    obj.Placement = placement
    # --------------------------------------------------------------
    # View provider
    # --------------------------------------------------------------

    if App.GuiUp:
        LightDomeViewProvider(obj.ViewObject)
    doc.recompute()
    if show_dialog:
        LightDomeDialog(obj).show()
    return obj


# ======================================================================
# Public create() entry point
# ======================================================================


def create(
    doc=None,
    label="Component_Mirror",
    width=100.0,
    height=30.0,
    a=40.0,
    b=30.0,
    x=0,
    y=0,
    z=0,
):
    return OBA_CreateLightDome(
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
