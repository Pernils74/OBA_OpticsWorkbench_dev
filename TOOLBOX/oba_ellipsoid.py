# oba_ellipsoid.py
#
# OBA Ellipsoid optical component.
#
#

import math


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
    validate_ellipsoid,
    ensure_debug_property,
    set_property_if_changed,
    set_quantity_if_changed,
)

# ============================================================
#  P R O P E R T I E S
# ============================================================


ELLIPSOID_PROPERTIES = [
    {"name": "A", "type": "App::PropertyLength", "group": "Ellipsoid", "unit": "mm", "min": 0, "max": 1_000_000, "doc": "Semi-major axis"},
    {"name": "B", "type": "App::PropertyLength", "group": "Ellipsoid", "unit": "mm", "min": 0, "max": 1_000_000, "doc": "Semi-minor axis"},
    {"name": "UseIndependentRadius3", "type": "App::PropertyBool", "group": "Ellipsoid", "doc": "Use independent radius in Y direction"},
    {"name": "B2", "type": "App::PropertyLength", "group": "Ellipsoid", "unit": "mm", "min": 0, "max": 1_000_000, "enabled_when": "UseIndependentRadius3", "doc": "Independent ellipsoid Y radius"},
    {"name": "WidthFactor", "type": "App::PropertyFloat", "group": "Ellipsoid", "default": 1.8, "min": 0.5, "max": 2, "step": 0.1},
    {"name": "FocusDistance", "type": "App::PropertyLength", "group": "Ellipsoid", "unit": "mm", "display_only": True, "doc": "Distance from ellipsoid centre to focus"},
    {"name": "ShowDebugEllipsoid", "type": "App::PropertyBool", "group": "Debug", "doc": "Show ellipsoid for debugging"},
    {"name": "ShowDebugFoci", "type": "App::PropertyBool", "group": "Debug", "doc": "Show focal points"},
    {"name": "APlaneWidth", "type": "App::PropertyLength", "group": "Box", "unit": "mm", "min": 0, "max": 100, "doc": "Aperture plane width"},
    {"name": "APlaneHeight", "type": "App::PropertyLength", "group": "Box", "unit": "mm", "min": 0, "max": 10, "doc": "Aperture plane height"},
    {"name": "APlaneZoffset", "type": "App::PropertyFloat", "group": "Box", "unit": "mm", "min": -2, "max": 5, "step": 0.1, "doc": "Additional Z offset from focus point"},
    {"name": "APlaneYoffset", "type": "App::PropertyFloat", "group": "Box", "unit": "mm", "min": -2, "max": 5, "step": 0.1, "doc": "Additional Y offset from focus point"},
    # --------------------------------------------------------
    # Orientation.
    # --------------------------------------------------------
    {"name": "RotX", "type": "App::PropertyAngle", "group": "Orientation", "unit": "deg", "min": -360, "max": 360, "enabled_when_not": "UseAimPoint", "doc": "Optical axis X rotation"},
    {"name": "RotY", "type": "App::PropertyAngle", "group": "Orientation", "unit": "deg", "min": -360, "max": 360, "readonly": True, "doc": "Optical axis Y rotation"},
    {"name": "RotZ", "type": "App::PropertyAngle", "group": "Orientation", "unit": "deg", "min": -360, "max": 360, "enabled_when_not": "UseAimPoint", "doc": "Optical axis Z rotation"},
    {"name": "UseAimPoint", "type": "App::PropertyBool", "group": "Orientation", "doc": "Aim the optical axis at a point"},
    {"name": "AimX", "type": "App::PropertyFloat", "group": "Orientation", "unit": "mm", "min": -1_000_000, "max": 1_000_000, "enabled_when": "UseAimPoint", "doc": "Target X coordinate"},
    {"name": "AimY", "type": "App::PropertyFloat", "group": "Orientation", "unit": "mm", "min": -1_000_000, "max": 1_000_000, "enabled_when": "UseAimPoint", "doc": "Target Y coordinate"},
    {"name": "AimZ", "type": "App::PropertyFloat", "group": "Orientation", "unit": "mm", "min": -1_000_000, "max": 1_000_000, "enabled_when": "UseAimPoint", "doc": "Target Z coordinate"},
    {"name": "PosX", "type": "App::PropertyFloat", "group": "Placement", "unit": "mm", "min": -1_000_000, "max": 1_000_000, "doc": "X coordinate"},
    {"name": "PosY", "type": "App::PropertyFloat", "group": "Placement", "unit": "mm", "min": -1_000_000, "max": 1_000_000, "doc": "Y coordinate"},
    {"name": "PosZ", "type": "App::PropertyFloat", "group": "Placement", "unit": "mm", "min": -1_000_000, "max": 1_000_000, "doc": "Z coordinate"},
]


