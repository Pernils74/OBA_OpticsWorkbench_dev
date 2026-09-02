# oba_ellipsoid_old.py
#
# OBA Ellipsoid
#
# Local origin = one focal point.
#
# A = semi-major axis
# B = semi-minor axis
# C = sqrt(A^2 - B^2)
#
# The ellipsoid is generated with centre at (-C, 0, 0),
# so the object's local origin is one of the two foci.
#
# Placement:
#   Placement.Base      = focal point position
#   Placement.Rotation  = object orientation
#
# The optical axis is the local +X direction.
#
# IMPORTANT:
#   Changing A or B only rebuilds the local Shape.
#   The existing Placement is preserved.
#
#   This means that a manual transformation made with the
#   FreeCAD Transform Gizmo is not lost when A or B changes.


import math

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtWidgets

from oba_objects.oba_base import (
    OBABaseDialog,
    OBAElementProxy,
    OBAViewProviderBase,
    _trigger_ray_engine,
)

# ============================================================
#  O B J E K T  –  E L L I P S O I D
# ============================================================


OPTICAL_PROPERTIES = [
    {
        "name": "A",
        "type": "App::PropertyLength",
        "group": "Ellipsoid",
        "default": 40.0,
        "doc": "Semi-major axis",
    },
    {
        "name": "B",
        "type": "App::PropertyLength",
        "group": "Ellipsoid",
        "default": 20.0,
        "doc": "Semi-minor axis",
    },
    {"name": "DirectionX", "type": "App::PropertyFloat", "group": "Orientation", "default": 1.0, "doc": "Optical axis X direction"},
    {"name": "DirectionY", "type": "App::PropertyFloat", "group": "Orientation", "default": 0.0, "doc": "Optical axis Y direction"},
    {"name": "DirectionZ", "type": "App::PropertyFloat", "group": "Orientation", "default": 0.0, "doc": "Optical axis Z direction"},
    {"name": "UseAimPoint", "type": "App::PropertyBool", "group": "Orientation", "default": False, "doc": "Aim the optical axis at a point"},
    {"name": "AimX", "type": "App::PropertyDistance", "group": "Orientation", "default": 100.0, "doc": "Target X coordinate"},
    {"name": "AimY", "type": "App::PropertyDistance", "group": "Orientation", "default": 0.0, "doc": "Target Y coordinate"},
    {"name": "AimZ", "type": "App::PropertyDistance", "group": "Orientation", "default": 0.0, "doc": "Target Z coordinate"},
    {
        "name": "FocusDistance",
        "type": "App::PropertyLength",
        "group": "Ellipsoid",
        "default": 34.6410161514,
        "doc": "Distance from centre to focus",
    },
]


