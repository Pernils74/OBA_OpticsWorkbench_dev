# oba_ellipsoid.py
#
# OBA Ellipsoid optical component.
#

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from oba_objects.oba_base import OBAElementProxy

from .oba_toolbox_base import (
    OBAToolboxDialogBase,
    OBAToolboxViewProviderBase,
    focus_distance,
    install_properties,
    make_optical_type,
    restore_view_provider,
    validate_ellipsoid,
)

# ============================================================
#  P R O P E R T I E S
# ============================================================

ELLIPSOID_PROPERTIES = [
    {
        "name": "A",
        "type": "App::PropertyLength",
        "group": "Ellipsoid",
        "doc": "Semi-major axis",
    },
    {
        "name": "B",
        "type": "App::PropertyLength",
        "group": "Ellipsoid",
        "doc": "Semi-minor axis",
    },
    {
        "name": "UseIndependentRadius3",
        "type": "App::PropertyBool",
        "group": "Ellipsoid",
        "doc": "Use independent Radius3",
    },
    {
        "name": "B2",
        "type": "App::PropertyLength",
        "group": "Ellipsoid",
        "doc": "Independent ellipsoid Radius3",
    },
    {
        "name": "FocusDistance",
        "type": "App::PropertyLength",
        "group": "Ellipsoid",
        "doc": "Distance from ellipsoid centre to focus",
    },
    {
        "name": "ShowDebugEllipsoid",
        "type": "App::PropertyBool",
        "group": "Debug",
        "doc": "Show ellipsoid for debugging",
    },
    # --------------------------------------------------------
    # Orientation.
    # --------------------------------------------------------
    {
        "name": "RotX",
        "type": "App::PropertyAngle",
        "group": "Orientation",
        "doc": "Optical axis X rotation",
    },
    {
        "name": "RotY",
        "type": "App::PropertyAngle",
        "group": "Orientation",
        "doc": "Optical axis Y rotation",
    },
    {
        "name": "RotZ",
        "type": "App::PropertyAngle",
        "group": "Orientation",
        "doc": "Optical axis Z rotation",
    },
    {
        "name": "UseAimPoint",
        "type": "App::PropertyBool",
        "group": "Orientation",
        "doc": "Aim the optical axis at a point",
    },
    {
        "name": "AimX",
        "type": "App::PropertyDistance",
        "group": "Orientation",
        "doc": "Target X coordinate",
    },
    {
        "name": "AimY",
        "type": "App::PropertyDistance",
        "group": "Orientation",
        "doc": "Target Y coordinate",
    },
    {
        "name": "AimZ",
        "type": "App::PropertyDistance",
        "group": "Orientation",
        "doc": "Target Z coordinate",
    },
]


# ============================================================
#  O B J E C T
# ============================================================