# ============================================================
#  O B J E C T
# ============================================================


class OBAEllipsoid:

    CHILD_OBJECTS = ("_box", "_box_ext", "_box_bound", "_fuse", "_ellipsoid", "_cut", "_focus1", "_focus2", "_focal_surface")

    def _init_runtime_state(self):
        """
        Initialise all Python-only runtime references.
        These references are not persisted by FreeCAD and therefore must
        also be recreated when a document is restored.
        """
        self._initializing = True
        self._rebuilding = False

        self._syncing_orientation = False
        self._suppress_onchange = False

        self._ellipsoid = None
        self._focus1 = None
        self._focus2 = None
        self._focal_surface = None
        self._focal_surface_signature = None

        self._box = None
        self._box_ext = None
        self._fuse = None
        self._box_bound = None
        self._cut = None

    def __init__(self, obj):
        self._init_runtime_state()
        obj.Proxy = self
        self.Object = obj

        install_properties(obj, ELLIPSOID_PROPERTIES)
        obj.addProperty("App::PropertyLinkList", "Group", "Base", "Owned children")
        # ensure_debug_property(obj)
        make_calculated_length(obj, "FocusDistance", "Distance from ellipsoid centre to focus")

        make_optical_type(obj, "Ellipsoid")

        self._initializing = False

        # self._ensure_features(obj)

    def delete(self):
        doc = self.Object.Document

        for attr_name in reversed(self.CHILD_OBJECTS):
            child = getattr(self, attr_name, None)

            if child and doc.getObject(child.Name):
                doc.removeObject(child.Name)

        if doc.getObject(self.Object.Name):
            doc.removeObject(self.Object.Name)

    @staticmethod
    def _obj_exists(obj):
        if obj is None:
            return False

        try:
            return obj.Document is not None and obj.Document.getObject(obj.Name) is obj
        except Exception:
            return False

    # ========================================================
    #  E N S U R E   F E A T U R E S
    # ========================================================

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

        # --------------------------------------------------------------
        # Construction geometry
        # --------------------------------------------------------------

        self._box = self._get_or_create(doc, f"{obj.Name}_Box", "Part::Box", f"{obj.Label} Box")
        self._box_ext = self._get_or_create(doc, f"{obj.Name}_BoxExt", "Part::Box", f"{obj.Label} BoxExt")
        self._box_bound = self._get_or_create(doc, f"{obj.Name}_BoxBound", "Part::Box", f"{obj.Label} BoxBound")
        self._fuse = self._get_or_create(doc, f"{obj.Name}_Fuse", "Part::Fuse", f"{obj.Label} Fuse")
        self._ellipsoid = self._get_or_create(doc, f"{obj.Name}_Ellipsoid", "Part::Ellipsoid", f"{obj.Label} Ellipsoid")
        self._cut = self._get_or_create(doc, f"{obj.Name}_Cut", "Part::Cut", f"{obj.Label} Cut")
        self._focal_surface = self._get_or_create(doc, f"{obj.Name}_FocalSurface", "Part::Feature", f"{obj.Label} FOCAL--SURFACE")

        self._focus1 = self._get_or_create(doc, f"{obj.Name}_Focus1", "Part::Sphere", f"{obj.Label} Focus1")
        self._focus2 = self._get_or_create(doc, f"{obj.Name}_Focus2", "Part::Sphere", f"{obj.Label} Focus2")

        children = [
            self._box,
            self._box_ext,
            self._box_bound,
            self._fuse,
            self._ellipsoid,
            self._cut,
            self._focal_surface,
            self._focus1,
            self._focus2,
        ]
        changed = set_property_if_changed(obj, "Group", children)

        # --------------------------------------------------------------
        # One-time visual settings
        # --------------------------------------------------------------

        changed |= set_property_if_changed(self._box_bound.ViewObject, "DisplayMode", "Wireframe")

        changed |= set_property_if_changed(self._ellipsoid.ViewObject, "ShapeColor", (0.7, 0.8, 1.0))
        changed |= set_property_if_changed(self._ellipsoid.ViewObject, "Transparency", 80)

        vo = self._focal_surface.ViewObject
        changed |= set_property_if_changed(vo, "ShapeColor", (1.0, 1.0, 0.0))
        changed |= set_property_if_changed(vo, "Transparency", 50)
        changed |= set_property_if_changed(vo, "LineWidth", 2)

        # --------------------------------------------------------------
        # Boolean relationship
        # --------------------------------------------------------------

        changed |= set_property_if_changed(self._fuse, "Base", self._box)
        changed |= set_property_if_changed(self._fuse, "Tool", self._box_ext)

        changed |= set_property_if_changed(self._cut, "Base", self._fuse)
        changed |= set_property_if_changed(self._cut, "Tool", self._ellipsoid)
        return changed

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

        changed = False
        changed |= set_quantity_if_changed(self._focus1, "Radius", 1, "mm")
        changed |= set_quantity_if_changed(self._focus2, "Radius", 1, "mm")

        focus1_placement = App.Placement(f1, self._focus1.Placement.Rotation)
        focus2_placement = App.Placement(f2, self._focus2.Placement.Rotation)
        changed |= set_property_if_changed(self._focus1, "Placement", focus1_placement)
        changed |= set_property_if_changed(self._focus2, "Placement", focus2_placement)

        changed |= set_property_if_changed(self._focus1.ViewObject, "ShapeColor", (0.0, 1.0, 0.0))
        changed |= set_property_if_changed(self._focus2.ViewObject, "ShapeColor", (1.0, 0.0, 0.0))
        return changed

    def _update_ellipsoid(self, obj):
        changed = self._ensure_features(obj)
        ellipsoid = self._ellipsoid

        if ellipsoid is None:
            return changed
        a = float(obj.A)
        b = float(obj.B)

        # guard emot felaktiva a och b värden
        if a <= 0 or b <= 0:
            return changed

        if obj.UseIndependentRadius3:
            b2 = float(obj.B2)
        else:
            b2 = b

        if b2 <= 0:
            return changed

        validate_ellipsoid(a, b, b2)
        c = focus_distance(a, b)

        # ----------------------------------------------------
        # FreeCAD Part::Ellipsoid parameters.
        #
        # Radius1 = major axis
        # Radius2 = first minor axis
        # Radius3 = second minor axis
        # ----------------------------------------------------

        changed |= set_quantity_if_changed(ellipsoid, "Radius1", a, "mm")
        changed |= set_quantity_if_changed(ellipsoid, "Radius2", b, "mm")
        changed |= set_quantity_if_changed(ellipsoid, "Radius3", b2, "mm")

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
        rotz = App.Rotation(App.Vector(0, 0, -1), float(obj.RotZ))

        rotation = rot0
        rotation = rotx.multiply(rotation)  # Rotera X *efter* rot0
        rotation = roty.multiply(rotation)  # Rotera Y *efter* det
        rotation = rotz.multiply(rotation)  # Rotera Z *sist*

        center_offset = rotation.multVec(App.Vector(0, 0, c))

        local = App.Placement(center_offset, rotation)
        changed |= set_property_if_changed(ellipsoid, "Placement", obj.Placement.multiply(local))

        # ellipsoid.Placement = App.Placement(obj.Placement.Base + center_offset, rotation)

        changed |= self.show_foci(obj)

        changed |= set_quantity_if_changed(obj, "FocusDistance", c, "mm")
        return changed

    def _update_cubes(self, obj):

        # nedan ger skopans längd
        length = float(obj.A * 0.8) + float(obj.A * 0.5) * math.sin(math.radians(obj.RotX))  # är omkastad enligt mitt orienteringssätt

        height = float(obj.B * 1.2)  # är omkastad enligt mitt orienteringssätt
        width = float(obj.B * obj.WidthFactor)  # 1.8)

        changed = False
        changed |= set_quantity_if_changed(self._box, "Length", width, "mm")
        changed |= set_quantity_if_changed(self._box, "Width", length, "mm")
        changed |= set_quantity_if_changed(self._box, "Height", height, "mm")

        # rot0 = App.Rotation(App.Vector(0, 0, 1), 90)  # rot i z för att Length skall bli i yaxeln
        # obj.RotX = 0

        rotx = App.Rotation(App.Vector(1, 0, 0), obj.RotX)  # roterar upp efter den optiska axeln i elipsoiden
        rotz = App.Rotation(App.Vector(0, 0, -1), obj.RotZ)
        rot = rotz.multiply(rotx)

        posX = float(obj.PosX) - (width / 2) * math.cos(math.radians(obj.RotZ))
        posY = float(obj.PosY) + (width / 2) * math.sin(math.radians(obj.RotZ))
        posZ = float(obj.PosZ)

        local = App.Placement(App.Vector(posX, posY, posZ), rot)  # centrerar den kring elipsoidens optiska centrum

        # local = App.Placement(App.Vector(-(width / 2), 0, 0), rot)  # centrerar den kring elipsoidens optiska centrum
        changed |= set_property_if_changed(self._box, "Placement", obj.Placement.multiply(local))

        # -----------------------------------
        # Extension box = den förlängning som skall kunna skära i comp mirror
        # -----------------------------------
        changed |= set_quantity_if_changed(self._box_ext, "Height", float(height * math.cos(math.radians(obj.RotX))), "mm")
        changed |= set_quantity_if_changed(self._box_ext, "Width", width, "mm")

        # c = focus_distance(obj.A, obj.B)
        # self._box_ext.Length = float(height * math.sin(math.radians(obj.RotX))) + (float(obj.A) - c) * 2  # lägger till det som fattas ifrån c + lite till
        changed |= set_quantity_if_changed(self._box_ext, "Length", float(obj.B) * 2.5, "mm")
        rot_ext_0 = App.Rotation(App.Vector(0, 0, 1), (-90))  # för att Length skall peka i -y
        rot_ext_z = App.Rotation(App.Vector(0, 0, -1), obj.RotZ)
        rot_ext = rot_ext_0.multiply(rot_ext_z)

        local_ext = App.Placement(App.Vector(posX, posY, posZ), rot_ext)  # justeras emot elipsoidens fokal centrum
        changed |= set_property_if_changed(self._box_ext, "Placement", obj.Placement.multiply(local_ext))

        # -----------------------------------
        # Bounding box = Bounding box som kan användas som cut.
        # -----------------------------------

        changed |= set_quantity_if_changed(self._box_bound, "Width", width, "mm")
        changed |= set_quantity_if_changed(self._box_bound, "Height", float(self._box_ext.Height) + float(length * math.sin(math.radians(obj.RotX))), "mm")
        changed |= set_quantity_if_changed(self._box_bound, "Length", float(self._box_ext.Length) + float(length * math.cos(math.radians(obj.RotX))), "mm")

        base_pos = App.Vector(posX, posY, posZ)
        offset_local = App.Vector(-float(length * math.cos(math.radians(obj.RotX))), 0, 0)
        offset_world = rot_ext.multVec(offset_local)
        local_bound = App.Placement(base_pos + offset_world, rot_ext)
        changed |= set_property_if_changed(self._box_bound, "Placement", obj.Placement.multiply(local_bound))
        return changed

    def _update_focal_surface(self, obj):
        import Part

        width = float(obj.APlaneWidth)
        height = float(obj.APlaneHeight)

        f1, f2 = self.focal_points_world(obj)

        # emitterytan ligger i första fokus
        focus = f1

        p1 = App.Vector(-width / 2, -height / 2 + obj.APlaneYoffset, obj.APlaneZoffset)
        p2 = App.Vector(+width / 2, -height / 2 + obj.APlaneYoffset, obj.APlaneZoffset)
        p3 = App.Vector(+width / 2, +height / 2 + obj.APlaneYoffset, obj.APlaneZoffset)
        p4 = App.Vector(-width / 2, +height / 2 + obj.APlaneYoffset, obj.APlaneZoffset)

        signature = tuple(round(float(value), 9) for point in (p1, p2, p3, p4) for value in (focus.x + point.x, focus.y + point.y, focus.z + point.z))
        if signature == getattr(self, "_focal_surface_signature", None):
            return False

        wire = Part.makePolygon([p1, p2, p3, p4, p1])
        face = Part.Face(wire)

        face.Placement = App.Placement(focus, App.Rotation())
        # face.Placement = App.Placement(focus, self._ellipsoid.Placement.Rotation) # vinkel rätt emot den optiska axeln

        self._focal_surface.Shape = face
        self._focal_surface_signature = signature
        return True

    # ========================================================
    #  R E B U I L D
    # ========================================================

    def _rebuild(self, obj):
        if self._rebuilding:
            return
        self._rebuilding = True
        try:
            changed = False
            changed |= self._update_ellipsoid(obj)
            changed |= self._update_cubes(obj)
            changed |= self._update_focal_surface(obj)

            changed |= self._update_debug(obj)

            if changed and not self._suppress_onchange:
                obj.Document.recompute()
                pass

        finally:
            self._rebuilding = False

    # ========================================================

    def _update_debug(self, obj):
        changed = False
        if self._ellipsoid:
            changed |= set_property_if_changed(self._ellipsoid.ViewObject, "Visibility", bool(obj.ShowDebugEllipsoid))

        if self._focus1:
            changed |= set_property_if_changed(self._focus1.ViewObject, "Visibility", bool(obj.ShowDebugFoci))

        if self._focus2:
            changed |= set_property_if_changed(self._focus2.ViewObject, "Visibility", bool(obj.ShowDebugFoci))
        return changed

    def synchronize_aim_from_rotation(self, obj):
        f1, f2 = self.focal_points_world(obj)
        set_property_if_changed(obj, "AimX", f2.x)
        set_property_if_changed(obj, "AimY", f2.y)
        set_property_if_changed(obj, "AimZ", f2.z)

    def synchronize_rotation_from_aim(self, obj):
        target = App.Vector(float(obj.AimX), float(obj.AimY), float(obj.AimZ))
        direction = target - obj.Placement.Base

        if direction.Length == 0:
            return

        import math

        # 1. Beräkna RotX (Pitch) FÖRST eftersom ellipsoiden applicerar rotx först.
        # När RotZ ännu inte har applicerats, tittar vi på vinkeln i det fasta globala YZ-planet.
        # Avståndet i YZ-planet (hypotenusan för höjden innan Z-vridning)
        yz_distance = math.hypot(direction.y, direction.z)

        # Om målet är i Y+ (rakt fram) och går upp i Z+
        rx_rad = math.atan2(direction.z, direction.y)
        rx = math.degrees(rx_rad)

        # 2. Ingen inneboende roll (RotY)
        ry = 0.0

        # 3. Beräkna RotZ (Yaw) SIST.
        # Eftersom ellipsoiden först roterar runt X (vilket tippar Y-axeln upp/ner i Z-led),
        # blir det faktiska "framåt"-avståndet i det nya systemet yz_distance.
        rz_rad = math.atan2(direction.x, yz_distance)
        rz = math.degrees(rz_rad)

        # print(f"Matchad med ellipsoiden -> RotX: {rx:.2f}°, RotY: {ry:.2f}°, RotZ: {rz:.2f}°")

        # 4. Tilldela till objektet
        set_quantity_if_changed(obj, "RotX", rx, "deg")
        set_quantity_if_changed(obj, "RotY", ry, "deg")
        set_quantity_if_changed(obj, "RotZ", rz, "deg")

    # ========================================================
    #  C H A N G E D
    # ========================================================

    def onChanged(self, obj, prop):

        # print("MainMirror onChanged:", prop)

        if prop == "Shape":
            return

        if prop == "Group":
            return

        if self._rebuilding:
            return

        if self._syncing_orientation:
            return

        if self._initializing:
            return

        # ----------------------------------------------------
        # Debug visibility.
        # ----------------------------------------------------
        if prop in {"ShowDebugEllipsoid", "ShowDebugFoci"}:
            self._update_debug(obj)

        if self._suppress_onchange:
            return

        # print("----------------")
        # print(f"onChanged: {prop}, rebuilding={self._rebuilding}, syncing_ori={self._syncing_orientation} , init={self._initializing}", obj.UseAimPoint)
        # print("value =", getattr(obj, prop))

        # ----------------------------------------------------
        # Geometry
        # ----------------------------------------------------
        if prop in ("A", "B", "UseIndependentRadius3", "B2", "APlaneWidth", "APlaneHeight", "WidthFactor", "APlaneZoffset", "APlaneYoffset"):
            try:
                self._rebuild(obj)
            except Exception as exc:
                App.Console.PrintError("[OBA] Ellipsoid rebuild failed: " f"{exc}\n")
        # ----------------------------------------------------
        # Orientation.
        # ----------------------------------------------------

        if prop in ("RotX", "RotY", "RotZ") and not obj.UseAimPoint:
            self._syncing_orientation = True
            try:
                self._rebuild(obj)
                self.synchronize_aim_from_rotation(obj)
                # print("Aim coords", obj.AimX, obj.AimY, obj.AimZ)
            finally:
                dialog = getattr(self, "_dialog", None)
                if dialog:
                    dialog.refresh_from_object()
                self._syncing_orientation = False

        if prop in ("AimX", "AimY", "AimZ") and obj.UseAimPoint:
            self._syncing_orientation = True
            try:
                self.synchronize_rotation_from_aim(obj)
                dialog = getattr(self, "_dialog", None)
                if dialog:
                    dialog.refresh_from_object()
                self._rebuild(obj)
            finally:
                # dialog = getattr(self, "_dialog", None)
                # dialog.refresh_from_object()

                self._syncing_orientation = False

        # ----------------------------------------------------
        # Main placement changed.
        # ----------------------------------------------------
        if prop == "Placement":
            try:
                self._rebuild(obj)
            except Exception as exc:
                App.Console.PrintError("[OBA] Ellipsoid placement update failed: " f"{exc}\n")

        # dialog = getattr(self, "_dialog", None)
        # if dialog:
        #     dialog.refresh_from_object()

    # ========================================================
    #  R E S T O R E
    # ========================================================

    def onDocumentRestored(self, obj):
        self._init_runtime_state()
        obj.Proxy = self
        self.Object = obj
        install_properties(obj, ELLIPSOID_PROPERTIES)
        ensure_debug_property(obj)
        make_calculated_length(obj, "FocusDistance", "Distance from ellipsoid centre to focus")
        self._initializing = False
        self._ensure_features(obj)
        try:
            if obj.UseAimPoint:
                self.synchronize_rotation_from_aim(obj)
            else:
                self.synchronize_aim_from_rotation(obj)
            self._rebuild(obj)
        except Exception as exc:
            App.Console.PrintError(f"[OBA] Ellipsoid restore rebuild failed: {exc}\n")
        restore_view_provider(obj, EllipsoidViewProvider)

    # ========================================================
    #  S T A T E
    # ========================================================

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        self._init_runtime_state()
        # return None


