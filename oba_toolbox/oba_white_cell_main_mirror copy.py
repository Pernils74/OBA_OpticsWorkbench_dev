# oba_white_cell_main_mirror.py
#
# OBA White Cell Main Mirror / Split Mirror
#
# Geometry:
#   - One rectangular cube/body
#   - Two identical ellipsoids
#   - The ellipsoids are mirrored around the cube centre plane
#   - Both ellipsoids are subtracted from the cube
#
# The ellipsoids use the same coordinate convention as oba_ellipsoid.py:
#
#   A = semi-major axis
#   B = semi-minor axis
#   C = sqrt(A^2 - B^2)
#
# The local origin of each ellipsoid is one focal point.
#
# Parameters:
#
#   Placement
#       Position of the complete white cell
#
#   Width
#       Cube width along X
#
#   Height
#       Cube height along Z
#
#   SplitOffset
#       Distance between the two ellipsoid focal points
#
#   A
#       Ellipsoid semi-major axis
#
#   B
#       Ellipsoid semi-minor radius
#
#   UseIndependentRadius3
#       Optional independent Y radius
#
#   B2
#       Independent Y radius when enabled
#
# ============================================================


import math
from posixpath import split


import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtWidgets


from oba_objects.oba_base import (
    OBABaseDialog,
    OBAElementProxy,
    OBAViewProviderBase,
    _trigger_ray_engine,
)

# ============================================================
#  P R O P E R T I E S
# ============================================================


WHITE_CELL_PROPERTIES = [
    {
        "name": "Width",
        "type": "App::PropertyLength",
        "group": "White Cell",
        "default": 100.0,
        "doc": "Width of the cube/body along X",
    },
    {
        "name": "Height",
        "type": "App::PropertyLength",
        "group": "White Cell",
        "default": 30.0,
        "doc": "Height of the cube/body along Z",
    },
    {
        "name": "SplitOffset",
        "type": "App::PropertyLength",
        "group": "White Cell",
        "default": 40.0,
        "doc": "Distance between the two ellipsoid focal points",
    },
    {
        "name": "A",
        "type": "App::PropertyLength",
        "group": "Ellipsoid",
        "default": 40.0,
        "doc": "Ellipsoid semi-major axis",
    },
    {
        "name": "B",
        "type": "App::PropertyLength",
        "group": "Ellipsoid",
        "default": 30.0,
        "doc": "Ellipsoid semi-minor radius",
    },
    {
        "name": "UseIndependentRadius3",
        "type": "App::PropertyBool",
        "group": "Ellipsoid",
        "default": False,
        "doc": "Use independent radius in Y direction",
    },
    {
        "name": "B2",
        "type": "App::PropertyLength",
        "group": "Ellipsoid",
        "default": 20.0,
        "doc": "Independent ellipsoid Y radius",
    },
    {
        "name": "FocusDistance",
        "type": "App::PropertyLength",
        "group": "Ellipsoid",
        "default": 26.4575131106,
        "doc": "Distance from ellipsoid centre to focus",
    },
    {
        "name": "TiltAngle",
        "type": "App::PropertyAngle",
        "group": "Ellipsoid",
        "default": 0.0,
        "doc": "Tilt angle of the ellipsoids around the Z axis",
    },
    {
        "name": "ShowDebugEllipsoids",
        "type": "App::PropertyBool",
        "group": "Debug",
        "default": False,
        "doc": "Show debug ellipsoids",
    },
]


# ============================================================
#  O B J E C T
# ============================================================