class OBAEllipsoid:
    CHILD_OBJECTS = ("_ellipsoid",)

    def __init__(self, obj):
        obj.Proxy = self
        self.Object = obj

        self._initializing = True
        self._updating_orientation = False

        self._ellipsoid = None

        # ----------------------------------------------------
        # Only create the properties here.
        #
        # Their actual values are supplied by
        # OBA_CreateEllipsoid().
        # ----------------------------------------------------

        install_properties(obj, ELLIPSOID_PROPERTIES)

        make_optical_type(obj, "Ellipsoid")

        self._initializing = False

    # ========================================================
    #  E N S U R E   F E A T U R E S
    # ========================================================

    def _ensure_features(self, obj):
        doc = obj.Document

        if doc is None:
            return

        existing = getattr(self, "_ellipsoid", None)

        if existing is not None:
            try:
                if existing.Document is doc:
                    return
            except Exception:
                pass

        name = f"{obj.Name}_Ellipsoid"
        ellipsoid = doc.getObject(name)

        if ellipsoid is None:
            ellipsoid = doc.addObject(
                "Part::Ellipsoid",
                name,
            )

        ellipsoid.Label = f"{obj.Label} Ellipsoid"

        self._ellipsoid = ellipsoid

    # ========================================================
    #  U P D A T E   E L L I P S O I D
    # ========================================================

    def _update_ellipsoid(self, obj):
        # ----------------------------------------------------
        # Never attempt geometry creation while the main
        # object's dimensions are not ready.
        # ----------------------------------------------------

        if getattr(self, "_initializing", False):
            return

        try:
            a = float(obj.A)
            b = float(obj.B)
        except Exception:
            return

        if a <= 0.0 or b <= 0.0:
            return

        if bool(obj.UseIndependentRadius3):
            try:
                b2 = float(obj.B2)
            except Exception:
                return

            if b2 <= 0.0:
                return
        else:
            b2 = b

        validate_ellipsoid(a, b, b2)

        self._ensure_features(obj)

        ellipsoid = self._ellipsoid

        if ellipsoid is None:
            return

        # ----------------------------------------------------
        # Calculate focal distance.
        # ----------------------------------------------------

        c = focus_distance(a, b)

        # ----------------------------------------------------
        # Real FreeCAD Part::Ellipsoid.
        # ----------------------------------------------------

        ellipsoid.Radius1 = a
        ellipsoid.Radius2 = b
        ellipsoid.Radius3 = b2

        # ----------------------------------------------------
        # Coordinate system.
        #
        # Part::Ellipsoid is centred at its local origin.
        #
        # rot0 preserves the existing OBA axis convention.
        # ----------------------------------------------------

        rot0 = App.Rotation(App.Vector(0, 0, 1), 90).multiply(App.Rotation(App.Vector(0, 1, 0), 90))

        rotx = App.Rotation(
            App.Vector(1, 0, 0),
            float(obj.RotX),
        )

        roty = App.Rotation(
            App.Vector(0, 1, 0),
            float(obj.RotY),
        )

        rotz = App.Rotation(
            App.Vector(0, 0, 1),
            float(obj.RotZ),
        )

        rotation = rot0
        rotation = rotation.multiply(rotx)
        rotation = rotation.multiply(roty)
        rotation = rotation.multiply(rotz)

        # ----------------------------------------------------
        # The OBA object's Placement is the component
        # reference placement.
        #
        # The actual Part::Ellipsoid is a direct child.
        # ----------------------------------------------------

        local_placement = App.Placement(
            App.Vector(0.0, 0.0, 0.0),
            rotation,
        )

        ellipsoid.Placement = obj.Placement.multiply(local_placement)

        # ----------------------------------------------------
        # Calculated property.
        # ----------------------------------------------------

        obj.FocusDistance = c

    # ========================================================
    #  R E B U I L D
    # ========================================================

    def _rebuild(self, obj):
        if getattr(self, "_initializing", False):
            return

        try:
            a = float(obj.A)
            b = float(obj.B)
        except Exception:
            return

        if a <= 0.0 or b <= 0.0:
            return

        if bool(obj.UseIndependentRadius3):
            try:
                b2 = float(obj.B2)
            except Exception:
                return

            if b2 <= 0.0:
                return

        try:
            self._update_ellipsoid(obj)
            obj.Document.recompute()
            self._update_debug(obj)

        except Exception as exc:
            App.Console.PrintError("[OBA] Ellipsoid rebuild failed: " f"{exc}\n")

    # ========================================================
    #  D E B U G
    # ========================================================

    def _update_debug(self, obj):
        ellipsoid = getattr(self, "_ellipsoid", None)

        if ellipsoid is None:
            return

        # ----------------------------------------------------
        # The Part::Ellipsoid is the actual construction
        # geometry, so it must remain visible.
        #
        # ShowDebugEllipsoid is retained as a compatibility
        # property but does not hide the real geometry.
        # ----------------------------------------------------

        ellipsoid.ViewObject.Visibility = True

    # ========================================================
    #  C H A N G E D
    # ========================================================

    def onChanged(self, obj, prop):
        if getattr(self, "_initializing", False):
            return

        # ----------------------------------------------------
        # Geometry.
        # ----------------------------------------------------

        if prop in (
            "A",
            "B",
            "UseIndependentRadius3",
            "B2",
        ):
            try:
                a = float(obj.A)
                b = float(obj.B)
            except Exception:
                return

            # During creation/restoration FreeCAD may temporarily
            # expose zero values.
            if a <= 0.0 or b <= 0.0:
                return

            if bool(obj.UseIndependentRadius3):
                try:
                    b2 = float(obj.B2)
                except Exception:
                    return

                if b2 <= 0.0:
                    return

            self._rebuild(obj)
            return

        # ----------------------------------------------------
        # Orientation.
        # ----------------------------------------------------

        if prop in (
            "RotX",
            "RotY",
            "RotZ",
            "UseAimPoint",
            "AimX",
            "AimY",
            "AimZ",
        ):
            if getattr(self, "_updating_orientation", False):
                return

            try:
                self._update_ellipsoid(obj)
                obj.Document.recompute()
                self._update_debug(obj)

            except Exception as exc:
                App.Console.PrintError("[OBA] Ellipsoid orientation failed: " f"{exc}\n")

            return

        # ----------------------------------------------------
        # Main Placement changed.
        # ----------------------------------------------------

        if prop == "Placement":
            if getattr(self, "_updating_orientation", False):
                return

            try:
                self._updating_orientation = True

                self._update_ellipsoid(obj)

            except Exception as exc:
                App.Console.PrintError("[OBA] Ellipsoid placement update failed: " f"{exc}\n")

            finally:
                self._updating_orientation = False

            obj.Document.recompute()
            self._update_debug(obj)
            return

        # ----------------------------------------------------
        # Debug.
        # ----------------------------------------------------

        if prop == "ShowDebugEllipsoid":
            self._update_debug(obj)
            return

    # ========================================================
    #  R E S T O R E
    # ========================================================

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self.Object = obj

        self._initializing = True
        self._updating_orientation = False
        self._ellipsoid = None

        install_properties(
            obj,
            ELLIPSOID_PROPERTIES,
        )

        make_optical_type(
            obj,
            "Ellipsoid",
        )

        self._initializing = False

        self._ensure_features(obj)

        try:
            self._rebuild(obj)

        except Exception as exc:
            App.Console.PrintError("[OBA] Ellipsoid restore rebuild failed: " f"{exc}\n")

        restore_view_provider(
            obj,
            EllipsoidViewProvider,
            EllipsoidDialog,
        )

    # ========================================================
    #  S T A T E
    # ========================================================

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


