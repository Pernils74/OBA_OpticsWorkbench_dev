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
# Construction objects are created directly in the document.
# The ViewProvider claims them as children of the main FeaturePython
# object, and CHILD_OBJECTS is used when the main object is deleted.
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
    set_property_if_changed,
    set_quantity_if_changed,
)

MAIN_MIRROR_PROPERTIES = [
    {"name": "Width", "type": "App::PropertyLength", "group": "Main Mirror", "default": 80.0, "unit": "mm", "min": 0, "max": 1000, "doc": "Width of the cube/body along X"},
    {"name": "Height", "type": "App::PropertyLength", "group": "Main Mirror", "default": 30.0, "unit": "mm", "min": 0, "max": 1000, "doc": "Height of the cube/body along Z"},
    {"name": "SplitOffset", "type": "App::PropertyLength", "group": "Main Mirror", "default": 40.0, "unit": "mm", "min": 0, "max": 1000, "doc": "Distance between the two ellipsoid focal points"},
    {"name": "A", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 40.0, "unit": "mm", "min": 0, "max": 1000, "doc": "Ellipsoid semi-major axis"},
    {"name": "B", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 30.0, "unit": "mm", "min": 0, "max": 1000, "doc": "Ellipsoid semi-minor radius"},
    {"name": "Radius3Offset", "label": "Radius3 Offset", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 0.0, "unit": "mm", "min": 0, "max": 1000, "doc": "Amount subtracted from Radius2 (B) to produce Radius3"},
    {"name": "FocusDistance", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 26.4575131106, "unit": "mm", "display_only": True, "doc": "Distance from ellipsoid centre to focus"},
    {"name": "Ellipsoid1FocusX", "type": "App::PropertyLength", "group": "Calculated", "unit": "mm", "display_only": True, "doc": "X position of first ellipsoid focus"},
    {"name": "Ellipsoid2FocusX", "type": "App::PropertyLength", "group": "Calculated", "unit": "mm", "display_only": True, "doc": "X position of second ellipsoid focus"},
    {"name": "MirrorPlaneX", "type": "App::PropertyLength", "group": "Calculated", "unit": "mm", "display_only": True, "doc": "X coordinate of mirror symmetry plane"},
    {"name": "TiltAngle", "type": "App::PropertyAngle", "group": "Ellipsoid", "default": 0.0, "unit": "deg", "min": -90, "max": 90, "doc": "Tilt angle of the ellipsoids around the Z axis"},
    {"name": "TiltAngleOffset", "label": "Tilt Angle Offset", "type": "App::PropertyAngle", "group": "Ellipsoid", "default": 0.0, "unit": "deg", "min": -90, "max": 90, "doc": "Additional tilt applied to the left ellipsoid"},
    {"name": "ShowDebugEllipsoids", "type": "App::PropertyBool", "group": "Debug", "default": False, "doc": "Show ellipsoids for debugging"},
    {"name": "PosX", "type": "App::PropertyFloat", "group": "Placement", "unit": "mm", "min": -1000, "max": 1000, "doc": "X coordinate"},
    {"name": "PosY", "type": "App::PropertyFloat", "group": "Placement", "unit": "mm", "min": -1000, "max": 1000, "doc": "Y coordinate"},
    {"name": "PosZ", "type": "App::PropertyFloat", "group": "Placement", "unit": "mm", "min": -1000, "max": 1000, "doc": "Z coordinate"},
]


