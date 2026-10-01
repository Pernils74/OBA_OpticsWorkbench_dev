# oba_toolbox_base.py
#
# Shared boilerplate for OBA cube + ellipsoid optical components.
#

import math
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtWidgets

from oba_objects.oba_base import (
    OBABaseDialog,
    OBAElementProxy,
    OBAViewProviderBase,
)

BASE_PATH = os.path.dirname(__file__)


def set_property_if_changed(obj, name, value):
    if getattr(obj, name) == value:
        return False

    setattr(obj, name, value)
    return True


def set_quantity_if_changed(obj, name, value, unit):
    current = float(getattr(obj, name))
    new = float(value)

    if abs(current - new) < 1e-9:
        return False

    setattr(obj, name, App.Units.Quantity(f"{new} {unit}"))
    return True


def focus_distance(a, b):
    """Return C = sqrt(A² - B²), the centre-to-focus distance."""
    if a <= 0 or b <= 0:
        raise ValueError("A and B must be greater than zero.")
    major = max(a, b)
    minor = min(a, b)
    return math.sqrt(major * major - minor * minor)
    # if a < b:
    #     # raise ValueError(f"A must be greater than or equal to B. A={a}, B={b}")
    #     return math.sqrt(max(0.0, b * b - a * a))
    # return math.sqrt(max(0.0, a * a - b * b))


def validate_cube(width, height):
    if width <= 0:
        raise ValueError("Width must be greater than zero.")
    if height <= 0:
        raise ValueError("Height must be greater than zero.")


def validate_ellipsoid(a, b, b2=None):
    if a <= 0 or b <= 0:
        raise ValueError("A and B must be greater than zero.")
    if a < b:
        raise ValueError(f"A must be greater than or equal to B. A={a}, B={b}")
    if b2 is not None and b2 <= 0:
        raise ValueError("B2 must be greater than zero.")


def install_properties(obj, specs):
    for spec in specs:
        name = spec["name"]
        created = False
        # ----------------------------------------------------------
        # Create property if missing
        # ----------------------------------------------------------
        if not hasattr(obj, name):
            obj.addProperty(spec["type"], name, spec["group"], spec.get("doc", ""))
            created = True
        # ----------------------------------------------------------
        # Set default only for newly created properties
        # ----------------------------------------------------------
        if created and "default" in spec:
            setattr(obj, name, spec["default"])
        # ----------------------------------------------------------
        # Optuna lock property
        # ----------------------------------------------------------
        if "optuna_locked" in spec:
            lock_name = f"{name}_OptunaLocked"
            lock_created = False

            if not hasattr(obj, lock_name):
                obj.addProperty("App::PropertyBool", lock_name, "Optimization", "Locked from Optuna")
                lock_created = True

            if lock_created:
                setattr(obj, lock_name, spec.get("optuna_locked", False))


def make_calculated_length(obj, name, doc):
    if not hasattr(obj, name):
        obj.addProperty("App::PropertyLength", name, "Calculated", doc)
    obj.setEditorMode(name, 1)


def make_optical_type(obj, value):
    if not hasattr(obj, "OpticalType"):
        obj.addProperty(
            "App::PropertyString",
            "OpticalType",
            "Base",
            "Type of optical element",
        )
    obj.OpticalType = value


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


class OBAToolboxViewProviderBase(OBAViewProviderBase):
    """Shared view-provider boilerplate for mirror components."""

    dialog_class = None

    def __init__(self, vobj, dialog_class):
        self.dialog_class = dialog_class
        super().__init__(vobj)
        self.dialog_class = dialog_class
        try:
            vobj.DisplayMode = "Flat Lines"
        except Exception:
            pass

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
        obj = getattr(self, "Object", None)
        if obj is None:
            return []
        return [child for child in getattr(obj, "Group", []) if _obj_exists(child)]

    def doubleClicked(self, vobj):
        obj = getattr(vobj, "Object", None)
        if obj is None:
            return False
        try:
            if not self.dialog_class:
                return False
            dialog = self.dialog_class(obj)
            try:
                obj.Proxy._dialog = dialog
            except Exception:
                pass
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return True
        except Exception as exc:
            App.Console.PrintError(f"[OBA] Failed to open dialog: {exc}\n")
            return False

    def getIcon(self):
        try:
            obj = self.Object
            ot = getattr(obj, "OpticalType", "").lower()
            if not ot:
                return ""

            # print("ikooon", ot)
            path = os.path.join(BASE_PATH, "..", "icons", f"oba_{ot}.svg")
            if os.path.exists(path):
                return path
        except Exception:
            pass
        return ""

    def onDocumentRestored(self, vobj):
        super().onDocumentRestored(vobj)
        self.dialog_class = type(self).dialog_class
        # restore_view_provider(obj, WhiteCellMainMirrorViewProvider, WhiteCellMainMirrorDialog)