class OBAWhiteCellMainMirror(OBAElementProxy):

    def __init__(self, obj):

        self._initializing = True
        self._updating = False

        # --------------------------------------------------------
        # Base OBA object.
        # --------------------------------------------------------

        super().__init__(obj, use_binders=False)

        # --------------------------------------------------------
        # Properties.
        # --------------------------------------------------------

        for p in WHITE_CELL_PROPERTIES:

            if not hasattr(obj, p["name"]):

                obj.addProperty(p["type"], p["name"], p["group"], p.get("doc", ""))

                setattr(obj, p["name"], p["default"])

                if p["name"] == "FocusDistance":

                    obj.setEditorMode("FocusDistance", 1)

        # --------------------------------------------------------
        # Optical type.
        # --------------------------------------------------------

        if not hasattr(obj, "OpticalType"):

            obj.addProperty(
                "App::PropertyString",
                "OpticalType",
                "Base",
                "Type of optical element",
            )

        obj.OpticalType = "WhiteCellMainMirror"

        # --------------------------------------------------------
        # Calculated geometry information.
        # --------------------------------------------------------

        if not hasattr(obj, "Ellipsoid1FocusX"):

            obj.addProperty(
                "App::PropertyLength",
                "Ellipsoid1FocusX",
                "Calculated",
                "X position of first ellipsoid focus",
            )

            obj.setEditorMode("Ellipsoid1FocusX", 1)

        if not hasattr(obj, "Ellipsoid2FocusX"):

            obj.addProperty(
                "App::PropertyLength",
                "Ellipsoid2FocusX",
                "Calculated",
                "X position of second ellipsoid focus",
            )

            obj.setEditorMode("Ellipsoid2FocusX", 1)

        if not hasattr(obj, "MirrorPlaneX"):
            obj.addProperty(
                "App::PropertyLength",
                "MirrorPlaneX",
                "Calculated",
                "X coordinate of mirror symmetry plane",
            )

            obj.setEditorMode("MirrorPlaneX", 1)

        self._initializing = False

    # ========================================================
    #  F O C U S
    # ========================================================

    @staticmethod
    def focus_distance(a, b):
        """
        Calculate distance from ellipsoid centre to focus.

            C = sqrt(A² - B²)
        """

        if a <= 0 or b <= 0:
            raise ValueError("A and B must be greater than zero.")

        if a < b:
            raise ValueError("A must be greater than or equal to B.")

        return math.sqrt(
            max(
                0.0,
                a * a - b * b,
            )
        )

    # ========================================================
    #  C R E A T E   E L L I P S O I D
    # ========================================================

    @staticmethod
    def _create_ellipsoid(doc, a, b, b2):
        """
        Create a temporary FreeCAD ellipsoid.

        FreeCAD Part::Ellipsoid:
            Radius1 = Z
            Radius2 = X
            Radius3 = Y

        The ellipsoid is subsequently rotated in _rebuild().
        """
        tmp_name = "_OBA_WhiteCell_EllipsoidTmp"
        old = doc.getObject(tmp_name)
        if old is not None:
            doc.removeObject(old.Name)
            doc.recompute()

        tmp = doc.addObject("Part::Ellipsoid", tmp_name)
        tmp.Label = "_OBA White Cell temporary ellipsoid"

        # ----------------------------------------------------
        # FreeCAD Part::Ellipsoid:
        #
        # Radius1 = Z
        # Radius2 = X
        # Radius3 = Y
        # ----------------------------------------------------

        tmp.Radius1 = a
        tmp.Radius2 = b
        tmp.Radius3 = b2

        tmp.Angle1 = -90.0
        tmp.Angle2 = 90.0
        tmp.Angle3 = 360.0

        doc.recompute()
        shape = tmp.Shape.copy()
        return (tmp, shape)

    # ========================================================
    #  R E B U I L D
    # ========================================================

    def _rebuild(self, obj):

        # ----------------------------------------------------
        # Save Placement.
        # ----------------------------------------------------

        old_placement = obj.Placement.copy()

        # ----------------------------------------------------
        # Read values.
        # ----------------------------------------------------

        width = float(obj.Width)
        height = float(obj.Height)
        split = float(obj.SplitOffset)
        a = float(obj.A)
        b = float(obj.B)
        tiltangle = float(obj.TiltAngle)

        # ----------------------------------------------------
        # Validate.
        # ----------------------------------------------------

        if width <= 0:
            raise ValueError("Width must be greater than zero.")
        if height <= 0:
            raise ValueError("Height must be greater than zero.")
        if split < 0:
            raise ValueError("SplitOffset must not be negative.")
        if split > width:
            raise ValueError("SplitOffset cannot be greater than Width.")
        if a <= 0 or b <= 0:
            raise ValueError("A and B must be greater than zero.")
        if a < b:
            raise ValueError("A must be greater than or equal to B.")

        # ----------------------------------------------------
        # Radius 3.
        # ----------------------------------------------------

        if obj.UseIndependentRadius3:
            b2 = float(obj.B2)
            if b2 <= 0:
                raise ValueError("B2 must be greater than zero.")
        else:
            b2 = b

        # ----------------------------------------------------
        # Focus distance.
        # ----------------------------------------------------

        c = self.focus_distance(a, b)

        # ----------------------------------------------------
        # Cube.
        #
        # Local coordinate system:
        #
        #   X = -Width/2 ... +Width/2
        #   Y = 0 ... depth
        #   Z = -Height/2 ... +Height/2
        #
        # Keep this coordinate system because it matches the
        # current White Cell geometry.
        # ----------------------------------------------------

        depth = 1.5 * b

        cube = Part.makeBox(width, depth, height, App.Vector(-width / 2.0, 0.0, -height / 2.0))

        # ----------------------------------------------------
        # Mirror plane.
        #
        # Since the cube is centred around X = 0, the mirror
        # plane is X = 0.
        #
        # The two focal points are:
        #
        #   -SplitOffset/2
        #   +SplitOffset/2
        # ----------------------------------------------------

        mirror_x = 0.0
        focus1_x = -split / 2.0
        focus2_x = split / 2.0

        # ----------------------------------------------------
        # Temporary ellipsoid 1.
        # ----------------------------------------------------
        doc = obj.Document
        tmp1, ellipsoid1 = self._create_ellipsoid(doc, a, b, b2)

        # ----------------------------------------------------
        # First ellipsoid.
        # ----------------------------------------------------

        ellipsoid1.translate(App.Vector(split / 2.0, 0.0, 0.0))

        ellipsoid1.rotate(App.Vector(split / 2.0, 0.0, 0.0), App.Vector(1.0, 0.0, 0.0), 90.0)
        ellipsoid1.rotate(App.Vector(split / 2.0, 0.0, 0.0), App.Vector(0.0, 0.0, 1.0), 90 - tiltangle)

        # ----------------------------------------------------
        # Temporary ellipsoid 2.
        # ----------------------------------------------------

        tmp2, ellipsoid2 = self._create_ellipsoid(doc, a, b, b2)

        # ----------------------------------------------------
        # Move second ellipsoid symmetrically.
        # ----------------------------------------------------
        ellipsoid2.translate(App.Vector(-split / 2.0, 0.0, 0.0))

        ellipsoid2.rotate(App.Vector(-split / 2.0, 0.0, 0.0), App.Vector(1.0, 0.0, 0.0), 90.0)
        ellipsoid2.rotate(App.Vector(-split / 2.0, 0.0, 0.0), App.Vector(0.0, 0.0, 1.0), 90 + tiltangle)

        # spar undan shape för debugg visning
        self._ellipsoid1 = ellipsoid1.copy()
        self._ellipsoid2 = ellipsoid2.copy()

        # ----------------------------------------------------
        # Boolean.
        #
        #     Cube
        #       -
        #     (Ellipsoid1 + Ellipsoid2)
        # ----------------------------------------------------

        try:
            ellipsoids = ellipsoid1.fuse(ellipsoid2)
            shape = cube.cut(ellipsoids)
        except Exception:
            ellipsoids = ellipsoid1.multiFuse([ellipsoid2])
            shape = cube.cut(ellipsoids)
        # ----------------------------------------------------
        # Refine.
        # ----------------------------------------------------
        try:
            shape = shape.removeSplitter()
        except Exception:
            pass

        # ----------------------------------------------------
        # Assign final Shape.
        # ----------------------------------------------------

        obj.Shape = shape

        # ----------------------------------------------------
        # Calculated properties.
        # ----------------------------------------------------

        obj.FocusDistance = c
        obj.Ellipsoid1FocusX = focus1_x
        obj.Ellipsoid2FocusX = focus2_x
        obj.MirrorPlaneX = mirror_x

        # ----------------------------------------------------
        # Restore exact Placement.
        # ----------------------------------------------------

        was_updating = getattr(self, "_updating", False)

        self._updating = True
        try:
            obj.Placement = old_placement
        finally:
            self._updating = was_updating

        # ----------------------------------------------------
        # Remove temporary Part::Ellipsoid objects.
        # ----------------------------------------------------

        for tmp in (tmp1, tmp2):
            if tmp is not None:
                try:
                    doc.removeObject(tmp.Name)
                except Exception:
                    pass
        try:
            doc.recompute()
        except Exception:
            pass
        # self.showDebuggElipsoids(obj)

    def showDebuggElipsoids(self, obj):
        import traceback

        if not obj.ShowDebugEllipsoids:
            self.removeDebugEllipsoids(obj)
            return
        # ----------------------------------------------------
        # Debug visning av ellipsoider
        # ----------------------------------------------------

        try:
            doc = obj.Document
            dbg1 = doc.getObject(f"{obj.Name}_DebugEllipsoid1")
            if dbg1 is None:
                dbg1 = doc.addObject("Part::Feature", f"{obj.Name}_DebugEllipsoid1")

            dbg2 = doc.getObject(f"{obj.Name}_DebugEllipsoid2")
            if dbg2 is None:
                dbg2 = doc.addObject("Part::Feature", f"{obj.Name}_DebugEllipsoid2")

            dbg1.Shape = self._ellipsoid1.copy()
            dbg2.Shape = self._ellipsoid2.copy()

            dbg1.ViewObject.Transparency = 80
            dbg2.ViewObject.Transparency = 80

            dbg1.ViewObject.ShapeColor = (1.0, 0.0, 0.0)  # röd
            dbg2.ViewObject.ShapeColor = (0.0, 0.0, 1.0)  # blå

            split = float(obj.SplitOffset)

            dbg1.Placement.Base = obj.Placement.Base + App.Vector(split / 2, 0, 0)
            dbg2.Placement.Base = obj.Placement.Base + App.Vector(-split / 2, 0, 0)

        except Exception:
            traceback.print_exc("[showDebuggElipsoids]")
            pass

    def removeDebugEllipsoids(self, obj):
        """
        Remove debug ellipsoids belonging to this White Cell.
        """
        doc = obj.Document
        for name in (f"{obj.Name}_DebugEllipsoid1", f"{obj.Name}_DebugEllipsoid2"):
            dbg = doc.getObject(name)
            if dbg is not None:
                try:
                    doc.removeObject(dbg.Name)
                except Exception:
                    pass
        try:
            doc.recompute()
        except Exception:
            pass

    # ========================================================
    #  C H A N G E D
    # ========================================================

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
                self.showDebuggElipsoids(obj)
            except Exception as exc:
                App.Console.PrintError(f"[OBA] White Cell rebuild failed: {exc}\n")
                return

        elif prop == "Placement":
            self.showDebuggElipsoids(obj)

        elif prop == "ShowDebugEllipsoids":
            if obj.ShowDebugEllipsoids:
                self.showDebuggElipsoids(obj)
            else:
                self.removeDebugEllipsoids(obj)

        super().onChanged(obj, prop)

    # ========================================================
    #  D O C U M E N T   R E S T O R E D
    # ========================================================

    def onDocumentRestored(self, obj):
        # ----------------------------------------------------
        # Restore proxy.
        # ----------------------------------------------------
        obj.Proxy = self
        self.Object = obj
        # ----------------------------------------------------
        # Restore properties.
        # ----------------------------------------------------

        for p in WHITE_CELL_PROPERTIES:
            if not hasattr(obj, p["name"]):

                obj.addProperty(
                    p["type"],
                    p["name"],
                    p["group"],
                    p.get("doc", ""),
                )

                setattr(obj, p["name"], p["default"])
                if p["name"] == "FocusDistance":
                    obj.setEditorMode("FocusDistance", 1)

        # ----------------------------------------------------
        # Calculated properties.
        # ----------------------------------------------------

        if not hasattr(obj, "Ellipsoid1FocusX"):
            obj.addProperty(
                "App::PropertyLength",
                "Ellipsoid1FocusX",
                "Calculated",
                "X position of first ellipsoid focus",
            )

            obj.setEditorMode("Ellipsoid1FocusX", 1)

        if not hasattr(obj, "Ellipsoid2FocusX"):
            obj.addProperty(
                "App::PropertyLength",
                "Ellipsoid2FocusX",
                "Calculated",
                "X position of second ellipsoid focus",
            )

            obj.setEditorMode("Ellipsoid2FocusX", 1)

        if not hasattr(obj, "MirrorPlaneX"):
            obj.addProperty(
                "App::PropertyLength",
                "MirrorPlaneX",
                "Calculated",
                "X coordinate of mirror symmetry plane",
            )
            obj.setEditorMode("MirrorPlaneX", 1)

        # ----------------------------------------------------
        # Optical type.
        # ----------------------------------------------------

        if not hasattr(obj, "OpticalType"):
            obj.addProperty(
                "App::PropertyString",
                "OpticalType",
                "Base",
                "Type of optical element",
            )
        obj.OpticalType = "WhiteCellMainMirror"

        # ----------------------------------------------------
        # Restore ViewProvider.
        # ----------------------------------------------------

        if App.GuiUp and obj.ViewObject:
            if not hasattr(obj.ViewObject, "Proxy") or obj.ViewObject.Proxy is None:
                WhiteCellMainMirrorViewProvider(obj.ViewObject)
            else:

                obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)
                obj.ViewObject.Proxy.dialog_class = WhiteCellMainMirrorDialog
            obj.ViewObject.update()

    # ========================================================
    #  D E L E T E
    # ========================================================

    def onDelete(self, obj, subelements):
        return True

    # ========================================================
    #  P I C K L E
    # ========================================================

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


