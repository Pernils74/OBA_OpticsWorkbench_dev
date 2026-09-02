# oba_main_mirror.py
#
# OBA White Cell / Split Mirror
#
# Geometry:
#   - One rectangular cube/body
#   - Two identical ellipsoids
#   - The ellipsoids are mirrored around the cube centre plane
#   - Both ellipsoids are subtracted from the cube
#
# Shared boilerplate lives in oba_mirror_common.py.
#

import math
from pydoc import doc
from weakref import proxy


import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from oba_objects.oba_base import OBAElementProxy

from .oba_toolbox_base import (
    OBAToolboxDialogBase,
    OBAToolboxViewProviderBase,
    create_ellipsoid,
    ensure_debug_property,
    focus_distance,
    install_properties,
    make_calculated_length,
    make_centered_cube,
    make_optical_type,
    remove_objects,
    update_debug_ellipsoid,
    restore_view_provider,
)

WHITE_CELL_PROPERTIES = [
    {"name": "Width", "type": "App::PropertyLength", "group": "White Cell", "default": 100.0, "doc": "Width of the cube/body along X"},
    {"name": "Height", "type": "App::PropertyLength", "group": "White Cell", "default": 30.0, "doc": "Height of the cube/body along Z"},
    {"name": "SplitOffset", "type": "App::PropertyLength", "group": "White Cell", "default": 40.0, "doc": "Distance between the two ellipsoid focal points"},
    {"name": "A", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 40.0, "doc": "Ellipsoid semi-major axis"},
    {"name": "B", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 30.0, "doc": "Ellipsoid semi-minor radius"},
    {"name": "UseIndependentRadius3", "type": "App::PropertyBool", "group": "Ellipsoid", "default": False, "doc": "Use independent radius in Y direction"},
    {"name": "B2", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 20.0, "doc": "Independent ellipsoid Y radius"},
    {"name": "FocusDistance", "type": "App::PropertyLength", "group": "Ellipsoid", "default": 26.4575131106, "doc": "Distance from ellipsoid centre to focus"},
    {"name": "TiltAngle", "type": "App::PropertyAngle", "group": "Ellipsoid", "default": 0.0, "doc": "Tilt angle of the ellipsoids around the Z axis"},
]