class OBAToolboxDialogBase(OBABaseDialog):
    """Shared placement/debug helpers used by mirror dialogs."""

    ALLOW_SURFACE_SELECTION = False

    PROPERTY_DEFINITIONS = []  # måste sättas i underklasserna

    def __init__(self, obj, title, parent=None):
        super().__init__(obj, title=title, parent=parent)
        self._closing = False

    def get_limits(self, value, unit):
        value = float(value)
        # Specialfall för nollvärden
        if abs(value) < 1e-9:
            if unit == "deg":
                return -3.0, 3.0
            if unit == "mm":
                return -5.0, 5.0
            if unit == "%":
                return 0.5, 2.0
            return -1.0, 1.0
        # Normalt ±5%
        delta = abs(value) * 0.1
        return value - delta, value + delta

    def export_to_spreadsheet(self, properties=PROPERTY_DEFINITIONS):
        doc = self.obj.Document
        obj = self.obj

        sheet = doc.getObject("Spreadsheet")
        if sheet is None:
            sheet = doc.addObject("Spreadsheet::Sheet", "Spreadsheet")

        sheet.set("A1", "Property")
        sheet.set("B1", "Value")
        sheet.set("C1", "Min")
        sheet.set("D1", "Max")
        row = 2

        for prop_def in properties:  #  WHITE_CELL_PROPERTIES:
            if prop_def["type"] == "App::PropertyLink":
                continue
            prop = prop_def["name"]
            unit = prop_def.get("unit", "")

            try:
                value = getattr(obj, prop)
                sheet.set(f"A{row}", prop)
                sheet.set(f"B{row}", str(value))

                sheet.setAlias(f"B{row}", prop)
                obj.setExpression(prop, f"{sheet.Name}.{prop}")

                try:
                    numeric_value = float(value)
                    min_val, max_val = self.get_limits(numeric_value, unit)
                    sheet.set(f"C{row}", str(min_val))
                    sheet.set(f"D{row}", str(max_val))
                    # sheet.set(f"C{row}", str(numeric_value * 0.95))
                    # sheet.set(f"D{row}", str(numeric_value * 1.05))
                except Exception:
                    print("error")
                    pass
                row += 1
            except Exception as exc:
                App.Console.PrintError(f"Spreadsheet export failed: {exc}\n")
            sheet.set(f"A{row}", "END")

        obj.touch()
        doc.recompute()
        self.reopen()

    def clear_spreadsheet_references(self, properties=PROPERTY_DEFINITIONS):
        for prop_def in properties:
            if prop_def["type"] == "App::PropertyLink":
                continue
            self.obj.setExpression(prop_def["name"], None)
        self.obj.Document.recompute()
        self.reopen()

    def update_optuna_config(self, properties=PROPERTY_DEFINITIONS):
        import json

        doc = self.obj.Document
        config = doc.getObject("OptimizeConfig")
        if config is None:
            config = doc.addObject("App::FeaturePython", "OptimizeConfig")
            if "json" not in config.PropertiesList:
                config.addProperty("App::PropertyString", "json", "Config")

            config.json = json.dumps(
                {
                    "active": "default",
                    "configs": {
                        "default": {
                            "entries": [],
                            "selected_params": [],
                            "sampler": "TPESampler",
                            "trials": 500,
                            "constant_liar": True,
                        }
                    },
                },
                indent=4,
            )
        try:
            data = json.loads(config.json)
        except Exception as exc:
            App.Console.PrintError(f"Invalid OptimizeConfig JSON: {exc}\n")
            return
        selected_params = []
        for prop_def in properties:  # self.PROPERTY_DEFINITIONS:
            if prop_def["type"] == "App::PropertyLink":
                continue
            prop = prop_def["name"]
            if getattr(self.obj, f"{prop}_OptunaLocked", False):
                continue
            selected_params.append(prop)

        active = data.get("active", "default")

        configs = data.setdefault("configs", {})
        cfg = configs.setdefault(active, {})
        cfg["selected_params"] = selected_params

        config.json = json.dumps(data, indent=4)
        doc.recompute()
        App.Console.PrintMessage(f"Updated Optuna config with " f"{len(selected_params)} parameters\n")

    def reopen(self):
        # import traceback

        # print("REOPEN")
        # traceback.print_stack(limit=5)

        # print("REOPEN")
        geom = self.geometry()
        self.close()
        dlg = self.__class__(self.obj, title=self.windowTitle())
        dlg.setGeometry(geom)
        try:
            self.obj.Proxy._dialog = dlg
        except Exception:
            pass

        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    # ==================
    # ==================

    def _add_checked_spin(self, prop, label, optuna_locked=False, minimum=0.0, maximum=1000.0, unit="mm", form=None, step=1):
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
        # checkbox.setChecked(bool(optuna_locked))
        checkbox.setChecked(getattr(self.obj, f"{prop}_OptunaLocked", False))
        # --------------------------------------------------------------
        # Quantity SpinBox
        # --------------------------------------------------------------

        spinbox = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        spinbox.setProperty("minimum", minimum)
        spinbox.setProperty("maximum", maximum)
        spinbox.setProperty("unit", unit)
        spinbox.setProperty("singleStep", step)
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

    def _add_spin(self, label, prop, mn, mx, unit, layout, step=1.0):
        w = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        w.setProperty("minimum", mn)
        w.setProperty("maximum", mx)
        w.setProperty("unit", unit)
        w.setProperty("singleStep", step)
        w.setProperty("rawValue", float(getattr(self.obj, prop)))
        w.setProperty("binding", f"{self.obj.Name}.{prop}")
        layout.addRow(label, w)
        return w

    def reload_placement(self):
        placement = self.obj.Placement.Base
        self.pos_x.setValue(placement.x)
        self.pos_y.setValue(placement.y)
        self.pos_z.setValue(placement.z)

    def add_debug_checkbox(self, text="Show debug ellipsoid"):
        self.show_debug = QtWidgets.QCheckBox(text)
        self.show_debug.setChecked(bool(self.obj.ShowDebugEllipsoid))
        self.show_debug.toggled.connect(lambda v: setattr(self.obj, "ShowDebugEllipsoid", v))
        self.custom_layout.addWidget(self.show_debug)

    def closeEvent(self, event):
        print("CLOSEEVENT")
        try:
            # self.obj.Proxy._dialog_is_open = False
            if self.obj.Proxy._dialog is self:
                self.obj.Proxy._dialog = None
        except Exception:
            pass

        super().closeEvent(event)

    def closeEvent_OLD(self, event):
        try:
            if hasattr(self.obj, "ShowDebugEllipsoid"):
                self.obj.ShowDebugEllipsoid = False
        except Exception:
            pass

        if self._closing:
            event.accept()
            return
        self._closing = True
        self.obj.Document.recompute()
        Gui.updateGui()
        super().closeEvent(event)


def ensure_debug_property(obj):
    if not hasattr(obj, "ShowDebugEllipsoid"):
        obj.addProperty(
            "App::PropertyBool",
            "ShowDebugEllipsoid",
            "Debug",
            "Show debug ellipsoid",
        )
        obj.ShowDebugEllipsoid = False


def restore_view_provider(obj, view_provider_cls):
    if not (App.GuiUp and obj.ViewObject):
        return
    if not hasattr(obj.ViewObject, "Proxy") or obj.ViewObject.Proxy is None:
        view_provider_cls(obj.ViewObject)
    else:
        obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)
    obj.ViewObject.update()