# ============================================================
#  D I A L O G
# ============================================================


class EllipsoidDialog(OBAToolboxDialogBase):
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

        group = QtWidgets.QGroupBox("Ellipsoid")
        form = QtWidgets.QFormLayout(group)

        self.a = self._add_spin(
            "A",
            "A",
            0,
            1_000_000,
            "mm",
            form,
        )

        self.b = self._add_spin(
            "B",
            "B",
            0,
            1_000_000,
            "mm",
            form,
        )

        self.use_b2 = QtWidgets.QCheckBox("Use independent Radius3")

        form.addWidget(self.use_b2)

        self.b2 = self._add_spin(
            "B2",
            "B2",
            0,
            1_000_000,
            "mm",
            form,
        )

        self.c = QtWidgets.QLabel()
        form.addRow(
            "Focus distance C",
            self.c,
        )

        self.chkAimPoint = QtWidgets.QCheckBox("Aim at point")

        form.addRow(self.chkAimPoint)

        self.rot_x = self._add_spin(
            "Rotation X",
            "RotX",
            -360,
            360,
            "deg",
            form,
        )

        self.rot_y = self._add_spin(
            "Rotation Y",
            "RotY",
            -360,
            360,
            "deg",
            form,
        )

        self.rot_z = self._add_spin(
            "Rotation Z",
            "RotZ",
            -360,
            360,
            "deg",
            form,
        )

        self.aim_x = self._coordinate_spin(" mm")
        self.aim_y = self._coordinate_spin(" mm")
        self.aim_z = self._coordinate_spin(" mm")

        form.addRow(
            "Target X",
            self.aim_x,
        )

        form.addRow(
            "Target Y",
            self.aim_y,
        )

        form.addRow(
            "Target Z",
            self.aim_z,
        )

        self.custom_layout.addWidget(group)

        # ====================================================
        #  I N F O
        # ====================================================

        info = QtWidgets.QLabel(
            "The local origin is one focal point.\n\n"
            "The optical axis is the local +X direction.\n\n"
            "Rotation X/Y/Z controls the optical axis "
            "orientation.\n\n"
            "In Aim mode the optical axis points from "
            "the focal point towards the specified target."
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

        self.reload()

    # ========================================================
    #  C O O R D I N A T E   S P I N
    # ========================================================

    @staticmethod
    def _coordinate_spin(suffix):
        spin = QtWidgets.QDoubleSpinBox()
        spin.setDecimals(4)
        spin.setRange(
            -1_000_000.0,
            1_000_000.0,
        )
        spin.setSingleStep(1.0)
        spin.setSuffix(suffix)
        return spin

    # ========================================================
    #  R E L O A D
    # ========================================================

    def reload(self):
        self.a.setValue(float(self.obj.A))

        self.b.setValue(float(self.obj.B))

        self.use_b2.setChecked(bool(self.obj.UseIndependentRadius3))

        self.b2.setValue(float(self.obj.B2))

        self.chkAimPoint.setChecked(bool(self.obj.UseAimPoint))

        self.rot_x.setProperty(
            "rawValue",
            float(self.obj.RotX),
        )

        self.rot_y.setProperty(
            "rawValue",
            float(self.obj.RotY),
        )

        self.rot_z.setProperty(
            "rawValue",
            float(self.obj.RotZ),
        )

        self.aim_x.setValue(float(self.obj.AimX))

        self.aim_y.setValue(float(self.obj.AimY))

        self.aim_z.setValue(float(self.obj.AimZ))

        self.reload_placement()

        self._update_orientation_controls()
        self._preview()

    # ========================================================
    #  O R I E N T A T I O N   C O N T R O L S
    # ========================================================

    def _update_orientation_controls(self):
        use_aim = self.chkAimPoint.isChecked()

        for control in (
            self.rot_x,
            self.rot_y,
            self.rot_z,
        ):
            control.setVisible(not use_aim)
            control.setEnabled(not use_aim)

        for control in (
            self.aim_x,
            self.aim_y,
            self.aim_z,
        ):
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

        c = focus_distance(a, b)

        self.c.setText(f"{c:.4f} mm")

        self.apply_button.setEnabled(True)

        self.b2.setEnabled(self.use_b2.isChecked())

    # ========================================================
    #  A P P L Y
    # ========================================================

    def apply(self):
        a = float(self.a.value())
        b = float(self.b.value())

        if a <= 0 or b <= 0:
            return

        try:
            if self.use_b2.isChecked():
                b2 = float(self.b2.value())
            else:
                b2 = b

            validate_ellipsoid(
                a,
                b,
                b2,
            )

        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid ellipsoid",
                str(exc),
            )
            return

        try:
            self.obj.A = App.Units.Quantity(f"{a} mm")

            self.obj.B = App.Units.Quantity(f"{b} mm")

            self.obj.UseIndependentRadius3 = self.use_b2.isChecked()

            self.obj.B2 = App.Units.Quantity(f"{b2} mm")

            self.obj.UseAimPoint = self.chkAimPoint.isChecked()

            self.obj.RotX = self.rot_x.value()
            self.obj.RotY = self.rot_y.value()
            self.obj.RotZ = self.rot_z.value()

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


