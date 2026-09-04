# oba_ellipsoid.py
#
# OBA Ellipsoid optical component.
#
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
    make_calculated_length,
    make_optical_type,
    remove_objects,
    restore_view_provider,
    validate_ellipsoid,
    ensure_debug_property,
)

# ============================================================
#  P R O P E R T I E S
# ============================================================


ELLIPSOID_PROPERTIES = [
    {"name": "A", "type": "App::PropertyLength", "group": "Ellipsoid", "doc": "Semi-major axis"},
    {"name": "B", "type": "App::PropertyLength", "group": "Ellipsoid", "doc": "Semi-minor axis"},
    {"name": "UseIndependentRadius3", "type": "App::PropertyBool", "group": "Ellipsoid", "doc": "Use independent radius in Y direction"},
    {"name": "B2", "type": "App::PropertyLength", "group": "Ellipsoid", "doc": "Independent ellipsoid Y radius"},
    {"name": "FocusDistance", "type": "App::PropertyLength", "group": "Ellipsoid", "doc": "Distance from ellipsoid centre to focus"},
    {"name": "ShowDebugEllipsoid", "type": "App::PropertyBool", "group": "Debug", "doc": "Show ellipsoid for debugging"},
    {"name": "ShowDebugFoci", "type": "App::PropertyBool", "group": "Debug", "doc": "Show focal points"},
    # --------------------------------------------------------
    # Orientation.
    # --------------------------------------------------------
    {"name": "RotX", "type": "App::PropertyAngle", "group": "Orientation", "doc": "Optical axis X rotation"},
    {"name": "RotY", "type": "App::PropertyAngle", "group": "Orientation", "doc": "Optical axis Y rotation"},
    {"name": "RotZ", "type": "App::PropertyAngle", "group": "Orientation", "doc": "Optical axis Z rotation"},
    {"name": "UseAimPoint", "type": "App::PropertyBool", "group": "Orientation", "doc": "Aim the optical axis at a point"},
    {"name": "AimX", "type": "App::PropertyDistance", "group": "Orientation", "doc": "Target X coordinate"},
    {"name": "AimY", "type": "App::PropertyDistance", "group": "Orientation", "doc": "Target Y coordinate"},
    {"name": "AimZ", "type": "App::PropertyDistance", "group": "Orientation", "doc": "Target Z coordinate"},
]


# ============================================================
#  O B J E C T
# ============================================================