# ============================================================
#  D I A L O G
# ============================================================


class WhiteCellMainMirrorDialog(OBABaseDialog):

    ALLOW_SURFACE_SELECTION = False

    def __init__(self, obj, title="White Cell Main Mirror Settings", parent=None):

        super().__init__(obj, title=title, parent=parent)
        self._closing = False

        # ====================================================
        #  W H I T E   C E L L
        # ====================================================

        group = QtWidgets.QGroupBox("White Cell")

        form_layout = QtWidgets.QFormLayout(group)

        self.width = self._add_spin("Width", "Width", 0, 1000, "mm", form_layout)
        self.height = self._add_spin("Height", "Height", 0, 1000, "mm", form_layout)
        self.split = self._add_spin("SplitOffset", "SplitOffset", 0, 1000, "mm", form_layout)
        self.a = self._add_spin("A", "A", 0, 1000, "mm", form_layout)
        self.b = self._add_spin("B", "B", 0, 1000, "mm", form_layout)

        # Kryssruta för oberoende Radius3 (läggs till direkt i layouten)
        self.use_b2 = QtWidgets.QCheckBox("Use independent Radius3")
        form_layout.addWidget(self.use_b2)

        # B2 och TiltAngle
        self.b2 = self._add_spin("B2", "B2", 0, 1000, "mm", form_layout)
        self.tiltangle = self._add_spin("Tilt angle", "TiltAngle", -90, 90, "°", form_layout)

        # ----------------------------------------------------
        # Labels
        # ----------------------------------------------------

        self.c = QtWidgets.QLabel()
        self.focus1 = QtWidgets.QLabel()
        self.focus2 = QtWidgets.QLabel()
        self.left_angle = QtWidgets.QLabel()
        self.right_angle = QtWidgets.QLabel()

        form_layout.addRow("Focus distance C", self.c)
        form_layout.addRow("Ellipsoid 1 focus X", self.focus1)
        form_layout.addRow("Ellipsoid 2 focus X", self.focus2)
        form_layout.addRow("Left ellipsoid angle", self.left_angle)
        form_layout.addRow("Right ellipsoid angle", self.right_angle)

        self.custom_layout.addWidget(group)

        self.show_debug = QtWidgets.QCheckBox("Show debug ellipsoids")
        self.show_debug.setChecked(bool(self.obj.ShowDebugEllipsoids))
        self.show_debug.toggled.connect(lambda v: setattr(self.obj, "ShowDebugEllipsoids", v))
        form_layout.addWidget(self.show_debug)

        # ====================================================
        #  P L A C E M E N T
        # ====================================================

        placement_group = QtWidgets.QGroupBox("Placement")
        placement_form = QtWidgets.QFormLayout(placement_group)

        self.pos_x = self._create_spinbox(" mm", changed=self._placement_changed)
        self.pos_y = self._create_spinbox(" mm", changed=self._placement_changed)
        self.pos_z = self._create_spinbox(" mm", changed=self._placement_changed)

        placement_form.addRow("X", self.pos_x)
        placement_form.addRow("Y", self.pos_y)
        placement_form.addRow("Z", self.pos_z)

        self.custom_layout.addWidget(placement_group)

        # ====================================================
        #  I N F O
        # ====================================================

        info = QtWidgets.QLabel("""
            The two ellipsoids are mirrored around the centre plane of the white cell.

            SplitOffset is the distance between the two ellipsoid focal points.

            TiltAngle
                Symmetric tilt of the ellipsoids relative
                to the White Cell centre axis.
            """)

        info.setWordWrap(True)
        self.custom_layout.addWidget(info)

        # ====================================================
        #  B U T T O N S
        # ====================================================

        # buttons = QtWidgets.QHBoxLayout()
        # self.custom_layout.addLayout(buttons)

        # ====================================================
        #  S I G N A L S
        # ====================================================

        self.width.valueChanged.connect(self._preview)
        self.height.valueChanged.connect(self._preview)
        self.split.valueChanged.connect(self._preview)
        self.a.valueChanged.connect(self._preview)
        self.b.valueChanged.connect(self._preview)
        self.tiltangle.valueChanged.connect(self._preview)
        self.use_b2.toggled.connect(self._use_b2_changed)

        self.b2.valueChanged.connect(self._preview)

        # ====================================================
        #  L O A D
        # ====================================================

        self.reload()

    def _use_b2_changed(self, checked):
        self.obj.UseIndependentRadius3 = checked
        self._preview

    def _placement_changed(self):
        placement = self.obj.Placement.copy()
        placement.Base = App.Vector(self.pos_x.value(), self.pos_y.value(), self.pos_z.value())
        self.obj.Placement = placement

    @staticmethod
    def _create_spinbox(suffix="", minimum=-1_000_000.0, maximum=1_000_000.0, decimals=4, step=1.0, changed=None):
        spin = QtWidgets.QDoubleSpinBox()

        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        if changed:
            spin.valueChanged.connect(changed)
        return spin

    def _add_spin(self, label, prop, mn, mx, unit, layout):
        w = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")

        w.setProperty("minimum", mn)
        w.setProperty("maximum", mx)
        w.setProperty("unit", unit)

        current_val = getattr(self.obj, prop)
        w.setProperty("rawValue", float(current_val))
        w.setProperty("binding", f"{self.obj.Name}.{prop}")

        w.valueChanged.connect(lambda v, p=prop: setattr(self.obj, p, v.Value))

        layout.addRow(label, w)

        return w

    # ========================================================
    #  C L O S E
    # ========================================================

    def closeEvent(self, event):

        if self._closing:
            event.accept()
            return

        self._closing = True
        self.obj.Document.recompute()
        Gui.updateGui()
        # ----------------------------------------------------
        # Let OBA base perform its normal close handling.
        # ----------------------------------------------------
        super().closeEvent(event)

    # ========================================================
    #  R E L O A D
    # ========================================================

    def reload(self):

        self.use_b2.setChecked(bool(self.obj.UseIndependentRadius3))

        placement = self.obj.Placement.Base
        self.pos_x.setValue(placement.x)
        self.pos_y.setValue(placement.y)
        self.pos_z.setValue(placement.z)

        self._preview()

    # ========================================================
    #  P R E V I E W
    # ========================================================

    def _preview(self):

        width = float(self.obj.Width)
        height = float(self.obj.Height)
        split = float(self.obj.SplitOffset)
        a = float(self.obj.A)
        b = float(self.obj.B)

        valid = True

        # ----------------------------------------------------
        # Validate.
        # ----------------------------------------------------

        if width <= 0:
            valid = False
        if height <= 0:
            valid = False
        if split < 0:
            valid = False
        if split > width:
            valid = False
        if a <= 0 or b <= 0:
            valid = False
        if a < b:
            self.c.setText("Invalid: A must be ≥ B")
            valid = False
        else:
            c = math.sqrt(max(0.0, a * a - b * b))
            self.c.setText(f"{c:.4f} mm")

        # ----------------------------------------------------
        # Focus positions.
        # ----------------------------------------------------

        focus1 = -split / 2.0
        focus2 = split / 2.0

        self.focus1.setText(f"{focus1:.4f} mm")
        self.focus2.setText(f"{focus2:.4f} mm")

        # tilt = self.tiltangle.value()
        tilt = float(self.obj.TiltAngle)

        self.left_angle.setText(f"{90 - tilt:.3f}°")
        self.right_angle.setText(f"{90 + tilt:.3f}°")

        # ----------------------------------------------------
        # B2.
        # ----------------------------------------------------

        self.b2.setEnabled(self.use_b2.isChecked())
        if self.use_b2.isChecked():
            if float(self.obj.B2) <= 0:
                valid = False

        # self.apply_button.setEnabled(valid)

    # ========================================================
    #  A P P L Y
    # ========================================================


