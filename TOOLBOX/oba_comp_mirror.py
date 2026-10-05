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

import FreeCAD as App
import FreeCADGui as Gui

# from oba_objects.oba_base import OBAElementProxy

from .oba_toolbox_base import (
    OBAToolboxDialogBase,
    OBAToolboxViewProviderBase,
    focus_distance,
    install_properties,
    make_calculated_length,
    make_optical_type,
    restore_view_provider,
    set_quantity_if_changed,
    set_property_if_changed,
)

COMP_MIRROR_PROPERTIES = [
    {"name": "Width", "type": "App::PropertyLength", "group": "Main Mirror", "default": 100.0, "unit": "mm", "min": 0, "max": 1000, "doc": "Width of the cube/body along X"},
    {"name": "Height", "type": "App::PropertyLength", "group": "Main Mirror", "default": 30.0, "unit": "mm", "min": 0, "max": 1000, "doc": "Height of the cube/body along Z"},
    {"name": "A", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 40.0, "unit": "mm", "min": 0, "max": 1000, "doc": "Ellipsoid semi-major axis"},
    {"name": "B", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 30.0, "unit": "mm", "min": 0, "max": 1000, "doc": "Ellipsoid semi-minor radius"},
    {"name": "Radius3Offset", "label": "Radius3 Offset", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 0.0, "unit": "mm", "min": 0, "max": 1000, "doc": "Amount subtracted from Radius2 (B) to produce Radius3"},
    {"name": "FocusDistance", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 26.4575131106, "unit": "mm", "display_only": True, "doc": "Distance from ellipsoid centre to focus"},
    # {"name": "TiltAngle", "type": "App::PropertyAngle", "group": "Ellipsoid", "default": 0.0, "doc": "Tilt angle of the ellipsoids around the Z axis"},
    {"name": "ShowDebugEllipsoids", "type": "App::PropertyBool", "group": "Debug", "default": False, "doc": "Show ellipsoids for debugging"},
    {"name": "PosX", "type": "App::PropertyFloat", "group": "Placement", "unit": "mm", "min": -1000, "max": 1000, "doc": "X coordinate"},
    {"name": "PosY", "type": "App::PropertyFloat", "group": "Placement", "unit": "mm", "min": -1000, "max": 1000, "doc": "Y coordinate"},
    {"name": "PosZ", "type": "App::PropertyFloat", "group": "Placement", "unit": "mm", "min": -1000, "max": 1000, "doc": "Z coordinate"},
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

        self._suppress_onchange = False

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

        obj.addProperty("App::PropertyLinkList", "Group", "Base", "Owned children")

        if hasattr(obj, "FocusDistance"):
            obj.setEditorMode("FocusDistance", 1)  # sets readonly

        make_optical_type(obj, "CompMirror")

        self._initializing = False

        App.Console.PrintMessage(f"[OBA] Proxy attached: {obj.Name}\n")

    # ------------------------------------------------------------------
    # Runtime object handling
    # ------------------------------------------------------------------

    def _get_or_create(self, doc, name, objtype, label):
        obj = doc.getObject(name)

        if obj is None:
            obj = doc.addObject(objtype, name)
            obj.Label = label
        return obj

    def _ensure_features(self, obj):
        """
        Find existing construction objects or create them if missing.
        Construction objects are created directly in the document.
        They are not placed inside an App::Part.
        """
        doc = obj.Document

        self._cube = self._get_or_create(doc, f"{obj.Name}_Cube", "Part::Box", f"{obj.Label} Cube")
        self._ellipsoid = self._get_or_create(doc, f"{obj.Name}_Ellipsoid", "Part::Ellipsoid", f"{obj.Label} Ellipsoid")
        self._cut = self._get_or_create(doc, f"{obj.Name}_Cut", "Part::Cut", f"{obj.Label} Cut")

        children = [
            self._cube,
            self._ellipsoid,
            self._cut,
        ]
        set_property_if_changed(obj, "Group", children)

        # --------------------------------------------------------------
        # Boolean relationship
        # --------------------------------------------------------------

        set_property_if_changed(self._cut, "Base", self._cube)
        set_property_if_changed(self._cut, "Tool", self._ellipsoid)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _update_cube(self, obj):
        base = obj.Placement
        width = float(obj.Width)
        height = float(obj.Height)

        # Keep enough depth for the ellipsoid geometry.
        depth = 1.8 * float(obj.B)

        changed = False
        changed |= set_quantity_if_changed(self._cube, "Length", width, "mm")
        changed |= set_quantity_if_changed(self._cube, "Width", depth, "mm")
        changed |= set_quantity_if_changed(self._cube, "Height", height, "mm")

        # self._cube.Placement.Base = App.Vector(-width / 2.0, -depth / 1.9, -height / 2.0)

        cube_local = App.Placement(App.Vector(-width / 2, -depth / 1.9, -height / 2), App.Rotation())
        changed |= set_property_if_changed(self._cube, "Placement", base.multiply(cube_local))
        return changed

    def _update_ellipsoid(self, obj):
        changed = False

        changed |= set_quantity_if_changed(self._ellipsoid, "Radius1", obj.A, "mm")
        changed |= set_quantity_if_changed(self._ellipsoid, "Radius2", obj.B, "mm")
        radius3 = max(0.0, float(obj.B) - float(obj.Radius3Offset))
        changed |= set_quantity_if_changed(self._ellipsoid, "Radius3", radius3, "mm")

        rot_z = App.Rotation(App.Vector(0, 0, 1), 90)
        rot_x = App.Rotation(App.Vector(1, 0, 0), -90)

        ell_local = App.Placement()
        ell_local.Base = App.Vector(0, float(obj.B), 0)
        ell_local.Rotation = rot_z.multiply(rot_x)

        new_placement = obj.Placement.multiply(ell_local)

        changed |= set_property_if_changed(self._ellipsoid, "Placement", new_placement)

        return changed

    def _update_debug_visibility(self, obj):
        try:
            debug = bool(obj.ShowDebugEllipsoids)
            changed = False

            # The cube is hidden because the Cut represents the
            # resulting geometry.
            changed |= set_property_if_changed(self._cube.ViewObject, "Visibility", False)

            # Resulting geometry.
            # self._cut.ViewObject.Visibility = True

            # Construction ellipsoid.
            if debug:
                changed |= set_property_if_changed(self._ellipsoid.ViewObject, "Visibility", True)
                changed |= set_property_if_changed(self._ellipsoid.ViewObject, "Transparency", 80)
            else:
                changed |= set_property_if_changed(self._ellipsoid.ViewObject, "Visibility", False)
            return changed

        except Exception:
            return False

    # ------------------------------------------------------------------
    # Rebuild
    # ------------------------------------------------------------------

    def _rebuild(self, obj):
        """
        Rebuild the complete Comp Mirror geometry immediately.
        """

        # if not hasattr(self, "_initializing"):
        #     self._init_runtime_state()

        if self._rebuilding:
            return

        self._rebuilding = True

        try:
            changed = False
            changed |= self._update_cube(obj)
            changed |= self._update_ellipsoid(obj)

            changed |= self._update_debug_visibility(obj)

            c = focus_distance(float(obj.A), float(obj.B))
            changed |= set_quantity_if_changed(obj, "FocusDistance", c, "mm")

            if changed and not self._suppress_onchange:
                # print("---------------------------------  skall inte ske ---------------------------")
                obj.Document.recompute()
                pass

        finally:
            self._rebuilding = False

    # ------------------------------------------------------------------
    # Property changes
    # ------------------------------------------------------------------

    def onChanged(self, obj, prop):

        # if not hasattr(self, "_initializing"):
        #     self._init_runtime_state()

        # if prop in ("Shape", "Label"):  # Early exits on special props
        #     return

        # print("CompMirror onChanged:", prop)

        if prop == "Shape":
            return

        if prop == "Group":
            return

        if self._initializing:
            return

        if self._rebuilding:
            return

        if prop in {"ShowDebugEllipsoids"}:
            self._update_debug_visibility(obj)

        if self._suppress_onchange:
            return

        # App.Console.PrintMessage(f"onChanged: {prop}\n")

        if prop in {"Width", "Height", "A", "B", "Radius3Offset", "ShowDebugEllipsoids"}:
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

        # obj.setEditorMode("Placement", 1)

        try:
            for legacy_property in ("UseIndependentRadius3", "B2"):
                if legacy_property in obj.PropertiesList:
                    obj.removeProperty(legacy_property)
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
        self._init_runtime_state()
        # return None


# ======================================================================
# Dialog
# ======================================================================


class CompMirrorDialog(OBAToolboxDialogBase):
    PROPERTY_DEFINITIONS = COMP_MIRROR_PROPERTIES

    def __init__(self, obj, title="Comp Mirror Settings", parent=None):
        super().__init__(obj, title=title, parent=parent)


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

    # def canTransform(self):
    #     """
    #     Disable the standard Transform/Gizmo action for the main object.
    #     """
    #     return False

    def claimChildren(self):
        obj = getattr(self, "Object", None)
        if obj is None:
            return []
        return list(getattr(obj, "Group", []))

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

        doc = obj.Document
        for child in getattr(obj, "Group", []):
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
    suppress_onchange=False,
    show_dialog=True,
    radius3_offset=0.0,
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
    # if b > height:
    #     raise ValueError("B must be less than or equal to Height.")

    # --------------------------------------------------------------
    # Main FeaturePython object
    # --------------------------------------------------------------

    obj = doc.addObject("Part::FeaturePython", "OBA_CompMirror")

    obj.Label = label

    proxy = OBACompMirror(obj)
    proxy._initializing = True
    proxy._suppress_onchange = suppress_onchange

    obj.Width = width  # App.Units.Quantity(f"{width} mm")
    obj.Height = height  # App.Units.Quantity(f"{height} mm")
    obj.A = a  # App.Units.Quantity(f"{a} mm")
    obj.B = b  # App.Units.Quantity(f"{b} mm")
    obj.Radius3Offset = radius3_offset
    # obj.TiltAngle = App.Units.Quantity(f"{tiltangle} deg")

    proxy._ensure_features(obj)
    proxy._initializing = False
    proxy._rebuild(obj)

    obj.Placement = App.Placement(App.Vector(x, y, z), App.Rotation())

    if App.GuiUp:
        CompMirrorViewProvider(obj.ViewObject)

    obj.Document.recompute()

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
    radius3_offset=0.0,
):
    return OBA_CreateCompMirror(
        doc=doc,
        label=label,
        width=width,
        height=height,
        a=a,
        b=b,
        radius3_offset=radius3_offset,
        # tiltangle=tiltangle,
        x=x,
        y=y,
        z=z,
        show_dialog=False,
    )
