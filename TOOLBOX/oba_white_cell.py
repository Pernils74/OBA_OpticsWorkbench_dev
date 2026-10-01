# oba_white_cell.py
#
# OBA White Cell
#
# Geometry:
#   - One Main Mirror
#   - One Comp Mirror
#   - One Emitter Ellipsoid
#   - One Detector Ellipsoid
#
# The White Cell is a container FeaturePython object which creates
# and owns the four high-level optical objects:
#
#   White Cell
#     ├── Main Mirror
#     ├── Comp Mirror
#     ├── Emitter
#     └── Detector
#
# The actual geometry is created by:
#   - oba_main_mirror.py
#   - oba_comp_mirror.py
#   - oba_ellipsoid.py
#
# The White Cell itself does not duplicate geometry.
# It only creates and manages the child optical objects.
#
# Double-clicking White Cell opens WhiteCellDialog.
# Double-clicking a child opens the child's own dialog.
#

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
from .oba_main_mirror import OBA_CreateMainMirror
from .oba_ellipsoid import OBA_CreateEllipsoid

from OPTIMIZER.optimize_worker import is_optimization_running
from OPTIMIZER.optuna_plotting import OptunaPlotWindow
from .xgboost_parameter_optimizer_dialog import XGBoostParameterOptimizerDialog

# ======================================================================
# P R O P E R T I E S
# ======================================================================