class OBAMainMirror:
    # ------------------------------------------------------------------
    # Construction objects belonging to this FeaturePython object
    #
    # Delete order is handled in ViewProvider.onDelete() using reversed()
    # so that Cut2 -> Cut1 -> ellipsoids/cube are removed safely.
    # ------------------------------------------------------------------

    CHILD_OBJECTS = ("_cube", "_ellipsoid_Left", "_ellipsoid_Right", "_cut1", "_cut2")

    def _init_runtime_state(self):
        self._initializing = True
        self._rebuilding = False

        self._suppress_onchange = False

        self._cube = None
        self._ellipsoid_Left = None
        self._ellipsoid_Right = None
        self._cut1 = None
        self._cut2 = None

    def __init__(self, obj):
        self._init_runtime_state()
        obj.Proxy = self
        self.Object = obj

        self._dialog = None

        # obj.setEditorMode("Placement", 1)

        install_properties(obj, MAIN_MIRROR_PROPERTIES)

        obj.addProperty("App::PropertyLinkList", "Group", "Base", "Owned children")

        if hasattr(obj, "FocusDistance"):
            obj.setEditorMode("FocusDistance", 1)
        make_calculated_length(obj, "Ellipsoid1FocusX", "X position of first ellipsoid focus")
        make_calculated_length(obj, "Ellipsoid2FocusX", "X position of second ellipsoid focus")
        make_calculated_length(obj, "MirrorPlaneX", "X coordinate of mirror symmetry plane")
        make_optical_type(obj, "MainMirror")
        self._initializing = False

    def delete(self):
        doc = self.Object.Document

        for attr_name in reversed(self.CHILD_OBJECTS):
            child = getattr(self, attr_name, None)

            if child and doc.getObject(child.Name):
                doc.removeObject(child.Name)

        if doc.getObject(self.Object.Name):
            doc.removeObject(self.Object.Name)

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
        doc = obj.Document
        self._cube = self._get_or_create(doc, f"{obj.Name}_Cube", "Part::Box", f"{obj.Label} Cube")
        self._ellipsoid_Left = self._get_or_create(doc, f"{obj.Name}_Ellipsoid1", "Part::Ellipsoid", f"{obj.Label} Ellipsoid 1")
        self._ellipsoid_Right = self._get_or_create(doc, f"{obj.Name}_Ellipsoid2", "Part::Ellipsoid", f"{obj.Label} Ellipsoid 2")
        self._cut1 = self._get_or_create(doc, f"{obj.Name}_Cut1", "Part::Cut", f"{obj.Label} Cut 1")
        self._cut2 = self._get_or_create(doc, f"{obj.Name}_Cut2", "Part::Cut", f"{obj.Label} Cut 2")

        children = [
            self._cube,
            self._ellipsoid_Left,
            self._ellipsoid_Right,
            self._cut1,
            self._cut2,
        ]
        set_property_if_changed(obj, "Group", children)

        set_property_if_changed(self._cut1, "Base", self._cube)
        set_property_if_changed(self._cut1, "Tool", self._ellipsoid_Left)

        set_property_if_changed(self._cut2, "Base", self._cut1)
        set_property_if_changed(self._cut2, "Tool", self._ellipsoid_Right)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _update_cube(self, obj):
        """
        Update the cube dimensions and apply the main object's Placement.

        The cube placement is defined locally around the Main Mirror
        origin and then transformed by obj.Placement.
        """
        width = float(obj.Width)
        height = float(obj.Height)

        # Keep enough depth for the ellipsoid geometry.
        depth = 1.0 * float(obj.B)

        changed = False
        changed |= set_quantity_if_changed(self._cube, "Length", width, "mm")
        changed |= set_quantity_if_changed(self._cube, "Width", depth, "mm")
        changed |= set_quantity_if_changed(self._cube, "Height", height, "mm")

        base = obj.Placement
        cube_local = App.Placement(App.Vector(-width / 2.0, float(obj.B * 0.4), -height / 2.0), App.Rotation())
        changed |= set_property_if_changed(self._cube, "Placement", base.multiply(cube_local))
        return changed

    def _update_ellipsoids(self, obj):
        """
        Update both ellipsoids.

        Their placements are defined locally relative to the Main Mirror
        object and then multiplied by obj.Placement.
        """
        split = float(obj.SplitOffset)

        a = float(obj.A)
        b = float(obj.B)

        radius3 = max(0.0, b - float(obj.Radius3Offset))

        tilt = float(obj.TiltAngle)

        tilt_offset = float(obj.TiltAngleOffset)

        # --------------------------------------------------------------
        # Left ellipsoid
        # --------------------------------------------------------------

        left = self._ellipsoid_Left
        changed = False

        changed |= set_quantity_if_changed(left, "Radius1", a, "mm")
        changed |= set_quantity_if_changed(left, "Radius2", b, "mm")
        changed |= set_quantity_if_changed(left, "Radius3", radius3, "mm")

        left_local = App.Placement()

        left_local.Base = App.Vector(-split / 2.0, b * 0, 0.0)
        rot1 = App.Rotation(App.Vector(1, 0, 0), 90)
        # rot2 = App.Rotation(App.Vector(0, 0, 1), 270 + tilt)

        rot2 = App.Rotation(App.Vector(0, 0, 1), 270 - (tilt + tilt_offset))

        left_local.Rotation = rot2.multiply(rot1)
        changed |= set_property_if_changed(left, "Placement", obj.Placement.multiply(left_local))
        # --------------------------------------------------------------
        # Right ellipsoid
        # --------------------------------------------------------------
        right = self._ellipsoid_Right

        changed |= set_quantity_if_changed(right, "Radius1", a, "mm")
        changed |= set_quantity_if_changed(right, "Radius2", b, "mm")
        changed |= set_quantity_if_changed(right, "Radius3", radius3, "mm")

        right_local = App.Placement()

        right_local.Base = App.Vector(split / 2.0, b * 0, 0.0)
        rot1 = App.Rotation(App.Vector(1, 0, 0), 90)
        rot2 = App.Rotation(App.Vector(0, 0, 1), 270 - tilt)

        right_local.Rotation = rot2.multiply(rot1)
        changed |= set_property_if_changed(right, "Placement", obj.Placement.multiply(right_local))
        return changed

    def _update_debug_visibility(self, obj):
        try:
            debug = bool(obj.ShowDebugEllipsoids)
            changed = False

            # Final result visible.
            changed |= set_property_if_changed(self._cube.ViewObject, "Visibility", False)
            changed |= set_property_if_changed(self._cut1.ViewObject, "Visibility", False)
            changed |= set_property_if_changed(self._cut2.ViewObject, "Visibility", True)

            if debug:
                changed |= set_property_if_changed(self._ellipsoid_Left.ViewObject, "Visibility", True)
                changed |= set_property_if_changed(self._ellipsoid_Right.ViewObject, "Visibility", True)

                changed |= set_property_if_changed(self._ellipsoid_Left.ViewObject, "ShapeColor", (1.0, 0.0, 0.0))
                changed |= set_property_if_changed(self._ellipsoid_Right.ViewObject, "ShapeColor", (0.0, 0.0, 1.0))

                changed |= set_property_if_changed(self._ellipsoid_Left.ViewObject, "Transparency", 80)
                changed |= set_property_if_changed(self._ellipsoid_Right.ViewObject, "Transparency", 80)
            else:
                changed |= set_property_if_changed(self._ellipsoid_Left.ViewObject, "Visibility", False)
                changed |= set_property_if_changed(self._ellipsoid_Right.ViewObject, "Visibility", False)
            return changed

        except Exception:
            return False

    # ------------------------------------------------------------------
    # Rebuild
    # ------------------------------------------------------------------

    def _rebuild(self, obj):
        """
        Rebuild the complete Main Mirror geometry immediately.
        """
        if self._rebuilding:
            return
        self._rebuilding = True

        try:
            changed = False
            changed |= self._update_ellipsoids(obj)
            changed |= self._update_cube(obj)

            changed |= self._update_debug_visibility(obj)

            c = focus_distance(float(obj.A), float(obj.B))

            changed |= set_quantity_if_changed(obj, "FocusDistance", c, "mm")
            changed |= set_quantity_if_changed(obj, "Ellipsoid1FocusX", -float(obj.SplitOffset) / 2.0, "mm")
            changed |= set_quantity_if_changed(obj, "Ellipsoid2FocusX", float(obj.SplitOffset) / 2.0, "mm")
            changed |= set_quantity_if_changed(obj, "MirrorPlaneX", 0.0, "mm")

            if changed and not self._suppress_onchange:
                obj.Document.recompute()
                pass

        finally:
            self._rebuilding = False

    # ------------------------------------------------------------------
    # Property changes
    # ------------------------------------------------------------------

    def onChanged(self, obj, prop):

        # print("MainMirror onChanged:", prop)

        IGNORE = {"Group", "Shape"}

        if prop in IGNORE:
            return

        if self._rebuilding:
            return
        if self._initializing:
            return

        if prop in {"ShowDebugEllipsoids"}:
            self._update_debug_visibility(obj)

        if self._suppress_onchange:
            return

        # App.Console.PrintMessage(f"onChanged: {prop}\n")

        if prop in {"Width", "Height", "SplitOffset", "A", "B", "Radius3Offset", "TiltAngle", "TiltAngleOffset", "ShowDebugEllipsoids"}:
            try:
                self._rebuild(obj)
            except Exception as exc:
                App.Console.PrintError(f"[OBA] Main Mirror rebuild failed: {exc}\n")

        if prop in ("Placement"):
            try:
                self._rebuild(obj)
            except Exception as exc:
                App.Console.PrintError("[OBA] Main Mirror placement update failed: " f"{exc}\n")

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
        self._initializing = True
        obj.Proxy = self
        self.Object = obj
        # obj.setEditorMode("Placement", 1)

        try:
            for legacy_property in ("UseIndependentRadius3", "B2"):
                if legacy_property in obj.PropertiesList:
                    obj.removeProperty(legacy_property)
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
            App.Console.PrintError("[OBA] Main Mirror restore rebuild failed: " f"{exc}\n")
        restore_view_provider(obj, MainMirrorViewProvider)

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