class EllipsoidViewProvider(OBAToolboxViewProviderBase):
    dialog_class = EllipsoidDialog

    def __init__(self, vobj):
        super().__init__(
            vobj,
            EllipsoidDialog,
        )

    # ========================================================
    #  C H I L D R E N
    # ========================================================

    def claimChildren(self):
        obj = getattr(
            self,
            "Object",
            None,
        )

        if obj is None:
            return []

        proxy = getattr(
            obj,
            "Proxy",
            None,
        )

        if proxy is None:
            return []

        children = []

        for attr_name in getattr(
            proxy,
            "CHILD_OBJECTS",
            (),
        ):
            child = getattr(
                proxy,
                attr_name,
                None,
            )

            if child is not None:
                children.append(child)

        return children

    # ========================================================
    #  D E L E T E
    # ========================================================

    def onDelete(self, vobj, subelements):
        obj = getattr(
            self,
            "Object",
            None,
        )

        if obj is None:
            return True

        proxy = getattr(
            obj,
            "Proxy",
            None,
        )

        if proxy is None:
            return True

        doc = obj.Document

        child_names = getattr(
            proxy,
            "CHILD_OBJECTS",
            (),
        )

        for attr_name in reversed(child_names):
            child = getattr(
                proxy,
                attr_name,
                None,
            )

            if child is not None and doc.getObject(child.Name) is not None:
                doc.removeObject(child.Name)

        return True