class OBAEllipsoid(OBAElementProxy):

    def __init__(self, obj):
        self._initializing = True

        # Initiera bas-properties.
        #
        # Ellipsoiden har sin egen Shape och använder inga
        # ShapeBinders.
        super().__init__(obj, use_binders=False)

        # --------------------------------------------------------
        # Properties
        # --------------------------------------------------------

        for p in OPTICAL_PROPERTIES:

            if not hasattr(obj, p["name"]):

                obj.addProperty(p["type"], p["name"], p["group"], p.get("doc", ""))

                if p["name"] == "FocusDistance":

                    # C är beräknat.
                    obj.setEditorMode("FocusDistance", 1)

                else:

                    setattr(obj, p["name"], p["default"])

        # --------------------------------------------------------
        # Optical type
        # --------------------------------------------------------

        if not hasattr(obj, "OpticalType"):

            obj.addProperty("App::PropertyString", "OpticalType", "Base", "Type of optical element")

        obj.OpticalType = "Ellipsoid"
        self._initializing = False

    # ========================================================
    #  F O C U S
    # ========================================================

    @staticmethod
    def focus_distance(a, b):
        """
        Calculate distance from ellipsoid centre to focus.

            C = sqrt(A² - B²)

        A = semi-major axis
        B = semi-minor axis
        """

        if a <= 0 or b <= 0:
            raise ValueError("A and B must be greater than zero.")

        if a < b:
            raise ValueError("A must be greater than or equal to B.")

        return math.sqrt(max(0.0, a * a - b * b))

    # ========================================================
    #  R E B U I L D   S H A P E
    # ========================================================

    def _rebuild(self, obj):

        # ----------------------------------------------------
        # IMPORTANT
        #
        # Save current Placement before changing Shape.
        #
        # This is what prevents a Transform Gizmo movement
        # from being lost when A or B is changed.
        # ----------------------------------------------------

        old_placement = obj.Placement.copy()

        a = float(obj.A)
        b = float(obj.B)

        # During creation one of the values may still be zero.
        if a <= 0 or b <= 0:
            return

        if a < b:
            raise ValueError("A must be greater than or equal to B.")

        c = self.focus_distance(a, b)

        # ----------------------------------------------------
        # Create temporary Part Ellipsoid.
        #
        # FreeCAD Part::Ellipsoid:
        #
        # Radius1 = Z
        # Radius2 = X
        # Radius3 = Y
        #
        # We want:
        #
        # X = A
        # Y = B
        # Z = B
        # ----------------------------------------------------

        doc = obj.Document

        tmp_name = "_OBA_Ellipsoid_Tmp"
        tmp = doc.getObject(tmp_name)
        if tmp is not None:

            doc.removeObject(tmp.Name)
            doc.recompute()

        tmp = doc.addObject("Part::Ellipsoid", tmp_name)

        tmp.Label = "_OBA temporary ellipsoid"

        tmp.Radius1 = b
        tmp.Radius2 = a
        tmp.Radius3 = b

        tmp.Angle1 = -90.0
        tmp.Angle2 = 90.0
        tmp.Angle3 = 360.0

        doc.recompute()

        # ----------------------------------------------------
        # Copy shape.
        # ----------------------------------------------------

        shape = tmp.Shape.copy()

        # ----------------------------------------------------
        # Move geometric centre to -C.
        #
        # Ellipsoid centre:
        #
        #     (-C, 0, 0)
        #
        # Local origin:
        #
        #     (0, 0, 0)
        #
        # Therefore local origin is a focal point.
        # ----------------------------------------------------

        shape.translate(App.Vector(-c, 0.0, 0.0))

        # ----------------------------------------------------
        # Assign Shape.
        # ----------------------------------------------------

        obj.Shape = shape

        # ----------------------------------------------------
        # Update calculated focus distance.
        # ----------------------------------------------------

        obj.FocusDistance = c

        # ----------------------------------------------------
        # VERY IMPORTANT:
        #
        # Restore EXACTLY the Placement we had before the
        # shape rebuild.
        #
        # This preserves:
        #
        #   - Transform Gizmo position
        #   - Transform Gizmo rotation
        #   - current focal point position
        #
        # A/B therefore never reset Placement.
        # ----------------------------------------------------

        was_updating = getattr(self, "_updating_orientation", False)
        self._updating_orientation = True
        try:
            obj.Placement = old_placement
        finally:
            self._updating_orientation = was_updating

        # ----------------------------------------------------
        # Remove temporary Part object.
        # ----------------------------------------------------

        doc.removeObject(tmp.Name)

    # ========================================================
    #  P L A C E M E N T   R O T A T I O N
    # ========================================================

    @staticmethod
    def rotation_from_direction(direction):
        direction = App.Vector(direction.x, direction.y, direction.z)
        if direction.Length == 0:
            raise ValueError("Direction must not be zero.")
        direction.normalize()
        return App.Rotation(App.Vector(1, 0, 0), direction)

    @classmethod
    def rotation_from_aimpoint(cls, obj, target_point):
        direction = target_point - obj.Placement.Base
        return cls.rotation_from_direction(direction)

    @classmethod
    def apply_orientation(cls, obj):
        if obj.UseAimPoint:
            target = App.Vector(obj.AimX, obj.AimY, obj.AimZ)
            rotation = cls.rotation_from_aimpoint(obj, target)
        else:
            direction = App.Vector(obj.DirectionX, obj.DirectionY, obj.DirectionZ)
            rotation = cls.rotation_from_direction(direction)

        placement = obj.Placement.copy()

        # IMPORTANT:
        # Only change Rotation.
        #
        # Placement.Base remains untouched.
        #
        # Therefore the focal point position remains exactly
        # where the user placed it.
        placement.Rotation = rotation

        obj.Placement = placement
        cls.synchronize_direction(obj)

    @staticmethod
    def synchronize_direction(obj):
        direction = obj.Placement.Rotation.multVec(App.Vector(1, 0, 0))
        obj.DirectionX = direction.x
        obj.DirectionY = direction.y
        obj.DirectionZ = direction.z

    # ========================================================
    #  C H A N G E D
    # ========================================================

    def onChanged(self, obj, prop):

        if getattr(self, "_initializing", False):
            return

        # ----------------------------------------------------
        # A/B
        #
        # Rebuild ONLY Shape.
        #
        # Placement is preserved inside _rebuild().
        # ----------------------------------------------------

        if prop in ("A", "B"):

            try:

                self._rebuild(obj)

            except Exception as exc:

                App.Console.PrintError("[OBA] Ellipsoid rebuild failed: " f"{exc}\n")

                return

        # ----------------------------------------------------
        # Direction and aim-point properties
        #
        # Change only Placement.Rotation.
        # Placement.Base is untouched.
        # ----------------------------------------------------

        elif prop in ("DirectionX", "DirectionY", "DirectionZ", "UseAimPoint", "AimX", "AimY", "AimZ"):

            was_updating = getattr(self, "_updating_orientation", False)
            try:

                if not was_updating:
                    self._updating_orientation = True
                    self.apply_orientation(obj)

            except Exception as exc:

                App.Console.PrintError("[OBA] Ellipsoid orientation failed: " f"{exc}\n")

                return

            finally:
                self._updating_orientation = was_updating

        elif prop == "Placement" and not getattr(self, "_updating_orientation", False):

            try:
                self._updating_orientation = True
                self.synchronize_direction(obj)
            finally:
                self._updating_orientation = False

        # ----------------------------------------------------
        # Let OBA base handle its normal processing.
        # ----------------------------------------------------

        super().onChanged(obj, prop)

    # ========================================================
    #  R E S T O R E
    # ========================================================

    def onDocumentRestored(self, obj):

        # ----------------------------------------------------
        # Restore App Proxy.
        # ----------------------------------------------------

        obj.Proxy = self

        self.Object = obj

        # ----------------------------------------------------
        # Make sure properties exist.
        # This also makes older documents safer to reopen.
        # ----------------------------------------------------

        if not hasattr(obj, "A"):
            obj.addProperty("App::PropertyLength", "A", "Ellipsoid", "Semi-major axis")

        if not hasattr(obj, "B"):
            obj.addProperty("App::PropertyLength", "B", "Ellipsoid", "Semi-minor axis")

        for p in OPTICAL_PROPERTIES:
            if p["name"] not in ("A", "B", "FocusDistance") and not hasattr(obj, p["name"]):
                obj.addProperty(p["type"], p["name"], p["group"], p.get("doc", ""))
                setattr(obj, p["name"], p["default"])

        self.synchronize_direction(obj)

        if not hasattr(obj, "FocusDistance"):
            obj.addProperty("App::PropertyLength", "FocusDistance", "Ellipsoid", "Distance from centre to focus")
            obj.setEditorMode("FocusDistance", 1)

        if not hasattr(obj, "OpticalType"):
            obj.addProperty("App::PropertyString", "OpticalType", "Base", "Type of optical element")

        obj.OpticalType = "Ellipsoid"

        # ----------------------------------------------------
        # Restore ViewProvider.
        # ----------------------------------------------------

        if App.GuiUp and obj.ViewObject:

            if (
                not hasattr(
                    obj.ViewObject,
                    "Proxy",
                )
                or obj.ViewObject.Proxy is None
            ):

                EllipsoidViewProvider(obj.ViewObject)

            else:

                obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)

                obj.ViewObject.Proxy.dialog_class = EllipsoidDialog

            obj.ViewObject.update()

    # ========================================================
    #  P I C K L E
    # ========================================================

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


