# oba_ellipsoid.py
#
# OBA Ellipsoid optical component.
#
#

import math
import time

import FreeCAD as App
import FreeCADGui as Gui

# from oba_objects.oba_base import OBAElementProxy

from .oba_toolbox_base import (
    OBAToolboxDialogBase,
    OBAToolboxViewProviderBase,
    OBAToolboxProxyBase,
    focus_distance,
    install_properties,
    make_calculated_length,
    make_optical_type,
    restore_view_provider,
    validate_ellipsoid,
    ensure_debug_property,
    set_property_if_changed,
    set_quantity_if_changed,
    rename_property,
)

from OPTIMIZER.optimize_worker import is_optimization_running

# ============================================================
#  P R O P E R T I E S
# ============================================================


ELLIPSOID_PROPERTIES = [
    {"name": "A_", "type": "App::PropertyLength", "group": "Ellipsoid", "unit": "mm", "min": 0, "max": 1_000_000, "doc": "Semi-major axis"},
    {"name": "B_", "type": "App::PropertyLength", "group": "Ellipsoid", "unit": "mm", "min": 0, "max": 1_000_000, "doc": "Semi-minor axis"},
    {"name": "Radius3Offset", "label": "--Radius3 Offset", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 0.0, "unit": "mm", "min": 0, "max": 1000, "doc": "Amount subtracted from Radius2 (B) to produce Radius3"},
    {"name": "WallThickness", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 1.0, "unit": "mm", "min": 0, "max": 100},
    # WidthFactor
    {"name": "WidthFactor", "type": "App::PropertyFloat", "group": "Ellipsoid", "default": 1.7, "min": 0, "max": 2, "step": 0.1},
    {"name": "FocusDistance", "type": "App::PropertyLength", "group": "Ellipsoid", "unit": "mm", "display_only": True, "doc": "Distance from ellipsoid centre to focus"},
    {"name": "OffsetX", "type": "App::PropertyFloat", "group": "Ellipsoid", "unit": "", "min": -10, "max": 10, "doc": "Offset in X", "step": 0.1},
    {"name": "OffsetY", "type": "App::PropertyFloat", "group": "Ellipsoid", "unit": "", "min": -10, "max": 10, "doc": "Offset in Y", "step": 0.1},
    {"name": "OffsetZ", "type": "App::PropertyFloat", "group": "Ellipsoid", "unit": "", "min": -10, "max": 10, "doc": "Offset in Y", "step": 0.1},
    #
    {"name": "ShowDebugEllipsoid", "type": "App::PropertyBool", "group": "Debug", "doc": "Show ellipsoid for debugging"},
    {"name": "ShowDebugFoci", "type": "App::PropertyBool", "group": "Debug", "doc": "Show focal points"},
    #
    {"name": "APlaneWidth", "type": "App::PropertyLength", "group": "Aperture Plane", "unit": "mm", "min": 0, "max": 100, "doc": "Aperture plane width"},
    {"name": "APlaneHeight", "type": "App::PropertyLength", "group": "Aperture Plane", "unit": "mm", "min": 0, "max": 10, "doc": "Aperture plane height"},
    # {"name": "APlaneZoffset", "type": "App::PropertyFloat", "group": "Aperture Plane", "unit": "", "min": -2, "max": 5, "step": 0.1, "doc": "Additional Z offset from focus point"},
    # {"name": "APlaneYoffset", "type": "App::PropertyFloat", "group": "Aperture Plane", "unit": "", "min": -2, "max": 5, "step": 0.1, "doc": "Additional Y offset from focus point"},
    {"name": "FilterPlaneSize", "type": "App::PropertyLength", "group": "Filter", "default": 2.0, "unit": "mm", "min": 0, "max": 100, "doc": "Square filter side length"},
    {"name": "FilterPlaneOffset", "type": "App::PropertyFloat", "group": "Filter", "default": 0.5, "unit": "", "min": -50, "max": 50, "step": 0.1, "doc": "Offset from aperture plane along optical axis"},
    # --------------------------------------------------------
    # Orientation.
    # --------------------------------------------------------
    {"name": "RotX", "type": "App::PropertyAngle", "group": "Orientation", "unit": "deg", "default": 0.0, "min": -360, "max": 360, "enabled_when_not": "UseAimPoint", "doc": "Optical axis X rotation"},
    # {"name": "RotY", "type": "App::PropertyAngle", "group": "Orientation", "unit": "deg", "min": -360, "max": 360, "readonly": True, "doc": "Optical axis Y rotation"},
    {"name": "RotZ", "type": "App::PropertyAngle", "group": "Orientation", "unit": "deg", "default": 0.0, "min": -360, "max": 360, "enabled_when_not": "UseAimPoint", "doc": "Optical axis Z rotation"},
    {"name": "UseAimPoint", "type": "App::PropertyBool", "group": "Orientation", "doc": "Aim the optical axis at a point"},
    {"name": "AimX", "type": "App::PropertyFloat", "group": "Orientation", "unit": "mm", "min": -1_000_000, "max": 1_000_000, "enabled_when": "UseAimPoint", "doc": "Target X coordinate"},
    {"name": "AimY", "type": "App::PropertyFloat", "group": "Orientation", "unit": "mm", "min": -1_000_000, "max": 1_000_000, "enabled_when": "UseAimPoint", "doc": "Target Y coordinate"},
    {"name": "AimZ", "type": "App::PropertyFloat", "group": "Orientation", "unit": "mm", "min": -1_000_000, "max": 1_000_000, "enabled_when": "UseAimPoint", "doc": "Target Z coordinate"},
    # {"name": "PosX", "type": "App::PropertyFloat", "group": "Placement", "unit": "mm", "min": -1_000_000, "max": 1_000_000, "doc": "X coordinate"},
    # {"name": "PosY", "type": "App::PropertyFloat", "group": "Placement", "unit": "mm", "min": -1_000_000, "max": 1_000_000, "doc": "Y coordinate"},
    # {"name": "PosZ", "type": "App::PropertyFloat", "group": "Placement", "unit": "mm", "min": -1_000_000, "max": 1_000_000, "doc": "Z coordinate"},
]


