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
)

from .oba_comp_mirror import OBA_CreateCompMirror
from .oba_main_mirror import OBA_CreateMainMirror
from .oba_ellipsoid import OBA_CreateEllipsoid

# ======================================================================
# P R O P E R T I E S
# ======================================================================

WHITE_CELL_PROPERTIES = [
    # ==============================================================
    # CHILD OBJECTS
    # ==============================================================
    {"name": "MainMirror", "type": "App::PropertyLink", "group": "Mirrors", "visible": False, "doc": "Main Mirror belonging to this White Cell"},
    {"name": "CompMirror", "type": "App::PropertyLink", "group": "Mirrors", "visible": False, "doc": "Comp Mirror belonging to this White Cell"},
    {"name": "Emitter", "type": "App::PropertyLink", "group": "Ellipsoids", "visible": False, "doc": "Emitter ellipsoid belonging to this White Cell"},
    {"name": "Detector", "type": "App::PropertyLink", "group": "Ellipsoids", "visible": False, "doc": "Detector ellipsoid belonging to this White Cell"},
    # ==============================================================
    # MAIN MIRROR
    # ==============================================================
    {"name": "MainMirrorWidth", "label": "Width", "type": "App::PropertyLength", "group": "Main Mirror", "default": 100.0, "unit": "mm", "min": 0, "max": 1000, "optimize": True},
    {"name": "MainMirrorHeight", "label": "Height", "type": "App::PropertyLength", "group": "Main Mirror", "default": 33.0, "unit": "mm", "min": 0, "max": 1000, "optimize": True},
    {"name": "MainMirrorSplitOffset", "label": "Split Offset", "type": "App::PropertyLength", "group": "Main Mirror", "default": 40.0, "unit": "mm", "min": 0, "max": 1000, "optimize": False},
    {"name": "MainMirrorA", "label": "A", "type": "App::PropertyLength", "group": "Main Mirror", "default": 40.0, "unit": "mm", "min": 0, "max": 1000, "optimize": False},
    {"name": "MainMirrorB", "label": "B", "type": "App::PropertyLength", "group": "Main Mirror", "default": 31.0, "unit": "mm", "min": 0, "max": 1000, "optimize": False},
    {"name": "MainMirrorTiltAngle", "label": "Tilt", "type": "App::PropertyAngle", "group": "Main Mirror", "default": 0.0, "unit": "deg", "min": -180, "max": 180, "optimize": False},
    # {"name": "MainMirrorX", "label": "X", "type": "App::PropertyDistance", "group": "Main Mirror", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optimize": False},
    {"name": "MainMirrorY", "label": "Y", "type": "App::PropertyDistance", "group": "Main Mirror", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optimize": False},
    # {"name": "MainMirrorZ", "label": "Z", "type": "App::PropertyDistance", "group": "Main Mirror", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optimize": False},
    # ==============================================================
    # COMP MIRROR
    # ==============================================================
    # {"name": "CompMirrorWidth", "label": "Width", "type": "App::PropertyLength", "group": "Comp Mirror", "default": 100.0, "unit": "mm", "min": 0, "max": 1000, "optimize": False},
    # {"name": "CompMirrorHeight", "label": "Height", "type": "App::PropertyLength", "group": "Comp Mirror", "default": 30.0, "unit": "mm", "min": 0, "max": 1000, "optimize": False},
    {"name": "CompMirrorA", "label": "A", "type": "App::PropertyLength", "group": "Comp Mirror", "default": 40.0, "unit": "mm", "min": 0, "max": 1000, "optimize": False},
    {"name": "CompMirrorB", "label": "B", "type": "App::PropertyLength", "group": "Comp Mirror", "default": 30.0, "unit": "mm", "min": 0, "max": 1000, "optimize": False},
    # {"name": "CompMirrorX", "label": "X", "type": "App::PropertyDistance", "group": "Comp Mirror", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optimize": False},
    # {"name": "CompMirrorY", "label": "Y", "type": "App::PropertyDistance", "group": "Comp Mirror", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optimize": False},
    # {"name": "CompMirrorZ", "label": "Z", "type": "App::PropertyDistance", "group": "Comp Mirror", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optimize": False},
    # ==============================================================
    # EMITTER
    # ==============================================================
    {"name": "EmitterAPlaneWidth", "label": "A-Plane Width", "type": "App::PropertyLength", "group": "Emitter", "default": 5.0, "unit": "mm", "min": 0, "max": 1000, "optimize": False},
    {"name": "EmitterAPlaneHeight", "label": "A-Plane Height", "type": "App::PropertyLength", "group": "Emitter", "default": 5.0, "unit": "mm", "min": 0, "max": 1000, "optimize": False},
    {"name": "EmitterA", "label": "A", "type": "App::PropertyLength", "group": "Emitter", "default": 40.0, "unit": "mm", "min": 0, "max": 1000, "optimize": False},
    {"name": "EmitterB", "label": "B", "type": "App::PropertyLength", "group": "Emitter", "default": 20.0, "unit": "mm", "min": 0, "max": 1000, "optimize": False},
    {"name": "EmitterB2", "label": "B2", "type": "App::PropertyLength", "group": "Emitter", "default": 20.0, "unit": "mm", "min": 0, "max": 1000, "optimize": False},
    {"name": "EmitterRotX", "label": "Rot X", "type": "App::PropertyAngle", "group": "Emitter", "default": 30.0, "unit": "deg", "min": -180, "max": 180, "optimize": False},
    {"name": "EmitterRotY", "label": "Rot Y", "type": "App::PropertyAngle", "group": "Emitter", "default": 0.0, "unit": "deg", "min": -180, "max": 180, "optimize": False},
    {"name": "EmitterRotZ", "label": "Rot Z", "type": "App::PropertyAngle", "group": "Emitter", "default": 0.0, "unit": "deg", "min": -180, "max": 180, "optimize": False},
    {"name": "EmitterX", "label": "X", "type": "App::PropertyDistance", "group": "Emitter", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optimize": False},
    {"name": "EmitterY", "label": "Y", "type": "App::PropertyDistance", "group": "Emitter", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optimize": False},
    {"name": "EmitterZ", "label": "Z", "type": "App::PropertyDistance", "group": "Emitter", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optimize": False},
    # ==============================================================
    # DETECTOR
    # ==============================================================
    {"name": "DetectorAPlaneWidth", "label": "A-Plane Width", "type": "App::PropertyLength", "group": "Detector", "default": 5.0, "unit": "mm", "min": 0, "max": 1000, "optimize": True},
    {"name": "DetectorAPlaneHeight", "label": "A-Plane Height", "type": "App::PropertyLength", "group": "Detector", "default": 5.0, "unit": "mm", "min": 0, "max": 1000, "optimize": True},
    {"name": "DetectorA", "label": "A", "type": "App::PropertyLength", "group": "Detector", "default": 40.0, "unit": "mm", "min": 0, "max": 1000, "optimize": True},
    {"name": "DetectorB", "label": "B", "type": "App::PropertyLength", "group": "Detector", "default": 20.0, "unit": "mm", "min": 0, "max": 1000, "optimize": True},
    {"name": "DetectorB2", "label": "B2", "type": "App::PropertyLength", "group": "Detector", "default": 20.0, "unit": "mm", "min": 0, "max": 1000, "optimize": False},
    {"name": "DetectorRotX", "label": "Rot X", "type": "App::PropertyAngle", "group": "Detector", "default": 30.0, "unit": "deg", "min": -180, "max": 180, "optimize": True},
    {"name": "DetectorRotY", "label": "Rot Y", "type": "App::PropertyAngle", "group": "Detector", "default": 0.0, "unit": "deg", "min": -180, "max": 180, "optimize": False},
    {"name": "DetectorRotZ", "label": "Rot Z", "type": "App::PropertyAngle", "group": "Detector", "default": 0.0, "unit": "deg", "min": -180, "max": 180, "optimize": True},
    {"name": "DetectorX", "label": "X", "type": "App::PropertyDistance", "group": "Detector", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optimize": False},
    {"name": "DetectorY", "label": "Y", "type": "App::PropertyDistance", "group": "Detector", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optimize": False},
    {"name": "DetectorZ", "label": "Z", "type": "App::PropertyDistance", "group": "Detector", "default": 0.0, "unit": "mm", "min": -1000, "max": 1000, "optimize": False},
]

# ======================================================================
# H E L P E R S
# ======================================================================


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


def _set_quantity(obj, name, value, unit):
    """
    Safely assign a FreeCAD quantity property.
    """
    setattr(obj, name, App.Units.Quantity(f"{float(value)} {unit}"))


# ======================================================================
# W H I T E   C E L L   P R O X Y
# ======================================================================


class OBAWhiteCell:

    CHILD_OBJECTS = ("_mainMirror", "_compMirror", "_emitter", "_detector")

    def _init_runtime_state(self):

        self._initializing = True
        self._rebuilding = False

        self._mainMirror = None
        self._compMirror = None
        self._emitter = None
        self._detector = None

        self._cutEmitter = None
        self._cutDetector = None

        self._dialog = None

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def __init__(self, obj):

        self._init_runtime_state()

        obj.Proxy = self
        self.Object = obj

        install_properties(obj, WHITE_CELL_PROPERTIES)
        make_optical_type(obj, "WhiteCell")

        self._initializing = False
        App.Console.PrintMessage(f"[OBA] White Cell proxy attached: {obj.Name}\n")

    # ==================================================================
    # C H I L D R E N
    # ==================================================================

    def _ensure_children(self, obj):
        doc = obj.Document
        # --------------------------------------------------------------
        # Main Mirror
        # --------------------------------------------------------------

        main_mirror = getattr(obj, "MainMirror", None)

        if _obj_exists(main_mirror):
            self._mainMirror = main_mirror

        elif not _obj_exists(self._mainMirror):
            self._mainMirror = None

        # --------------------------------------------------------------
        # Comp Mirror
        # --------------------------------------------------------------

        comp_mirror = getattr(obj, "CompMirror", None)

        if _obj_exists(comp_mirror):
            self._compMirror = comp_mirror

        elif not _obj_exists(self._compMirror):
            self._compMirror = None

        # --------------------------------------------------------------
        # Emitter
        # --------------------------------------------------------------

        emitter = getattr(obj, "Emitter", None)
        if _obj_exists(emitter):
            self._emitter = emitter

        elif not _obj_exists(self._emitter):
            self._emitter = None

        # --------------------------------------------------------------
        # Detector
        # --------------------------------------------------------------
        detector = getattr(obj, "Detector", None)
        if _obj_exists(detector):
            self._detector = detector
        elif not _obj_exists(self._detector):
            self._detector = None

        # ==============================================================
        # CREATE MAIN MIRROR
        # ==============================================================
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
                x=0,  # float(obj.MainMirrorX),
                y=float(obj.MainMirrorY),
                z=0,  # float(obj.MainMirrorZ),
                show_dialog=False,
            )

        # ==============================================================
        # CREATE COMP MIRROR
        # ==============================================================
        if self._compMirror is None:
            self._compMirror = OBA_CreateCompMirror(
                doc=doc,
                label=f"{obj.Label} Comp Mirror",
                width=float(obj.MainMirrorWidth),  # CompMirrorWidth),
                height=float(obj.MainMirrorHeight),  # CompMirrorHeight),
                a=float(obj.CompMirrorA),
                b=float(obj.CompMirrorB),
                x=0,  # float(obj.CompMirrorX),
                y=0,  # float(obj.CompMirrorY),
                z=0,  # float(obj.CompMirrorZ),
                show_dialog=False,
            )

        # ==============================================================
        # CREATE EMITTER
        # ==============================================================

        if self._emitter is None:
            self._emitter = OBA_CreateEllipsoid(
                doc=doc,
                label=f"{obj.Label} Emitter",
                aplanewidth=float(obj.EmitterAPlaneWidth),
                aplaneheight=float(obj.EmitterAPlaneHeight),
                a=float(obj.EmitterA),
                b=float(obj.EmitterB),
                b2=float(obj.EmitterB2),
                rot_x=float(obj.EmitterRotX),
                rot_y=float(obj.EmitterRotY),
                rot_z=float(obj.EmitterRotZ),
                x=float(obj.EmitterX),
                y=float(obj.EmitterY),
                z=-float(obj.MainMirrorHeight / 2),  #     float(obj.EmitterZ),
                show_dialog=False,
            )

        # ==============================================================
        # CREATE DETECTOR
        # ==============================================================
        if self._detector is None:
            self._detector = OBA_CreateEllipsoid(
                doc=doc,
                label=f"{obj.Label} Detector",
                aplanewidth=float(obj.DetectorAPlaneWidth),
                aplaneheight=float(obj.DetectorAPlaneHeight),
                a=float(obj.DetectorA),
                b=float(obj.DetectorB),
                b2=float(obj.DetectorB2),
                rot_x=float(obj.DetectorRotX),
                rot_y=float(obj.DetectorRotY),
                rot_z=float(obj.DetectorRotZ),
                x=float(obj.DetectorX),
                y=float(obj.DetectorY),
                z=-float(obj.MainMirrorHeight / 2),  #  float(obj.DetectorZ),
                show_dialog=False,
            )

        if self._cutEmitter is None:
            self._cutEmitter = doc.addObject("Part::Cut", f"{obj.Name}_CutEmitter")
            self._cutEmitter.Label = f"{obj.Label} Cut"

        self._cutEmitter.Base = self._compMirror.Proxy._cut
        self._cutEmitter.Tool = self._emitter.Proxy._box_bound

        # --------------------------------------------------------------
        # Persistent links
        # --------------------------------------------------------------
        obj.MainMirror = self._mainMirror
        obj.CompMirror = self._compMirror
        obj.Emitter = self._emitter
        obj.Detector = self._detector

    # ==================================================================
    # U P D A T E   M A I N   M I R R O R
    # ==================================================================

    def _update_main_mirror(self, obj):
        mirror = self._mainMirror
        if not _obj_exists(mirror):
            return
        proxy = getattr(mirror, "Proxy", None)
        try:
            if proxy is not None:
                proxy._initializing = True

            _set_quantity(mirror, "Width", obj.MainMirrorWidth, "mm")
            _set_quantity(mirror, "Height", obj.MainMirrorHeight, "mm")
            _set_quantity(mirror, "SplitOffset", obj.MainMirrorSplitOffset, "mm")
            _set_quantity(mirror, "A", obj.MainMirrorA, "mm")
            _set_quantity(mirror, "B", obj.MainMirrorB, "mm")
            _set_quantity(mirror, "TiltAngle", obj.MainMirrorTiltAngle, "deg")

            mirror.Placement = App.Placement(
                App.Vector(
                    0,  # float(obj.MainMirrorX),
                    float(obj.MainMirrorY),
                    0,  # float(obj.MainMirrorZ),
                ),
                App.Rotation(),
            )
        finally:
            if proxy is not None:
                proxy._initializing = False
        try:
            if proxy is not None:
                proxy._rebuild(mirror)
        except Exception as exc:
            App.Console.PrintError("[OBA] Failed to rebuild Main Mirror " f"from White Cell: {exc}\n")

    # ==================================================================
    # U P D A T E   C O M P   M I R R O R
    # ==================================================================

    def _update_comp_mirror(self, obj):

        mirror = self._compMirror
        if not _obj_exists(mirror):
            return
        proxy = getattr(mirror, "Proxy", None)

        try:
            if proxy is not None:
                proxy._initializing = True

            _set_quantity(mirror, "Width", obj.MainMirrorWidth, "mm")  # CompMirrorWidth
            _set_quantity(mirror, "Height", obj.MainMirrorHeight, "mm")  # CompMirrorHeight
            _set_quantity(mirror, "A", obj.CompMirrorA, "mm")
            _set_quantity(mirror, "B", obj.CompMirrorB, "mm")

            mirror.Placement = App.Placement(
                App.Vector(
                    0,  # float(obj.CompMirrorX),
                    0,  #  float(obj.CompMirrorY),
                    0,  #  float(obj.CompMirrorZ),
                ),
                App.Rotation(),
            )

        finally:

            if proxy is not None:
                proxy._initializing = False

        try:

            if proxy is not None:
                proxy._rebuild(mirror)

        except Exception as exc:

            App.Console.PrintError("[OBA] Failed to rebuild Comp Mirror " f"from White Cell: {exc}\n")

    # ==================================================================
    # U P D A T E   E L L I P S O I D
    # ==================================================================

    def _update_ellipsoid(self, ellipsoid, prefix, obj):
        if not _obj_exists(ellipsoid):
            return

        proxy = getattr(ellipsoid, "Proxy", None)
        try:
            if proxy is not None:
                proxy._initializing = True

            # ----------------------------------------------------------
            # Geometry
            # ----------------------------------------------------------

            if hasattr(ellipsoid, "APlaneWidth"):
                _set_quantity(ellipsoid, "APlaneWidth", getattr(obj, f"{prefix}APlaneWidth"), "mm")

            if hasattr(ellipsoid, "APlaneHeight"):
                _set_quantity(ellipsoid, "APlaneHeight", getattr(obj, f"{prefix}APlaneHeight"), "mm")

            if hasattr(ellipsoid, "A"):
                _set_quantity(ellipsoid, "A", getattr(obj, f"{prefix}A"), "mm")

            if hasattr(ellipsoid, "B"):
                _set_quantity(ellipsoid, "B", getattr(obj, f"{prefix}B"), "mm")

            # ----------------------------------------------------------
            # B2
            # ----------------------------------------------------------

            if hasattr(ellipsoid, "B2"):
                _set_quantity(ellipsoid, "B2", getattr(obj, f"{prefix}B2"), "mm")

            # ----------------------------------------------------------
            # Rotation
            # ----------------------------------------------------------

            if hasattr(ellipsoid, "RotX"):
                _set_quantity(ellipsoid, "RotX", getattr(obj, f"{prefix}RotX"), "deg")

            if hasattr(ellipsoid, "RotY"):
                _set_quantity(ellipsoid, "RotY", getattr(obj, f"{prefix}RotY"), "deg")

            if hasattr(ellipsoid, "RotZ"):
                _set_quantity(ellipsoid, "RotZ", getattr(obj, f"{prefix}RotZ"), "deg")

            # ----------------------------------------------------------
            # Placement
            # ----------------------------------------------------------

            ellipsoid.Placement = App.Placement(
                App.Vector(
                    float(getattr(obj, f"{prefix}X")),
                    float(getattr(obj, f"{prefix}Y")),
                    float(getattr(obj, f"{prefix}Z")) - float(obj.MainMirrorHeight) / 2,
                ),
                App.Rotation(),
            )

        finally:
            if proxy is not None:
                proxy._initializing = False

        # --------------------------------------------------------------
        # Rebuild
        # --------------------------------------------------------------
        try:
            if proxy is not None:
                proxy._rebuild(ellipsoid)
        except Exception as exc:
            App.Console.PrintError(f"[OBA] Failed to rebuild {prefix} " f"from White Cell: {exc}\n")

    # ==================================================================
    # R E B U I L D
    # ==================================================================

    def _rebuild(self, obj):
        if self._rebuilding:
            return
        self._rebuilding = True

        try:
            self._ensure_children(obj)
            self._update_main_mirror(obj)
            self._update_comp_mirror(obj)
            self._update_ellipsoid(self._emitter, "Emitter", obj)
            self._update_ellipsoid(self._detector, "Detector", obj)

            obj.Document.recompute()

        except Exception as exc:

            App.Console.PrintError("[OBA] White Cell rebuild failed: " f"{exc}\n")

        finally:

            self._rebuilding = False

    # ==================================================================
    # C H A N G E D
    # ==================================================================

    def onChanged(self, obj, prop):

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
            # comp mirror
            "CompMirrorWidth",
            "CompMirrorHeight",
            "CompMirrorA",
            "CompMirrorB",
        }

        comp_properties = {
            "CompMirrorWidth",
            "CompMirrorHeight",
            "CompMirrorA",
            "CompMirrorB",
            # "CompMirrorX",
            # "CompMirrorY",
            # "CompMirrorZ",
        }

        emitter_properties = {
            "EmitterAPlaneWidth",
            "EmitterAPlaneHeight",
            "EmitterA",
            "EmitterB",
            "EmitterB2",
            "EmitterRotX",
            "EmitterRotY",
            "EmitterRotZ",
            "EmitterX",
            "EmitterY",
            "EmitterZ",
        }

        detector_properties = {
            "DetectorAPlaneWidth",
            "DetectorAPlaneHeight",
            "DetectorA",
            "DetectorB",
            "DetectorB2",
            "DetectorRotX",
            "DetectorRotY",
            "DetectorRotZ",
            "DetectorX",
            "DetectorY",
            "DetectorZ",
        }

        # --------------------------------------------------------------
        # Main Mirror
        # --------------------------------------------------------------

        if prop in main_properties:
            try:
                self._ensure_children(obj)
                self._update_main_mirror(obj)
                self._update_comp_mirror(obj)

                obj.Document.recompute()
            except Exception as exc:
                App.Console.PrintError("[OBA] White Cell Main Mirror " f"update failed: {exc}\n")
            self._refresh_dialog()
            return

        # --------------------------------------------------------------
        # Comp Mirror
        # --------------------------------------------------------------

        # if prop in comp_properties:
        #     try:
        #         self._ensure_children(obj)
        #         self._update_comp_mirror(obj)
        #         obj.Document.recompute()

        #     except Exception as exc:
        #         App.Console.PrintError("[OBA] White Cell Comp Mirror " f"update failed: {exc}\n")
        #     self._refresh_dialog()

        #     return

        # --------------------------------------------------------------
        # Emitter
        # --------------------------------------------------------------

        if prop in emitter_properties:
            try:
                self._ensure_children(obj)
                self._update_ellipsoid(self._emitter, "Emitter", obj)

                obj.Document.recompute()
            except Exception as exc:
                App.Console.PrintError("[OBA] White Cell Emitter " f"update failed: {exc}\n")
            self._refresh_dialog()

            return

        # --------------------------------------------------------------
        # Detector
        # --------------------------------------------------------------

        if prop in detector_properties:
            try:
                self._ensure_children(obj)
                self._update_ellipsoid(self._detector, "Detector", obj)
                obj.Document.recompute()

            except Exception as exc:

                App.Console.PrintError("[OBA] White Cell Detector " f"update failed: {exc}\n")

            self._refresh_dialog()

            return

    # ==================================================================
    # D I A L O G   R E F R E S H
    # ==================================================================

    def _refresh_dialog(self):

        dialog = getattr(
            self,
            "_dialog",
            None,
        )

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

    def _add_checked_spin_old(self, label, optimize, minimum, maximum, unit, form):
        from types import SimpleNamespace

        row_widget = QtWidgets.QWidget()

        layout = QtWidgets.QHBoxLayout(row_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        checkbox = QtWidgets.QCheckBox()
        checkbox.setChecked(bool(optimize))

        spinbox = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")

        spinbox.setProperty("minimum", minimum)
        spinbox.setProperty("maximum", maximum)
        spinbox.setProperty("unit", unit)

        layout.addWidget(checkbox)
        layout.addWidget(spinbox)

        form.addRow(label, row_widget)

        return SimpleNamespace(
            widget=row_widget,
            checkbox=checkbox,
            spinbox=spinbox,
        )

    # def _add_checked_spin(self, label, optimize=False, minimum=0.0, maximum=1000.0, unit="mm", form=None):

    def _add_checked_spin(self, prop, label, optimize=False, minimum=0.0, maximum=1000.0, unit="mm", form=None):
        """
        Create a row containing:
            [ ] checkbox    [ QuantitySpinBox ]
        Returns:

            widget.checkbox
            widget.spinbox
            widget.widget
        """
        from types import SimpleNamespace

        row_widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        # --------------------------------------------------------------
        # Checkbox
        # --------------------------------------------------------------
        checkbox = QtWidgets.QCheckBox()
        checkbox.setChecked(bool(optimize))
        # --------------------------------------------------------------
        # Quantity SpinBox
        # --------------------------------------------------------------

        spinbox = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        spinbox.setProperty("minimum", minimum)
        spinbox.setProperty("maximum", maximum)
        spinbox.setProperty("unit", unit)
        spinbox.setProperty("rawValue", float(getattr(self.obj, prop)))
        spinbox.setProperty("binding", f"{self.obj.Name}.{prop}")

        # --------------------------------------------------------------
        # Layout
        # --------------------------------------------------------------
        layout.addWidget(checkbox, 0)
        layout.addWidget(spinbox, 1)
        if form is not None:
            form.addRow(label, row_widget)

        return SimpleNamespace(widget=row_widget, checkbox=checkbox, spinbox=spinbox, label=label)

    def __init__(self, obj, title="White Cell Settings", parent=None):

        super().__init__(obj, title=title, parent=parent)

        self._refreshing_ui = False

        self._widgets = {}
        groups = {}

        for prop in WHITE_CELL_PROPERTIES:
            if not prop.get("visible", True):
                continue
            if prop["type"] == "App::PropertyLink":
                continue

            group_name = prop["group"]
            if group_name not in groups:
                group_box = QtWidgets.QGroupBox(group_name)
                form = QtWidgets.QFormLayout(group_box)
                groups[group_name] = form
                self.custom_layout.addWidget(group_box)
            form = groups[group_name]

            widget = self._add_checked_spin(
                prop=prop["name"],
                label=prop.get("label", prop["name"]),
                optimize=prop.get("optimize", False),
                minimum=prop.get("min", 0),
                maximum=prop.get("max", 1000),
                unit=prop.get("unit", "mm"),
                form=form,
            )
            self._widgets[prop["name"]] = widget

        # ==============================================================
        # S I G N A L S
        # ==============================================================

        for name, widget in self._widgets.items():
            widget.spinbox.valueChanged.connect(lambda value, p=name: self._set_property(p, value.Value))

        self.refresh_from_object()

        try:
            self.obj.Proxy._dialog = self
        except Exception:
            pass

    # ==================================================================
    # S E T   P R O P E R T Y
    # ==================================================================

    def _set_property(self, prop, value):

        if self._refreshing_ui:
            return
        try:
            setattr(self.obj, prop, value)
            self.obj.Document.recompute()
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

    def closeEvent(self, event):

        try:

            if self.obj.Proxy._dialog is self:
                self.obj.Proxy._dialog = None

        except Exception:
            pass

        super().closeEvent(event)


# ======================================================================
# V I E W   P R O V I D E R
# ======================================================================


class WhiteCellViewProvider(OBAToolboxViewProviderBase):

    dialog_class = WhiteCellDialog

    def __init__(self, vobj):

        super().__init__(
            vobj,
            WhiteCellDialog,
        )

    def attach(self, vobj):

        self.ViewObject = vobj
        self.Object = vobj.Object

    # ==================================================================
    # T R A N S F O R M
    # ==================================================================

    def canTransform(self):

        # White Cell itself has no geometry.
        #
        # Placement is handled by the child optical objects.

        return False

    # ==================================================================
    # C H I L D R E N
    # ==================================================================

    def claimChildren(self):

        obj = getattr(
            self,
            "Object",
            None,
        )

        if obj is None:
            return []

        proxy = getattr(
            obj,
            "Proxy",
            None,
        )

        if proxy is None:
            return []

        children = []

        main_mirror = getattr(
            proxy,
            "_mainMirror",
            None,
        )

        comp_mirror = getattr(
            proxy,
            "_compMirror",
            None,
        )

        emitter = getattr(
            proxy,
            "_emitter",
            None,
        )

        detector = getattr(
            proxy,
            "_detector",
            None,
        )

        if _obj_exists(main_mirror):
            children.append(main_mirror)

        if _obj_exists(comp_mirror):
            children.append(comp_mirror)

        if _obj_exists(emitter):
            children.append(emitter)

        if _obj_exists(detector):
            children.append(detector)

        return children

    # ==================================================================
    # D O U B L E   C L I C K
    # ==================================================================

    def doubleClicked(self, vobj):

        obj = getattr(
            vobj,
            "Object",
            None,
        )

        if obj is None:
            return False

        try:

            dialog = WhiteCellDialog(
                obj,
                title="White Cell Settings",
            )

            self._dialog = dialog

            try:
                obj.Proxy._dialog = dialog
            except Exception:
                pass

            dialog.show()
            dialog.raise_()
            dialog.activateWindow()

            return True

        except Exception as exc:

            App.Console.PrintError("[OBA] Failed to open White Cell dialog: " f"{exc}\n")

            return False

    # ==================================================================
    # D E L E T E
    # ==================================================================

    def onDelete(self, vobj, subelements):

        obj = getattr(self, "Object", None)

        if obj is None:
            return True

        proxy = getattr(obj, "Proxy", None)

        if proxy is None:
            return True

        doc = obj.Document

        # --------------------------------------------------------------
        # Close White Cell dialog
        # --------------------------------------------------------------

        dialog = getattr(
            proxy,
            "_dialog",
            None,
        )

        if dialog is not None:

            try:
                dialog.close()
            except Exception:
                pass

            proxy._dialog = None

        # --------------------------------------------------------------
        # Delete high-level child objects.
        #
        # Each child owns its own construction geometry.
        # --------------------------------------------------------------

        for attr_name in reversed(
            getattr(
                proxy,
                "CHILD_OBJECTS",
                (),
            )
        ):

            child = getattr(
                proxy,
                attr_name,
                None,
            )

            if not _obj_exists(child):
                continue

            try:

                child_proxy = getattr(
                    child,
                    "Proxy",
                    None,
                )

                # If the child provides its own delete method,
                # use it. This is the safest way to let the child
                # remove its construction objects.
                if child_proxy is not None and hasattr(
                    child_proxy,
                    "delete",
                ):

                    child_proxy.delete()

                else:

                    existing = doc.getObject(child.Name)

                    if existing is not None:
                        doc.removeObject(child.Name)

            except Exception as exc:

                App.Console.PrintError("[OBA] Could not remove White Cell child " f"{child.Name}: {exc}\n")

        return True


# ======================================================================
# F A C T O R Y
# ======================================================================


def OBA_CreateWhiteCell(
    doc=None,
    label="White_Cell",
    # ------------------------------------------------------------------
    # Main Mirror
    # ------------------------------------------------------------------
    main_mirror_width=100.0,
    main_mirror_height=33.0,
    main_mirror_split_offset=40.0,
    main_mirror_a=40.0,
    main_mirror_b=31.0,
    main_mirror_tiltangle=0.0,
    main_mirror_x=0.0,
    main_mirror_y=0.0,
    main_mirror_z=0.0,
    # ------------------------------------------------------------------
    # Comp Mirror
    # ------------------------------------------------------------------
    comp_mirror_width=100.0,
    comp_mirror_height=30.0,
    comp_mirror_a=40.0,
    comp_mirror_b=30.0,
    comp_mirror_x=0.0,
    comp_mirror_y=0.0,
    comp_mirror_z=0.0,
    # ------------------------------------------------------------------
    # Emitter
    # ------------------------------------------------------------------
    emitter_aplanewidth=5.0,
    emitter_aplaneheight=5.0,
    emitter_a=40.0,
    emitter_b=20.0,
    emitter_b2=20.0,
    emitter_rot_x=30.0,
    emitter_rot_y=0.0,
    emitter_rot_z=0.0,
    emitter_x=-50.0,
    emitter_y=0.0,
    emitter_z=0.0,
    # ------------------------------------------------------------------
    # Detector
    # ------------------------------------------------------------------
    detector_aplanewidth=5.0,
    detector_aplaneheight=5.0,
    detector_a=40.0,
    detector_b=20.0,
    detector_b2=20.0,
    detector_rot_x=30.0,
    detector_rot_y=0.0,
    detector_rot_z=0.0,
    detector_x=50.0,
    detector_y=0.0,
    detector_z=0.0,
    show_dialog=True,
):
    doc = doc or App.ActiveDocument or App.newDocument()

    # ==================================================================
    # V A L I D A T E
    # ==================================================================

    # Main Mirror
    if main_mirror_width <= 0:
        raise ValueError("Main Mirror Width must be greater than zero.")
    if main_mirror_height <= 0:
        raise ValueError("Main Mirror Height must be greater than zero.")
    if main_mirror_split_offset < 0 or main_mirror_split_offset > main_mirror_width:
        raise ValueError("Main Mirror SplitOffset must be between " "zero and Width.")
    if main_mirror_a <= 0:
        raise ValueError("Main Mirror A must be greater than zero.")
    if main_mirror_b <= 0:
        raise ValueError("Main Mirror B must be greater than zero.")
    if main_mirror_a < main_mirror_b:
        raise ValueError("Main Mirror A must be greater than or equal to B.")
    if main_mirror_b > main_mirror_height:
        raise ValueError("Main Mirror B must be less than or equal to Height.")
    # Comp Mirror
    if comp_mirror_width <= 0:
        raise ValueError("Comp Mirror Width must be greater than zero.")
    if comp_mirror_height <= 0:
        raise ValueError("Comp Mirror Height must be greater than zero.")
    if comp_mirror_a <= 0:
        raise ValueError("Comp Mirror A must be greater than zero.")
    if comp_mirror_b <= 0:
        raise ValueError("Comp Mirror B must be greater than zero.")
    if comp_mirror_a < comp_mirror_b:
        raise ValueError("Comp Mirror A must be greater than or equal to B.")
    if comp_mirror_b > comp_mirror_height:
        raise ValueError("Comp Mirror B must be less than or equal to Height.")
    # Emitter
    if emitter_aplanewidth <= 0:
        raise ValueError("Emitter APlaneWidth must be greater than zero.")
    if emitter_aplaneheight <= 0:
        raise ValueError("Emitter APlaneHeight must be greater than zero.")
    if emitter_a <= 0:
        raise ValueError("Emitter A must be greater than zero.")
    if emitter_b <= 0:
        raise ValueError("Emitter B must be greater than zero.")
    if emitter_b2 <= 0:
        raise ValueError("Emitter B2 must be greater than zero.")
    if emitter_a < emitter_b:
        raise ValueError("Emitter A must be greater than or equal to B.")
    if emitter_x >= 0:
        raise ValueError("Emitter X must be negative.")

    # Detector

    if detector_aplanewidth <= 0:
        raise ValueError("Detector APlaneWidth must be greater than zero.")
    if detector_aplaneheight <= 0:
        raise ValueError("Detector APlaneHeight must be greater than zero.")
    if detector_a <= 0:
        raise ValueError("Detector A must be greater than zero.")
    if detector_b <= 0:
        raise ValueError("Detector B must be greater than zero.")
    if detector_b2 <= 0:
        raise ValueError("Detector B2 must be greater than zero.")
    if detector_a < detector_b:
        raise ValueError("Detector A must be greater than or equal to B.")
    if detector_x <= 0:
        raise ValueError("Detector X must be positive.")

    # ==================================================================
    # C R E A T E   W H I T E   C E L L
    # ==================================================================

    obj = doc.addObject("Part::FeaturePython", "OBA_WhiteCell")
    obj.Label = label
    proxy = OBAWhiteCell(obj)
    proxy._initializing = True

    # ==================================================================
    # S T O R E   M A I N   M I R R O R
    # ==================================================================

    obj.MainMirrorWidth = App.Units.Quantity(f"{main_mirror_width} mm")
    obj.MainMirrorHeight = App.Units.Quantity(f"{main_mirror_height} mm")
    obj.MainMirrorSplitOffset = App.Units.Quantity(f"{main_mirror_split_offset} mm")
    obj.MainMirrorA = App.Units.Quantity(f"{main_mirror_a} mm")
    obj.MainMirrorB = App.Units.Quantity(f"{main_mirror_b} mm")
    obj.MainMirrorTiltAngle = App.Units.Quantity(f"{main_mirror_tiltangle} deg")
    # obj.MainMirrorX = App.Units.Quantity(f"{main_mirror_x} mm")
    obj.MainMirrorY = App.Units.Quantity(f"{main_mirror_y} mm")
    # obj.MainMirrorZ = App.Units.Quantity(f"{main_mirror_z} mm")

    # ==================================================================
    # S T O R E   C O M P   M I R R O R
    # ==================================================================

    # obj.CompMirrorWidth = App.Units.Quantity(f"{comp_mirror_width} mm")
    # obj.CompMirrorHeight = App.Units.Quantity(f"{comp_mirror_height} mm")
    obj.CompMirrorA = App.Units.Quantity(f"{comp_mirror_a} mm")
    obj.CompMirrorB = App.Units.Quantity(f"{comp_mirror_b} mm")
    # obj.CompMirrorX = App.Units.Quantity(f"{comp_mirror_x} mm")
    # obj.CompMirrorY = App.Units.Quantity(f"{comp_mirror_y} mm")
    # obj.CompMirrorZ = App.Units.Quantity(f"{comp_mirror_z} mm")

    # ==================================================================
    # S T O R E   E M I T T E R
    # ==================================================================

    obj.EmitterAPlaneWidth = App.Units.Quantity(f"{emitter_aplanewidth} mm")
    obj.EmitterAPlaneHeight = App.Units.Quantity(f"{emitter_aplaneheight} mm")
    obj.EmitterA = App.Units.Quantity(f"{emitter_a} mm")
    obj.EmitterB = App.Units.Quantity(f"{emitter_b} mm")
    obj.EmitterB2 = App.Units.Quantity(f"{emitter_b2} mm")
    obj.EmitterRotX = App.Units.Quantity(f"{emitter_rot_x} deg")
    obj.EmitterRotY = App.Units.Quantity(f"{emitter_rot_y} deg")
    obj.EmitterRotZ = App.Units.Quantity(f"{emitter_rot_z} deg")

    obj.EmitterX = App.Units.Quantity(f"{emitter_x} mm")
    obj.EmitterY = App.Units.Quantity(f"{emitter_y} mm")

    obj.EmitterZ = App.Units.Quantity(f"{emitter_z} mm")

    # ==================================================================
    # S T O R E   D E T E C T O R
    # ==================================================================

    obj.DetectorAPlaneWidth = App.Units.Quantity(f"{detector_aplanewidth} mm")
    obj.DetectorAPlaneHeight = App.Units.Quantity(f"{detector_aplaneheight} mm")
    obj.DetectorA = App.Units.Quantity(f"{detector_a} mm")
    obj.DetectorB = App.Units.Quantity(f"{detector_b} mm")
    obj.DetectorB2 = App.Units.Quantity(f"{detector_b2} mm")
    obj.DetectorRotX = App.Units.Quantity(f"{detector_rot_x} deg")
    obj.DetectorRotY = App.Units.Quantity(f"{detector_rot_y} deg")
    obj.DetectorRotZ = App.Units.Quantity(f"{detector_rot_z} deg")

    obj.DetectorX = App.Units.Quantity(f"{detector_x} mm")

    obj.DetectorY = App.Units.Quantity(f"{detector_y} mm")

    obj.DetectorZ = App.Units.Quantity(f"{detector_z} mm")

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

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    return obj


# ======================================================================
# P U B L I C   C R E A T E
# ======================================================================


def create(
    doc=None,
    label="White_Cell",
    # ------------------------------------------------------------------
    # Main Mirror
    # ------------------------------------------------------------------
    main_mirror_width=100.0,
    main_mirror_height=33.0,
    main_mirror_split_offset=40.0,
    main_mirror_a=40.0,
    main_mirror_b=31.0,
    main_mirror_tiltangle=0.0,
    main_mirror_x=0.0,
    main_mirror_y=32.0,
    main_mirror_z=0.0,
    # ------------------------------------------------------------------
    # Comp Mirror
    # ------------------------------------------------------------------
    comp_mirror_width=100.0,
    comp_mirror_height=30.0,
    comp_mirror_a=40.0,
    comp_mirror_b=30.0,
    comp_mirror_x=0.0,
    comp_mirror_y=0.0,
    comp_mirror_z=0.0,
    # ------------------------------------------------------------------
    # Emitter
    # ------------------------------------------------------------------
    emitter_aplanewidth=5.0,
    emitter_aplaneheight=5.0,
    emitter_a=40.0,
    emitter_b=20.0,
    emitter_b2=20.0,
    emitter_rot_x=30.0,
    emitter_rot_y=0.0,
    emitter_rot_z=0.0,
    emitter_x=-50.0,
    emitter_y=0.0,
    emitter_z=0.0,
    # ------------------------------------------------------------------
    # Detector
    # ------------------------------------------------------------------
    detector_aplanewidth=5.0,
    detector_aplaneheight=5.0,
    detector_a=40.0,
    detector_b=20.0,
    detector_b2=20.0,
    detector_rot_x=30.0,
    detector_rot_y=0.0,
    detector_rot_z=0.0,
    detector_x=50.0,
    detector_y=0.0,
    detector_z=0.0,
):

    return OBA_CreateWhiteCell(
        doc=doc,
        label=label,
        # --------------------------------------------------------------
        # Main Mirror
        # --------------------------------------------------------------
        main_mirror_width=main_mirror_width,
        main_mirror_height=main_mirror_height,
        main_mirror_split_offset=main_mirror_split_offset,
        main_mirror_a=main_mirror_a,
        main_mirror_b=main_mirror_b,
        main_mirror_tiltangle=main_mirror_tiltangle,
        main_mirror_x=main_mirror_x,
        main_mirror_y=main_mirror_y,
        main_mirror_z=main_mirror_z,
        # --------------------------------------------------------------
        # Comp Mirror
        # --------------------------------------------------------------
        comp_mirror_width=comp_mirror_width,
        comp_mirror_height=comp_mirror_height,
        comp_mirror_a=comp_mirror_a,
        comp_mirror_b=comp_mirror_b,
        comp_mirror_x=comp_mirror_x,
        comp_mirror_y=comp_mirror_y,
        comp_mirror_z=comp_mirror_z,
        # --------------------------------------------------------------
        # Emitter
        # --------------------------------------------------------------
        emitter_aplanewidth=emitter_aplanewidth,
        emitter_aplaneheight=emitter_aplaneheight,
        emitter_a=emitter_a,
        emitter_b=emitter_b,
        emitter_b2=emitter_b2,
        emitter_rot_x=emitter_rot_x,
        emitter_rot_y=emitter_rot_y,
        emitter_rot_z=emitter_rot_z,
        emitter_x=emitter_x,
        emitter_y=emitter_y,
        emitter_z=emitter_z,
        # --------------------------------------------------------------
        # Detector
        # --------------------------------------------------------------
        detector_aplanewidth=detector_aplanewidth,
        detector_aplaneheight=detector_aplaneheight,
        detector_a=detector_a,
        detector_b=detector_b,
        detector_b2=detector_b2,
        detector_rot_x=detector_rot_x,
        detector_rot_y=detector_rot_y,
        detector_rot_z=detector_rot_z,
        detector_x=detector_x,
        detector_y=detector_y,
        detector_z=detector_z,
    )
