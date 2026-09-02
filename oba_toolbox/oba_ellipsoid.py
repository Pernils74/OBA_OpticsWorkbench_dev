# oba_ellipsoid.py
#
# OBA Ellipsoid optical component.
#
# Shared boilerplate:
#
#     oba_toolbox_base.py
#
# Optical behaviour retained from:
#
#     oba_ellipsoid_copy.py
#
#
# IMPORTANT COORDINATE CONVENTION
# --------------------------------
#
# The local origin is ONE FOCAL POINT.
#
# A = semi-major axis
# B = semi-minor axis
# C = sqrt(A² - B²)
#
# Ellipsoid centre:
#
#     (-C, 0, 0)
#
# Local origin:
#
#     (0, 0, 0)
#
# Therefore local origin is one focus.
#
# The optical axis is local +X.
#
# Placement.Base:
#
#     focal point position
#
# Placement.Rotation:
#
#     optical axis orientation
#
# Changing A/B rebuilds ONLY the Shape.
# Existing Placement is preserved.
#
# DirectionX/Y/Z:
#
#     explicit optical-axis direction
#
# UseAimPoint:
#
#     orient optical axis towards AimX/Y/Z
#

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from oba_objects.oba_base import OBAElementProxy

from .oba_toolbox_base import (
    OBAToolboxDialogBase,
    OBAToolboxViewProviderBase,
    create_ellipsoid,
    focus_distance,
    install_properties,
    make_calculated_length,
    make_optical_type,
    remove_objects,
    update_debug_ellipsoid,
    validate_ellipsoid,
    ensure_debug_property,
    restore_view_provider,
)

# ============================================================
#  P R O P E R T I E S
# ============================================================


ELLIPSOID_PROPERTIES = [
    {"name": "A", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 40.0, "doc": "Semi-major axis"},
    {"name": "B", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 20.0, "doc": "Semi-minor axis"},
    {"name": "UseIndependentRadius3", "type": "App::PropertyBool", "group": "Ellipsoid", "default": False, "doc": "Use independent radius in Y direction"},
    {"name": "B2", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 20.0, "doc": "Independent ellipsoid Y radius"},
    # --------------------------------------------------------
    # Orientation.
    # --------------------------------------------------------
    {"name": "DirectionX", "type": "App::PropertyFloat", "group": "Orientation", "default": 1.0, "doc": "Optical axis X direction"},
    {"name": "DirectionY", "type": "App::PropertyFloat", "group": "Orientation", "default": 0.0, "doc": "Optical axis Y direction"},
    {"name": "DirectionZ", "type": "App::PropertyFloat", "group": "Orientation", "default": 0.0, "doc": "Optical axis Z direction"},
    {"name": "UseAimPoint", "type": "App::PropertyBool", "group": "Orientation", "default": False, "doc": "Aim the optical axis at a point"},
    {"name": "AimX", "type": "App::PropertyDistance", "group": "Orientation", "default": 100.0, "doc": "Target X coordinate"},
    {"name": "AimY", "type": "App::PropertyDistance", "group": "Orientation", "default": 0.0, "doc": "Target Y coordinate"},
    {"name": "AimZ", "type": "App::PropertyDistance", "group": "Orientation", "default": 0.0, "doc": "Target Z coordinate"},
]


# ============================================================
#  O B J E C T
# ============================================================