# ============================================================
#  C R E A T O R
# ============================================================


def OBA_CreateEllipsoid(
    doc=None,
    label="Ellipsoid",
    a=40.0,
    b=20.0,
    b2=None,
    rot_x=45,
    rot_y=45,
    rot_z=0,
    x=0,
    y=0,
    z=0,
    placement=None,
    show_dialog=True,
):
    doc = doc or App.ActiveDocument or App.newDocument()

    # --------------------------------------------------------
    # Radius3 default is derived from B.
    # --------------------------------------------------------

    if b2 is None:
        b2 = b
        use_b2 = False
    else:
        use_b2 = True

    # --------------------------------------------------------
    # Validate BEFORE creating the object.
    # --------------------------------------------------------

    validate_ellipsoid(
        a,
        b,
        b2,
    )

    # --------------------------------------------------------
    # Create main OBA object.
    # --------------------------------------------------------

    obj = doc.addObject(
        "Part::FeaturePython",
        "OBAEllipsoid",
    )

    obj.Label = label

    proxy = OBAEllipsoid(obj)

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # All actual defaults are assigned HERE.
    #
    # Nothing in ELLIPSOID_PROPERTIES provides defaults.
    # --------------------------------------------------------

    obj.A = App.Units.Quantity(f"{a} mm")

    obj.B = App.Units.Quantity(f"{b} mm")

    obj.UseIndependentRadius3 = use_b2

    obj.B2 = App.Units.Quantity(f"{b2} mm")

    obj.FocusDistance = focus_distance(
        float(a),
        float(b),
    )

    obj.ShowDebugEllipsoid = False

    obj.RotX = rot_x
    obj.RotY = rot_y
    obj.RotZ = rot_z

    obj.UseAimPoint = False

    obj.AimX = App.Units.Quantity("100 mm")

    obj.AimY = App.Units.Quantity("0 mm")

    obj.AimZ = App.Units.Quantity("0 mm")

    # --------------------------------------------------------
    # Placement.
    # --------------------------------------------------------

    if placement is None:
        placement = App.Placement(
            App.Vector(
                x,
                y,
                z,
            ),
            App.Rotation(),
        )

    obj.Placement = placement

    # --------------------------------------------------------
    # Only NOW create/update the real Part::Ellipsoid.
    # --------------------------------------------------------

    proxy._ensure_features(obj)
    proxy._update_ellipsoid(obj)

    # --------------------------------------------------------
    # View provider.
    # --------------------------------------------------------

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
#  C R E A T E
# ============================================================


def create(
    doc=None,
    label="Ellipsoid",
    a=40.0,
    b=20.0,
    b2=None,
    rot_x=0,
    rot_y=0,
    rot_z=0,
    x=0,
    y=0,
    z=0,
):
    return OBA_CreateEllipsoid(
        doc=doc,
        label=label,
        a=a,
        b=b,
        b2=b2,
        rot_x=rot_x,
        rot_y=rot_y,
        rot_z=rot_z,
        x=x,
        y=y,
        z=z,
        show_dialog=False,
    )