WHITE_CELL_PROPERTIES = [
    # ==============================================================
    # CHILD OBJECTS
    # ==============================================================
    {"name": "MainMirror", "type": "App::PropertyLink", "group": "Child objects", "visible": False, "doc": "Main Mirror belonging to this White Cell"},
    {"name": "CompMirror", "type": "App::PropertyLink", "group": "Child objects", "visible": False, "doc": "Comp Mirror belonging to this White Cell"},
    {"name": "Emitter", "type": "App::PropertyLink", "group": "Child objects", "visible": False, "doc": "Emitter ellipsoid belonging to this White Cell"},
    {"name": "Detector", "type": "App::PropertyLink", "group": "Child objects", "visible": False, "doc": "Detector ellipsoid belonging to this White Cell"},
    # ==============================================================
    # MAIN MIRROR
    # ==============================================================
    {
        "name": "MainMirrorWidth",
        "label": "Width",
        "type": "App::PropertyLength",
        "group": "Main Mirror",
        "parent_group": "Mirrors",
        "default": 30.0,
        "unit": "mm",
        "min": 0,
        "max": 1000,
        "optuna_locked": True,
        "step": 1,
    },
    {"name": "MainMirrorHeight", "label": "Height", "type": "App::PropertyLength", "group": "Main Mirror", "parent_group": "Mirrors", "default": 9.5, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True},
    {"name": "MainMirrorSplitOffset", "label": "Split Offset", "type": "App::PropertyLength", "group": "Main Mirror", "parent_group": "Mirrors", "default": 6.5, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    {"name": "MainMirrorA", "label": "A", "type": "App::PropertyLength", "group": "Main Mirror", "parent_group": "Mirrors", "default": 20.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    {"name": "MainMirrorB", "label": "B", "type": "App::PropertyLength", "group": "Main Mirror", "parent_group": "Mirrors", "default": 19.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    {"name": "MainMirrorTiltAngle", "label": "Tilt", "type": "App::PropertyAngle", "group": "Main Mirror", "parent_group": "Mirrors", "default": 0.0, "unit": "deg", "min": -180, "max": 180, "optuna_locked": False},
    # {"name": "MainMirrorX", "label": "X", "type": "App::PropertyDistance", "group": "Main Mirror", "parent_group": "Mirrors","default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": False},
    {"name": "MainMirrorY", "label": "Y", "type": "App::PropertyFloat", "group": "Main Mirror", "parent_group": "Mirrors", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": False},
    # {"name": "MainMirrorZ", "label": "Z", "type": "App::PropertyDistance", "group": "Main Mirror", "parent_group": "Mirrors","default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": False},
    # ==============================================================
    # COMP MIRROR
    # ==============================================================
    # {"name": "CompMirrorWidth", "label": "Width", "type": "App::PropertyLength", "group": "Comp Mirror", "parent_group": "Mirrors","default": 100.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    # {"name": "CompMirrorHeight", "label": "Height", "type": "App::PropertyLength", "group": "Comp Mirror", "parent_group": "Mirrors","default": 30.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    {"name": "CompMirrorA", "label": "A", "type": "App::PropertyLength", "group": "Comp Mirror", "parent_group": "Mirrors", "default": 20.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    {"name": "CompMirrorB", "label": "B", "type": "App::PropertyLength", "group": "Comp Mirror", "parent_group": "Mirrors", "default": 19.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    # {"name": "CompMirrorX", "label": "X", "type": "App::PropertyDistance", "group": "Comp Mirror", "parent_group": "Mirrors","default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": False},
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
    {"name": "EmitterA", "label": "A", "type": "App::PropertyLength", "group": "Emitter", "parent_group": "Input_Output", "default": 12.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    {"name": "EmitterB", "label": "B", "type": "App::PropertyLength", "group": "Emitter", "parent_group": "Input_Output", "default": 6.4, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    # {"name": "EmitterB2", "label": "B2", "type": "App::PropertyLength", "group": "Emitter", "parent_group": "Input_Output", "default": 12.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    {"name": "EmitterWidthFactor", "label": "WidthFactor", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": 0.9, "unit": "", "min": 0.5, "max": 2, "step": 0.1, "optuna_locked": False},
    {"name": "EmitterRotX", "label": "Rot X", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": 12.0, "unit": "deg", "min": -180, "max": 180, "optuna_locked": False},
    # {"name": "EmitterRotY", "label": "Rot Y", "type": "App::PropertyAngle", "group": "Emitter","parent_group": "Input_Output", "default": 0.0, "unit": "deg", "min": -180, "max": 180, "optuna_locked": False},
    {"name": "EmitterRotZ", "label": "Rot Z", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": -3.0, "unit": "deg", "min": -180, "max": 180, "optuna_locked": False},
    {"name": "EmitterX", "label": "X", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": 6.1, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": False},
    # {"name": "EmitterY", "label": "Y", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": False},
    # {"name": "EmitterZ", "label": "Z", "type": "App::PropertyFloat", "group": "Emitter", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": False},
    # ==============================================================
    # DETECTOR
    # ==============================================================
    {"name": "DetectorAPlaneWidth", "label": "A-Plane Width", "type": "App::PropertyLength", "group": "Detector", "parent_group": "Input_Output", "default": 0.8, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True, "step": 0.2},
    {"name": "DetectorAPlaneHeight", "label": "A-Plane Height", "type": "App::PropertyLength", "group": "Detector", "parent_group": "Input_Output", "default": 0.8, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True, "step": 0.2},
    {"name": "DetectorAPlaneZoffset", "label": "A-Plane offset in Z", "type": "App::PropertyFloat", "group": "Detector", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": -5, "max": 10, "optuna_locked": False, "step": 0.1},
    {"name": "DetectorAPlaneYoffset", "label": "A-Plane offset in y", "type": "App::PropertyFloat", "group": "Detector", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": -5, "max": 10, "optuna_locked": False, "step": 0.1},
    {"name": "DetectorNormalOffset", "label": "Normal Offset", "type": "App::PropertyLength", "group": "Detector", "parent_group": "Input_Output", "default": 0.7, "unit": "mm", "min": 0, "max": 20, "optuna_locked": False},
    {"name": "DetectorA", "label": "A", "type": "App::PropertyLength", "group": "Detector", "parent_group": "Input_Output", "default": 12.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True},
    {"name": "DetectorB", "label": "B", "type": "App::PropertyLength", "group": "Detector", "parent_group": "Input_Output", "default": 6.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": True},
    # {"name": "DetectorB2", "label": "B2", "type": "App::PropertyLength", "group": "Detector", "parent_group": "Input_Output", "default": 12.0, "unit": "mm", "min": 0, "max": 1000, "optuna_locked": False},
    {"name": "DetectorWidthFactor", "label": "WidthFactor", "type": "App::PropertyFloat", "group": "Detector", "parent_group": "Input_Output", "default": 0.9, "unit": "", "min": 0.5, "max": 2, "step": 0.1, "optuna_locked": False},
    {"name": "DetectorRotX", "label": "Rot X", "type": "App::PropertyAngle", "group": "Detector", "parent_group": "Input_Output", "default": 12.0, "unit": "deg", "min": -180, "max": 180, "optuna_locked": True},
    # {"name": "DetectorRotY", "label": "Rot Y", "type": "App::PropertyAngle", "group": "Detector","parent_group": "Input_Output", "default": 0.0, "unit": "deg", "min": -180, "max": 180, "optuna_locked": False},
    {"name": "DetectorRotZ", "label": "Rot Z", "type": "App::PropertyAngle", "group": "Detector", "parent_group": "Input_Output", "default": 3.0, "unit": "deg", "min": -180, "max": 180, "optuna_locked": True},
    {"name": "DetectorX", "label": "X", "type": "App::PropertyFloat", "group": "Detector", "parent_group": "Input_Output", "default": -6.1, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": False},
    # {"name": "DetectorY", "label": "Y", "type": "App::PropertyFloat", "group": "Detector", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": False},
    # {"name": "DetectorZ", "label": "Z", "type": "App::PropertyFloat", "group": "Detector", "parent_group": "Input_Output", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optuna_locked": False},
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


class OBAWhiteCell:

    def _init_runtime_state(self):

        self._dirty = False  # används för att rebuilda via optuna

        self._initializing = True
        self._rebuilding = False

        self._mainMirror = None
        self._compMirror = None
        self._emitter = None
        self._detector = None

        self._cutEmitter = None
        self._cutDetector = None

        self._dialog = None
        # self._dialog_is_open = False

        self._rebuild_count = 0

    def __init__(self, obj):

        self._init_runtime_state()

        obj.Proxy = self
        self.Object = obj

        # print("EmitterX before =", obj.EmitterX)
        # print("DetectorX before =", obj.DetectorX)

        install_properties(obj, WHITE_CELL_PROPERTIES)

        print("EmitterX type :", obj.getTypeIdOfProperty("EmitterX"))
        print("DetectorX type:", obj.getTypeIdOfProperty("DetectorX"))

        # print("EmitterX expr :", obj.getExpression("EmitterX"))
        # print("DetectorX expr:", obj.getExpression("DetectorX"))

        obj.addProperty("App::PropertyLinkList", "Group", "Base", "Owned children")

        make_optical_type(obj, "WhiteCell")

        self._initializing = False
        App.Console.PrintMessage(f"[OBA] White Cell proxy attached: {obj.Name}\n")

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
        for child in (self._mainMirror, self._compMirror, self._emitter, self._detector):
            proxy = getattr(child, "Proxy", None)
            if proxy is None:
                continue
            proxy._suppress_onchange = True

    def _ensure_children(self, obj):
        doc = obj.Document

        # ----------------------------------------------------------
        # Restore existing children from persistent links
        # ----------------------------------------------------------

        self._mainMirror = obj.MainMirror if _obj_exists(getattr(obj, "MainMirror", None)) else None
        self._compMirror = obj.CompMirror if _obj_exists(getattr(obj, "CompMirror", None)) else None
        self._emitter = obj.Emitter if _obj_exists(getattr(obj, "Emitter", None)) else None
        self._detector = obj.Detector if _obj_exists(getattr(obj, "Detector", None)) else None

        # ----------------------------------------------------------
        # Main Mirror
        # ----------------------------------------------------------

        if self._mainMirror is None:
            self._mainMirror = OBA_CreateMainMirror(
                doc=doc,
                label=f"{obj.Label} Main Mirror",
                width=float(obj.MainMirrorWidth),
                height=float(obj.MainMirrorHeight),
                split_offset=float(obj.MainMirrorSplitOffset),
                a=float(obj.MainMirrorA),
                b=float(obj.MainMirrorB),
                tiltangle=float(obj.MainMirrorTiltAngle),
                x=0,
                y=float(obj.MainMirrorY),
                z=0,
                suppress_onchange=True,
                show_dialog=False,
            )

        # ----------------------------------------------------------
        # Comp Mirror
        # ----------------------------------------------------------

        if self._compMirror is None:
            self._compMirror = OBA_CreateCompMirror(
                doc=doc,
                label=f"{obj.Label} Comp Mirror",
                width=float(obj.MainMirrorWidth),
                height=float(obj.MainMirrorHeight),
                a=float(obj.CompMirrorA),
                b=float(obj.CompMirrorB),
                x=0,
                y=0,
                z=0,
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
                # b2=float(obj.EmitterB2),
                rot_x=float(obj.EmitterRotX),
                rot_y=0,  # float(obj.EmitterRotY),
                rot_z=float(obj.EmitterRotZ),
                x=float(obj.EmitterX),
                y=0,  # float(obj.EmitterY),
                z=-float(obj.MainMirrorHeight) / 2.0,
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
                # b2=float(obj.DetectorB2),
                rot_x=float(obj.DetectorRotX),
                rot_y=0,  # float(obj.DetectorRotY),
                rot_z=float(obj.DetectorRotZ),
                x=float(obj.DetectorX),
                y=0,  # float(obj.DetectorY),
                z=-float(obj.MainMirrorHeight) / 2.0,
                suppress_onchange=True,
                show_dialog=False,
            )

        # ----------------------------------------------------------
        # Cut emitter
        # ----------------------------------------------------------

        self._cutEmitter = self._get_or_create(doc, f"{obj.Name}_CutEmitter", "Part::Cut", f"{obj.Label} {self._compMirror.Label} Cut")
        changed = False
        changed |= _set_link_if_changed(self._cutEmitter, "Base", self._compMirror.Proxy._cut)
        changed |= _set_link_if_changed(self._cutEmitter, "Tool", self._emitter.Proxy._box_bound)

        # ----------------------------------------------------------
        # Cut detector
        # ----------------------------------------------------------
        # self._cutDetector = self._get_or_create(doc, f"{obj.Name}_CutDetector", "Part::Cut", f"{obj.Label} {self._compMirror.Label} Cut")
        self._cutDetector = self._get_or_create(doc, f"{obj.Name}_CutDetector", "Part::Cut", f"{obj.Label}  Cut CompMirror")
        changed |= _set_link_if_changed(self._cutDetector, "Base", self._cutEmitter)
        changed |= _set_link_if_changed(self._cutDetector, "Tool", self._detector.Proxy._box_bound)

        # ----------------------------------------------------------
        # Visibility
        # ----------------------------------------------------------
        self._compMirror.Proxy._cut.ViewObject.hide()

        # ----------------------------------------------------------
        # Group ownership
        # ----------------------------------------------------------

        group = [
            self._mainMirror,
            self._compMirror,
            self._emitter,
            self._detector,
            self._cutEmitter,
            self._cutDetector,
        ]

        group = [child for child in group if child is not None]

        if list(obj.Group) != group:
            obj.Group = group

        # ----------------------------------------------------------
        # Persistent links
        # ----------------------------------------------------------

        obj.MainMirror = self._mainMirror
        obj.CompMirror = self._compMirror
        obj.Emitter = self._emitter
        obj.Detector = self._detector

        # ----------------------------------------------------------
        # Cut object
        # ----------------------------------------------------------

    # ==================================================================
    # U P D A T E   M A I N   M I R R O R
    # ==================================================================

    def _update_main_mirror(self, obj):
        mirror = self._mainMirror
        # if not self._obj_exists(mirror):
        #     return
        proxy = getattr(mirror, "Proxy", None)
        changed = False
        try:
            if proxy is not None:
                proxy._initializing = True

            changed |= set_quantity_if_changed(mirror, "Width", obj.MainMirrorWidth, "mm")
            changed |= set_quantity_if_changed(mirror, "Height", obj.MainMirrorHeight, "mm")
            changed |= set_quantity_if_changed(mirror, "SplitOffset", obj.MainMirrorSplitOffset, "mm")
            changed |= set_quantity_if_changed(mirror, "A", obj.MainMirrorA, "mm")
            changed |= set_quantity_if_changed(mirror, "B", obj.MainMirrorB, "mm")
            changed |= set_quantity_if_changed(mirror, "TiltAngle", obj.MainMirrorTiltAngle, "deg")

            # mirror.Placement = App.Placement(
            #     App.Vector(
            #         0,  # float(obj.MainMirrorX),
            #         float(obj.MainMirrorY),
            #         0,  # float(obj.MainMirrorZ),
            #     ),
            #     App.Rotation(),
            # )
        finally:
            if proxy is not None:
                proxy._initializing = False
        try:
            if proxy is not None and changed:
                proxy._rebuild(mirror)
                pass
        except Exception as exc:
            App.Console.PrintError("[OBA] Failed to rebuild Main Mirror " f"from White Cell: {exc}\n")

    # ==================================================================
    # U P D A T E   C O M P   M I R R O R
    # ==================================================================

    def _update_comp_mirror(self, obj):

        mirror = self._compMirror
        # if not self._obj_exists(mirror):
        #     return
        proxy = getattr(mirror, "Proxy", None)
        changed = False
        try:
            if proxy is not None:
                proxy._initializing = True

            required_width = 2 * max(abs(float(obj.EmitterX)), abs(float(obj.DetectorX)))
            changed |= set_quantity_if_changed(mirror, "Width", required_width, "mm")
            changed |= set_quantity_if_changed(mirror, "Height", obj.MainMirrorHeight, "mm")  # CompMirrorHeightchanged |=

            changed |= set_quantity_if_changed(mirror, "A", obj.CompMirrorA, "mm")
            changed |= set_quantity_if_changed(mirror, "B", obj.CompMirrorB, "mm")
            # set_quantity_if_changed(mirror, "Width", obj.MainMirrorWidth, "mm")  # CompMirrorWidth

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

            App.Console.PrintError("[OBA] Failed to rebuild Comp Mirror " f"from White Cell: {exc}\n")

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

            # if hasattr(ellipsoid, "APlaneZoffset"):
            #     ellipsoid.APlaneZoffset = float(getattr(obj, f"{prefix}APlaneZoffset"))

            # if hasattr(ellipsoid, "APlaneYoffset"):
            #     ellipsoid.APlaneYoffset = float(getattr(obj, f"{prefix}APlaneYoffset"))

            if hasattr(ellipsoid, "APlaneZoffset"):
                changed |= _set_float_if_changed(ellipsoid, "APlaneZoffset", getattr(obj, f"{prefix}APlaneZoffset"))

            if hasattr(ellipsoid, "APlaneYoffset"):
                changed |= _set_float_if_changed(ellipsoid, "APlaneYoffset", getattr(obj, f"{prefix}APlaneYoffset"))

            if hasattr(ellipsoid, "WidthFactor"):
                changed |= _set_float_if_changed(ellipsoid, "WidthFactor", getattr(obj, f"{prefix}WidthFactor"))

            if hasattr(ellipsoid, "A"):
                changed |= set_quantity_if_changed(ellipsoid, "A", getattr(obj, f"{prefix}A"), "mm")

            if hasattr(ellipsoid, "B"):
                changed |= set_quantity_if_changed(ellipsoid, "B", getattr(obj, f"{prefix}B"), "mm")

            # if hasattr(ellipsoid, "WidthFactor"):
            #     setattr(ellipsoid, "WidthFactor", float(getattr(obj, f"{prefix}WidthFactor")))
            # ----------------------------------------------------------
            # B2
            # ----------------------------------------------------------

            # if hasattr(ellipsoid, "B2"):
            #     set_quantity_if_changed(ellipsoid, "B2", getattr(obj, f"{prefix}B2"), "mm")

            # ----------------------------------------------------------
            # Rotation
            # ----------------------------------------------------------

            if hasattr(ellipsoid, "RotX"):
                changed |= set_quantity_if_changed(ellipsoid, "RotX", getattr(obj, f"{prefix}RotX"), "deg")

            if hasattr(ellipsoid, "RotZ"):
                changed |= set_quantity_if_changed(ellipsoid, "RotZ", getattr(obj, f"{prefix}RotZ"), "deg")

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
                    # float(getattr(obj, f"{prefix}Z")) - float(obj.MainMirrorHeight) / 2,
                    -float(obj.MainMirrorHeight) / 2,
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
            App.Console.PrintError(f"[OBA] Failed to rebuild {prefix} " f"from White Cell: {exc}\n")

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

        # for objekt in ("_emitter", "_detector", "_mainMirror", "_compMirror"):
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
        print("REBUILD")
        # self._rebuild_count += 1
        # print(f"{obj.Label} rebuild #{self._rebuild_count}")

        if self._rebuilding:
            return
        self._rebuilding = True
        try:
            # self._ensure_children(obj)
            self._update_main_mirror(obj)
            self._update_comp_mirror(obj)
            # nedan finns det depedent_optics
            self._update_dependent_optics(obj)

            # for child in obj.Group:
            #     print("*** från white cell rebuild ", child.Name, child.State)

            # self._update_ellipsoid(self._emitter, "Emitter", obj)
            # self._update_ellipsoid(self._detector, "Detector", obj)
            # obj.Document.recompute()
        except Exception as exc:
            App.Console.PrintError("[OBA] White Cell rebuild failed: " f"{exc}\n")
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

        IGNORE = {"Group", "MainMirror", "CompMirror", "Emitter", "Detector", "Label", "Proxy", "Shape"}
        if prop in IGNORE:
            # print("//// WHITECELL IGNORE:", prop)
            return

        # print("WHITECELL onChanged:", prop)

        if self._initializing:
            return
        if self._rebuilding:
            return

        main_properties = {
            "MainMirrorWidth",
            "MainMirrorHeight",
            "MainMirrorSplitOffset",
            "MainMirrorA",
            "MainMirrorB",
            "MainMirrorTiltAngle",
            # "MainMirrorX",
            "MainMirrorY",
            # "MainMirrorZ",
            # --- comp mirror
            "CompMirrorWidth",
            "CompMirrorHeight",
            "CompMirrorA",
            "CompMirrorB",
            # --- Emitter
            "EmitterAPlaneWidth",
            "EmitterAPlaneHeight",
            "EmitterAPlaneZoffset",
            "EmitterAPlaneYoffset",
            "EmitterNormalOffset",
            "EmitterA",
            "EmitterB",
            # "EmitterB2",
            "EmitterWidthFactor",
            "EmitterRotX",
            # "EmitterRotY",
            "EmitterRotZ",
            "EmitterX",
            # "EmitterY",
            # "EmitterZ",
            # --- Detector
            "DetectorAPlaneWidth",
            "DetectorAPlaneHeight",
            "DetectorAPlaneZoffset",
            "DetectorAPlaneYoffset",
            "DetectorNormalOffset",
            "DetectorA",
            "DetectorB",
            # "DetectorB2",
            "DetectorWidthFactor",
            "DetectorRotX",
            # "DetectorRotY",
            "DetectorRotZ",
            "DetectorX",
            # "DetectorY",
            # "DetectorZ",
        }

        if prop in main_properties:
            # Expression Engine changes can arrive during recompute.  Only
            # mark the object dirty here; execute() performs one coalesced
            # rebuild in the current recompute pass.
            if is_optimization_running():
                # print("== optimisering körs ==")
                self._dirty = True
                # return

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
            install_properties(obj, WHITE_CELL_PROPERTIES)
            make_optical_type(obj, "WhiteCell")
            self._ensure_children(obj)
            self._restore_runtime_flags()
        finally:
            self._initializing = False
        try:
            self._rebuild(obj)
        except Exception as exc:
            App.Console.PrintError("[OBA] White Cell restore rebuild failed: " f"{exc}\n")
        restore_view_provider(obj, WhiteCellViewProvider)

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


class WhiteCellDialog(OBAToolboxDialogBase):

    PROPERTY_DEFINITIONS = WHITE_CELL_PROPERTIES

    def __init__(self, obj, title="White Cell Settings", parent=None):
        super().__init__(obj, title=title, parent=parent)

        self._refreshing_ui = False

        button_layout = QtWidgets.QHBoxLayout()

        self.export_button = QtWidgets.QPushButton("1). Export to Spreadsheet     --->")
        self.export_button.clicked.connect(lambda: self.export_to_spreadsheet(WHITE_CELL_PROPERTIES))

        self.optuna_button = QtWidgets.QPushButton("2). Update Optuna Config")
        self.optuna_button.clicked.connect(lambda: self.update_optuna_config(WHITE_CELL_PROPERTIES))

        button_layout.addWidget(self.export_button)
        button_layout.addWidget(self.optuna_button)
        # valfritt
        # button_layout.addStretch(1)
        self.custom_layout.addLayout(button_layout)

        button_layout_2 = QtWidgets.QHBoxLayout()
        self.clear_button = QtWidgets.QPushButton("1b). Remove Spreadsheet References")
        self.clear_button.clicked.connect(lambda: self.clear_spreadsheet_references(WHITE_CELL_PROPERTIES))
        button_layout_2.addWidget(self.clear_button)
        # button_layout_2.addStretch(0)

        self.help_button = QtWidgets.QPushButton("Help / XGBoost Optimizer")
        self.help_button.clicked.connect(self._open_xgboost_optimizer)

        button_layout_2.addWidget(self.help_button)
        # button_layout_2.addStretch(0)

        self.custom_layout.addLayout(button_layout_2)

        self._widgets = {}
        parent_groups = {}
        groups = {}
        for prop in WHITE_CELL_PROPERTIES:
            if not prop.get("visible", True):
                continue
            if prop["type"] == "App::PropertyLink":
                continue
            parent_name = prop.get("parent_group")
            group_name = prop["group"]

            # --------------------------------------------------
            # Parent group
            # --------------------------------------------------
            if parent_name:
                if parent_name not in parent_groups:
                    parent_box = QtWidgets.QGroupBox(parent_name)
                    parent_layout = QtWidgets.QHBoxLayout(parent_box)

                    parent_groups[parent_name] = {
                        "box": parent_box,
                        "layout": parent_layout,
                    }

                    self.custom_layout.addWidget(parent_box)

            # --------------------------------------------------
            # Child group
            # --------------------------------------------------
            group_key = (parent_name, group_name)
            if group_key not in groups:
                group_box = QtWidgets.QGroupBox(group_name)
                form = QtWidgets.QFormLayout(group_box)
                groups[group_key] = form
                if parent_name:
                    parent_groups[parent_name]["layout"].addWidget(group_box)
                else:
                    self.custom_layout.addWidget(group_box)
            form = groups[group_key]
            widget = self._add_checked_spin(
                prop=prop["name"],
                label=prop.get("label", prop["name"]),
                optuna_locked=prop.get("optuna_locked", False),
                minimum=prop.get("min", 0),
                maximum=prop.get("max", 1000),
                unit=prop.get("unit", "mm"),
                form=form,
                step=prop.get("step", 1),
            )
            self._widgets[prop["name"]] = widget

        # ==============================================================
        # S I G N A L S
        # ==============================================================

        for name, widget in self._widgets.items():
            widget.checkbox.toggled.connect(lambda state, p=name: setattr(self.obj, f"{p}_OptunaLocked", state))
            widget.spinbox.valueChanged.connect(lambda value, p=name: self._set_property(p, value.Value))

        self.refresh_from_object()
        try:
            self.obj.Proxy._dialog = self
        except Exception:
            pass

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

        self._xgboost_optimizer_dialog = OBA_CreateXGBoostParameterOptimizerDialog(
            self.obj,
            parent=self,
            show_dialog=True,
        )

    # ==================================================================
    # S E T   P R O P E R T Y
    # ==================================================================

    def _set_property(self, prop, value):
        # print("SET", prop, value)
        if self._refreshing_ui:
            return
        try:
            setattr(self.obj, prop, value)
            # self.obj.Document.recompute()
        except Exception as exc:
            App.Console.PrintError(f"[OBA] White Cell dialog failed to update " f"{prop}: {exc}\n")

    # ==================================================================
    # R E F R E S H
    # ==================================================================

    def refresh_from_object(self):
        if not self.obj:
            return
        self._refreshing_ui = True
        try:
            for name, widget in self._widgets.items():
                widget.spinbox.setProperty("rawValue", float(getattr(self.obj, name)))
        finally:
            self._refreshing_ui = False

    # ==================================================================
    # C L O S E
    # ==================================================================


# ======================================================================
# V I E W   P R O V I D E R
# ======================================================================


class WhiteCellViewProvider(OBAToolboxViewProviderBase):

    dialog_class = WhiteCellDialog

    def __init__(self, vobj):
        super().__init__(vobj, WhiteCellDialog)

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


def OBA_CreateWhiteCell(doc=None, label="White_Cell", show_dialog=True):
    doc = doc or App.ActiveDocument or App.newDocument()
    # ==================================================================
    # C R E A T E   W H I T E   C E L L
    # ==================================================================

    obj = doc.addObject("Part::FeaturePython", "OBA_WhiteCell")
    obj.Label = label
    proxy = OBAWhiteCell(obj)
    proxy._initializing = True
    # install_properties(obj, WHITE_CELL_PROPERTIES)
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
        WhiteCellViewProvider(obj.ViewObject)

    doc.recompute()

    # ==================================================================
    # O P E N   D I A L O G
    # ==================================================================

    if show_dialog and App.GuiUp:
        dialog = WhiteCellDialog(obj, title="White Cell Settings")
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
    return OBA_CreateWhiteCell(**kwargs)