class OBAEllipsoid(OBAElementProxy):

    def __init__(self, obj):

        self._initializing = True
        self._updating_orientation = False

        self._ellipsoid_shape = None

        super().__init__(obj, use_binders=False)

        install_properties(obj, ELLIPSOID_PROPERTIES)
        ensure_debug_property(obj)
        make_calculated_length(obj, "FocusDistance", "Distance from ellipsoid centre to focus")
        make_optical_type(obj, "Ellipsoid")
        self._initializing = False

    def _rebuild(self, obj):
        old_placement = obj.Placement.copy()
        a = float(obj.A)
        b = float(obj.B)

        if obj.UseIndependentRadius3:
            b2 = float(obj.B2)
        else:
            b2 = b

        print(
            "rebuild",
            "A=",
            float(obj.A),
            "B=",
            float(obj.B),
            "B2=",
            float(obj.B2),
            "UseB2=",
            obj.UseIndependentRadius3,
        )

        validate_ellipsoid(a, b, b2)
        c = focus_distance(a, b)

        doc = obj.Document
        tmp, shape = create_ellipsoid(doc, a, b, b2, tmp_name=f"{obj.Name}_EllipsoidTmp", label=f"{obj.Label} temporary ellipsoid")
        try:

            shape.translate(App.Vector(-c, 0.0, 0.0))
            self._ellipsoid_shape = shape.copy()
            obj.Shape = shape

            obj.FocusDistance = c

            was_updating = self._updating_orientation
            self._updating_orientation = True
            try:
                obj.Placement = old_placement
            finally:
                self._updating_orientation = was_updating
        finally:
            remove_objects(doc, [tmp.Name])

        self._update_debug(obj)

    @staticmethod
    def rotation_from_direction(direction):
        """
        Create a rotation that maps local +X onto direction.
        """

        direction = App.Vector(direction.x, direction.y, direction.z)

        if direction.Length == 0:
            raise ValueError("Direction must not be zero.")

        direction.normalize()
        return App.Rotation(App.Vector(1, 0, 0), direction)

    # ========================================================

    @classmethod
    def rotation_from_aimpoint(cls, obj, target_point):
        """
        Aim from the focal point (Placement.Base)
        towards target_point.
        """
        direction = target_point - obj.Placement.Base
        return cls.rotation_from_direction(direction)

    # ========================================================

    @classmethod
    def apply_orientation(cls, obj):
        """
        Apply Direction or AimPoint orientation.
        Placement.Base is NEVER changed.
        Only Placement.Rotation is changed.
        """

        proxy = obj.Proxy

        if getattr(proxy, "_updating_orientation", False):
            return
        proxy._updating_orientation = True
        try:

            # ------------------------------------------------
            # Aim mode.
            # ------------------------------------------------

            if obj.UseAimPoint:
                target = App.Vector(obj.AimX, obj.AimY, obj.AimZ)
                rotation = cls.rotation_from_aimpoint(obj, target)
            else:
                direction = App.Vector(obj.DirectionX, obj.DirectionY, obj.DirectionZ)
                rotation = cls.rotation_from_direction(direction)

            placement = obj.Placement.copy()
            placement.Rotation = rotation
            obj.Placement = placement

            cls.synchronize_direction(obj)

        finally:
            proxy._updating_orientation = False

    # ========================================================

    @staticmethod
    def synchronize_direction(obj):
        """
        Read the actual local +X axis from Placement.Rotation
        and store it in DirectionX/Y/Z.
        """

        direction = obj.Placement.Rotation.multVec(App.Vector(1, 0, 0))
        obj.DirectionX = direction.x
        obj.DirectionY = direction.y
        obj.DirectionZ = direction.z

    def _update_debug(self, obj):
        if self._ellipsoid_shape is None:
            remove_objects(obj.Document, [f"{obj.Name}_DebugEllipsoid"])
            return
        update_debug_ellipsoid(obj, self._ellipsoid_shape, bool(obj.ShowDebugEllipsoid))

    def onChanged(self, obj, prop):

        print("onChanged:", prop)

        if getattr(self, "_initializing", False):
            return

        # ----------------------------------------------------
        # Geometry
        # ----------------------------------------------------

        if prop in ("A", "B", "UseIndependentRadius3", "B2"):

            a = float(obj.A)
            b = float(obj.B)

            if obj.UseIndependentRadius3:
                b2 = float(obj.B2)
            else:
                b2 = b

            # During creation / reload properties may
            # temporarily become zero.

            if a <= 0 or b <= 0:
                return
            if b2 <= 0:
                return
            try:
                self._rebuild(obj)
            except Exception as exc:
                App.Console.PrintError("[OBA] Ellipsoid rebuild failed: " f"{exc}\n")
            return

        if prop in (
            "DirectionX",
            "DirectionY",
            "DirectionZ",
            "UseAimPoint",
            "AimX",
            "AimY",
            "AimZ",
        ):
            if getattr(self, "_updating_orientation", False):
                return
            try:
                self.apply_orientation(obj)
            except Exception as exc:
                App.Console.PrintError("[OBA] Ellipsoid orientation failed: " f"{exc}\n")
            return

        if prop == "Placement":
            if getattr(self, "_updating_orientation", False):
                return

            try:
                self._updating_orientation = True
                self.synchronize_direction(obj)
            finally:
                self._updating_orientation = False
            self._update_debug(obj)
            return

        if prop == "ShowDebugEllipsoid":
            self._update_debug(obj)
            return

        super().onChanged(obj, prop)

    def onChanged_old(self, obj, prop):
        # if self._initializing:
        #     return
        print("onChanged:", prop)

        if getattr(self, "_initializing", False):
            return

        if prop in ("A", "B", "UseIndependentRadius3", "B2"):
            try:
                self._rebuild(obj)
            except Exception as exc:
                App.Console.PrintError("[OBA] " "Ellipsoid rebuild failed: " f"{exc}\n")
                return

        elif prop in (
            "DirectionX",
            "DirectionY",
            "DirectionZ",
            "UseAimPoint",
            "AimX",
            "AimY",
            "AimZ",
        ):

            if not getattr(self, "_updating_orientation", False):
                try:
                    self.apply_orientation(obj)
                except Exception as exc:
                    App.Console.PrintError("[OBA] " "Ellipsoid orientation failed: " f"{exc}\n")
                    return

        elif prop == "Placement" and not getattr(self, "_updating_orientation", False):
            try:
                self._updating_orientation = True
                self.synchronize_direction(obj)
            finally:
                self._updating_orientation = False

            self._update_debug(obj)

        elif prop == "ShowDebugEllipsoid":
            self._update_debug(obj)

        super().onChanged(obj, prop)

    # ========================================================
    #  R E S T O R E
    # ========================================================

    def onDocumentRestored(self, obj):

        obj.Proxy = self
        self.Object = obj

        install_properties(obj, ELLIPSOID_PROPERTIES)

        ensure_debug_property(obj)
        make_calculated_length(obj, "FocusDistance", "Distance from ellipsoid centre to focus")

        make_optical_type(obj, "Ellipsoid")

        self._updating_orientation = True
        try:
            self.synchronize_direction(obj)
        finally:
            self._updating_orientation = False
        restore_view_provider(obj, EllipsoidViewProvider, EllipsoidDialog)

    def onDelete(self, obj, subelements):
        remove_objects(obj.Document, [f"{obj.Name}_DebugEllipsoid", f"{obj.Name}_EllipsoidTmp"])
        return True

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


