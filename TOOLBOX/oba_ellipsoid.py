# oba_ellipsoid.py
#
# OBA Ellipsoid optical component.
#
#

import math


import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from PySide.QtCore import QSignalBlocker

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
    {"name": "APlaneWidth", "type": "App::PropertyLength", "group": "Box", "doc": "Aperture plane width"},
    {"name": "APlaneHeight", "type": "App::PropertyLength", "group": "Box", "doc": "Aperture plane height"},
    {"name": "Depth", "type": "App::PropertyLength", "group": "Box", "doc": "Box depth"},
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
    {"name": "PosX", "type": "App::PropertyDistance", "group": "Placement", "doc": "X coordinate"},
    {"name": "PosY", "type": "App::PropertyDistance", "group": "Placement", "doc": "Y coordinate"},
    {"name": "PosZ", "type": "App::PropertyDistance", "group": "Placement", "doc": "Z coordinate"},
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

        self._ellipsoid = None
        self._focus1 = None
        self._focus2 = None
        self._focal_surface = None

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

    def _ensure_features(self, obj):
        """
        Find existing construction objects or create them if missing.

        Construction objects are created directly in the document.
        They are not placed inside an App::Part.
        """
        doc = obj.Document
        if self._box is None:
            self._box = doc.getObject(f"{obj.Name}_Box")
        if self._box_ext is None:
            self._box_ext = doc.getObject(f"{obj.Name}_BoxExt")
        if self._box_bound is None:
            self._box_bound = doc.getObject(f"{obj.Name}_BoxBound")

        if self._fuse is None:
            self._fuse = doc.getObject(f"{obj.Name}_Fuse")
        if self._ellipsoid is None:
            self._ellipsoid = doc.getObject(f"{obj.Name}_Ellipsoid")
        if self._cut is None:
            self._cut = doc.getObject(f"{obj.Name}_Cut")
        if self._focal_surface is None:
            self._focal_surface = doc.getObject(f"{obj.Name}_FocalSurface")

        # --------------------------------------------------------------
        # Validate existing references
        # --------------------------------------------------------------
        if not self._obj_exists(self._box):
            self._box = None
        if not self._obj_exists(self._box_ext):
            self._box_ext = None

        if not self._obj_exists(self._box_bound):
            self._box_bound = None

        if not self._obj_exists(self._fuse):
            self._fuse = None

        if not self._obj_exists(self._ellipsoid):
            self._ellipsoid = None

        if not self._obj_exists(self._cut):
            self._cut = None

        if not self._obj_exists(self._focal_surface):
            self._focal_surface = None
        # --------------------------------------------------------------
        # Create missing construction objects
        # --------------------------------------------------------------

        if self._box is None:
            self._box = doc.addObject("Part::Box", f"{obj.Name}_Box")
            self._box.Label = f"{obj.Label} Box"

        if self._box_ext is None:
            self._box_ext = doc.addObject("Part::Box", f"{obj.Name}_BoxExt")
            self._box_ext.Label = f"{obj.Label} Box"

        if self._fuse is None:
            self._fuse = doc.addObject("Part::Fuse", f"{obj.Name}_Fuse")
            self._fuse.Label = f"{obj.Label} Fuse"

        if self._box_bound is None:
            self._box_bound = doc.addObject("Part::Box", f"{obj.Name}_BoxBound")
            self._box_bound.Label = f"{obj.Label} BoxBound"
            self._box_bound.ViewObject.DisplayMode = "Wireframe"
            # self._box_bound.ViewObject.ShapeColor = (0.7, 0.8, 1.0)

        if self._ellipsoid is None:
            self._ellipsoid = doc.addObject("Part::Ellipsoid", f"{obj.Name}_Ellipsoid")
            self._ellipsoid.Label = f"{obj.Label} Ellipsoid"
            self._ellipsoid.ViewObject.ShapeColor = (0.7, 0.8, 1.0)
            self._ellipsoid.ViewObject.Transparency = 80

        if self._cut is None:
            self._cut = doc.addObject("Part::Cut", f"{obj.Name}_Cut")
            self._cut.Label = f"{obj.Label} Cut"

        if self._focal_surface is None:
            self._focal_surface = doc.addObject("Part::Feature", f"{obj.Name}_FocalSurface")
            self._focal_surface.Label = f"{obj.Label} Focal_Surface"

            vo = self._focal_surface.ViewObject
            vo.ShapeColor = (1.0, 1.0, 0.0)
            vo.Transparency = 50
            vo.LineWidth = 2

        # return Part.Face(Part.makePolygon([p1, p2, p3, p4, p1]))

        # --------------------------------------------------------------
        # Boolean relationship
        # --------------------------------------------------------------

        self._fuse.Base = self._box
        self._fuse.Tool = self._box_ext

        self._cut.Base = self._fuse
        self._cut.Tool = self._ellipsoid

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
        rotz = App.Rotation(App.Vector(0, 0, -1), float(obj.RotZ))

        rotation = rot0
        rotation = rotx.multiply(rotation)  # Rotera X *efter* rot0
        rotation = roty.multiply(rotation)  # Rotera Y *efter* det
        rotation = rotz.multiply(rotation)  # Rotera Z *sist*

        center_offset = rotation.multVec(App.Vector(0, 0, c))

        local = App.Placement(center_offset, rotation)
        ellipsoid.Placement = obj.Placement.multiply(local)

        # ellipsoid.Placement = App.Placement(obj.Placement.Base + center_offset, rotation)

        self.show_foci(obj)

        obj.FocusDistance = c

    def _update_cubes(self, obj):

        length = float(obj.A * 0.9) + float(obj.A * 0.7) * math.sin(math.radians(obj.RotX))  # är omkastad enligt mitt orienteringssätt

        height = float(obj.B * 1.2)  # är omkastad enligt mitt orienteringssätt
        width = float(obj.B * 1.8)

        self._box.Length = width  # length är width, pga box orginal orientering
        self._box.Width = length  # width är length, pga box orginal orientering
        self._box.Height = height

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
        self._box.Placement = obj.Placement.multiply(local)

        # -----------------------------------
        # Extension box = den förlängning som skall kunna skära i comp mirror
        # -----------------------------------
        self._box_ext.Height = float(height * math.cos(math.radians(obj.RotX)))
        self._box_ext.Width = width

        # c = focus_distance(obj.A, obj.B)
        # self._box_ext.Length = float(height * math.sin(math.radians(obj.RotX))) + (float(obj.A) - c) * 2  # lägger till det som fattas ifrån c + lite till
        self._box_ext.Length = float(obj.B) * 1.5
        rot_ext_0 = App.Rotation(App.Vector(0, 0, 1), (-90))  # för att Length skall peka i -y
        rot_ext_z = App.Rotation(App.Vector(0, 0, -1), obj.RotZ)
        rot_ext = rot_ext_0.multiply(rot_ext_z)

        local_ext = App.Placement(App.Vector(posX, posY, posZ), rot_ext)  # justeras emot elipsoidens fokal centrum
        self._box_ext.Placement = obj.Placement.multiply(local_ext)  # slutgilta flytten

        # -----------------------------------
        # Bounding box = Bounding box som kan användas som cut.
        # -----------------------------------

        self._box_bound.Width = width
        self._box_bound.Height = float(self._box_ext.Height) + float(length * math.sin(math.radians(obj.RotX)))
        self._box_bound.Length = float(self._box_ext.Length) + float(length * math.cos(math.radians(obj.RotX)))

        base_pos = App.Vector(posX, posY, posZ)
        offset_local = App.Vector(-float(length * math.cos(math.radians(obj.RotX))), 0, 0)
        offset_world = rot_ext.multVec(offset_local)
        local_bound = App.Placement(base_pos + offset_world, rot_ext)
        self._box_bound.Placement = obj.Placement.multiply(local_bound)

    def _update_focal_surface(self, obj):
        import Part

        width = float(obj.APlaneWidth)
        height = float(obj.APlaneHeight)

        f1, f2 = self.focal_points_world(obj)

        # emitterytan ligger i första fokus
        focus = f1

        p1 = App.Vector(-width / 2, -height / 2, 0)
        p2 = App.Vector(+width / 2, -height / 2, 0)
        p3 = App.Vector(+width / 2, +height / 2, 0)
        p4 = App.Vector(-width / 2, +height / 2, 0)

        wire = Part.makePolygon([p1, p2, p3, p4, p1])
        face = Part.Face(wire)

        face.Placement = App.Placement(focus, App.Rotation())
        # face.Placement = App.Placement(focus, self._ellipsoid.Placement.Rotation) # vinkel rätt emot den optiska axeln

        self._focal_surface.Shape = face

    # ========================================================
    #  R E B U I L D
    # ========================================================

    def _rebuild(self, obj):
        if self._rebuilding:
            return
        self._rebuilding = True
        try:
            self._update_ellipsoid(obj)
            self._update_cubes(obj)
            self._update_focal_surface(obj)

            self._update_debug(obj)
            obj.Document.recompute()

        finally:
            self._rebuilding = False

    # ========================================================

    def _update_debug(self, obj):
        ellipsoid = getattr(self, "_ellipsoid", None)
        if ellipsoid is None:
            return
        show_debug_focal = bool(obj.ShowDebugEllipsoid)
        if show_debug_focal:
            ellipsoid.ViewObject.Visibility = True

        if self._focus1:
            self._focus1.ViewObject.Visibility = obj.ShowDebugFoci
        if self._focus2:
            self._focus2.ViewObject.Visibility = obj.ShowDebugFoci

    def synchronize_aim_from_rotation(self, obj):
        f1, f2 = self.focal_points_world(obj)
        obj.AimX = App.Units.Quantity(f"{f2.x} mm")
        obj.AimY = App.Units.Quantity(f"{f2.y} mm")
        obj.AimZ = App.Units.Quantity(f"{f2.z} mm")

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
        obj.RotX = App.Units.Quantity(f"{rx} deg")
        obj.RotY = App.Units.Quantity(f"{ry} deg")
        obj.RotZ = App.Units.Quantity(f"{rz} deg")

    # ========================================================
    #  C H A N G E D
    # ========================================================

    def onChanged(self, obj, prop):

        # if prop in ("Shape", "Label"):  # , "FocusDistance"):
        #     pass
        # return

        if self._rebuilding:
            return

        if self._syncing_orientation:
            return

        if self._initializing:
            return

        # print("----------------")
        print(f"onChanged: {prop}, rebuilding={self._rebuilding}, syncing_ori={self._syncing_orientation} , init={self._initializing}")
        # print("value =", getattr(obj, prop))

        # ----------------------------------------------------
        # Geometry
        # ----------------------------------------------------
        if prop in ("A", "B", "UseIndependentRadius3", "B2", "APlaneWidth", "APlaneHeight"):
            try:
                self._rebuild(obj)
            except Exception as exc:
                App.Console.PrintError("[OBA] Ellipsoid rebuild failed: " f"{exc}\n")
        # ----------------------------------------------------
        # Orientation.
        # ----------------------------------------------------
        if prop in ("RotX", "RotY", "RotZ"):
            self._syncing_orientation = True
            try:
                if not obj.UseAimPoint:
                    self.synchronize_aim_from_rotation(obj)
                self._rebuild(obj)
            finally:
                self._syncing_orientation = False

        if prop in ("AimX", "AimY", "AimZ"):
            if not obj.UseAimPoint:
                return
            self._syncing_orientation = True
            try:
                self.synchronize_rotation_from_aim(obj)
                self._rebuild(obj)

            finally:
                self._syncing_orientation = False

        # ----------------------------------------------------
        # Main placement changed.
        # ----------------------------------------------------
        if prop == "Placement":
            try:
                self._rebuild(obj)
            except Exception as exc:
                App.Console.PrintError("[OBA] Ellipsoid placement update failed: " f"{exc}\n")

        # ----------------------------------------------------
        # Debug visibility.
        # ----------------------------------------------------
        if prop in ("ShowDebugEllipsoid", "ShowDebugFoci"):
            self._update_debug(obj)
            return

        dialog = getattr(self, "_dialog", None)
        if dialog:
            dialog.refresh_from_object()

    # ========================================================
    #  R E S T O R E
    # ========================================================

    def onDocumentRestored(self, obj):
        """
        Restore Python runtime state and reconnect to the existing
        FreeCAD construction objects.
        """
        self._init_runtime_state()

        obj.Proxy = self
        self.Object = obj

        install_properties(obj, ELLIPSOID_PROPERTIES)
        ensure_debug_property(obj)

        make_calculated_length(obj, "FocusDistance", "Distance from ellipsoid centre to focus")

        # make_optical_type(obj, "Ellipsoid")

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

        self.obj.Proxy._dialog = self  # registrering av dialogen

        self._refreshing_ui = False

        # group = QtWidgets.QGroupBox("Aperture Plane")
        # form = QtWidgets.QFormLayout(group)
        # self.width = self._add_spin("Width _", "Width", -1_000_000, 1_000_000, "mm", form)
        # self.height = self._add_spin("Height _", "Height", -1_000_000, 1_000_000, "mm", form)

        group = QtWidgets.QGroupBox("Aperture Plane")
        form = QtWidgets.QFormLayout(group)
        self.aplane_width = self._add_spin("Width", "APlaneWidth", 0, 1000000, "mm", form)
        self.aplane_height = self._add_spin("Height", "APlaneHeight", 0, 1000000, "mm", form)
        self.custom_layout.addWidget(group)

        group = QtWidgets.QGroupBox("Ellipsoid")
        form = QtWidgets.QFormLayout(group)

        self.show_debug_ellipsoid = QtWidgets.QCheckBox("Show ellipsoids (debug)")
        form.addRow(self.show_debug_ellipsoid)
        self.show_debug_focal = QtWidgets.QCheckBox("Show focus points (debug)")
        form.addRow(self.show_debug_focal)

        self.a = self._add_spin("A", "A", 0, 1_000_000, "mm", form)
        self.b = self._add_spin("B", "B", 0, 1_000_000, "mm", form)
        self.use_b2 = QtWidgets.QCheckBox("Use independent Radius3")
        form.addWidget(self.use_b2)
        self.b2 = self._add_spin("B2", "B2", 0, 1_000_000, "mm", form)
        self.c = QtWidgets.QLabel()
        form.addRow("Focus distance C", self.c)

        # self.add_debug_checkbox("Show debug ellipsoid")

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
        #  S I G N A L S
        # ====================================================
        self.aplane_width.valueChanged.connect(lambda value: self._set_property("APlaneWidth", value.Value))
        self.aplane_height.valueChanged.connect(lambda value: self._set_property("APlaneHeight", value.Value))

        self.a.valueChanged.connect(lambda value: self._set_property("A", value.Value))
        self.b.valueChanged.connect(lambda value: self._set_property("B", value.Value))
        self.b2.valueChanged.connect(lambda value: self._set_property("B2", value.Value))

        self.rot_x.valueChanged.connect(lambda value: self._set_property("RotX", value.Value))
        self.rot_y.valueChanged.connect(lambda value: self._set_property("RotY", value.Value))
        self.rot_z.valueChanged.connect(lambda value: self._set_property("RotZ", value.Value))

        self.aim_x.valueChanged.connect(lambda value: self._set_property("AimX", value.Value))
        self.aim_y.valueChanged.connect(lambda value: self._set_property("AimY", value.Value))
        self.aim_z.valueChanged.connect(lambda value: self._set_property("AimZ", value.Value))

        self.show_debug_focal.toggled.connect(lambda checked: self._set_property("ShowDebugFoci", checked))
        self.show_debug_ellipsoid.toggled.connect(lambda checked: self._set_property("ShowDebugEllipsoid", checked))

        self.chkAimPoint.toggled.connect(lambda checked: self._set_property("UseAimPoint", checked))

        self.chkAimPoint.toggled.connect(self._update_dialog_orientation_controls)

        self.refresh_from_object()

    def _set_property(self, prop, value):
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

    def _set_property_new(self, prop, value):
        if self._refreshing_ui:
            return

        try:
            value = float(value)
            # ----------------------------------------------------
            # Ellipsoid: A måste alltid vara >= B
            # ----------------------------------------------------
            if prop == "A":
                b = float(self.obj.B)
                if value < b:
                    value = b

            elif prop == "B":
                a = float(self.obj.A)
                if value > a:
                    value = a

            current = float(getattr(self.obj, prop))

            if current == value:
                self._update_a_b_limits()
                self._update_information()
                return

            setattr(self.obj, prop, value)

            # Uppdatera spinbox-gränser efter att objektet ändrats.
            if prop in ("A", "B"):
                self._update_a_b_limits()

            self._update_information()

        except Exception as exc:
            App.Console.PrintError(f"[OBA] Failed to update {prop}: {exc}\n")

    def _update_a_b_limits(self, a=None, b=None):
        a = float(self.obj.A) if a is None else a
        b = float(self.obj.B) if b is None else b

        self.a.setProperty("minimum", b)
        self.b.setProperty("maximum", a)

    def reload(self):

        # self.c.setText(f"{float(self.obj.FocusDistance):.4f} mm")

        self._update_a_b_limits()

        self.a.setProperty("rawValue", float(self.obj.A))

        self.b.setProperty("rawValue", float(self.obj.B))

        self.use_b2.setChecked(bool(self.obj.UseIndependentRadius3))
        self.b2.setProperty("rawValue", float(self.obj.B2))

        # self.b2.setValue(float(self.obj.B2))  # funkar inte

        self.chkAimPoint.setChecked(bool(self.obj.UseAimPoint))
        self.show_debug_focal.setChecked(bool(self.obj.ShowDebugFoci))

        self.rot_x.setProperty("rawValue", float(self.obj.RotX))
        self.rot_y.setProperty("rawValue", float(self.obj.RotY))
        self.rot_z.setProperty("rawValue", float(self.obj.RotZ))

        self.aim_x.setProperty("rawValue", float(self.obj.AimX))
        self.aim_y.setProperty("rawValue", float(self.obj.AimY))
        self.aim_z.setProperty("rawValue", float(self.obj.AimZ))

        self.pos_x.setProperty("rawValue", float(self.obj.PosX))
        self.pos_y.setProperty("rawValue", float(self.obj.PosY))
        self.pos_z.setProperty("rawValue", float(self.obj.PosZ))

        # self.reload_placement()
        # ----------------------------------------------------
        # UI.
        # ----------------------------------------------------

        self._preview()

    def refresh_from_object(self):
        if self._refreshing_ui:
            return

        self._refreshing_ui = True
        try:
            # Object -> UI
            values = {
                self.a: self.obj.A,
                self.b: self.obj.B,
                self.b2: self.obj.B2,
                self.aplane_width: self.obj.APlaneWidth,
                self.aplane_height: self.obj.APlaneHeight,
                self.rot_x: self.obj.RotX,
                self.rot_y: self.obj.RotY,
                self.rot_z: self.obj.RotZ,
                self.aim_x: self.obj.AimX,
                self.aim_y: self.obj.AimY,
                self.aim_z: self.obj.AimZ,
            }

            for widget, value in values.items():
                with QSignalBlocker(widget):
                    widget.setProperty("rawValue", float(value))

            with QSignalBlocker(self.use_b2):
                self.use_b2.setChecked(bool(self.obj.UseIndependentRadius3))

            with QSignalBlocker(self.chkAimPoint):
                self.chkAimPoint.setChecked(bool(self.obj.UseAimPoint))

            with QSignalBlocker(self.show_debug_focal):
                self.show_debug_focal.setChecked(bool(self.obj.ShowDebugFoci))

            self.b2.setEnabled(bool(self.obj.UseIndependentRadius3))

            self._update_a_b_limits()
            self._update_information()

        finally:
            self._refreshing_ui = False

    def _update_information(self):
        self.c.setText(f"{float(self.obj.FocusDistance):.4f} mm")

        self._update_dialog_orientation_controls()
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

    # ========================================================
    #  O R I E N T A T I O N   C O N T R O L S
    # ========================================================

    def _update_dialog_orientation_controls(self):
        use_aim = self.chkAimPoint.isChecked()

        # Aim mode
        if use_aim:
            self.rot_x.setEnabled(False)
            self.rot_y.setEnabled(False)
            self.rot_z.setEnabled(False)

            self.aim_x.setEnabled(True)
            self.aim_y.setEnabled(True)
            self.aim_z.setEnabled(True)

        # Rotation mode
        else:
            self.rot_x.setEnabled(True)
            self.rot_y.setEnabled(False)  # som tidigare
            self.rot_z.setEnabled(True)

            self.aim_x.setEnabled(False)
            self.aim_y.setEnabled(False)
            self.aim_z.setEnabled(False)

        self.rot_y.setReadOnly(True)
        self.rot_y.setToolTip("Rotation around the optical axis. " "Not controlled by Aim Point.")

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


def OBA_CreateEllipsoid(
    doc=None,
    label="Ellipsoid",
    aplanewidth=5,
    aplaneheight=5,
    a=40.0,
    b=20.0,
    b2=None,
    rot_x=30,
    rot_y=0,
    rot_z=0,
    x=0,
    y=0,
    z=0,
    show_dialog=True,
):
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

    proxy._initializing = True

    obj.APlaneWidth = App.Units.Quantity(f"{aplanewidth} mm")
    obj.APlaneHeight = App.Units.Quantity(f"{aplaneheight} mm")

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
        aplanewidth=aplanewidth,
        aplaneheight=aplaneheight,
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
