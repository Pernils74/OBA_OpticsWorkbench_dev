# oba_comp_mirror.py
#
# OBA Comp Mirror
#
# Geometry:
#   - One rectangular cube/body
#   - One ellipsoid
#   - The ellipsoid is subtracted from the cube
#
# Construction objects are kept directly under the main FeaturePython
# object in the tree through the ViewProvider.claimChildren() mechanism.
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

COMP_MIRROR_PROPERTIES = [
    {"name": "Width", "type": "App::PropertyLength", "group": "Main Mirror", "default": 100.0, "doc": "Width of the cube/body along X"},
    {"name": "Height", "type": "App::PropertyLength", "group": "Main Mirror", "default": 30.0, "doc": "Height of the cube/body along Z"},
    {"name": "A", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 40.0, "doc": "Ellipsoid semi-major axis"},
    {"name": "B", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 30.0, "doc": "Ellipsoid semi-minor radius"},
    {"name": "UseIndependentRadius3", "type": "App::PropertyBool", "group": "Ellipsoid", "default": False, "doc": "Use independent radius in Y direction"},
    {"name": "B2", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 20.0, "doc": "Independent ellipsoid Y radius"},
    {"name": "FocusDistance", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 26.4575131106, "doc": "Distance from ellipsoid centre to focus"},
    # {"name": "TiltAngle", "type": "App::PropertyAngle", "group": "Ellipsoid", "default": 0.0, "doc": "Tilt angle of the ellipsoids around the Z axis"},
    {"name": "ShowDebugEllipsoids", "type": "App::PropertyBool", "group": "Debug", "default": False, "doc": "Show ellipsoids for debugging"},
    {"name": "PosX", "type": "App::PropertyDistance", "group": "Placement", "doc": "X coordinate"},
    {"name": "PosY", "type": "App::PropertyDistance", "group": "Placement", "doc": "Y coordinate"},
    {"name": "PosZ", "type": "App::PropertyDistance", "group": "Placement", "doc": "Z coordinate"},
]