# ============================================================
#  O B J E C T
# ============================================================


class OBAEllipsoid(OBAToolboxProxyBase):

    # CHILD_OBJECTS = ("_box", "_box_ext", "_box_bound", "_fuse", "_ellipsoid_inner", "_cut", "_focus1", "_focus2", "_focal_surface", "_filter_surface")
    CHILD_OBJECTS = (
        "_ellipsoid_bound",
        "_ellipsoid_outer",
        "_ellipsoid_inner",
        "_cut",
        "_opening_box_pos",
        "_opening_cut1",
        "_opening_box_neg",
        "_opening_cut2",
        "_split_box",
        "_split_cut",
        "_focus1",
        "_focus2",
        "_focal_surface",
        "_filter_surface",
    )

    def _init_runtime_state(self):
        """
        Initialise all Python-only runtime references.
        These references are not persisted by FreeCAD and therefore must
        also be recreated when a document is restored.
        """
        self._initializing = True
        self._rebuilding = False
        self._dirty = False
        self._sync_aim_after_rebuild = False
        self._sync_rotation_before_rebuild = False

        self._syncing_orientation = False
        self._suppress_onchange = False

        self._ellipsoid_bound = None
        self._ellipsoid_outer = None
        self._ellipsoid_inner = None
        self._focus1 = None
        self._focus2 = None
        self._focal_surface = None
        self._filter_surface = None
        self._focal_surface_signature = None
        self._filter_surface_signature = None

        self._cut = None
        self._opening_box_pos = None
        self._opening_box_neg = None
        self._opening_cut1 = None
        self._opening_cut2 = None

        self._split_box = None
        self._split_cut = None

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

        self._ellipsoid_bound = self._get_or_create(doc, f"{obj.Name}_EllipsoidBound", "Part::Ellipsoid", f"{obj.Label} Ellipsoid_bound")
        self._ellipsoid_outer = self._get_or_create(doc, f"{obj.Name}_EllipsoidOuter", "Part::Ellipsoid", f"{obj.Label} Ellipsoid_outer")

        changed = set_property_if_changed(self._ellipsoid_outer, "Angle2", 15)

        self._ellipsoid_inner = self._get_or_create(doc, f"{obj.Name}_EllipsoidInner", "Part::Ellipsoid", f"{obj.Label} Ellipsoid")
        self._cut = self._get_or_create(doc, f"{obj.Name}_Cut", "Part::Cut", f"{obj.Label} Cut")

        self._focal_surface = self._get_or_create(doc, f"{obj.Name}_FocalSurface", "Part::Feature", f"{obj.Label} FOCAL--SURFACE")
        self._filter_surface = self._get_or_create(doc, f"{obj.Name}_FilterSurface", "Part::Feature", f"{obj.Label} FILTER-SURFACE")
        # self._focal_surface.ViewObject.Visibility = True
        # self._filter_surface.ViewObject.Visibility = True

        self._focus1 = self._get_or_create(doc, f"{obj.Name}_Focus1", "Part::Sphere", f"{obj.Label} Focus1")
        self._focus2 = self._get_or_create(doc, f"{obj.Name}_Focus2", "Part::Sphere", f"{obj.Label} Focus2")

        self._cut.Base = self._ellipsoid_outer
        self._cut.Tool = self._ellipsoid_inner

        self._split_box = self._get_or_create(doc, f"{obj.Name}_SplitBox", "Part::Box", f"{obj.Label} Split Box")
        self._split_cut = self._get_or_create(doc, f"{obj.Name}_SplitCut", "Part::Cut", f"{obj.Label} Split Cut")

        self._split_cut.Base = self._cut
        self._split_cut.Tool = self._split_box

        # för att skala bort sidorna
        self._opening_box_pos = self._get_or_create(doc, f"{obj.Name}_OpeningBoxPos", "Part::Box", f"{obj.Label} Opening Box Pos")
        self._opening_cut1 = self._get_or_create(doc, f"{obj.Name}_OpeningCut1", "Part::Cut", f"{obj.Label} Opening Cut1")

        self._opening_cut1.Base = self._split_cut
        self._opening_cut1.Tool = self._opening_box_pos

        self._opening_box_neg = self._get_or_create(doc, f"{obj.Name}_OpeningBoxNeg", "Part::Box", f"{obj.Label} Opening Box Neg")
        self._opening_cut2 = self._get_or_create(doc, f"{obj.Name}_OpeningCut2", "Part::Cut", f"{obj.Label} Opening Cut2")

        self._opening_cut2.Base = self._opening_cut1
        self._opening_cut2.Tool = self._opening_box_neg

        children = [
            self._ellipsoid_bound,
            self._ellipsoid_outer,
            self._ellipsoid_inner,
            self._cut,
            self._split_box,
            self._split_cut,
            self._focal_surface,
            self._filter_surface,
            self._focus1,
            self._focus2,
            self._opening_box_pos,
            self._opening_cut1,
            self._opening_box_neg,
            self._opening_cut2,
        ]
        changed = set_property_if_changed(obj, "Group", children)

        # --------------------------------------------------------------
        # One-time visual settings
        # --------------------------------------------------------------

        changed |= set_property_if_changed(self._ellipsoid_bound.ViewObject, "ShapeColor", (0.7, 0.3, 0.7))
        changed |= set_property_if_changed(self._ellipsoid_bound.ViewObject, "Transparency", 85)
        # changed |= set_property_if_changed(self._ellipsoid_bound.ViewObject, "Visibility", False)

        changed |= set_property_if_changed(self._ellipsoid_inner.ViewObject, "ShapeColor", (0.7, 0.8, 1.0))
        changed |= set_property_if_changed(self._ellipsoid_inner.ViewObject, "Transparency", 80)

        vo = self._focal_surface.ViewObject
        changed |= set_property_if_changed(vo, "ShapeColor", (1.0, 1.0, 0.0))
        changed |= set_property_if_changed(vo, "Transparency", 50)
        changed |= set_property_if_changed(vo, "LineWidth", 2)

        vo = self._filter_surface.ViewObject
        changed |= set_property_if_changed(vo, "ShapeColor", (1.0, 0.0, 1.0))
        changed |= set_property_if_changed(vo, "Transparency", 60)
        changed |= set_property_if_changed(vo, "LineWidth", 2)

        # --------------------------------------------------------------
        # Boolean relationship
        # --------------------------------------------------------------
        # changed |= set_property_if_changed(self._cut, "Base", self._ellipsoid_outer)
        # changed |= set_property_if_changed(self._cut, "Tool", self._ellipsoid_inner)

        return changed

    # ========================================================
    #  U P D A T E   E L L I P S O I D
    # ========================================================

    def focal_points_world(self, obj):
        a = float(obj.A_)
        b = float(obj.B_)

        c = focus_distance(a, b)

        rotation = self._ellipsoid_inner.Placement.Rotation
        center = self._ellipsoid_inner.Placement.Base

        f1 = center + rotation.multVec(App.Vector(0, 0, +c))
        f2 = center + rotation.multVec(App.Vector(0, 0, -c))

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
        changed = False
        # changed = self._ensure_features(obj)
        if self._ellipsoid_inner is None:
            return changed

        a = float(obj.A_)
        b = float(obj.B_)

        t = float(obj.WallThickness)

        radius3 = max(0.0, b - float(obj.Radius3Offset))

        inner_a = a
        inner_b = b
        inner_r3 = radius3

        outer_a = inner_a + t
        outer_b = inner_b + t
        outer_r3 = inner_r3 + t

        changed |= set_quantity_if_changed(self._ellipsoid_bound, "Radius1", outer_a, "mm")
        changed |= set_quantity_if_changed(self._ellipsoid_bound, "Radius2", outer_b, "mm")
        changed |= set_quantity_if_changed(self._ellipsoid_bound, "Radius3", outer_r3, "mm")

        changed |= set_quantity_if_changed(self._ellipsoid_outer, "Radius1", outer_a, "mm")
        changed |= set_quantity_if_changed(self._ellipsoid_outer, "Radius2", outer_b, "mm")
        changed |= set_quantity_if_changed(self._ellipsoid_outer, "Radius3", outer_r3, "mm")

        changed |= set_quantity_if_changed(self._ellipsoid_inner, "Radius1", inner_a, "mm")
        changed |= set_quantity_if_changed(self._ellipsoid_inner, "Radius2", inner_b, "mm")
        changed |= set_quantity_if_changed(self._ellipsoid_inner, "Radius3", inner_r3, "mm")

        # guard emot felaktiva a och b värden
        if a <= 0 or b <= 0:
            return changed

        validate_ellipsoid(a, b, radius3)
        c = focus_distance(a, b)

        # rot0 = App.Rotation(App.Vector(1, 0, 0), 90)

        rot0 = App.Rotation(App.Vector(1, 0, 0), 90).multiply(App.Rotation(App.Vector(0, 1, 0), 180))
        rotation = rot0

        rotation = App.Rotation(App.Vector(1, 0, 0), float(obj.RotX)).multiply(rotation)
        rotation = App.Rotation(App.Vector(0, 0, 1), float(obj.RotZ)).multiply(rotation)
        # ----------------------------------------------------
        # 2. Beräkna positionen (brännpunkt lokalt + offset globalt)
        # ----------------------------------------------------
        # Brännpunktens förskjutning (c) ligger längs ellipsoidens lokala axel och ska roteras
        focal_offset = rotation.multVec(App.Vector(0, 0, c))

        # OffsetX/Y/Z appliceras direkt i globala (world) koordinater utan rotation
        world_offset = App.Vector(float(obj.OffsetX), float(obj.OffsetY), float(obj.OffsetZ))

        placement = App.Placement(obj.Placement.Base + focal_offset + world_offset, rotation)

        # center_offset = rot0.multVec(App.Vector(-float(obj.OffsetX), c - float(obj.OffsetZ), float(obj.OffsetY)))
        # center_offset = rotation.multVec(center_offset)
        # placement = App.Placement(obj.Placement.Base + center_offset, rotation)

        changed |= set_property_if_changed(self._ellipsoid_bound, "Placement", placement)
        changed |= set_property_if_changed(self._ellipsoid_outer, "Placement", placement)
        changed |= set_property_if_changed(self._ellipsoid_inner, "Placement", placement)

        # ========================
        #  Avskärning av undersidan
        # ========================

        changed |= set_quantity_if_changed(self._split_box, "Length", 4 * outer_b, "mm")
        changed |= set_quantity_if_changed(self._split_box, "Width", 4 * outer_a, "mm")
        changed |= set_quantity_if_changed(self._split_box, "Height", 4 * outer_a, "mm")
        # split_local = App.Vector(-2 * outer_b, 0.0, -2 * outer_a)
        split_local = App.Vector(-2 * outer_b, -4 * outer_a, -2 * outer_a)

        split_placement = App.Placement(placement.multVec(split_local), rotation)
        changed |= set_property_if_changed(self._split_box, "Placement", split_placement)

        # ========================
        #  Avskärning av sidorna
        # ========================

        widthFactor = float(obj.WidthFactor)

        # Generös marginal så boxarna säkert täcker hela yttre ellipsoiden
        margin = 10.0
        box_lenght = 2 * outer_b + margin  # Längs lokal X (Radius1)
        box_width = 2 * outer_a + margin  # Längs lokal Y (Radius2)
        box_height = 2 * outer_a + margin  # Längs lokal Z (Radius3)

        # Halva tjockleken som ska bli kvar i mitten
        keep_half = outer_r3 * (widthFactor * 0.5)

        # Sätt samma dimensioner på båda boxarna
        for box in (self._opening_box_pos, self._opening_box_neg):
            changed |= set_quantity_if_changed(box, "Length", box_lenght, "mm")
            changed |= set_quantity_if_changed(box, "Width", box_width, "mm")
            changed |= set_quantity_if_changed(box, "Height", box_height, "mm")

        # Centrera i X och Y (-box_lenght/2, -box_width/2)
        # Positiv box: startar vid +keep_half och sträcker sig uppåt (+Z)
        pos_local = App.Vector(-box_lenght - keep_half, -box_width * 0.5, -box_height * 0.5)
        pos_placement = App.Placement(placement.multVec(pos_local), rotation)
        changed |= set_property_if_changed(self._opening_box_pos, "Placement", pos_placement)

        #

        neg_local = App.Vector(+keep_half, -box_width * 0.5, -box_height * 0.5)

        neg_placement = App.Placement(placement.multVec(neg_local), rotation)
        changed |= set_property_if_changed(self._opening_box_neg, "Placement", neg_placement)

        changed |= self.show_foci(obj)
        changed |= set_quantity_if_changed(obj, "FocusDistance", c, "mm")
        return changed

    def _update_focal_surface(self, obj):
        import Part

        width = float(obj.APlaneWidth)
        height = float(obj.APlaneHeight)

        f1, f2 = self.focal_points_world(obj)

        # emitterytan ligger i första fokus
        # focus = f1
        focus = obj.Placement.Base

        p1 = App.Vector(-width / 2, -height / 2, 0)
        p2 = App.Vector(+width / 2, -height / 2, 0)
        p3 = App.Vector(+width / 2, +height / 2, 0)
        p4 = App.Vector(-width / 2, +height / 2, 0)

        signature = tuple(
            round(float(value), 9)
            for point in (p1, p2, p3, p4)
            for value in (
                focus.x + point.x,
                focus.y + point.y,
                focus.z + point.z,
            )
        )
        if signature == getattr(self, "_focal_surface_signature", None):
            return False

        wire = Part.makePolygon([p1, p2, p3, p4, p1])
        face = Part.Face(wire)

        face.Placement = App.Placement(focus, App.Rotation())
        # face.Placement = App.Placement(focus, self._ellipsoid_inner.Placement.Rotation) # vinkel rätt emot den optiska axeln

        # self._focal_surface.Shape = face

        self._focal_surface.Shape = face
        self._focal_surface.Placement = App.Placement(
            focus,
            App.Rotation(),
        )
        # self._focal_surface.Placement = App.Placement(
        #     obj.Placement.Base,
        #     App.Rotation(),
        # )

        self._focal_surface_signature = signature
        return True

    def _update_filter_surface(self, obj):
        import Part

        size = float(obj.FilterPlaneSize)

        # Filter avstängd
        if size <= 1e-9:
            self._filter_surface.Shape = Part.Shape()
            self._filter_surface_signature = None
            return True

        f1, _ = self.focal_points_world(obj)

        z = -float(obj.FilterPlaneOffset)

        p1 = App.Vector(-size / 2, -size / 2, z)
        p2 = App.Vector(+size / 2, -size / 2, z)
        p3 = App.Vector(+size / 2, +size / 2, z)
        p4 = App.Vector(-size / 2, +size / 2, z)

        signature = (
            round(size, 9),
            # round(y, 9),
            round(z, 9),
            round(f1.x, 9),
            # round(f1.y, 9),
            round(f1.z, 9),
        )

        if signature == getattr(self, "_filter_surface_signature", None):
            return False

        wire = Part.makePolygon([p1, p2, p3, p4, p1])
        face = Part.Face(wire)

        face.Placement = App.Placement(
            obj.Placement.Base,  # f1,
            App.Rotation(),
        )

        self._filter_surface.Shape = face
        self._filter_surface_signature = signature

        return True

    def _update_debug(self, obj):
        changed = False
        if self._ellipsoid_inner:
            changed |= set_property_if_changed(self._ellipsoid_inner.ViewObject, "Visibility", bool(obj.ShowDebugEllipsoid))

        if self._focus1:
            changed |= set_property_if_changed(self._focus1.ViewObject, "Visibility", bool(obj.ShowDebugFoci))

        if self._focus2:
            changed |= set_property_if_changed(self._focus2.ViewObject, "Visibility", bool(obj.ShowDebugFoci))

        if self._ellipsoid_bound:
            changed |= set_property_if_changed(self._ellipsoid_bound.ViewObject, "Visibility", bool(obj.ShowDebugEllipsoid))

        return changed

    def synchronize_aim_from_rotation_old(self, obj):
        f1, f2 = self.focal_points_world(obj)
        set_property_if_changed(obj, "AimX", f2.x)
        set_property_if_changed(obj, "AimY", f2.y)
        set_property_if_changed(obj, "AimZ", f2.z)

    def optical_axis_world(self, obj):
        f1, f2 = self.focal_points_world(obj)

        direction = f2 - f1
        direction.normalize()

        return direction

    def synchronize_aim_from_rotation_old(self, obj, init=False):
        f1, f2 = self.focal_points_world(obj)
        print("[aim ]", f1, f2)
        set_property_if_changed(obj, "AimX", f2.x)
        set_property_if_changed(obj, "AimY", f2.y)
        set_property_if_changed(obj, "AimZ", f2.z)

    def synchronize_aim_from_rotation(self, obj, init=False):
        f1, f2 = self.focal_points_world(obj)

        if init:
            target = f1
        else:
            direction = f1 - f2
            direction.normalize()
            target = f1 + direction * 1

        set_property_if_changed(obj, "AimX", target.x)
        set_property_if_changed(obj, "AimY", target.y)
        set_property_if_changed(obj, "AimZ", target.z)

    def synchronize_rotation_from_aim(self, obj):
        target = App.Vector(float(obj.AimX), float(obj.AimY), float(obj.AimZ))
        direction = target - obj.Placement.Base

        # f1, _ = self.focal_points_world(obj)
        # direction = target - f1

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

        # fix för att tillåta att man transformerar förbi aimx,y ..
        horizontal = math.hypot(direction.x, direction.y)
        rx = math.degrees(math.atan2(direction.z, horizontal))
        rz = math.degrees(math.atan2(direction.x, direction.y))

        # print(f"Matchad med ellipsoiden -> RotX: {rx:.2f}°, RotY: {ry:.2f}°, RotZ: {rz:.2f}°")

        # print("direction", direction)
        # print("rx", rx)
        # print("rz", rz)
        # print("RotX", obj.RotX)
        # print("RotZ", obj.RotZ)

        # 4. Tilldela till objektet
        set_quantity_if_changed(obj, "RotX", rx, "deg")
        # set_quantity_if_changed(obj, "RotY", ry, "deg")
        set_quantity_if_changed(obj, "RotZ", rz, "deg")

    def _is_dialog_open(self):
        dlg = getattr(self, "_dialog", None)
        if dlg is None:
            return False
        try:
            return dlg.isVisible()
        except Exception:
            self._dialog = None
            return False

    # ========================================================
    #  R E B U I L D
    # ========================================================

    def execute(self, obj):
        if self._initializing or self._rebuilding or not self._dirty:
            return

        if self._sync_rotation_before_rebuild:
            self._syncing_orientation = True
            try:
                self.synchronize_rotation_from_aim(obj)
            finally:
                self._syncing_orientation = False
            self._sync_rotation_before_rebuild = False

        self._rebuild(obj)

        if self._sync_aim_after_rebuild:
            self._syncing_orientation = True
            try:
                self.synchronize_aim_from_rotation(obj)
            finally:
                self._syncing_orientation = False
            self._sync_aim_after_rebuild = False

        self._dirty = False

    def _rebuild(self, obj):
        if self._rebuilding:
            return
        self._rebuilding = True

        try:
            # t0 = time.perf_counter()
            # def printChangedIfTrue(changed, fromUpdate):
            #     if changed:
            #         print(fromUpdate, " är changed", changed)

            changed = False
            # t0 = time.perf_counter()
            changed |= self._update_ellipsoid(obj)
            # print("ellipsoid", time.perf_counter() - t0)
            # printChangedIfTrue(changed, " --- update elipsoid")
            # changed |= self._update_cubes(obj)
            # printChangedIfTrue(changed, "update_cubes")
            # t0 = time.perf_counter()
            changed |= self._update_focal_surface(obj)
            # print("focal", time.perf_counter() - t0)

            # t0 = time.perf_counter()

            changed |= self._update_filter_surface(obj)
            # print("filter", time.perf_counter() - t0)

            # t0 = time.perf_counter()

            changed |= self._update_debug(obj)
            # print("filter", time.perf_counter() - t0)

            if changed and not self._suppress_onchange and not is_optimization_running():
                # Optuna's evaluation performs the document recompute after applying parameters.
                print("=== [ellipsoid]  recompute i rebuild  ===", changed)
                # t0 = time.perf_counter()

                obj.Document.recompute()
                # print("RECOMPUTE", time.perf_counter() - t0)

        finally:
            self._rebuilding = False

        if self._is_dialog_open():
            print("======================= Elipsoid  recomputar ===========================")
            # obj.Document.recompute()

    # ========================================================

    # ========================================================
    #  C H A N G E D
    # ========================================================

    def onChanged(self, obj, prop):

        IGNORE = {"Group", "Shape"}
        if prop in IGNORE:
            # print("//// Ellipsoid IGNORE:", prop)
            return

        if self._rebuilding:
            return
        if self._syncing_orientation:
            return
        if self._initializing:
            return

        if prop in ("AimX", "AimY", "AimZ") and obj.UseAimPoint:
            # print("[Ellipsoi]d onChanged:", prop)

            self._syncing_orientation = True
            try:
                self.synchronize_rotation_from_aim(obj)
                dialog = getattr(self, "_dialog", None)
                if dialog:
                    dialog.refresh_from_object()
                if not self._suppress_onchange:
                    self._rebuild(obj)
            finally:
                # dialog = getattr(self, "_dialog", None)
                # dialog.refresh_from_object()

                self._syncing_orientation = False

        if self._suppress_onchange:
            return
        # ----------------------------------------------------
        # Debug visibility.
        # ----------------------------------------------------
        if prop in {"ShowDebugEllipsoid", "ShowDebugFoci"}:
            self._update_debug(obj)

        # ----------------------------------------------------
        # Geometry
        # ----------------------------------------------------
        main_properties = {
            "A_",
            "B_",
            "Radius3Offset",
            "WallThickness",
            "WidthFactor",
            "OffsetX",
            "OffsetY",
            "OffsetZ",
            "APlaneWidth",
            "APlaneHeight",
            "FilterPlaneSize",
            "FilterPlaneOffset",
        }

        if prop in main_properties:
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

        # ----------------------------------------------------
        # Main placement changed. This event is for the use of Transform Gizmo
        # ----------------------------------------------------

        if prop == "Placement" and not is_optimization_running():
            try:
                rotation_applied = math.degrees(obj.Placement.Rotation.Angle) > 0.01

                if rotation_applied:
                    print("[Ellipsoid] Transform rotation ignored")
                    obj.Placement = App.Placement(obj.Placement.Base, App.Rotation())
                    return

                if obj.UseAimPoint:
                    self.synchronize_rotation_from_aim(obj)

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

        # rename_property(
        #     obj,
        #     "_B",
        #     "B_",
        #     "App::PropertyLength",
        #     "Dimensions",
        # )

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
    aplanewidth=3.0,
    aplaneheight=3.0,
    offsetX=0.0,
    offsetY=0.0,
    offsetZ=0.0,
    a=15.0,
    b=6.0,
    widthfactor=1.8,
    walltickness=1,
    rot_x=20.0,
    # rot_y=0.0,
    rot_z=0.0,
    use_aim_point=False,
    aim_x=0,
    aim_y=0,
    aim_z=0,
    # x=0.0,
    # y=0.0,
    # z=0.0,
    suppress_onchange=False,
    show_dialog=True,
    radius3_offset=0.0,
):

    #   target = App.Vector(float(obj.AimX), float(obj.AimY), float(obj.AimZ))

    doc = doc or App.ActiveDocument or App.newDocument()
    obj = doc.addObject("Part::FeaturePython", "OBAEllipsoid")

    obj.Label = label

    proxy = OBAEllipsoid(obj)

    proxy._initializing = True
    proxy._suppress_onchange = suppress_onchange

    obj.APlaneWidth = aplanewidth  # App.Units.Quantity(f"{aplanewidth} mm")
    obj.APlaneHeight = aplaneheight  # App.Units.Quantity(f"{aplaneheight} mm")

    obj.OffsetX = offsetX
    obj.OffsetY = offsetY
    obj.OffsetZ = offsetZ

    obj.A_ = a  # App.Units.Quantity(f"{a} mm")
    obj.B_ = b  # App.Units.Quantity(f"{b} mm")

    obj.Radius3Offset = radius3_offset

    obj.WidthFactor = float(widthfactor)
    obj.WallThickness = float(walltickness)

    obj.RotX = rot_x  # App.Units.Quantity(f"{rot_x} deg")
    # obj.RotY = rot_y  # App.Units.Quantity(f"{rot_y} deg")
    obj.RotZ = rot_z  # App.Units.Quantity(f"{rot_z} deg")

    obj.UseAimPoint = use_aim_point

    obj.AimX = aim_x  # App.Units.Quantity("100 mm")
    obj.AimY = aim_y  # App.Units.Quantity("0 mm")
    obj.AimZ = aim_z  # App.Units.Quantity("0 mm")

    proxy._ensure_features(obj)
    proxy._update_ellipsoid(obj)

    proxy.synchronize_aim_from_rotation(obj, init=True)  # för att sätta korrekta värden direkt

    # obj.ShowDebugEllipsoid = False
    obj.FocusDistance = focus_distance(float(a), float(b))

    # --------------------------------------------------------
    # Build the real Part::Ellipsoid once everything is ready.
    # --------------------------------------------------------

    proxy._initializing = False
    proxy._rebuild(obj)

    # print("************ initizing ", proxy._initializing)

    if App.GuiUp:
        EllipsoidViewProvider(obj.ViewObject)

    # doc.recompute()

    if show_dialog:
        EllipsoidDialog(obj).show()
    return obj


# def create(
#     doc=None,
#     label="Ellipsoid",
#     aplanewidth=5.0,
#     aplaneheight=5.0,
#     aplaneZoffset=0.0,
#     aplaneYoffset=0.0,
#     a=40.0,
#     b=20.0,
#     widthfactor=1.8,
#     rot_x=0.0,
#     rot_y=0.0,
#     rot_z=0.0,
#     x=0.0,
#     y=0.0,
#     z=0.0,
#     radius3_offset=0.0,
# ):
#     return OBA_CreateEllipsoid(
#         doc=doc,
#         label=label,
#         aplanewidth=aplanewidth,
#         aplaneheight=aplaneheight,
#         aplaneZoffset=aplaneZoffset,
#         aplaneYoffset=aplaneYoffset,
#         a=a,
#         b=b,
#         radius3_offset=radius3_offset,
#         widthfactor=widthfactor,
#         rot_x=rot_x,
#         rot_y=rot_y,
#         rot_z=rot_z,
#         x=x,
#         y=y,
#         z=z,
#         show_dialog=False,
#     )