# ============================================================
#  D I A L O G
# ============================================================


class EllipsoidDialog(OBABaseDialog):

    # Ellipsoid does not use ShapeBinder selection.
    ALLOW_SURFACE_SELECTION = False

    def __init__(
        self,
        obj,
        title="Ellipsoid Settings",
        parent=None,
    ):

        super().__init__(
            obj,
            title=title,
            parent=parent,
        )

        # ====================================================
        #  E L L I P S O I D
        # ====================================================

        group = QtWidgets.QGroupBox("Ellipsoid")

        form = QtWidgets.QFormLayout(group)

        # ----------------------------------------------------
        # A
        # ----------------------------------------------------

        self.a = QtWidgets.QDoubleSpinBox()

        self.a.setDecimals(4)
        self.a.setRange(0.0001, 1_000_000.0)
        self.a.setSingleStep(1.0)
        self.a.setSuffix(" mm")

        # ----------------------------------------------------
        # B
        # ----------------------------------------------------

        self.b = QtWidgets.QDoubleSpinBox()

        self.b.setDecimals(4)
        self.b.setRange(0.0001, 1_000_000.0)
        self.b.setSingleStep(1.0)
        self.b.setSuffix(" mm")

        # ----------------------------------------------------
        # C
        # ----------------------------------------------------

        self.c = QtWidgets.QLabel()

        # ----------------------------------------------------
        self.chkAimPoint = QtWidgets.QCheckBox("Aim at point")

        self.direction_x = self._coordinate_spin("")
        self.direction_y = self._coordinate_spin("")
        self.direction_z = self._coordinate_spin("")
        self.aim_x = self._coordinate_spin(" mm")
        self.aim_y = self._coordinate_spin(" mm")
        self.aim_z = self._coordinate_spin(" mm")

        # ----------------------------------------------------
        # Form
        # ----------------------------------------------------

        form.addRow("A (semi-major axis)", self.a)
        form.addRow("B (semi-minor axis)", self.b)
        form.addRow("Focus distance C", self.c)
        form.addRow(self.chkAimPoint)
        form.addRow("Direction X", self.direction_x)
        form.addRow("Direction Y", self.direction_y)
        form.addRow("Direction Z", self.direction_z)
        form.addRow("Target X", self.aim_x)
        form.addRow("Target Y", self.aim_y)
        form.addRow("Target Z", self.aim_z)
        self.custom_layout.addWidget(group)

        # ====================================================
        #  I N F O
        # ====================================================

        info = QtWidgets.QLabel(
            "The optical axis is the local +X direction.\n\n"
            "In Direction mode the axis direction is entered directly.\n\n"
            "In Aim mode the ellipsoid is rotated so that the optical "
            "axis points from the focal point towards the specified "
            "target coordinate."
        )

        info.setWordWrap(True)

        self.custom_layout.addWidget(info)

        # ====================================================
        #  B U T T O N S
        # ====================================================

        buttons = QtWidgets.QHBoxLayout()
        self.apply_button = QtWidgets.QPushButton("Apply")
        self.reset_button = QtWidgets.QPushButton("Reset")
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.reset_button)
        self.custom_layout.addLayout(buttons)

        # ====================================================
        #  S I G N A L S
        # ====================================================

        self.apply_button.clicked.connect(self.apply)
        self.reset_button.clicked.connect(self.reload)
        self.a.valueChanged.connect(self._preview)
        self.b.valueChanged.connect(self._preview)
        self.chkAimPoint.toggled.connect(self._update_orientation_controls)

        # ====================================================
        #  L O A D
        # ====================================================

        self.reload()

    # ========================================================
    #  R E L O A D
    # ========================================================

    def reload(self):

        direction = self.obj.Placement.Rotation.multVec(App.Vector(1, 0, 0))
        proxy = getattr(self.obj, "Proxy", None)
        was_updating = getattr(proxy, "_updating_orientation", False)
        if proxy is not None:
            proxy._updating_orientation = True
        try:
            self.obj.DirectionX = direction.x
            self.obj.DirectionY = direction.y
            self.obj.DirectionZ = direction.z
        finally:
            if proxy is not None:
                proxy._updating_orientation = was_updating

        self.a.setValue(float(self.obj.A))
        self.b.setValue(float(self.obj.B))

        self.chkAimPoint.setChecked(bool(self.obj.UseAimPoint))
        self.direction_x.setValue(float(self.obj.DirectionX))
        self.direction_y.setValue(float(self.obj.DirectionY))
        self.direction_z.setValue(float(self.obj.DirectionZ))
        self.aim_x.setValue(float(self.obj.AimX))
        self.aim_y.setValue(float(self.obj.AimY))
        self.aim_z.setValue(float(self.obj.AimZ))

        self._update_orientation_controls()
        self._preview()

    @staticmethod
    def _coordinate_spin(suffix):
        spin = QtWidgets.QDoubleSpinBox()
        spin.setDecimals(4)
        spin.setRange(-1_000_000.0, 1_000_000.0)
        spin.setSingleStep(1.0)
        spin.setSuffix(suffix)
        return spin

    def _update_orientation_controls(self):
        use_aim = self.chkAimPoint.isChecked()
        for control in (self.direction_x, self.direction_y, self.direction_z):
            control.setVisible(not use_aim)
            control.setEnabled(not use_aim)
        for control in (self.aim_x, self.aim_y, self.aim_z):
            control.setVisible(use_aim)
            control.setEnabled(use_aim)

    # ========================================================
    #  P R E V I E W
    # ========================================================

    def _preview(self):

        a = self.a.value()
        b = self.b.value()

        if a <= 0 or b <= 0:

            self.c.setText("Invalid")

            self.apply_button.setEnabled(False)

            return

        if a < b:

            self.c.setText("Invalid: A must be ≥ B")

            self.apply_button.setEnabled(False)

            return

        c = math.sqrt(
            max(
                0.0,
                a * a - b * b,
            )
        )

        self.c.setText(f"{c:.4f} mm")

        self.apply_button.setEnabled(True)

    # ========================================================
    #  A P P L Y
    # ========================================================

    def apply(self):

        a = self.a.value()
        b = self.b.value()

        # ----------------------------------------------------
        # Validate geometry first.
        # ----------------------------------------------------

        if a <= 0 or b <= 0:

            QtWidgets.QMessageBox.warning(
                self,
                "Invalid ellipsoid",
                "A and B must be greater than zero.",
            )

            return

        if a < b:

            QtWidgets.QMessageBox.warning(
                self,
                "Invalid ellipsoid",
                "A must be greater than or equal to B.",
            )

            return

        # ----------------------------------------------------
        # Apply properties.
        #
        # IMPORTANT:
        # A/B rebuild Shape but preserve Placement.
        #
        # Direction and aim-point values update Placement.Rotation but do not
        # change Placement.Base.
        # ----------------------------------------------------

        try:

            self.obj.A = App.Units.Quantity(f"{a} mm")

            self.obj.B = App.Units.Quantity(f"{b} mm")

            self.obj.UseAimPoint = self.chkAimPoint.isChecked()
            self.obj.DirectionX = self.direction_x.value()
            self.obj.DirectionY = self.direction_y.value()
            self.obj.DirectionZ = self.direction_z.value()
            self.obj.AimX = App.Units.Quantity(f"{self.aim_x.value()} mm")
            self.obj.AimY = App.Units.Quantity(f"{self.aim_y.value()} mm")
            self.obj.AimZ = App.Units.Quantity(f"{self.aim_z.value()} mm")

            self.obj.Document.recompute()

            Gui.updateGui()

        except Exception as exc:

            App.Console.PrintError("[OBA] Failed to update ellipsoid: " f"{exc}\n")