class OBACompMirror:
    CHILD_OBJECTS = ("_cut", "_cube", "_ellipsoid")

    def _init_runtime_state(self):
        """
        Initialise all Python-only runtime references.
        These references are not persisted by FreeCAD and therefore must
        also be recreated when a document is restored.
        """
        self._initializing = True

        self._rebuilding = False

        self._cube = None
        self._ellipsoid = None
        self._cut = None

    def __init__(self, obj):
        self._init_runtime_state()
        obj.Proxy = self
        self.Object = obj
        self._dialog = None

        # obj.setEditorMode("Placement", 1)

        install_properties(obj, COMP_MIRROR_PROPERTIES)

        if hasattr(obj, "FocusDistance"):
            obj.setEditorMode("FocusDistance", 1)  # sets readonly

        # make_optical_type(obj, "MainMirror")

        self._initializing = False

        App.Console.PrintMessage(f"[OBA] Proxy attached: {obj.Name}\n")

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

        Construction objects are created directly in the document.
        They are not placed inside an App::Part.
        """
        doc = obj.Document
        if self._cube is None:
            self._cube = doc.getObject(f"{obj.Name}_Cube")
        if self._ellipsoid is None:
            self._ellipsoid = doc.getObject(f"{obj.Name}_Ellipsoid")
        if self._cut is None:
            self._cut = doc.getObject(f"{obj.Name}_Cut")

        # --------------------------------------------------------------
        # Validate existing references
        # --------------------------------------------------------------
        if not self._obj_exists(self._cube):
            self._cube = None
        if not self._obj_exists(self._ellipsoid):
            self._ellipsoid = None
        if not self._obj_exists(self._cut):
            self._cut = None
        # --------------------------------------------------------------
        # Create missing construction objects
        # --------------------------------------------------------------

        if self._cube is None:
            self._cube = doc.addObject("Part::Box", f"{obj.Name}_Cube")
            self._cube.Label = f"{obj.Label} Cube"

        if self._ellipsoid is None:
            self._ellipsoid = doc.addObject("Part::Ellipsoid", f"{obj.Name}_Ellipsoid")

            self._ellipsoid.Label = f"{obj.Label} Ellipsoid"

            self._ellipsoid.ViewObject.ShapeColor = (0.0, 0.0, 1.0)

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
        base = obj.Placement
        width = float(obj.Width)
        height = float(obj.Height)

        # Keep enough depth for the ellipsoid geometry.
        depth = 2 * float(obj.B)

        self._cube.Length = width
        self._cube.Width = depth
        self._cube.Height = height

        # self._cube.Placement.Base = App.Vector(-width / 2.0, -depth / 1.9, -height / 2.0)

        cube_local = App.Placement(App.Vector(-width / 2, -depth / 1.9, -height / 2), App.Rotation())
        self._cube.Placement = base.multiply(cube_local)

    def _update_ellipsoid(self, obj):
        a = float(obj.A)
        b = float(obj.B)

        b2 = float(obj.B2) if obj.UseIndependentRadius3 else b

        self._ellipsoid.Radius1 = a
        self._ellipsoid.Radius2 = b
        self._ellipsoid.Radius3 = b2

        rot_z = App.Rotation(App.Vector(0, 0, 1), 90)
        rot_x = App.Rotation(App.Vector(1, 0, 0), -90)

        ell_local = App.Placement()
        ell_local.Base = App.Vector(0, b, 0)
        ell_local.Rotation = rot_z.multiply(rot_x)

        self._ellipsoid.Placement = obj.Placement.multiply(ell_local)

    def _update_debug_visibility(self, obj):
        try:
            debug = bool(obj.ShowDebugEllipsoids)

            # The cube is hidden because the Cut represents the
            # resulting geometry.
            self._cube.ViewObject.Visibility = False

            # Resulting geometry.
            self._cut.ViewObject.Visibility = True

            # Construction ellipsoid.
            if debug:
                self._ellipsoid.ViewObject.Visibility = True
                self._ellipsoid.ViewObject.Transparency = 80
            else:
                self._ellipsoid.ViewObject.Visibility = False

        except Exception:
            pass

    # ------------------------------------------------------------------
    # Rebuild
    # ------------------------------------------------------------------

    def _rebuild(self, obj):
        """
        Rebuild the complete Comp Mirror geometry immediately.
        """
        if self._rebuilding:
            return

        self._rebuilding = True
        try:

            # required = ("Width", "Height", "A", "B")

            # for name in required:
            #     if not hasattr(obj, name):
            #         return

            # self._ensure_features(obj)
            self._update_cube(obj)
            self._update_ellipsoid(obj)

            self._update_debug_visibility(obj)

            c = focus_distance(float(obj.A), float(obj.B))
            obj.FocusDistance = c

            obj.Document.recompute()
        finally:
            # dialog = getattr(self, "_dialog", None)
            # if dialog:
            #     dialog.refresh_from_object()

            self._rebuilding = False

    # ------------------------------------------------------------------
    # Property changes
    # ------------------------------------------------------------------

    def onChanged(self, obj, prop):

        if prop in ("Shape", "Label"):  # Early exits on special props
            return

        if self._initializing:
            return

        if self._rebuilding:
            return

        App.Console.PrintMessage(f"onChanged: {prop}\n")

        if prop in {"Width", "Height", "A", "B", "UseIndependentRadius3", "B2", "ShowDebugEllipsoids"}:
            try:
                self._rebuild(obj)
            except Exception as exc:
                App.Console.PrintError("[OBA] Comp Mirror rebuild failed: " f"{exc}\n")

        if prop in ("Placement"):
            try:
                self._rebuild(obj)
            except Exception as exc:
                App.Console.PrintError("[OBA] Comp Mirror placement update failed: " f"{exc}\n")

        # update dialog if its open
        dialog = getattr(self, "_dialog", None)
        if dialog:
            dialog.refresh_from_object()

    # ------------------------------------------------------------------
    # Document restore
    # ------------------------------------------------------------------

    def onDocumentRestored(self, obj):
        """
        Restore Python runtime state and reconnect to the existing
        FreeCAD construction objects.
        """
        self._init_runtime_state()

        obj.Proxy = self
        self.Object = obj

        obj.setEditorMode("Placement", 1)

        try:
            install_properties(obj, COMP_MIRROR_PROPERTIES)
            if hasattr(obj, "FocusDistance"):
                obj.setEditorMode("FocusDistance", 1)

            # make_optical_type(obj, "CompMirror")
            self._ensure_features(obj)
        finally:
            self._initializing = False
        try:
            self._rebuild(obj)
        except Exception as exc:
            App.Console.PrintError("[OBA] Comp Mirror restore rebuild failed: " f"{exc}\n")
        restore_view_provider(obj, CompMirrorViewProvider)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


# ======================================================================
# Dialog
# ======================================================================


class CompMirrorDialog(OBAToolboxDialogBase):

    def __init__(self, obj, title="Main Mirror Main Mirror Settings", parent=None):
        super().__init__(obj, title=title, parent=parent)

        # self.obj.Proxy._dialog = self  # registrering av dialog på objektet

        self._refreshing_ui = False

        group = QtWidgets.QGroupBox("Main Mirror Main Mirror Parameters")
        form = QtWidgets.QFormLayout(group)

        self.width = self._add_spin("Width", "Width", 0, 1000, "mm", form)
        self.height = self._add_spin("Height", "Height", 0, 1000, "mm", form)
        self.a = self._add_spin("A", "A", 0, 1000, "mm", form)
        self.b = self._add_spin("B", "B", 0, 1000, "mm", form)
        self.use_b2 = QtWidgets.QCheckBox("Use independent Radius3")
        form.addRow(self.use_b2)
        self.b2 = self._add_spin("B2", "B2", 0, 1000, "mm", form)
        # self.tiltangle = self._add_spin("Tilt angle", "TiltAngle", -90, 90, "°", form)
        self.c = QtWidgets.QLabel()

        # info text
        form.addRow("Focus distance C", self.c)

        self.debug_show = QtWidgets.QCheckBox("Show ellipsoids (debug)")
        form.addRow(self.debug_show)
        self.custom_layout.addWidget(group)

        # group = QtWidgets.QGroupBox("Placement")
        # form = QtWidgets.QFormLayout(group)
        # self.pos_x = self._add_spin("X", "PosX", -1_000_000, 1_000_000, "mm", form)
        # self.pos_y = self._add_spin("Y", "PosY", -1_000_000, 1_000_000, "mm", form)
        # self.pos_z = self._add_spin("Z", "PosZ", -1_000_000, 1_000_000, "mm", form)
        # self.custom_layout.addWidget(group)
        # self.add_placement_group()

        info = QtWidgets.QLabel("The two ellipsoids are mirrored around the centre " "plane of the Main Mirror.\n\n" "TiltAngle is the symmetric tilt of the ellipsoids.")
        info.setWordWrap(True)
        self.custom_layout.addWidget(info)
        # --------------------------------------------------------------
        # Signals
        # --------------------------------------------------------------
        self.width.valueChanged.connect(lambda value: self._set_property("Width", value.Value))
        self.height.valueChanged.connect(lambda value: self._set_property("Height", value.Value))
        self.a.valueChanged.connect(lambda value: self._set_property("A", value.Value))
        self.b.valueChanged.connect(lambda value: self._set_property("B", value.Value))
        self.b2.valueChanged.connect(lambda value: self._set_property("B2", value.Value))
        # self.tiltangle.valueChanged.connect(lambda value: self._set_property("TiltAngle", value.Value))
        self.use_b2.toggled.connect(self._use_b2_changed)
        self.debug_show.toggled.connect(lambda checked: self._set_property("ShowDebugEllipsoids", checked))

        # self.pos_x.valueChanged.connect(lambda value: self._set_property("PosX", value.Value))
        # self.pos_y.valueChanged.connect(lambda value: self._set_property("PosY", value.Value))
        # self.pos_z.valueChanged.connect(lambda value: self._set_property("PosZ", value.Value))

        self.refresh_from_object()

    # ------------------------------------------------------------------
    # Property editing
    # ------------------------------------------------------------------

    def _set_property(self, prop, value):
        # print("_set_property", prop, value)
        if self._refreshing_ui:
            return
        # current = getattr(self.obj, prop)
        # if float(current) == float(value):
        #     print(f"[OBA] {prop} unchanged -> skip")
        #     return
        try:
            setattr(self.obj, prop, value)
            self._update_information()
        except Exception as exc:
            App.Console.PrintError(f"[OBA] Failed to update {prop}: {exc}\n")

    def _use_b2_changed(self, checked):
        if self._refreshing_ui:
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

    def refresh_from_object(self):
        self._refreshing_ui = True

        try:
            self.use_b2.setChecked(bool(self.obj.UseIndependentRadius3))
            self.b2.setEnabled(bool(self.obj.UseIndependentRadius3))
            self.debug_show.setChecked(bool(self.obj.ShowDebugEllipsoids))

            self.a.setProperty("rawValue", float(self.obj.A))
            self.b.setProperty("rawValue", float(self.obj.B))
            self.b2.setProperty("rawValue", float(self.obj.B2))

            self.width.setProperty("rawValue", float(self.obj.Width))
            self.height.setProperty("rawValue", float(self.obj.Height))
            # self.tiltangle.setProperty("rawValue", float(self.obj.TiltAngle))
            self._update_information()

        finally:
            self._refreshing_ui = False

    def _update_information(self):
        print("_update_information called")
        width = float(self.obj.Width)
        height = float(self.obj.Height)
        a = float(self.obj.A)
        b = float(self.obj.B)
        # tilt = float(self.obj.TiltAngle)

        if a > 0 and b > 0 and a >= b:
            c = math.sqrt(max(0.0, a * a - b * b))
            self.c.setText(f"{c:.4f} mm")
        else:
            self.c.setText("Invalid A/B")

        self.b2.setEnabled(bool(self.obj.UseIndependentRadius3))

    # def closeEvent(self, event):
    #     self.obj.Proxy._dialog = None
    #     super().closeEvent(event)

    # def showEvent(self, event):
    #     self.obj.Proxy._dialog = self
    #     super().showEvent(event)
    #     print("dialog opened")


# ======================================================================
# View Provider
# ======================================================================


class CompMirrorViewProvider(OBAToolboxViewProviderBase):

    dialog_class = CompMirrorDialog

    def __init__(self, vobj):
        super().__init__(vobj, CompMirrorDialog)

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
        Show the construction objects directly underneath the main
        Comp Mirror object in the tree.

        No App::Part / _Internal container is used.
        """
        obj = getattr(self, "Object", None)
        if obj is None:
            return []
        proxy = getattr(obj, "Proxy", None)
        if proxy is None:
            return []
        children = []
        cube = getattr(proxy, "_cube", None)
        ellipsoid = getattr(proxy, "_ellipsoid", None)
        cut = getattr(proxy, "_cut", None)
        if cube is not None:
            children.append(cube)
        if ellipsoid is not None:
            children.append(ellipsoid)
        if cut is not None:
            children.append(cut)

        return children

    def doubleClicked(self, vobj):
        """
        Open the Main Mirror settings dialog when the object is
        double-clicked in the tree.
        """
        obj = getattr(vobj, "Object", None)
        if obj is None:
            return False
        try:
            dialog = CompMirrorDialog(obj)
            # Keep a reference so the dialog cannot be garbage-collected
            # while it is still open.
            self._dialog = dialog

            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return True
        except Exception as exc:
            App.Console.PrintError("[OBA] Failed to open Main Mirror dialog: " f"{exc}\n")
            return False

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