# ============================================================
#  D I A L O G
# ============================================================


class EllipsoidDialog(OBAToolboxDialogBase):
    ALLOW_SURFACE_SELECTION = False

    def __init__(self, obj, title="Ellipsoid Settings", parent=None):

        super().__init__(obj, title=title, parent=parent)

        group = QtWidgets.QGroupBox("Ellipsoid")
        form = QtWidgets.QFormLayout(group)

        self.a = self._add_spin("A", "A", 0, 1_000_000, "mm", form)
        self.b = self._add_spin("B", "B", 0, 1_000_000, "mm", form)
        self.use_b2 = QtWidgets.QCheckBox("Use independent Radius3")
        form.addWidget(self.use_b2)
        self.b2 = self._add_spin("B2", "B2", 0, 1_000_000, "mm", form)

        self.c = QtWidgets.QLabel()

        form.addRow("Focus distance C", self.c)
        self.chkAimPoint = QtWidgets.QCheckBox("Aim at point")
        form.addRow(self.chkAimPoint)
        self.direction_x = self._coordinate_spin("")
        self.direction_y = self._coordinate_spin("")
        self.direction_z = self._coordinate_spin("")

        form.addRow("Direction X", self.direction_x)
        form.addRow("Direction Y", self.direction_y)
        form.addRow("Direction Z", self.direction_z)

        self.aim_x = self._coordinate_spin(" mm")
        self.aim_y = self._coordinate_spin(" mm")
        self.aim_z = self._coordinate_spin(" mm")
        form.addRow("Target X", self.aim_x)
        form.addRow("Target Y", self.aim_y)
        form.addRow("Target Z", self.aim_z)

        # ----------------------------------------------------
        # Add group.
        # ----------------------------------------------------

        self.custom_layout.addWidget(group)

        # ====================================================
        #  I N F O
        # ====================================================

        info = QtWidgets.QLabel(
            "The local origin is one focal point.\n\n"
            "The optical axis is the local +X direction.\n\n"
            "In Direction mode the optical axis direction "
            "is entered directly.\n\n"
            "In Aim mode the ellipsoid is rotated so that "
            "the optical axis points from the focal point "
            "towards the specified target coordinate."
        )

        info.setWordWrap(True)

        self.custom_layout.addWidget(info)

        #  B U T T O N S
        buttons = QtWidgets.QHBoxLayout()
        self.apply_button = QtWidgets.QPushButton("Apply")
        self.reset_button = QtWidgets.QPushButton("Reset")
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.reset_button)
        self.custom_layout.addLayout(buttons)

        self.add_debug_checkbox("Show debug ellipsoid")

        self.add_placement_group()

        # ====================================================
        #  S I G N A L S
        # ====================================================

        self.apply_button.clicked.connect(self.apply)
        self.reset_button.clicked.connect(self.reload)
        self.a.valueChanged.connect(self._preview)
        self.b.valueChanged.connect(self._preview)
        self.b2.valueChanged.connect(self._preview)
        self.use_b2.toggled.connect(self._preview)
        self.chkAimPoint.toggled.connect(self._update_orientation_controls)

        # ----------------------------------------------------
        # Load.
        # ----------------------------------------------------

        self.reload()

    # ========================================================
    #  C O O R D I N A T E   S P I N
    # ========================================================

    @staticmethod
    def _coordinate_spin(suffix):
        spin = QtWidgets.QDoubleSpinBox()
        spin.setDecimals(4)
        spin.setRange(-1_000_000.0, 1_000_000.0)
        spin.setSingleStep(1.0)
        spin.setSuffix(suffix)
        return spin

    # ========================================================
    #  R E L O A D
    # ========================================================

    def reload(self):

        direction = self.obj.Placement.Rotation.multVec(App.Vector(1, 0, 0))
        proxy = getattr(self.obj, "Proxy", None)
        was_updating = getattr(proxy, "_updating_orientation", False) if proxy is not None else False

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
        self.use_b2.setChecked(bool(self.obj.UseIndependentRadius3))
        self.b2.setValue(float(self.obj.B2))

        self.chkAimPoint.setChecked(bool(self.obj.UseAimPoint))
        self.direction_x.setValue(float(self.obj.DirectionX))
        self.direction_y.setValue(float(self.obj.DirectionY))
        self.direction_z.setValue(float(self.obj.DirectionZ))
        self.aim_x.setValue(float(self.obj.AimX))
        self.aim_y.setValue(float(self.obj.AimY))
        self.aim_z.setValue(float(self.obj.AimZ))

        self.reload_placement()

        # ----------------------------------------------------
        # UI.
        # ----------------------------------------------------

        self._update_orientation_controls()

        self._preview()

    # ========================================================
    #  O R I E N T A T I O N   C O N T R O L S
    # ========================================================

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
        a = float(self.obj.A)
        b = float(self.obj.B)

        if a <= 0 or b <= 0:
            self.c.setText("Invalid")
            self.apply_button.setEnabled(False)
            return

        if a < b:
            self.c.setText("Invalid: A must be ≥ B")
            self.apply_button.setEnabled(False)
            return

        if self.use_b2.isChecked() and self.b2.value() <= 0:
            self.c.setText("Invalid: B2 must be > 0")
            self.apply_button.setEnabled(False)
            return

        # if self.use_b2.isChecked():
        #     b2 = float(self.obj.B2)
        # else:
        #     b2 = b

        c = focus_distance(a, b)

        self.c.setText(f"{c:.4f} mm")
        self.apply_button.setEnabled(True)
        self.b2.setEnabled(self.use_b2.isChecked())

    # ========================================================
    #  A P P L Y
    # ========================================================

    def apply(self):
        a = float(self.obj.A)
        b = float(self.obj.B)

        if a <= 0 or b <= 0:  # guard för felaktiga värden
            return
        try:
            if self.use_b2.isChecked():
                b2 = float(self.obj.B2)
            else:
                b2 = b
            validate_ellipsoid(a, b, b2)

        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid ellipsoid", str(exc))
            return

        try:
            self.obj.A = App.Units.Quantity(f"{a} mm")
            self.obj.B = App.Units.Quantity(f"{b} mm")
            self.obj.UseIndependentRadius3 = self.use_b2.isChecked()
            self.obj.B2 = App.Units.Quantity(f"{b2} mm")

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
            App.Console.PrintError("[OBA] " "Failed to update ellipsoid: " f"{exc}\n")