class OBAEllipsoid:
    CHILD_OBJECTS = ("_ellipsoid", "_focus1", "_focus2")

    def __init__(self, obj):
        self._initializing = True
        self._updating_widgets = False
        self._syncing_orientation = False

        self._ellipsoid = None
        self._focus1 = None
        self._focus2 = None

        obj.Proxy = self
        self.Object = obj

        install_properties(obj, ELLIPSOID_PROPERTIES)

        # ensure_debug_property(obj)
        make_calculated_length(obj, "FocusDistance", "Distance from ellipsoid centre to focus")

        make_optical_type(obj, "Ellipsoid")

        self._initializing = False

        # self._ensure_features(obj)

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
            ellipsoid = doc.addObject("Part::Ellipsoid", name)
        ellipsoid.Label = f"{obj.Label} Ellipsoid"

        ellipsoid.ViewObject.Transparency = 80
        ellipsoid.ViewObject.ShapeColor = (0.7, 0.8, 1.0)

        self._ellipsoid = ellipsoid

    # ========================================================
    #  U P D A T E   E L L I P S O I D
    # ========================================================

    def focal_points_world(self, obj):
        a = float(obj.A)
        b = float(obj.B)

        c = focus_distance(a, b)

        rotation = self._ellipsoid.Placement.Rotation
        center = self._ellipsoid.Placement.Base

        f1 = center + rotation.multVec(App.Vector(0, 0, -c))
        f2 = center + rotation.multVec(App.Vector(0, 0, +c))

        return f1, f2

    def show_foci(self, obj):
        f1, f2 = self.focal_points_world(obj)
        doc = obj.Document
        s1 = doc.getObject(f"{obj.Name}_Focus1")
        if s1 is None:
            s1 = doc.addObject("Part::Sphere", f"{obj.Name}_Focus1")
        s2 = doc.getObject(f"{obj.Name}_Focus2")
        if s2 is None:
            s2 = doc.addObject("Part::Sphere", f"{obj.Name}_Focus2")

        s1.ViewObject.ShapeColor = (0.0, 1.0, 0.0)  # grön
        s2.ViewObject.ShapeColor = (1.0, 0.0, 0.0)  # röd

        s1.Label = f"{obj.Label} OriginFocus"
        s2.Label = f"{obj.Label} Focus 2"

        s1.Radius = 1
        s2.Radius = 1

        s1.Placement.Base = f1
        s2.Placement.Base = f2

        self._focus1 = s1
        self._focus2 = s2

    def _update_ellipsoid(self, obj):
        self._ensure_features(obj)
        ellipsoid = self._ellipsoid

        if ellipsoid is None:
            return
        a = float(obj.A)
        b = float(obj.B)

        # guard emot felaktiva a och b värden
        if a <= 0 or b <= 0:
            return

        if obj.UseIndependentRadius3:
            b2 = float(obj.B2)
        else:
            b2 = b

        if b2 <= 0:
            return

        validate_ellipsoid(a, b, b2)
        c = focus_distance(a, b)

        # ----------------------------------------------------
        # FreeCAD Part::Ellipsoid parameters.
        #
        # Radius1 = major axis
        # Radius2 = first minor axis
        # Radius3 = second minor axis
        # ----------------------------------------------------

        ellipsoid.Radius1 = a
        ellipsoid.Radius2 = b
        ellipsoid.Radius3 = b2

        # ----------------------------------------------------
        # Part::Ellipsoid is centred on its local origin.
        # We want the OBA local origin to be one focal point.
        # Therefore move the ellipsoid centre to:
        #     (0, C, 0)
        # relative to the OBA focal-point origin.
        # ----------------------------------------------------

        rot0 = App.Rotation(App.Vector(0, 0, 1), 90).multiply(App.Rotation(App.Vector(0, 1, 0), 90))
        rotx = App.Rotation(App.Vector(1, 0, 0), float(obj.RotX))
        roty = App.Rotation(App.Vector(0, 1, 0), float(obj.RotY))
        rotz = App.Rotation(App.Vector(0, 0, 1), float(obj.RotZ))

        rotation = rot0
        rotation = rotx.multiply(rotation)
        rotation = roty.multiply(rotation)
        rotation = rotz.multiply(rotation)

        # rotation = rot0
        # rotation = rotx.multiply(rotation)
        # rotation = roty.multiply(rotation)
        # rotation = rotz.multiply(rotation)

        center_offset = rotation.multVec(App.Vector(0, 0, c))
        ellipsoid.Placement = App.Placement(obj.Placement.Base + center_offset, rotation)

        f1, f2 = self.focal_points_world(obj)

        # print("origin =", obj.Placement.Base)
        # print("f1     =", f1)
        # print("f2     =", f2)

        self.show_foci(obj)

        obj.FocusDistance = c

    # ========================================================
    #  R E B U I L D
    # ========================================================

    def _rebuild(self, obj):
        if getattr(self, "_initializing", False):
            return

        self._update_ellipsoid(obj)

        obj.Document.recompute()
        self._update_debug(obj)

    # ========================================================

    def _update_debug(self, obj):
        ellipsoid = getattr(self, "_ellipsoid", None)
        if ellipsoid is None:
            return
        show_debug = bool(obj.ShowDebugEllipsoid)
        if show_debug:
            ellipsoid.ViewObject.Visibility = True

        if self._focus1:
            self._focus1.ViewObject.Visibility = obj.ShowDebugFoci
        if self._focus2:
            self._focus2.ViewObject.Visibility = obj.ShowDebugFoci

    def synchronize_aim_from_rotation(self, obj):
        if self._syncing_orientation:
            return
        self._syncing_orientation = True
        try:
            f1, f2 = self.focal_points_world(obj)
            obj.AimX = App.Units.Quantity(f"{f2.x} mm")
            obj.AimY = App.Units.Quantity(f"{f2.y} mm")
            obj.AimZ = App.Units.Quantity(f"{f2.z} mm")
        finally:
            self._syncing_orientation = False

    def synchronize_rotation_from_aim(self, obj):

        if self._syncing_orientation:
            return
        self._syncing_orientation = True
        try:
            target = App.Vector(float(obj.AimX), float(obj.AimY), float(obj.AimZ))
            direction = target - obj.Placement.Base

            if direction.Length == 0:
                return

            direction.normalize()
            rot0 = App.Rotation(App.Vector(0, 0, 1), 90).multiply(App.Rotation(App.Vector(0, 1, 0), 90))
            rotation = App.Rotation(App.Vector(0, 1, 0), direction)

            print(rotation.multVec(App.Vector(1, 0, 0)))
            print(rotation.multVec(App.Vector(0, 1, 0)))
            print(rotation.multVec(App.Vector(0, 0, 1)))

            print("X", rotation.multVec(App.Vector(1, 0, 0)))
            print("Y", rotation.multVec(App.Vector(0, 1, 0)))
            print("Z", rotation.multVec(App.Vector(0, 0, 1)))

            # rotation = rotation.multiply(rot0)

            yaw, pitch, roll = rotation.toEuler()

            obj.RotX = yaw
            obj.RotY = pitch
            obj.RotZ = roll
        finally:
            self._syncing_orientation = False

    # ========================================================
    #  C H A N G E D
    # ========================================================

    def onChanged(self, obj, prop):

        if getattr(self, "_initializing", False):
            return

        # ----------------------------------------------------
        # Geometry
        # ----------------------------------------------------
        if prop in ("A", "B", "UseIndependentRadius3", "B2"):
            try:
                self._rebuild(obj)
            except Exception as exc:
                App.Console.PrintError("[OBA] Ellipsoid rebuild failed: " f"{exc}\n")
            return

        # ----------------------------------------------------
        # Orientation.
        # ----------------------------------------------------

        if prop in ("RotX", "RotY", "RotZ", "UseAimPoint", "AimX", "AimY", "AimZ"):
            if obj.UseAimPoint:
                self.synchronize_rotation_from_aim(obj)
            else:
                self.synchronize_aim_from_rotation(obj)
            try:
                self._rebuild(obj)
            except Exception as exc:
                App.Console.PrintError("[OBA] Ellipsoid orientation failed: " f"{exc}\n")
            return

        # ----------------------------------------------------
        # Main placement changed.
        # ----------------------------------------------------
        if prop == "Placement":
            try:
                self._update_ellipsoid(obj)
            except Exception as exc:
                App.Console.PrintError("[OBA] Ellipsoid placement update failed: " f"{exc}\n")
            return

        # ----------------------------------------------------
        # Debug visibility.
        # ----------------------------------------------------
        if prop in ("ShowDebugEllipsoid", "ShowDebugFoci"):
            self._update_debug(obj)
            return

    # ========================================================
    #  R E S T O R E
    # ========================================================

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self.Object = obj

        self._initializing = True
        self._ellipsoid = None
        self._focus1 = None
        self._focus2 = None

        install_properties(obj, ELLIPSOID_PROPERTIES)
        ensure_debug_property(obj)

        make_calculated_length(obj, "FocusDistance", "Distance from ellipsoid centre to focus")

        make_optical_type(obj, "Ellipsoid")
        self._initializing = False
        self._ensure_features(obj)
        try:
            self.synchronize_direction(obj)
        finally:
            pass
        try:
            self._rebuild(obj)
        except Exception as exc:
            App.Console.PrintError("[OBA] Ellipsoid restore rebuild failed: " f"{exc}\n")

        restore_view_provider(obj, EllipsoidViewProvider, EllipsoidDialog)

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

    def __init__(self, obj, title="Ellipsoid Settings", parent=None):

        super().__init__(obj, title=title, parent=parent)

        self._updating_widgets = False

        group = QtWidgets.QGroupBox("Ellipsoid")
        form = QtWidgets.QFormLayout(group)

        self.a = self._add_spin("A", "A", 0, 1_000_000, "mm", form)
        self.b = self._add_spin("B", "B", 0, 1_000_000, "mm", form)
        self.use_b2 = QtWidgets.QCheckBox("Use independent Radius3")
        form.addWidget(self.use_b2)
        self.b2 = self._add_spin("B2", "B2", 0, 1_000_000, "mm", form)
        self.c = QtWidgets.QLabel()
        form.addRow("Focus distance C", self.c)

        self.add_debug_checkbox("Show debug ellipsoid")

        self.show_debug = QtWidgets.QCheckBox("Show focus points (debug)")
        form.addRow(self.show_debug)

        self.rot_x = self._add_spin("Rotation X", "RotX", -360, 360, "deg", form)
        self.rot_y = self._add_spin("Rotation Y", "RotY", -360, 360, "deg", form)
        self.rot_z = self._add_spin("Rotation Z", "RotZ", -360, 360, "deg", form)

        self.chkAimPoint = QtWidgets.QCheckBox("Aim at point")
        form.addRow(self.chkAimPoint)

        self.aim_x = self._add_spin("Target X", "AimX", -1_000_000, 1_000_000, "mm", form)
        self.aim_y = self._add_spin("Target Y", "AimY", -1_000_000, 1_000_000, "mm", form)
        self.aim_z = self._add_spin("Target Z", "AimZ", -1_000_000, 1_000_000, "mm", form)

        # ----------------------------------------------------
        # Add group.
        # ----------------------------------------------------
        self.custom_layout.addWidget(group)

        # ====================================================
        #  B U T T O N S
        # ====================================================
        buttons = QtWidgets.QHBoxLayout()

        self.custom_layout.addLayout(buttons)
        self.add_placement_group()

        # ====================================================
        #  S I G N A L S
        # ====================================================

        self.a.valueChanged.connect(lambda value: self._set_property("A", value.Value))
        self.b.valueChanged.connect(lambda value: self._set_property("B", value.Value))
        self.b2.valueChanged.connect(lambda value: self._set_property("B2", value.Value))

        self.rot_x.valueChanged.connect(lambda value: self._set_property("RotX", value.Value))
        self.rot_y.valueChanged.connect(lambda value: self._set_property("RotY", value.Value))
        self.rot_z.valueChanged.connect(lambda value: self._set_property("RotZ", value.Value))

        self.aim_x.valueChanged.connect(lambda value: self._set_property("AimX", value.Value))
        self.aim_y.valueChanged.connect(lambda value: self._set_property("AimY", value.Value))
        self.aim_z.valueChanged.connect(lambda value: self._set_property("AimZ", value.Value))

        self.show_debug.toggled.connect(lambda checked: self._set_property("ShowDebugFoci", checked))
        self.chkAimPoint.toggled.connect(lambda checked: self._set_property("UseAimPoint", checked))

        self.chkAimPoint.toggled.connect(self._update_dialog_orientation_controls)
        # ----------------------------------------------------
        # Load.
        # ----------------------------------------------------
        self.reload()

    def _set_property(self, prop, value):
        if self._updating_widgets:
            return

        try:
            setattr(self.obj, prop, value)
            self._update_information()

        except Exception as exc:
            App.Console.PrintError(f"[OBA] Failed to update {prop}: {exc}\n")

    def _update_information(self):
        self.c.setText(f"{float(self.obj.FocusDistance):.4f} mm")

        # f1, f2 = self.focal_points_world(self.obj)

        # obj.AimX = f2.x
        # obj.AimY = f2.y
        # obj.AimZ = f2.z

        # --------------------------------------------------------------
        # Symmetric ellipsoid angles
        # --------------------------------------------------------------
        # self.left_angle.setText(f"{90 - tilt:.3f}°")
        # self.right_angle.setText(f"{90 + tilt:.3f}°")
        # self.b2.setEnabled(bool(self.obj.UseIndependentRadius3))

    # ========================================================
    #  R E L O A D
    # ========================================================

    def reload(self):

        direction = self.obj.Placement.Rotation.multVec(App.Vector(1, 0, 0))
        proxy = getattr(self.obj, "Proxy", None)
        # was_updating = getattr(proxy, "_updating_orientation", False) if proxy is not None else False
        # if proxy is not None:
        #     proxy._updating_orientation = True
        # try:
        #     self.obj.RotX = direction.x
        #     self.obj.RotY = direction.y
        #     self.obj.RotZ = direction.z
        # finally:
        #     if proxy is not None:
        #         proxy._updating_orientation = was_updating

        # self.c.setText(f"{float(self.obj.FocusDistance):.4f} mm")

        self.a.setProperty("rawValue", float(self.obj.A))
        self.b.setProperty("rawValue", float(self.obj.B))

        self.use_b2.setChecked(bool(self.obj.UseIndependentRadius3))
        self.b2.setProperty("rawValue", float(self.obj.B2))

        # self.b2.setValue(float(self.obj.B2))  # funkar inte

        self.chkAimPoint.setChecked(bool(self.obj.UseAimPoint))
        self.show_debug.setChecked(bool(self.obj.ShowDebugFoci))

        self.rot_x.setProperty("rawValue", float(self.obj.RotX))
        self.rot_y.setProperty("rawValue", float(self.obj.RotY))
        self.rot_z.setProperty("rawValue", float(self.obj.RotZ))

        self.aim_x.setProperty("rawValue", float(self.obj.AimX))
        self.aim_y.setProperty("rawValue", float(self.obj.AimY))
        self.aim_z.setProperty("rawValue", float(self.obj.AimZ))

        self.reload_placement()
        # ----------------------------------------------------
        # UI.
        # ----------------------------------------------------
        self._update_dialog_orientation_controls()

        self._preview()

    # ========================================================
    #  O R I E N T A T I O N   C O N T R O L S
    # ========================================================

    def _update_dialog_orientation_controls(self):
        use_aim = self.chkAimPoint.isChecked()
        for control in (self.rot_x, self.rot_y, self.rot_z):
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
            return

        c = focus_distance(a, b)
        self.c.setText(f"{c:.4f} mm")

        self.b2.setEnabled(self.use_b2.isChecked())

    # ========================================================
    #  A P P L Y
    # ========================================================