# ======================================================================
# Factory
# ======================================================================


def OBA_CreateCompMirror(
    doc=None,
    label="Comp_Mirror",
    width=100.0,
    height=30.0,
    a=40.0,
    b=30.0,
    # tiltangle=0.0,
    x=0.0,
    y=0.0,
    z=0.0,
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

    obj = doc.addObject("Part::FeaturePython", "OBA_CompMirror")

    obj.Label = label

    proxy = OBACompMirror(obj)
    proxy._initializing = True

    obj.Width = App.Units.Quantity(f"{width} mm")
    obj.Height = App.Units.Quantity(f"{height} mm")
    obj.A = App.Units.Quantity(f"{a} mm")
    obj.B = App.Units.Quantity(f"{b} mm")
    # obj.TiltAngle = App.Units.Quantity(f"{tiltangle} deg")

    proxy._ensure_features(obj)
    proxy._initializing = False
    proxy._rebuild(obj)

    obj.Placement = App.Placement(App.Vector(x, y, z), App.Rotation())

    if App.GuiUp:
        CompMirrorViewProvider(obj.ViewObject)

    doc.recompute()

    if show_dialog:
        dialog = CompMirrorDialog(obj)
        dialog.show()

    return obj


# ======================================================================
# Public create() entry point
# ======================================================================


def create(
    doc=None,
    label="Comp_Mirror",
    width=100.0,
    height=30.0,
    a=40.0,
    b=30.0,
    # tiltangle=0.0,
    x=0.0,
    y=30.0,
    z=0.0,
):
    return OBA_CreateCompMirror(
        doc=doc,
        label=label,
        width=width,
        height=height,
        a=a,
        b=b,
        # tiltangle=tiltangle,
        x=x,
        y=y,
        z=z,
        show_dialog=False,
    )
