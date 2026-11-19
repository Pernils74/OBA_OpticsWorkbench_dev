# oba_v_cell.py


import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtWidgets

from .oba_toolbox_base import (
    OBAToolboxDialogBase,
    OBAToolboxViewProviderBase,
    install_properties,
    make_optical_type,
    restore_view_provider,
    set_quantity_if_changed,
)

from .oba_comp_mirror import OBA_CreateCompMirror
from .oba_ellipsoid import OBA_CreateEllipsoid

from OPTIMIZER.optimize_worker import is_optimization_running
from OPTIMIZER.optuna_plotting import OptunaPlotWindow
from .xgboost_parameter_optimizer_dialog import XGBoostParameterOptimizerDialog

# ======================================================================
# P R O P E R T I E S
# ======================================================================

V_CELL_PROPERTIES = [
    # ==============================================================
    # CHILD OBJECTS
    # ==============================================================
    {"name": "CompMirror", "type": "App::PropertyLink", "group": "Child objects", "visible": False, "doc": "Comp Mirror belonging to this V Cell"},
    {"name": "Emitter", "type": "App::PropertyLink", "group": "Child objects", "visible": False, "doc": "Emitter ellipsoid belonging to this V Cell"},
    {"name": "Detector", "type": "App::PropertyLink", "group": "Child objects", "visible": False, "doc": "Detector ellipsoid belonging to this V Cell"},
    # ==============================================================
    # COMP MIRROR
    # ==============================================================
    {"name": "CompMirrorWidth", "label": "Width", "type": "App::PropertyLength", "group": "Comp Mirror", "parent_group": "Mirrors", "default": 30.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True, "step": 1},
    {"name": "CompMirrorHeight", "label": "Height", "type": "App::PropertyLength", "group": "Comp Mirror", "parent_group": "Mirrors", "default": 9.5, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True},
    {"name": "CompMirrorA", "label": "A_", "type": "App::PropertyLength", "group": "Comp Mirror", "parent_group": "Mirrors", "default": 20.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    {"name": "CompMirrorB", "label": "B_", "type": "App::PropertyLength", "group": "Comp Mirror", "parent_group": "Mirrors", "default": 19.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    {"name": "CompMirrorRadius3Offset", "label": "Radius3 Offset", "type": "App::PropertyLength", "group": "Comp Mirror", "parent_group": "Mirrors", "default": 0.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    # ==============================================================
    {"name": "CompMirrorRotZ", "label": "RotZ", "type": "App::PropertyAngle", "group": "Comp Mirror", "parent_group": "Mirrors", "default": 180, "unit": "mm", "min": -360, "max": 360, "optuna_locked": False},
    # {"name": "CompMirrorY", "label": "Y", "type": "App::PropertyDistance", "group": "Comp Mirror", "parent_group": "Mirrors","default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": False},
    # {"name": "CompMirrorZ", "label": "Z", "type": "App::PropertyDistance", "group": "Comp Mirror", "parent_group": "Mirrors","default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": False},
    # ==============================================================
    # EMITTER
    # ==============================================================
    {"name": "EmitterAPlaneWidth", "label": "A-Plane Width", "type": "App::PropertyLength", "group": "Emitter", "parent_group": "Input_Output", "default": 0.5, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True, "step": 0.2},
    {"name": "EmitterAPlaneHeight", "label": "A-Plane Height", "type": "App::PropertyLength", "group": "Emitter", "parent_group": "Input_Output", "default": 0.3, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True, "step": 0.2},
    {"name": "EmitterAPlaneZoffset", "label": "A-Plane offset in Z", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": -5, "max": 10, "optuna_locked": False, "step": 0.1},
    {"name": "EmitterAPlaneYoffset", "label": "A-Plane offset in y", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": -5, "max": 10, "optuna_locked": False, "step": 0.1},
    {"name": "EmitterNormalOffset", "label": "Normal Offset", "type": "App::PropertyLength", "group": "Emitter", "parent_group": "Input_Output", "default": 0.7, "unit": "mm", "min": 0, "max": 20, "optuna_locked": False},
    # Filter
    {"name": "EmitterFilterPlaneSize", "label": "-Filter Size", "type": "App::PropertyLength", "group": "Emitter", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    {"name": "EmitterFilterPlaneOffset", "label": "Filter Offset", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": 0.5, "unit": "mm", "min": -20, "max": 20, "step": 0.1, "optuna_locked": False},
    # ---
    {"name": "EmitterA", "label": "-A_", "type": "App::PropertyLength", "group": "Emitter", "parent_group": "Input_Output", "default": 12.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    {"name": "EmitterB", "label": "B_", "type": "App::PropertyLength", "group": "Emitter", "parent_group": "Input_Output", "default": 6.4, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    {"name": "EmitterRadius3Offset", "label": "Radius3 Offset", "type": "App::PropertyLength", "group": "Emitter", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True},
    {"name": "EmitterWidthFactor", "label": "WidthFactor", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": 0.9, "unit": "", "min": 0.5, "max": 2, "step": 0.1, "optuna_locked": False},
    # {"name": "EmitterRotX", "label": "-Rot X", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": 12.0, "unit": "deg", "min": -180, "max": 180, "optuna_locked": False},
    # {"name": "EmitterRotY", "label": "Rot Y", "type": "App::PropertyAngle", "group": "Emitter","parent_group": "Input_Output", "default": 0.0, "unit": "deg", "min": -180, "max": 180, "optuna_locked": False},
    # {"name": "EmitterRotZ", "label": "Rot Z", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": -3.0, "unit": "deg", "min": -180, "max": 180, "optuna_locked": False},
    {"name": "EmitterAimX", "label": "-AimX", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": True},
    {"name": "EmitterAimZ", "label": "AimZ", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": True},
    #
    {"name": "EmitterX", "label": "X", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": 6.1, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": False},
    #
    # ==============================================================
    # DETECTOR
    # ==============================================================
    {"name": "DetectorAPlaneWidth", "label": "A-Plane Width", "type": "App::PropertyLength", "group": "Detector", "parent_group": "Input_Output", "default": 0.8, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True, "step": 0.2},
    {"name": "DetectorAPlaneHeight", "label": "A-Plane Height", "type": "App::PropertyLength", "group": "Detector", "parent_group": "Input_Output", "default": 0.8, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True, "step": 0.2},
    {"name": "DetectorAPlaneZoffset", "label": "A-Plane offset in Z", "type": "App::PropertyFloat", "group": "Detector", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": -5, "max": 10, "optuna_locked": False, "step": 0.1},
    {"name": "DetectorAPlaneYoffset", "label": "A-Plane offset in y", "type": "App::PropertyFloat", "group": "Detector", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": -5, "max": 10, "optuna_locked": False, "step": 0.1},
    {"name": "DetectorNormalOffset", "label": "Normal Offset", "type": "App::PropertyLength", "group": "Detector", "parent_group": "Input_Output", "default": 0.7, "unit": "mm", "min": 0, "max": 20, "optuna_locked": False},
    # Filter
    {"name": "DetectorFilterPlaneSize", "label": "-Filter Size", "type": "App::PropertyLength", "group": "Detector", "parent_group": "Input_Output", "default": 2.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    {"name": "DetectorFilterPlaneOffset", "label": "Filter Offset", "type": "App::PropertyFloat", "group": "Detector", "parent_group": "Input_Output", "default": 0.5, "unit": "mm", "min": -20, "max": 20, "step": 0.1, "optuna_locked": False},
    # ....
    {"name": "DetectorA", "label": "-A_", "type": "App::PropertyLength", "group": "Detector", "parent_group": "Input_Output", "default": 12.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True},
    {"name": "DetectorB", "label": "B_", "type": "App::PropertyLength", "group": "Detector", "parent_group": "Input_Output", "default": 6.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True},
    {"name": "DetectorRadius3Offset", "label": "Radius3 Offset", "type": "App::PropertyLength", "group": "Detector", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True},
    {"name": "DetectorWidthFactor", "label": "WidthFactor", "type": "App::PropertyFloat", "group": "Detector", "parent_group": "Input_Output", "default": 0.9, "unit": "", "min": 0.5, "max": 2, "step": 0.1, "optuna_locked": False},
    # {"name": "DetectorRotX", "label": "-Rot X", "type": "App::PropertyAngle", "group": "Detector", "parent_group": "Input_Output", "default": 12.0, "unit": "deg", "min": -180, "max": 180, "optuna_locked": True},
    # {"name": "DetectorRotY", "label": "Rot Y", "type": "App::PropertyAngle", "group": "Detector","parent_group": "Input_Output", "default": 0.0, "unit": "deg", "min": -180, "max": 180, "optuna_locked": False},
    # {"name": "DetectorRotZ", "label": "Rot Z", "type": "App::PropertyAngle", "group": "Detector", "parent_group": "Input_Output", "default": 3.0, "unit": "deg", "min": -180, "max": 180, "optuna_locked": True},
    {"name": "DetectorAimX", "label": "-AimX", "type": "App::PropertyFloat", "group": "Detector", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": True},
    {"name": "DetectorAimZ", "label": "AimZ", "type": "App::PropertyFloat", "group": "Detector", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": True},
    #
    {"name": "DetectorX", "label": "X", "type": "App::PropertyFloat", "group": "Detector", "parent_group": "Input_Output", "default": -6.1, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": False},
    # ** OBS "App::PropertyDistance"  kan hantera negativa tal , "App::PropertyLength" kan inte göra det. Använder istället App::PropertyFloat
]

# ======================================================================
# H E L P E R S
# ======================================================================


def _set_property_if_changed(obj, name, value):
    current = getattr(obj, name)

    if current == value:
        return False

    setattr(obj, name, value)
    return True


def _set_float_if_changed(obj, name, value, tol=1e-9):
    current = float(getattr(obj, name))
    new = float(value)

    if abs(current - new) < tol:
        return False

    setattr(obj, name, new)
    return True


def _obj_exists(obj):
    """
    Return True if the FreeCAD object still exists in its document.
    """
    if obj is None:
        return False
    try:
        return obj.Document is not None and obj.Document.getObject(obj.Name) is obj
    except Exception:
        return False


def _set_link_if_changed(obj, prop, target):
    if getattr(obj, prop) is target:
        return False

    setattr(obj, prop, target)
    return True


# ======================================================================
# W H I T E   C E L L   P R O X Y
# ======================================================================


class OBAVCell:

    def _init_runtime_state(self):

        self._dirty = False  # används för att rebuilda via optuna

        self._initializing = True
        self._rebuilding = False

        self._compMirror = None
        self._emitter = None
        self._detector = None

        # self._cutEmitter = None
        # self._cutDetector = None

        self._dialog = None
        # self._dialog_is_open = False

        self._rebuild_count = 0

    def __init__(self, obj):

        self._init_runtime_state()

        obj.Proxy = self
        self.Object = obj

        # print("EmitterX before =", obj.EmitterX)
        # print("DetectorX before =", obj.DetectorX)

        install_properties(obj, V_CELL_PROPERTIES)

        print("EmitterX type :", obj.getTypeIdOfProperty("EmitterX"))
        print("DetectorX type:", obj.getTypeIdOfProperty("DetectorX"))

        # print("EmitterX expr :", obj.getExpression("EmitterX"))
        # print("DetectorX expr:", obj.getExpression("DetectorX"))

        obj.addProperty("App::PropertyLinkList", "Group", "Base", "Owned children")

        make_optical_type(obj, "VCell")

        self._initializing = False
        App.Console.PrintMessage(f"[OBA] V Cell proxy attached: {obj.Name}\n")

    # ==================================================================
    # C H I L D R E N
    # ==================================================================

    def _get_or_create(self, doc, name, objtype, label):
        obj = doc.getObject(name)

        if obj is None:
            obj = doc.addObject(objtype, name)
            obj.Label = label
        return obj

    def _restore_runtime_flags(self):
        for child in (self._compMirror, self._emitter, self._detector):
            proxy = getattr(child, "Proxy", None)
            if proxy is None:
                continue
            proxy._suppress_onchange = True

    def _ensure_children(self, obj):
        doc = obj.Document

        # ----------------------------------------------------------
        # Restore existing children from persistent links
        # ----------------------------------------------------------

        self._compMirror = obj.CompMirror if _obj_exists(getattr(obj, "CompMirror", None)) else None
        self._emitter = obj.Emitter if _obj_exists(getattr(obj, "Emitter", None)) else None
        self._detector = obj.Detector if _obj_exists(getattr(obj, "Detector", None)) else None

        # ----------------------------------------------------------
        # Comp Mirror
        # ----------------------------------------------------------

        if self._compMirror is None:
            self._compMirror = OBA_CreateCompMirror(
                doc=doc,
                label=f"{obj.Label} Comp Mirror",
                width=float(obj.CompMirrorWidth),
                height=float(obj.CompMirrorHeight),
                a=float(obj.CompMirrorA),
                b=float(obj.CompMirrorB),
                radius3_offset=float(obj.CompMirrorRadius3Offset),
                x=0,
                y=0,
                z=0,
                rot_z=180,
                suppress_onchange=True,
                show_dialog=False,
            )

        # ----------------------------------------------------------
        # Emitter
        # ----------------------------------------------------------

        if self._emitter is None:
            self._emitter = OBA_CreateEllipsoid(
                doc=doc,
                label=f"{obj.Label} Emitter",
                aplanewidth=float(obj.EmitterAPlaneWidth),
                aplaneheight=float(obj.EmitterAPlaneHeight),
                aplaneZoffset=float(obj.EmitterAPlaneZoffset),
                aplaneYoffset=float(obj.EmitterAPlaneYoffset),
                a=float(obj.EmitterA),
                b=float(obj.EmitterB),
                radius3_offset=float(obj.EmitterRadius3Offset),
                # rot_x=float(obj.EmitterRotX),
                # rot_y=0,  # float(obj.EmitterRotY),
                # rot_z=float(obj.EmitterRotZ),
                x=float(obj.EmitterX),
                y=-float(obj.CompMirrorB),
                z=-float(obj.CompMirrorHeight) / 2.0,
                suppress_onchange=True,
                show_dialog=False,
            )

        # ----------------------------------------------------------
        # Detector
        # ----------------------------------------------------------

        if self._detector is None:
            self._detector = OBA_CreateEllipsoid(
                doc=doc,
                label=f"{obj.Label} Detector",
                aplanewidth=float(obj.DetectorAPlaneWidth),
                aplaneheight=float(obj.DetectorAPlaneHeight),
                aplaneZoffset=float(obj.DetectorAPlaneZoffset),
                aplaneYoffset=float(obj.DetectorAPlaneYoffset),
                a=float(obj.DetectorA),
                b=float(obj.DetectorB),
                radius3_offset=float(obj.DetectorRadius3Offset),
                # rot_x=float(obj.DetectorRotX),
                # rot_y=0,  # float(obj.DetectorRotY),
                # rot_z=float(obj.DetectorRotZ),
                x=float(obj.DetectorX),
                y=-float(obj.CompMirrorB),
                z=-float(obj.CompMirrorHeight) / 2.0,
                suppress_onchange=True,
                show_dialog=False,
            )

        # ----------------------------------------------------------
        # Cut emitter
        # ----------------------------------------------------------

        # self._cutEmitter = self._get_or_create(
        #     doc,
        #     f"{obj.Name}_CutEmitter",
        #     "Part::Cut",
        #     f"{obj.Label} {self._compMirror.Label} Cut",
        # )
        # changed = False
        # changed |= _set_link_if_changed(self._cutEmitter, "Base", self._compMirror.Proxy._cut)
        # changed |= _set_link_if_changed(self._cutEmitter, "Tool", self._emitter.Proxy._box_bound)

        # ----------------------------------------------------------
        # Cut detector
        # ----------------------------------------------------------

        # self._cutDetector = self._get_or_create(
        #     doc,
        #     f"{obj.Name}_CutDetector",
        #     "Part::Cut",
        #     f"{obj.Label} Cut CompMirror",
        # )
        # changed |= _set_link_if_changed(self._cutDetector, "Base", self._cutEmitter)
        # changed |= _set_link_if_changed(self._cutDetector, "Tool", self._detector.Proxy._box_bound)

        # ----------------------------------------------------------
        # Visibility
        # ----------------------------------------------------------

        # self._compMirror.Proxy._cut.ViewObject.hide()

        # ----------------------------------------------------------
        # Group ownership
        # ----------------------------------------------------------

        group = [
            self._compMirror,
            self._emitter,
            self._detector,
            # self._cutEmitter,
            # self._cutDetector,
        ]

        group = [child for child in group if child is not None]

        if list(obj.Group) != group:
            obj.Group = group

        # ----------------------------------------------------------
        # Persistent links
        # ----------------------------------------------------------

        obj.CompMirror = self._compMirror
        obj.Emitter = self._emitter
        obj.Detector = self._detector

    # ==================================================================
    # U P D A T E   C O M P   M I R R O R
    # ==================================================================

    def _update_comp_mirror(self, obj):

        mirror = self._compMirror

        # mirror.Placement = App.Placement(
        #     App.Vector(0, 0, 0),
        #     App.Rotation(App.Vector(0, 0, 1), 180),
        # )

        # if not self._obj_exists(mirror):
        #     return
        proxy = getattr(mirror, "Proxy", None)
        changed = False
        try:
            if proxy is not None:
                proxy._initializing = True

            changed |= set_quantity_if_changed(mirror, "Width", obj.CompMirrorWidth, "mm")
            changed |= set_quantity_if_changed(mirror, "Height", obj.CompMirrorHeight, "mm")

            changed |= set_quantity_if_changed(mirror, "A_", obj.CompMirrorA, "mm")
            changed |= set_quantity_if_changed(mirror, "B_", obj.CompMirrorB, "mm")
            changed |= set_quantity_if_changed(mirror, "Radius3Offset", obj.CompMirrorRadius3Offset, "mm")

            # mirror.Placement = App.Placement(
            #         App.Vector(
            #             0,  # float(obj.CompMirrorX),
            #             0,  #  float(obj.CompMirrorY),
            #             0,  #  float(obj.CompMirrorZ),
            #         ),
            #         App.Rotation(),
            #     )

        finally:
            if proxy is not None:
                proxy._initializing = False
        try:
            if proxy is not None and changed:
                proxy._rebuild(mirror)
                pass
                # print(mirror.Name, mirror.State)

        except Exception as exc:

            App.Console.PrintError("[OBA] Failed to rebuild Comp Mirror " f"from V Cell: {exc}\n")

    # ==================================================================
    # U P D A T E   E L L I P S O I D
    # ==================================================================

    def ellipse_y_point_offset_from_x(self, ellipsoid, x, offset=2.0):
        import math

        # a = float(ellipsoid.Radius1 * 1.2)
        # b = float(ellipsoid.Radius2 * 1.2)

        a = float(ellipsoid.Radius1)
        b = float(ellipsoid.Radius2)

        if abs(x) > a:
            return None
        y = b * math.sqrt(1.0 - (x * x) / (a * a))
        nx = x / (a * a)
        ny = y / (b * b)
        nlen = math.sqrt(nx * nx + ny * ny)
        nx /= nlen
        ny /= nlen

        # print("a =", a)
        # print("b =", b)
        # print("x =", x)
        # print("abs(x)>a =", abs(x) > a)

        return (x + nx * offset, y + ny * offset)

    def _update_ellipsoid(self, ellipsoid, prefix, obj):
        # if not self._obj_exists(ellipsoid):
        #     return
        proxy = getattr(ellipsoid, "Proxy", None)
        changed = False
        try:
            if proxy is not None:
                proxy._initializing = True

            # ----------------------------------------------------------
            # Geometry
            # ----------------------------------------------------------

            if hasattr(ellipsoid, "APlaneWidth"):
                changed |= set_quantity_if_changed(ellipsoid, "APlaneWidth", getattr(obj, f"{prefix}APlaneWidth"), "mm")
            if hasattr(ellipsoid, "APlaneHeight"):
                changed |= set_quantity_if_changed(ellipsoid, "APlaneHeight", getattr(obj, f"{prefix}APlaneHeight"), "mm")
            if hasattr(ellipsoid, "FilterPlaneSize"):
                changed |= set_quantity_if_changed(ellipsoid, "FilterPlaneSize", getattr(obj, f"{prefix}FilterPlaneSize"), "mm")
            if hasattr(ellipsoid, "FilterPlaneOffset"):
                changed |= _set_float_if_changed(ellipsoid, "FilterPlaneOffset", getattr(obj, f"{prefix}FilterPlaneOffset"))
            if hasattr(ellipsoid, "APlaneZoffset"):
                changed |= _set_float_if_changed(ellipsoid, "APlaneZoffset", getattr(obj, f"{prefix}APlaneZoffset"))
            if hasattr(ellipsoid, "APlaneYoffset"):
                changed |= _set_float_if_changed(ellipsoid, "APlaneYoffset", getattr(obj, f"{prefix}APlaneYoffset"))
            if hasattr(ellipsoid, "WidthFactor"):
                changed |= _set_float_if_changed(ellipsoid, "WidthFactor", getattr(obj, f"{prefix}WidthFactor"))
            if hasattr(ellipsoid, "A_"):
                changed |= set_quantity_if_changed(ellipsoid, "A_", getattr(obj, f"{prefix}A"), "mm")
            if hasattr(ellipsoid, "B_"):
                changed |= set_quantity_if_changed(ellipsoid, "B_", getattr(obj, f"{prefix}B"), "mm")
            if hasattr(ellipsoid, "Radius3Offset"):
                changed |= set_quantity_if_changed(ellipsoid, "Radius3Offset", getattr(obj, f"{prefix}Radius3Offset"), "mm")
            # ----------------------------------------------------------
            # Aiming
            # ----------------------------------------------------------
            if hasattr(ellipsoid, "AimX"):
                changed |= set_quantity_if_changed(ellipsoid, "AimX", getattr(obj, f"{prefix}AimX"), "mm")
            if hasattr(ellipsoid, "AimZ"):
                changed |= set_quantity_if_changed(ellipsoid, "AimZ", getattr(obj, f"{prefix}AimZ"), "mm")
            # ----------------------------------------------------------
            # Placement
            # ----------------------------------------------------------

            x = float(getattr(obj, f"{prefix}X"))
            comp_ellipsoid = self._compMirror.Proxy._ellipsoid
            center = comp_ellipsoid.Placement.Base
            offset = float(getattr(obj, f"{prefix}NormalOffset"))

            # print("CompMirror")
            # print("A =", comp_ellipsoid.Radius1)
            # print("B =", comp_ellipsoid.Radius2)
            # print("X =", x)

            x2, y2 = self.ellipse_y_point_offset_from_x(comp_ellipsoid, x, offset=offset)
            # ellipsoid.Placement = App.Placement(
            new_placement = App.Placement(
                App.Vector(
                    # center.x + x2,
                    x,
                    center.y - y2,
                    # float(getattr(obj, f"{prefix}Z")) - float(obj.CompMirrorHeight) / 2,
                    -float(obj.CompMirrorHeight) / 2,
                ),
                App.Rotation(),
            )
            if ellipsoid.Placement != new_placement:
                ellipsoid.Placement = new_placement
                changed = True

        finally:
            if proxy is not None:
                proxy._initializing = False

        # --------------------------------------------------------------
        # Rebuild
        # --------------------------------------------------------------
        try:
            if proxy is not None and changed:
                proxy._rebuild(ellipsoid)
                pass

        except Exception as exc:
            App.Console.PrintError(f"[OBA] Failed to rebuild {prefix} " f"from V Cell: {exc}\n")

    # ==================================================================
    # R E B U I L D
    # ==================================================================

    def execute(self, obj):
        # print("=== WHITECELL EXECUTE ===")

        if self._initializing:
            # print("  skip: initializing")
            return

        if self._rebuilding:
            # print("  skip: rebuilding")
            return

        # print("  dirty =", self._dirty)

        # for objekt in ("_emitter", "_detector", "_compMirror"):
        #     print(f"---- {objekt} suppress onchange:", getattr(getattr(self, objekt).Proxy, "_suppress_onchange", None))

        if not self._dirty:
            # print("  skip: not dirty")
            return

        # print("  rebuilding...")
        self._rebuild(obj)
        self._dirty = False
        # print("  rebuild done")

    def _update_dependent_optics(self, obj):
        self._update_ellipsoid(self._emitter, "Emitter", obj)
        self._update_ellipsoid(self._detector, "Detector", obj)

    def _is_dialog_open(self):
        dlg = getattr(self, "_dialog", None)
        if dlg is None:
            return False
        try:
            return dlg.isVisible()
        except Exception:
            self._dialog = None
            return False

    def _rebuild(self, obj):
        # print("REBUILD")
        # self._rebuild_count += 1
        # print(f"{obj.Label} rebuild #{self._rebuild_count}")

        if self._rebuilding:
            return
        self._rebuilding = True
        try:
            # self._ensure_children(obj)
            # self._update_main_mirror(obj)
            self._update_comp_mirror(obj)
            # nedan finns det depedent_optics
            self._update_dependent_optics(obj)

            # for child in obj.Group:
            #     print("*** från white cell rebuild ", child.Name, child.State)

            # self._update_ellipsoid(self._emitter, "Emitter", obj)
            # self._update_ellipsoid(self._detector, "Detector", obj)
            # obj.Document.recompute()
        except Exception as exc:
            App.Console.PrintError("[OBA] V Cell rebuild failed: " f"{exc}\n")
        finally:
            self._rebuilding = False

        if self._is_dialog_open() and not OptunaPlotWindow.is_open() and not XGBoostParameterOptimizerDialog.is_open():
            print("============================ recomputar ===========================")
            obj.Document.recompute()

        # if not is_optimization_running():
        #     # print("  optimering körs inte ---------------")
        #     obj.Document.recompute()
        #     pass

    # ==================================================================
    # C H A N G E D
    # ==================================================================

    def onChanged(self, obj, prop):

        IGNORE = {"Group", "CompMirror", "Emitter", "Detector", "Label", "Proxy", "Shape"}
        if prop in IGNORE:
            # print("//// WHITECELL IGNORE:", prop)
            return

        # print("WHITECELL onChanged:", prop)

        if self._initializing:
            return
        if self._rebuilding:
            return

        main_properties = {
            # --- comp mirror
            "CompMirrorWidth",
            "CompMirrorHeight",
            "CompMirrorA",
            "CompMirrorB",
            "CompMirrorRadius3Offset",
            # --- Emitter
            "EmitterAPlaneWidth",
            "EmitterAPlaneHeight",
            "EmitterAPlaneZoffset",
            "EmitterAPlaneYoffset",
            "EmitterNormalOffset",
            "EmitterFilterPlaneSize",
            "EmitterFilterPlaneOffset",
            "EmitterA",
            "EmitterB",
            "EmitterRadius3Offset",
            "EmitterWidthFactor",
            # "EmitterRotX",
            # "EmitterRotY",
            # "EmitterRotZ",
            "EmitterX",
            # "EmitterY",
            # "EmitterZ",
            "EmitterAimX",
            "EmitterAimZ",
            # --- Detector
            "DetectorAPlaneWidth",
            "DetectorAPlaneHeight",
            "DetectorAPlaneZoffset",
            "DetectorAPlaneYoffset",
            "DetectorNormalOffset",
            "DetectorFilterPlaneSize",
            "DetectorFilterPlaneOffset",
            "DetectorA",
            "DetectorB",
            "DetectorRadius3Offset",
            "DetectorWidthFactor",
            # "DetectorRotX",
            # "DetectorRotY",
            # "DetectorRotZ",
            "DetectorX",
            # "DetectorY",
            # "DetectorZ",
            "DetectorAimX",
            "DetectorAimZ",
        }

        if prop in main_properties:
            # Expression Engine changes can arrive during recompute.  Only
            # mark the object dirty here; execute() performs one coalesced
            # rebuild in the current recompute pass.
            if is_optimization_running():
                # print("== optimisering körs ==")
                self._dirty = True
                obj.touch()
                return

            self._rebuild(obj)

            # self._dirty = True
            # obj.touch()
            self._refresh_dialog()
            return

    # ==================================================================
    # D I A L O G   R E F R E S H
    # ==================================================================

    def _refresh_dialog(self):
        dialog = getattr(self, "_dialog", None)
        if dialog is not None:
            try:
                dialog.refresh_from_object()
            except Exception:
                pass

    # ==================================================================
    # D O C U M E N T   R E S T O R E
    # ==================================================================

    def onDocumentRestored(self, obj):
        self._init_runtime_state()
        obj.Proxy = self
        self.Object = obj

        self._initializing = True

        try:
            install_properties(obj, V_CELL_PROPERTIES)
            make_optical_type(obj, "VCell")
            self._ensure_children(obj)
            self._restore_runtime_flags()
        finally:
            self._initializing = False
        try:
            self._rebuild(obj)
        except Exception as exc:
            App.Console.PrintError("[OBA] V Cell restore rebuild failed: " f"{exc}\n")
        restore_view_provider(obj, VCellViewProvider)

    # ==================================================================
    # S T A T E
    # ==================================================================

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        self._init_runtime_state()


# ======================================================================
# D I A L O G
# ======================================================================


class VCellDialog(OBAToolboxDialogBase):

    PROPERTY_DEFINITIONS = V_CELL_PROPERTIES

    def __init__(self, obj, title="V Cell Settings", parent=None):
        super().__init__(obj, title=title, parent=parent)
        self.help_button = QtWidgets.QPushButton("Help / XGBoost Optimizer")

        self.help_button.clicked.connect(self._open_xgboost_optimizer)

        self.help_button.setStyleSheet("""
        QPushButton {
            background-color: #6b4c9a;
            color: white;
            font-weight: 600;
        }
        QPushButton:hover {
            background-color: #583d80;
        }
        """)

        self.custom_layout.addWidget(self.help_button)

    def _get_spreadsheet_references(self):
        refs = []
        try:
            for prop, expr in self.obj.ExpressionEngine:
                if "Spreadsheet." in str(expr):
                    refs.append(prop)
        except Exception as exc:
            print("ExpressionEngine error:", exc)
        return refs

    def _open_xgboost_optimizer(self):
        refs = self._get_spreadsheet_references()
        if refs:
            QtWidgets.QMessageBox.warning(
                self,
                "Spreadsheet References Found",
                "The following parameters are controlled by Spreadsheet " "expressions:\n\n" + "\n".join(refs) + "\n\nRemove Spreadsheet References before using " "the XGBoost Optimizer.",
            )
            return
        from .xgboost_parameter_optimizer_dialog import OBA_CreateXGBoostParameterOptimizerDialog

        self._xgboost_optimizer_dialog = OBA_CreateXGBoostParameterOptimizerDialog(self.obj, parent=self, show_dialog=True)

    # ==================================================================
    # S E T   P R O P E R T Y
    # ==================================================================

    def _set_property(self, prop, value):
        super()._set_property(prop, value)

    # ==================================================================
    # R E F R E S H
    # ==================================================================

    def refresh_from_object(self):
        super().refresh_from_object()

    # ==================================================================
    # C L O S E
    # ==================================================================


# ======================================================================
# V I E W   P R O V I D E R
# ======================================================================


class VCellViewProvider(OBAToolboxViewProviderBase):

    dialog_class = VCellDialog

    def __init__(self, vobj):
        super().__init__(vobj, VCellDialog)

    # ==================================================================
    # D E L E T E
    # ==================================================================

    def onDelete(self, vobj, subelements):
        obj = getattr(self, "Object", None)
        if obj is None:
            return True

        doc = obj.Document
        for child in reversed(list(obj.Group)):
            if not _obj_exists(child):
                continue
            child_proxy = getattr(child, "Proxy", None)
            if child_proxy and hasattr(child_proxy, "delete"):
                child_proxy.delete()
            else:
                doc.removeObject(child.Name)
        return True


# ======================================================================
# F A C T O R Y
# ======================================================================


def OBA_CreateVCell(doc=None, label="V_Cell", show_dialog=True):
    doc = doc or App.ActiveDocument or App.newDocument()
    # ==================================================================
    # C R E A T E   W H I T E   C E L L
    # ==================================================================

    obj = doc.addObject("Part::FeaturePython", "OBA_VCell")
    obj.Label = label
    proxy = OBAVCell(obj)
    proxy._initializing = True
    # install_properties(obj, V_CELL_PROPERTIES)
    # ==================================================================
    # C R E A T E   C H I L D R E N
    # ==================================================================
    proxy._ensure_children(obj)
    proxy._initializing = False

    # ==================================================================
    # I N I T I A L   R E B U I L D
    # ==================================================================

    proxy._rebuild(obj)

    # ==================================================================
    # V I E W   P R O V I D E R
    # ==================================================================
    if App.GuiUp:
        VCellViewProvider(obj.ViewObject)

    doc.recompute()

    # ==================================================================
    # O P E N   D I A L O G
    # ==================================================================

    if show_dialog and App.GuiUp:
        dialog = VCellDialog(obj, title="V Cell Settings")
        proxy._dialog = dialog
        # proxy._dialog_is_open = True

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
    return obj


# ======================================================================
# P U B L I C   C R E A T E
# ======================================================================


def create(**kwargs):
    return OBA_CreateVCell(**kwargs)