# ============================================================
#  V I E W   P R O V I D E R
# ============================================================


class EllipsoidViewProvider(OBAToolboxViewProviderBase):
    dialog_class = EllipsoidDialog

    def __init__(self, vobj):
        super().__init__(vobj, EllipsoidDialog)

    # ========================================================
    #  C H I L D R E N
    # ========================================================

    def claimChildren(self):
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
        obj = getattr(self, "Object", None)
        if obj is None:
            return True
        proxy = getattr(obj, "Proxy", None)
        if proxy is None:
            return True
        doc = obj.Document
        child_names = getattr(proxy, "CHILD_OBJECTS", ())
        print("childnames ", child_names)
        for attr_name in reversed(child_names):
            child = getattr(proxy, attr_name, None)
            if child and doc.getObject(child.Name):
                doc.removeObject(child.Name)
        return True


def OBA_CreateEllipsoid(doc=None, label="Ellipsoid", a=40.0, b=20.0, b2=None, rot_x=0, rot_y=0, rot_z=0, x=0, y=0, z=0, placement=None, show_dialog=True):
    doc = doc or App.ActiveDocument or App.newDocument()
    if b2 is None:
        b2 = b
        use_b2 = False
    else:
        use_b2 = True
    validate_ellipsoid(a, b, b2)
    obj = doc.addObject("Part::FeaturePython", "OBAEllipsoid")

    obj.Label = label

    proxy = OBAEllipsoid(obj)

    obj.A = App.Units.Quantity(f"{a} mm")
    obj.B = App.Units.Quantity(f"{b} mm")

    obj.UseIndependentRadius3 = use_b2
    obj.B2 = App.Units.Quantity(f"{b2} mm")

    obj.RotX = App.Units.Quantity(f"{rot_x} deg")
    obj.RotY = App.Units.Quantity(f"{rot_y} deg")
    obj.RotZ = App.Units.Quantity(f"{rot_z} deg")

    obj.UseAimPoint = False

    obj.AimX = App.Units.Quantity("100 mm")
    obj.AimY = App.Units.Quantity("0 mm")
    obj.AimZ = App.Units.Quantity("0 mm")

    obj.ShowDebugEllipsoid = False
    obj.FocusDistance = focus_distance(float(a), float(b))

    # --------------------------------------------------------
    # Build the real Part::Ellipsoid once everything is ready.
    # --------------------------------------------------------

    if placement is None:
        placement = App.Placement(App.Vector(x, y, z), App.Rotation())

    obj.Placement = placement

    proxy._ensure_features(obj)
    proxy._update_ellipsoid(obj)

    if App.GuiUp:
        EllipsoidViewProvider(obj.ViewObject)

    doc.recompute()

    if show_dialog:
        EllipsoidDialog(obj).show()
    return obj


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