# ============================================================
#  V I E W   P R O V I D E R
# ============================================================


class EllipsoidViewProvider(OBAViewProviderBase):

    dialog_class = EllipsoidDialog

    def __init__(self, vobj):

        super().__init__(vobj)

        # Tell OBA base which dialog to open
        # on double click.
        self.dialog_class = EllipsoidDialog

    def onDocumentRestored(self, vobj):

        super().onDocumentRestored(vobj)

        # dialog_class is not persisted by FreeCAD.
        self.dialog_class = EllipsoidDialog


# ============================================================
#  S K A P A   E L L I P S O I D
# ============================================================


def OBA_CreateEllipsoid_old(doc=None, label="Ellipsoid", a=40.0, b=20.0, show_dialog=True):
    """
    Create an OBA ellipsoid.

    The local origin is one focal point.
    """

    doc = doc or App.ActiveDocument or App.newDocument()

    # --------------------------------------------------------
    # Validate.
    # --------------------------------------------------------

    if a <= 0 or b <= 0:
        raise ValueError("A and B must be greater than zero.")
    if a < b:
        raise ValueError("A must be greater than or equal to B.")

    # --------------------------------------------------------
    # Create FeaturePython object.
    # --------------------------------------------------------

    obj = doc.addObject("Part::FeaturePython", "OBAEllipsoid")

    obj.Label = label

    # --------------------------------------------------------
    # Attach Proxy.
    # --------------------------------------------------------

    OBAEllipsoid(obj)

    # --------------------------------------------------------
    # Initial geometry.
    # --------------------------------------------------------

    obj.A = App.Units.Quantity(f"{a} mm")

    obj.B = App.Units.Quantity(f"{b} mm")

    # --------------------------------------------------------
    # Placement.
    #
    # IMPORTANT:
    #
    # Placement belongs to the focal point.
    #
    # The local origin:
    #
    #     (0, 0, 0)
    #
    # is therefore the focus.
    # --------------------------------------------------------

    obj.Placement = App.Placement(
        App.Vector(
            0,
            0,
            0,
        ),
        App.Rotation(),
    )

    # --------------------------------------------------------
    # ViewProvider.
    # --------------------------------------------------------

    if App.GuiUp:

        EllipsoidViewProvider(obj.ViewObject)

    # --------------------------------------------------------
    # Recompute.
    # --------------------------------------------------------

    doc.recompute()

    # --------------------------------------------------------
    # Display mode.
    # --------------------------------------------------------

    try:

        obj.ViewObject.DisplayMode = "Flat Lines"

    except Exception:
        pass

    # --------------------------------------------------------
    # Show dialog.
    # --------------------------------------------------------

    if show_dialog:

        EllipsoidDialog(obj).show()

    return obj


# ============================================================
#  K O N V E N I E N S F U N K T I O N
# ============================================================


def create(doc=None, label="Ellipsoid", a=40.0, b=20.0):
    """
    Convenience function for the FreeCAD Python console.
    """

    return OBA_CreateEllipsoid_old(doc=doc, label=label, a=a, b=b, show_dialog=False)