class EllipsoidViewProvider(OBAToolboxViewProviderBase):
    dialog_class = EllipsoidDialog

    def __init__(self, vobj):
        super().__init__(vobj, EllipsoidDialog)


# ============================================================
#  C R E A T E
# ============================================================


def OBA_CreateEllipsoid(doc=None, label="Ellipsoid", a=40.0, b=20.0, b2=None, placement=None, show_dialog=True):
    """
    Create an OBA Ellipsoid.

    The local origin is one focal point.

    The optical axis is local +X.
    """

    doc = doc or App.ActiveDocument or App.newDocument()

    if b2 is None:
        b2 = b
        use_b2 = False
    else:
        use_b2 = True

    validate_ellipsoid(a, b, b2)

    obj = doc.addObject("Part::FeaturePython", "OBAEllipsoid")
    obj.Label = label

    OBAEllipsoid(obj)

    obj.A = App.Units.Quantity(f"{a} mm")
    obj.B = App.Units.Quantity(f"{b} mm")
    obj.UseIndependentRadius3 = use_b2
    obj.B2 = App.Units.Quantity(f"{b2} mm")

    obj.DirectionX = 1.0
    obj.DirectionY = 0.0
    obj.DirectionZ = 0.0

    obj.UseAimPoint = False
    obj.AimX = App.Units.Quantity("100 mm")
    obj.AimY = App.Units.Quantity("0 mm")
    obj.AimZ = App.Units.Quantity("0 mm")

    if placement is None:
        placement = App.Placement(App.Vector(0.0, 0.0, 0.0), App.Rotation())
    obj.Placement = placement
    if App.GuiUp:
        EllipsoidViewProvider(obj.ViewObject)
    doc.recompute()
    try:
        obj.ViewObject.DisplayMode = "Flat Lines"
    except Exception:
        pass
    if show_dialog:
        EllipsoidDialog(obj).show()

    return obj


# ============================================================
#  C O N V E N I E N C E   F U N C T I O N
# ============================================================


def create(doc=None, label="Ellipsoid", a=40.0, b=20.0, b2=None):
    """
    Convenience function for the FreeCAD Python console.
    """

    return OBA_CreateEllipsoid(
        doc=doc,
        label=label,
        a=a,
        b=b,
        b2=b2,
        show_dialog=False,
    )