class OBAWhiteCell(OBAElementProxy):
    def __init__(self, obj):
        self._initializing = True
        self._updating = False

        self._internal = None

        self._cube = None
        self._ellipsoid_Left = None
        self._ellipsoid_Right = None
        self._fusion = None
        self._cut = None

        self._cut1 = None
        self._cut2 = None

        super().__init__(obj, use_binders=False)
        install_properties(obj, WHITE_CELL_PROPERTIES)
        ensure_debug_property(obj)

        if hasattr(obj, "FocusDistance"):
            obj.setEditorMode("FocusDistance", 1)

        make_calculated_length(obj, "Ellipsoid1FocusX", "X position of first ellipsoid focus")
        make_calculated_length(obj, "Ellipsoid2FocusX", "X position of second ellipsoid focus")
        make_calculated_length(obj, "MirrorPlaneX", "X coordinate of mirror symmetry plane")
        make_optical_type(obj, "WhiteCellMainMirror")

        self._initializing = False

    def _obj_exists(self, obj):
        if obj is None:
            return False
        try:
            return obj.Document is not None and obj.Document.getObject(obj.Name) is obj
        except Exception:
            return False

    def _ensure_features(self, obj):

        doc = obj.Document

        # Repair dangling references
        if not self._obj_exists(self._internal):
            self._internal = None
        if not self._obj_exists(self._cube):
            self._cube = None
        if not self._obj_exists(self._ellipsoid_Left):
            self._ellipsoid_Left = None
        if not self._obj_exists(self._ellipsoid_Right):
            self._ellipsoid_Right = None
        if not self._obj_exists(self._cut1):
            self._cut1 = None
        if not self._obj_exists(self._cut2):
            self._cut2 = None

        # Internal container
        if self._internal is None:
            self._internal = doc.addObject("App::Part", f"{obj.Name}_Internal")
            self._internal.Label = f"{obj.Label} Internal"

        # Cube
        if self._cube is None:
            self._cube = doc.addObject("Part::Box", f"{obj.Name}_Cube")

        # Left ellipsoid
        if self._ellipsoid_Left is None:
            self._ellipsoid_Left = doc.addObject("Part::Ellipsoid", f"{obj.Name}_Ellipsoid1")

        # Right ellipsoid
        if self._ellipsoid_Right is None:
            self._ellipsoid_Right = doc.addObject("Part::Ellipsoid", f"{obj.Name}_Ellipsoid2")

        # Add objects to internal part
        children = set(self._internal.Group)

        if self._cube not in children:
            self._internal.addObject(self._cube)

        if self._ellipsoid_Left not in children:
            self._internal.addObject(self._ellipsoid_Left)

        if self._ellipsoid_Right not in children:
            self._internal.addObject(self._ellipsoid_Right)

        # if self._fusion is None:
        #     self._fusion = doc.addObject("Part::Fuse", f"{obj.Name}_Fusion")
        #     self._fusion.Base = self._ellipsoid_Left
        #     self._fusion.Tool = self._ellipsoid_Right

        #     self._cut = doc.addObject("Part::Cut", f"{obj.Name}_Cut")
        #     self._cut.Base = self._cube
        #     self._cut.Tool = self._fusion

        # if self._fusion not in self._internal.Group:
        #     self._internal.addObject(self._fusion)

        # if self._cut not in self._internal.Group:
        #     self._internal.addObject(self._cut)

        # # First cut
        if self._cut1 is None:
            self._cut1 = doc.addObject("Part::Cut", f"{obj.Name}_Cut1")
        self._cut1.Base = self._cube
        self._cut1.Tool = self._ellipsoid_Left

        # # Second cut
        if self._cut2 is None:
            self._cut2 = doc.addObject("Part::Cut", f"{obj.Name}_Cut2")

        self._cut2.Base = self._cut1
        self._cut2.Tool = self._ellipsoid_Right

        if self._cut1 not in self._internal.Group:
            self._internal.addObject(self._cut1)

        if self._cut2 not in self._internal.Group:
            self._internal.addObject(self._cut2)

    def _ensure_features_old(self, obj):
        doc = obj.Document  # Säkerställ referens till rätt dokument

        if self._internal is None:
            self._internal = doc.addObject("App::Part", f"{obj.Name}_Internal")
            self._internal.Label = f"{obj.Label} Internal"
            self._internal.ViewObject.Visibility = True  # Visa i trädet
            self._cube = doc.addObject("Part::Box", f"{obj.Name}_Cube")
            self._update_cube(obj)
            self._internal.addObject(self._cube)
            self._ellipsoid_Left = doc.addObject("Part::Ellipsoid", f"{obj.Name}_Ellipsoid1")
            # self._update_ellipsoids(obj)

            self._internal.addObject(self._ellipsoid_Left)
            self._ellipsoid_Right = doc.addObject("Part::Ellipsoid", f"{obj.Name}_Ellipsoid2")
            self._update_ellipsoids(obj)
            self._internal.addObject(self._ellipsoid_Right)

            cut1 = doc.addObject("Part::Cut", f"{obj.Name}_Cut1")
            cut1.Base = self._cube
            cut1.Tool = self._ellipsoid_Left

            cut2 = doc.addObject("Part::Cut", f"{obj.Name}_Cut2")
            cut2.Base = cut1
            cut2.Tool = self._ellipsoid_Right

        # 1. Skapa kuben om den inte finns

        # if self._cube is None:
        #     # self._cube.ViewObject.Visibility = False  # Dölj i trädet

        # # 2. Skapa första ellipsoiden (Korrigerat variabelnamn)
        # if self._ellipsoid_Left is None:
        #     # self._ellipsoid_Left.ViewObject.Visibility = False

        # # 3. Skapa andra ellipsoiden (Korrigerat variabelnamn)
        # if self._ellipsoid_Right is None:
        #     # self._ellipsoid_Right.ViewObject.Visibility = False

        # 4. Skapa Cut-objektet och länka samman geometrin
        # if self._cut1 is None:
        #     cut1 = doc.addObject("Part::Cut", f"{obj.Name}_Cut1")
        #     cut1.Base = self._cube
        #     cut1.Tool = self._ellipsoid_Left
        # if self._cut2 is None:
        #     cut2 = doc.addObject("Part::Cut", f"{obj.Name}_Cut2")
        #     cut2.Base = cut1
        #     cut2.Tool = self._ellipsoid_Right

    def _update_cube(self, obj):

        width = float(obj.Width)
        height = float(obj.Height)
        depth = 1.5 * float(obj.B)

        self._cube.Length = width
        self._cube.Width = depth
        self._cube.Height = height
        self._cube.Placement.Base = App.Vector(-width / 2.0, 0.0, -height / 2.0)

    def _update_ellipsoids(self, obj):

        split = float(obj.SplitOffset)

        a = float(obj.A)
        b = float(obj.B)
        b2 = float(obj.B2) if obj.UseIndependentRadius3 else b

        tilt = float(obj.TiltAngle)

        # LEFT (-X)
        left = self._ellipsoid_Left
        left.Radius1 = a
        left.Radius2 = b
        left.Radius3 = b2

        pl = App.Placement()
        pl.Base = App.Vector(-split / 2.0, 0, 0)

        rot1 = App.Rotation(App.Vector(1, 0, 0), 90)
        rot2 = App.Rotation(App.Vector(0, 0, 1), 90 + tilt)

        pl.Rotation = rot2.multiply(rot1)
        left.Placement = pl

        # RIGHT (+X)
        right = self._ellipsoid_Right
        right.Radius1 = a
        right.Radius2 = b
        right.Radius3 = b2

        pl = App.Placement()
        pl.Base = App.Vector(split / 2.0, 0, 0)

        rot1 = App.Rotation(App.Vector(1, 0, 0), 90)
        rot2 = App.Rotation(App.Vector(0, 0, 1), 90 - tilt)

        pl.Rotation = rot2.multiply(rot1)
        right.Placement = pl

    def _rebuild(self, obj):

        self._ensure_features(obj)

        self._update_cube(obj)
        self._update_ellipsoids(obj)

        c = focus_distance(
            float(obj.A),
            float(obj.B),
        )

        obj.FocusDistance = c

        obj.Ellipsoid1FocusX = -float(obj.SplitOffset) / 2.0
        obj.Ellipsoid2FocusX = float(obj.SplitOffset) / 2.0
        obj.MirrorPlaneX = 0.0

        obj.Document.recompute()

    def _rebuild_old(self, obj):
        self._ensure_features(obj)

        return
        old_placement = obj.Placement.copy()

        width = float(obj.Width)
        height = float(obj.Height)
        split = float(obj.SplitOffset)
        a = float(obj.A)
        b = float(obj.B)

        if width <= 0 or height <= 0:
            raise ValueError("Width and Height must be greater than zero.")
        if split < 0:
            raise ValueError("SplitOffset must not be negative.")
        if split > width:
            raise ValueError("SplitOffset cannot be greater than Width.")
        if a <= 0 or b <= 0:
            raise ValueError("A and B must be greater than zero.")
        if a < b:
            raise ValueError("A must be greater than or equal to B.")

        b2 = float(obj.B2) if obj.UseIndependentRadius3 else b
        if b2 <= 0:
            raise ValueError("B2 must be greater than zero.")

        c = focus_distance(a, b)
        depth = 1.5 * b
        cube = make_centered_cube(width, depth, height, x=0, y=depth / 2, z=0)

        focus1_x = -split / 2.0
        focus2_x = split / 2.0

        doc = obj.Document
        tmp1, ellipsoid1 = create_ellipsoid(doc, a, b, b2, "_OBA_WhiteCell_EllipsoidTmp1", "_OBA White Cell temporary ellipsoid 1")
        tmp2, ellipsoid2 = create_ellipsoid(doc, a, b, b2, "_OBA_WhiteCell_EllipsoidTmp2", "_OBA White Cell temporary ellipsoid 2")

        try:
            ellipsoid1.translate(App.Vector(split / 2.0, 0.0, 0.0))
            ellipsoid1.rotate(App.Vector(split / 2.0, 0.0, 0.0), App.Vector(1.0, 0.0, 0.0), 90.0)
            ellipsoid1.rotate(App.Vector(split / 2.0, 0.0, 0.0), App.Vector(0.0, 0.0, 1.0), 90.0 - float(obj.TiltAngle))

            ellipsoid2.translate(App.Vector(-split / 2.0, 0.0, 0.0))
            ellipsoid2.rotate(App.Vector(-split / 2.0, 0.0, 0.0), App.Vector(1.0, 0.0, 0.0), 90.0)
            ellipsoid2.rotate(App.Vector(-split / 2.0, 0.0, 0.0), App.Vector(0.0, 0.0, 1.0), 90.0 + float(obj.TiltAngle))

            self._ellipsoid_Left = ellipsoid1.copy()
            self._ellipsoid_Right = ellipsoid2.copy()

            try:
                ellipsoids = ellipsoid1.fuse(ellipsoid2)
            except Exception:
                ellipsoids = ellipsoid1.multiFuse([ellipsoid2])

            try:
                shape = cube.cut(ellipsoids)
            except Exception:
                shape = cube.cut(ellipsoid1).cut(ellipsoid2)

            try:
                shape = shape.removeSplitter()
            except Exception:
                pass

            obj.Shape = shape
            obj.FocusDistance = c
            obj.Ellipsoid1FocusX = focus1_x
            obj.Ellipsoid2FocusX = focus2_x
            obj.MirrorPlaneX = 0.0

            was_updating = self._updating
            self._updating = True
            try:
                obj.Placement = old_placement
            finally:
                self._updating = was_updating
        finally:
            remove_objects(doc, [tmp1.Name, tmp2.Name])

    def _update_debug(self, obj):
        if obj.ShowDebugEllipsoid:
            # Keep the two source surfaces separately visible.
            for index, shape in enumerate((self._ellipsoid_Left, self._ellipsoid_Right), start=1):
                if shape is None:
                    continue
                name = f"{obj.Name}_DebugEllipsoid{index}"
                dbg = obj.Document.getObject(name)
                if dbg is None:
                    dbg = obj.Document.addObject("Part::Feature", name)
                dbg.Shape = shape.copy()

                split = float(obj.SplitOffset)
                if index == 1:
                    dbg.Placement.Base = obj.Placement.Base + App.Vector(split / 2.0, 0.0, 0.0)
                else:
                    dbg.Placement.Base = obj.Placement.Base + App.Vector(-split / 2.0, 0.0, 0.0)

                dbg.ViewObject.Transparency = 80
                dbg.ViewObject.ShapeColor = (1.0, 0.0, 0.0) if index == 1 else (0.0, 0.0, 1.0)

        else:
            remove_objects(obj.Document, [f"{obj.Name}_DebugEllipsoid1", f"{obj.Name}_DebugEllipsoid2"])

    def onChanged(self, obj, prop):
        if getattr(self, "_initializing", False):
            return

        if prop in (
            "Width",
            "Height",
            "SplitOffset",
            "A",
            "B",
            "UseIndependentRadius3",
            "B2",
            "TiltAngle",
        ):
            try:
                self._rebuild(obj)
                self._update_debug(obj)
            except Exception as exc:
                App.Console.PrintError(f"[OBA] White Cell rebuild failed: {exc}\n")
        elif prop == "Placement":
            self._update_debug(obj)
        elif prop == "ShowDebugEllipsoid":
            self._update_debug(obj)

        super().onChanged(obj, prop)

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self.Object = obj
        install_properties(obj, WHITE_CELL_PROPERTIES)
        ensure_debug_property(obj)
        obj.setEditorMode("FocusDistance", 1)
        make_calculated_length(obj, "Ellipsoid1FocusX", "X position of first ellipsoid focus")
        make_calculated_length(obj, "Ellipsoid2FocusX", "X position of second ellipsoid focus")
        make_calculated_length(obj, "MirrorPlaneX", "X coordinate of mirror symmetry plane")
        make_optical_type(obj, "WhiteCellMainMirror")

        restore_view_provider(obj, MainMirrorViewProvider)
        # if App.GuiUp and obj.ViewObject:
        #     if not hasattr(obj.ViewObject, "Proxy") or obj.ViewObject.Proxy is None:
        #         MainMirrorViewProvider(obj.ViewObject)
        #     else:
        #         obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)
        #         obj.ViewObject.Proxy.dialog_class = MainMirrorDialog
        #     obj.ViewObject.update()

    def onDelete(self, obj, subelements):
        remove_objects(
            obj.Document,
            [
                f"{obj.Name}_DebugEllipsoid1",
                f"{obj.Name}_DebugEllipsoid2",
            ],
        )
        return True

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class MainMirrorDialog(OBAToolboxDialogBase):
    def __init__(self, obj, title="White Cell Main Mirror Settings", parent=None):
        super().__init__(obj, title=title, parent=parent)

        group = QtWidgets.QGroupBox("White Cell Main Mirror Parameters")
        form = QtWidgets.QFormLayout(group)

        self.width = self._add_spin("Width", "Width", 0, 1000, "mm", form)
        self.height = self._add_spin("Height", "Height", 0, 1000, "mm", form)
        self.split = self._add_spin("SplitOffset", "SplitOffset", 0, 1000, "mm", form)
        self.a = self._add_spin("A", "A", 0, 1000, "mm", form)
        self.b = self._add_spin("B", "B", 0, 1000, "mm", form)

        self.use_b2 = QtWidgets.QCheckBox("Use independent Radius3")
        form.addWidget(self.use_b2)
        self.b2 = self._add_spin("B2", "B2", 0, 1000, "mm", form)
        self.tiltangle = self._add_spin("Tilt angle", "TiltAngle", -90, 90, "°", form)

        self.c = QtWidgets.QLabel()
        self.focus1 = QtWidgets.QLabel()
        self.focus2 = QtWidgets.QLabel()
        self.left_angle = QtWidgets.QLabel()
        self.right_angle = QtWidgets.QLabel()

        form.addRow("Focus distance C", self.c)
        form.addRow("Ellipsoid 1 focus X", self.focus1)
        form.addRow("Ellipsoid 2 focus X", self.focus2)
        form.addRow("Left ellipsoid angle", self.left_angle)
        form.addRow("Right ellipsoid angle", self.right_angle)

        self.custom_layout.addWidget(group)
        self.add_debug_checkbox("Show debug ellipsoids")
        self.add_placement_group()

        info = QtWidgets.QLabel("The two ellipsoids are mirrored around the centre plane of " "the white cell.\n\n" "SplitOffset is the distance between the two ellipsoid focal " "points.\n\n" "TiltAngle is the symmetric tilt of the ellipsoids.")
        info.setWordWrap(True)
        self.custom_layout.addWidget(info)

        for w in (
            self.width,
            self.height,
            self.split,
            self.a,
            self.b,
            self.tiltangle,
            self.b2,
        ):
            w.valueChanged.connect(self._preview)
        self.use_b2.toggled.connect(self._use_b2_changed)

        self.reload()

    def _use_b2_changed(self, checked):
        self.obj.UseIndependentRadius3 = checked
        self._preview()

    def reload(self):
        self.use_b2.setChecked(bool(self.obj.UseIndependentRadius3))
        self.reload_placement()
        self._preview()

    def _preview(self):
        width = float(self.obj.Width)
        height = float(self.obj.Height)
        split = float(self.obj.SplitOffset)
        a = float(self.obj.A)
        b = float(self.obj.B)

        valid = width > 0 and height > 0 and 0 <= split <= width and a > 0 and b > 0 and a >= b

        if a > 0 and b > 0 and a >= b:
            self.c.setText(f"{math.sqrt(max(0.0, a*a-b*b)):.4f} mm")
        else:
            self.c.setText("Invalid A/B")

        self.focus1.setText(f"{-split / 2.0:.4f} mm")
        self.focus2.setText(f"{split / 2.0:.4f} mm")

        tilt = float(self.obj.TiltAngle)
        self.left_angle.setText(f"{90 - tilt:.3f}°")
        self.right_angle.setText(f"{90 + tilt:.3f}°")

        self.b2.setEnabled(self.use_b2.isChecked())
        if self.use_b2.isChecked() and float(self.obj.B2) <= 0:
            valid = False

        return valid