class MainMirrorDialog(OBAToolboxDialogBase):
    PROPERTY_DEFINITIONS = MAIN_MIRROR_PROPERTIES

    def __init__(self, obj, title="Main Mirror Settings", parent=None):
        super().__init__(obj, title=title, parent=parent)


# ======================================================================
# View Provider
# ======================================================================
class MainMirrorViewProvider(OBAToolboxViewProviderBase):

    dialog_class = MainMirrorDialog

    def __init__(self, vobj):
        super().__init__(vobj, MainMirrorDialog)

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

    def onDelete(self, vobj, subelements):
        obj = getattr(self, "Object", None)
        if obj is None:
            return True

        doc = obj.Document
        for child in getattr(obj, "Group", []):
            if child and doc.getObject(child.Name):
                doc.removeObject(child.Name)
        return True

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
            App.Console.PrintError("[OBA] Failed to open Main Mirror dialog: " f"{exc}\n")
            return False


# ======================================================================
# Factory
# ======================================================================


def OBA_CreateMainMirror(
    doc=None,
    label="Main_Mirror",
    width=100.0,
    height=33.0,
    split_offset=40.0,
    a=40.0,
    b=31.0,
    tiltangle=0.0,
    tiltangle_offset=0.0,
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
    if split_offset < 0 or split_offset > width:
        raise ValueError("SplitOffset must be between zero and Width.")
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

    obj = doc.addObject("Part::FeaturePython", "OBA_MainMirror")
    obj.Label = label
    proxy = OBAMainMirror(obj)
    proxy._initializing = True
    proxy._suppress_onchange = suppress_onchange

    obj.Width = width  # App.Units.Quantity(f"{width} mm")
    obj.Height = height  # App.Units.Quantity(f"{height} mm")
    obj.SplitOffset = split_offset  # App.Units.Quantity(f"{split_offset} mm")
    obj.A = a  # App.Units.Quantity(f"{a} mm")
    obj.B = b  # App.Units.Quantity(f"{b} mm")
    obj.Radius3Offset = radius3_offset
    obj.TiltAngle = tiltangle  # App.Units.Quantity(f"{tiltangle} deg")
    obj.TiltAngleOffset = tiltangle_offset  # App.Units.Quantity(f"{tiltangle_offset} deg")
    obj.Placement = App.Placement(App.Vector(x, y, z), App.Rotation())

    proxy._ensure_features(obj)

    proxy._initializing = False

    proxy._rebuild(obj)

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


def create(
    doc=None,
    label="Main_Mirror",
    width=100.0,
    height=30.0,
    split_offset=40.0,
    a=40.0,
    b=30.0,
    tiltangle=0.0,
    x=0.0,
    y=0.0,
    z=0.0,
    radius3_offset=0.0,
):
    return OBA_CreateMainMirror(
        doc=doc,
        label=label,
        width=width,
        height=height,
        split_offset=split_offset,
        a=a,
        b=b,
        radius3_offset=radius3_offset,
        tiltangle=tiltangle,
        x=x,
        y=y,
        z=z,
        show_dialog=False,
    )