# ============================================================
#  V I E W   P R O V I D E R
# ============================================================


class WhiteCellMainMirrorViewProvider(OBAViewProviderBase):

    dialog_class = WhiteCellMainMirrorDialog

    def __init__(self, vobj):

        super().__init__(vobj)
        self.dialog_class = WhiteCellMainMirrorDialog
        try:
            vobj.DisplayMode = "Flat Lines"
        except Exception:
            pass

    def onDocumentRestored(self, vobj):
        super().onDocumentRestored(vobj)
        self.dialog_class = WhiteCellMainMirrorDialog


# ============================================================
#  C R E A T E
# ============================================================


def OBA_CreateWhiteCellMainMirror(
    doc=None,
    label="White Cell Main Mirror",
    width=100.0,
    height=30.0,
    split_offset=40.0,
    a=40.0,
    b=30.0,
    tiltangle=0.0,
    placement=None,
    show_dialog=True,
):
    """
    Create an OBA White Cell Main Mirror.

    Parameters
    ----------
    width:
        Cube width along X.

    height:
        Cube height along Z.

    split_offset:
        Distance between the two ellipsoid focal points.

    a:
        Ellipsoid semi-major axis.

    b:
        Ellipsoid semi-minor radius.

    placement:
        Optional App.Placement for the complete object.

    show_dialog:
        If True, open the settings dialog.
    """

    # --------------------------------------------------------
    # Document.
    # --------------------------------------------------------

    doc = doc or App.ActiveDocument or App.newDocument()

    # --------------------------------------------------------
    # Validate.
    # --------------------------------------------------------

    if width <= 0:
        raise ValueError("Width must be greater than zero.")
    if height <= 0:
        raise ValueError("Height must be greater than zero.")
    if split_offset < 0:
        raise ValueError("SplitOffset must not be negative.")
    if split_offset > width:
        raise ValueError("SplitOffset cannot be greater than Width.")
    if a <= 0 or b <= 0:
        raise ValueError("A and B must be greater than zero.")
    if a < b:
        raise ValueError("A must be greater than or equal to B.")

    # --------------------------------------------------------
    # Create FeaturePython object.
    # --------------------------------------------------------

    obj = doc.addObject("Part::FeaturePython", "OBAWhiteCellMainMirror")

    obj.Label = label

    # --------------------------------------------------------
    # Proxy.
    # --------------------------------------------------------

    OBAWhiteCellMainMirror(obj)

    # --------------------------------------------------------
    # Initial properties.
    # --------------------------------------------------------

    obj.Width = App.Units.Quantity(f"{width} mm")
    obj.Height = App.Units.Quantity(f"{height} mm")
    obj.SplitOffset = App.Units.Quantity(f"{split_offset} mm")
    obj.A = App.Units.Quantity(f"{a} mm")
    obj.B = App.Units.Quantity(f"{b} mm")
    obj.TiltAngle = App.Units.Quantity(f"{tiltangle} deg")

    # --------------------------------------------------------
    # Placement.
    # --------------------------------------------------------

    if placement is None:
        placement = App.Placement(App.Vector(0.0, 0.0, 0.0), App.Rotation())

    obj.Placement = placement

    # --------------------------------------------------------
    # ViewProvider.
    # --------------------------------------------------------

    if App.GuiUp:

        WhiteCellMainMirrorViewProvider(obj.ViewObject)

    # --------------------------------------------------------
    # Recompute.
    # --------------------------------------------------------

    doc.recompute()

    # --------------------------------------------------------
    # Display.
    # --------------------------------------------------------

    try:

        obj.ViewObject.DisplayMode = "Flat Lines"
    except Exception:
        pass

    # --------------------------------------------------------
    # Show dialog.
    # --------------------------------------------------------

    if show_dialog:
        WhiteCellMainMirrorDialog(obj).show()
    return obj


# ============================================================
#  C O N V E N I E N C E   F U N C T I O N
# ============================================================


def create(
    doc=None,
    label="White Cell Main Mirror",
    width=100.0,
    height=30.0,
    split_offset=40.0,
    a=40.0,
    b=30.0,
    tiltangle=0.0,
):
    """
    Convenience function for the FreeCAD Python console.
    """

    return OBA_CreateWhiteCellMainMirror(
        doc=doc,
        label=label,
        width=width,
        height=height,
        split_offset=split_offset,
        a=a,
        b=b,
        tiltangle=tiltangle,
        show_dialog=False,
    )