class MainMirrorViewProvider(OBAToolboxViewProviderBase):
    dialog_class = MainMirrorDialog

    def __init__(self, vobj):
        super().__init__(vobj, MainMirrorDialog)

    def attach(self, vobj):
        # 1. Anropa ALLTID super så att OBAViewProviderBase kan sätta upp sina preview-roots
        super().attach(vobj)
        # 2. Sätt dina lokala referenser (valfritt, då super oftast redan gör detta)
        self.ViewObject = vobj
        self.Object = vobj.Object

    def claimChildren(self):
        proxy = self.Object.Proxy
        if proxy._internal:
            return [proxy._internal]

        return []


def OBA_CreateMainMirror(
    doc=None,
    label="Main_Mirror",
    width=100.0,
    height=30.0,
    split_offset=40.0,
    a=40.0,
    b=30.0,
    tiltangle=0.0,
    x=0.0,
    y=30,
    z=0.0,
    placement=None,
    show_dialog=True,
):
    doc = doc or App.ActiveDocument or App.newDocument()

    if width <= 0 or height <= 0:
        raise ValueError("Width and Height must be greater than zero.")
    if split_offset < 0 or split_offset > width:
        raise ValueError("SplitOffset must be between zero and Width.")
    if a <= 0 or b <= 0:
        raise ValueError("A and B must be greater than zero.")
    if a < b:
        raise ValueError("A must be greater than or equal to B.")

    obj = doc.addObject("Part::FeaturePython", "OBAWhiteCellMainMirror")

    # obj = doc.addObject("App::Part", "OBAWhiteCellMainMirror")
    obj.Label = label
    OBAWhiteCell(obj)

    obj.Width = App.Units.Quantity(f"{width} mm")
    obj.Height = App.Units.Quantity(f"{height} mm")
    obj.SplitOffset = App.Units.Quantity(f"{split_offset} mm")
    obj.A = App.Units.Quantity(f"{a} mm")
    obj.B = App.Units.Quantity(f"{b} mm")
    obj.TiltAngle = App.Units.Quantity(f"{tiltangle} deg")

    if placement is None:
        placement = App.Placement(App.Vector(x, y, z), App.Rotation())
    obj.Placement = placement

    if App.GuiUp:
        MainMirrorViewProvider(obj.ViewObject)

    doc.recompute()

    if show_dialog:
        MainMirrorDialog(obj).show()
    return obj


def create(
    doc=None,
    label="Main_Mirror",
    width=100.0,
    height=30.0,
    split_offset=40.0,
    a=40.0,
    b=30.0,
    tiltangle=0.0,
    x=0,
    y=30,
    z=0,
):

    return OBA_CreateMainMirror(
        doc=doc,
        label=label,
        width=width,
        height=height,
        split_offset=split_offset,
        a=a,
        b=b,
        tiltangle=tiltangle,
        x=x,
        y=y,
        z=z,
        show_dialog=False,
    )