# ============================================================
#  D I A L O G
# ============================================================


class EllipsoidDialog(OBAToolboxDialogBase):
    ALLOW_SURFACE_SELECTION = False
    PROPERTY_DEFINITIONS = ELLIPSOID_PROPERTIES

    def __init__(self, obj, title="Ellipsoid Settings", parent=None):
        super().__init__(obj, title=title, parent=parent)


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


def OBA_CreateEllipsoid(
    doc=None,
    label="Ellipsoid",
    aplanewidth=3,
    aplaneheight=3,
    aplaneZoffset=0,
    aplaneYoffset=0,
    a=15.0,
    b=6.0,
    b2=None,
    use_b2=False,
    widthfactor=1.8,
    rot_x=30,
    rot_y=0,
    rot_z=0,
    x=0,
    y=0,
    z=0,
    suppress_onchange=False,
    show_dialog=True,
):
    doc = doc or App.ActiveDocument or App.newDocument()
    if b2 is None:
        b2 = b
        use_b2 = False
    else:
        use_b2 = True
    # validate_ellipsoid(a, b, b2)
    obj = doc.addObject("Part::FeaturePython", "OBAEllipsoid")

    obj.Label = label

    proxy = OBAEllipsoid(obj)

    proxy._initializing = True
    proxy._suppress_onchange = suppress_onchange

    obj.APlaneWidth = aplanewidth  # App.Units.Quantity(f"{aplanewidth} mm")
    obj.APlaneHeight = aplaneheight  # App.Units.Quantity(f"{aplaneheight} mm")

    obj.APlaneZoffset = aplaneZoffset
    obj.APlaneYoffset = aplaneYoffset

    obj.A = a  # App.Units.Quantity(f"{a} mm")
    obj.B = b  # App.Units.Quantity(f"{b} mm")

    obj.UseIndependentRadius3 = use_b2
    obj.B2 = b2  # App.Units.Quantity(f"{b2} mm")

    obj.WidthFactor = float(widthfactor)

    obj.RotX = rot_x  # App.Units.Quantity(f"{rot_x} deg")
    obj.RotY = rot_y  # App.Units.Quantity(f"{rot_y} deg")
    obj.RotZ = rot_z  # App.Units.Quantity(f"{rot_z} deg")

    obj.UseAimPoint = False

    obj.AimX = 0  # App.Units.Quantity("100 mm")
    obj.AimY = 0  # App.Units.Quantity("0 mm")
    obj.AimZ = 0  # App.Units.Quantity("0 mm")

    proxy._ensure_features(obj)
    proxy._update_ellipsoid(obj)
    proxy.synchronize_aim_from_rotation(obj)  # för att sätta korrekta värden direkt

    # obj.ShowDebugEllipsoid = False
    obj.FocusDistance = focus_distance(float(a), float(b))

    # --------------------------------------------------------
    # Build the real Part::Ellipsoid once everything is ready.
    # --------------------------------------------------------

    obj.Placement = App.Placement(App.Vector(x, y, z), App.Rotation())

    proxy._ensure_features(obj)

    proxy._initializing = False
    proxy._rebuild(obj)
    # proxy._update_cubes(obj)
    # proxy._update_ellipsoid(obj)

    if App.GuiUp:
        EllipsoidViewProvider(obj.ViewObject)

    # doc.recompute()

    if show_dialog:
        EllipsoidDialog(obj).show()
    return obj


def create(
    doc=None,
    label="Ellipsoid",
    aplanewidth=5,
    aplaneheight=5,
    aplaneZoffset=0,
    aplaneYoffset=0,
    a=40.0,
    b=20.0,
    b2=None,
    widthfactor=1.8,
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
        aplanewidth=aplanewidth,
        aplaneheight=aplaneheight,
        aplaneZoffset=aplaneZoffset,
        aplaneYoffset=aplaneYoffset,
        a=a,
        b=b,
        b2=b2,
        widthfactor=widthfactor,
        rot_x=rot_x,
        rot_y=rot_y,
        rot_z=rot_z,
        x=x,
        y=y,
        z=z,
        show_dialog=False,
    )
