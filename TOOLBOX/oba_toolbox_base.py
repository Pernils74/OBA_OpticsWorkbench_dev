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
from PySide.QtCore import QSignalBlocker

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


def set_spreadsheet_references(obj, properties=None):
    doc = obj.Document
    sheet = doc.getObject("Spreadsheet")
    if sheet is None:
        App.Console.PrintWarning("Spreadsheet not found; no references were set.\n")
        return

    if properties is None:
        view_provider = getattr(getattr(obj, "ViewObject", None), "Proxy", None)
        dialog_class = getattr(view_provider, "dialog_class", None)
        properties = getattr(dialog_class, "PROPERTY_DEFINITIONS", [])

    property_rows = {}
    for row in range(1, 601):
        try:
            property_name = str(sheet.get(f"A{row}") or "").strip()
        except Exception:
            continue
        if property_name.upper() == "END":
            break
        if property_name:
            property_rows[property_name] = row

    try:
        current_expressions = dict(obj.ExpressionEngine)
    except Exception:
        current_expressions = {}

    updated = 0
    missing = []
    numeric_property_types = {
        "App::PropertyAngle",
        "App::PropertyDistance",
        "App::PropertyFloat",
        "App::PropertyInteger",
        "App::PropertyLength",
    }
    for prop_def in properties:
        if not prop_def.get("visible", True) or prop_def.get("display_only", False) or prop_def.get("readonly", False):
            continue
        prop_type = prop_def.get("type", "")
        if prop_type == "App::PropertyLink" or prop_type not in numeric_property_types:
            continue

        prop = prop_def["name"]
        row = property_rows.get(prop)
        if row is None:
            missing.append(prop)
            continue

        try:
            alias = sheet.getAlias(f"B{row}")
        except Exception:
            alias = ""
        cell_reference = alias or f"B{row}"
        expression = f"{sheet.Name}.{cell_reference}"
        if current_expressions.get(prop) == expression:
            continue
        obj.setExpression(prop, expression)
        updated += 1

    if missing:
        App.Console.PrintWarning("Spreadsheet rows missing for: {}\n".format(", ".join(missing)))
    if not updated:
        App.Console.PrintMessage("Spreadsheet references are already up to date.\n")
        return

    doc.recompute()
    App.Console.PrintMessage("Set {} Spreadsheet reference(s).\n".format(updated))


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
    """Shared property-driven dialog and spreadsheet/Optuna actions."""

    ALLOW_SURFACE_SELECTION = False

    PROPERTY_DEFINITIONS = []
    NUMERIC_PROPERTY_TYPES = {
        "App::PropertyAngle",
        "App::PropertyDistance",
        "App::PropertyFloat",
        "App::PropertyInteger",
        "App::PropertyLength",
    }

    def __init__(self, obj, title, parent=None):
        super().__init__(obj, title=title, parent=parent)
        self._closing = False
        self._refreshing_ui = False
        self._widgets = {}
        self._display_widgets = {}
        self._build_action_buttons()
        self._build_property_widgets()
        self.refresh_from_object()
        try:
            self.obj.Proxy._dialog = self
        except Exception:
            pass

    def _property_definitions(self, properties=None):
        return self.PROPERTY_DEFINITIONS if properties is None else properties

    def _iter_editable_properties(self, properties=None, numeric_only=False):
        for prop_def in self._property_definitions(properties):
            if not prop_def.get("visible", True) or prop_def.get("display_only", False) or prop_def.get("readonly", False):
                continue
            prop_type = prop_def.get("type", "")
            if prop_type == "App::PropertyLink":
                continue
            if numeric_only and prop_type not in self.NUMERIC_PROPERTY_TYPES:
                continue
            yield prop_def

    def _build_action_buttons(self):
        layout = QtWidgets.QHBoxLayout()
        self.export_button = QtWidgets.QPushButton("Export to Spreadsheet")
        self.export_button.clicked.connect(lambda: self.export_to_spreadsheet())
        self.clear_button = QtWidgets.QPushButton("Remove Spreadsheet References")
        self.clear_button.clicked.connect(lambda: self.clear_spreadsheet_references())  # lambda används för att kunna skicka med argument
        self.set_references_button = QtWidgets.QPushButton("Set Spreadsheet References")
        self.set_references_button.clicked.connect(lambda: self.set_spreadsheet_references())
        self.optuna_button = QtWidgets.QPushButton("Update Optuna Config")
        self.optuna_button.clicked.connect(lambda: self.update_optuna_config())
        self.boundsEditor_button = QtWidgets.QPushButton("Optuna Bounds Editor")
        self.boundsEditor_button.clicked.connect(lambda: self._open_optuna_bounds_editor())

        self.export_button.setStyleSheet("""
        QPushButton {
            background-color: #176b5b;
            color: white;
            font-weight: 600;
        }
        QPushButton:hover {
            background-color: #125648;
        }
        """)
        self.set_references_button.setStyleSheet("""
        QPushButton {
            background-color: #176b5b;
            color: white;
            font-weight: 600;
        }
        QPushButton:hover {
            background-color: #125648;
        }
        """)
        self.clear_button.setStyleSheet("""
        QPushButton {
            background-color: #a63b3b;
            color: white;
            font-weight: 600;
        }
        QPushButton:hover {
            background-color: #8b2e2e;
        }
        """)
        self.optuna_button.setStyleSheet("""
        QPushButton {
            background-color: #315f91;
            color: white;
            font-weight: 600;
        }
        QPushButton:hover {
            background-color: #264c75;
        }
        """)
        self.boundsEditor_button.setStyleSheet("""
        QPushButton {
            background-color: #6b4c9a;
            color: white;
            font-weight: 600;
        }
        QPushButton:hover {
            background-color: #583d80;
        }
        """)

        layout.addWidget(self.export_button)
        layout.addWidget(self.clear_button)
        layout.addWidget(self.set_references_button)
        layout.addWidget(self.optuna_button)
        layout.addWidget(self.boundsEditor_button)
        self.custom_layout.addLayout(layout)

    def _build_property_widgets(self):
        from types import SimpleNamespace

        parent_groups = {}
        groups = {}
        for prop_def in self.PROPERTY_DEFINITIONS:
            if not prop_def.get("visible", True):
                continue
            prop = prop_def["name"]
            parent_name = prop_def.get("parent_group")
            group_name = prop_def.get("group", "Properties")
            group_key = (parent_name, group_name)

            if parent_name and parent_name not in parent_groups:
                parent_box = QtWidgets.QGroupBox(parent_name)
                parent_layout = QtWidgets.QHBoxLayout(parent_box)
                parent_groups[parent_name] = parent_layout
                self.custom_layout.addWidget(parent_box)

            if group_key not in groups:
                group_box = QtWidgets.QGroupBox(group_name)
                form = QtWidgets.QFormLayout(group_box)
                groups[group_key] = form
                if parent_name:
                    parent_groups[parent_name].addWidget(group_box)
                else:
                    self.custom_layout.addWidget(group_box)
            form = groups[group_key]
            prop_type = prop_def.get("type", "")
            label = prop_def.get("label", prop)

            if prop_def.get("display_only", False):
                value_label = QtWidgets.QLabel()
                form.addRow(label, value_label)
                self._display_widgets[prop] = (value_label, prop_def.get("unit", ""))
                continue
            if prop_type == "App::PropertyLink":
                continue
            if prop_type == "App::PropertyBool":
                widget = QtWidgets.QCheckBox(label)
                form.addRow(widget)
                widget.toggled.connect(lambda value, name=prop: self._set_property(name, value))
                self._widgets[prop] = SimpleNamespace(widget=widget, checkbox=widget, spinbox=None)
                continue
            if prop_type not in self.NUMERIC_PROPERTY_TYPES:
                continue

            unit = prop_def.get("unit")
            if unit is None:
                unit = "deg" if prop_type == "App::PropertyAngle" else "mm" if prop_type in ("App::PropertyLength", "App::PropertyDistance") else ""
            minimum = prop_def.get("min", -360 if unit == "deg" else 0 if prop_type == "App::PropertyLength" else -1_000_000)
            maximum = prop_def.get("max", 360 if unit == "deg" else 1_000_000)
            step = prop_def.get("step", 0.1 if prop_type == "App::PropertyFloat" else 1)
            if "optuna_locked" in prop_def:
                control = self._add_checked_spin(
                    prop=prop,
                    label=label,
                    optuna_locked=prop_def["optuna_locked"],
                    minimum=minimum,
                    maximum=maximum,
                    unit=unit,
                    form=form,
                    step=step,
                )
                control.checkbox.toggled.connect(lambda value, name=prop: self._set_optuna_locked(name, value))
            else:
                spinbox = self._add_spin(label, prop, minimum, maximum, unit, form, step)
                control = SimpleNamespace(widget=spinbox, checkbox=None, spinbox=spinbox)
            if prop_def.get("readonly", False):
                control.spinbox.setReadOnly(True)
            control.spinbox.valueChanged.connect(lambda value, name=prop: self._set_property(name, value.Value))
            self._widgets[prop] = control

        self._refresh_property_enablement()

    def _set_optuna_locked(self, prop, value):
        lock_prop = f"{prop}_OptunaLocked"
        if hasattr(self.obj, lock_prop) and getattr(self.obj, lock_prop) != value:
            setattr(self.obj, lock_prop, value)

    def _set_property(self, prop, value):
        if self._refreshing_ui:
            return
        try:
            current = getattr(self.obj, prop)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if abs(float(current) - float(value)) < 1e-9:
                    return
            elif current == value:
                return
            setattr(self.obj, prop, value)
            self.refresh_from_object()
        except Exception as exc:
            App.Console.PrintError(f"[OBA] Failed to update {prop}: {exc}\n")

    def _refresh_property_enablement(self):
        for prop_def in self.PROPERTY_DEFINITIONS:
            control = self._widgets.get(prop_def["name"])
            if control is None or control.spinbox is None:
                continue
            enabled = True
            dependency = prop_def.get("enabled_when")
            if dependency:
                enabled = bool(getattr(self.obj, dependency, False))
            dependency = prop_def.get("enabled_when_not")
            if dependency:
                enabled = not bool(getattr(self.obj, dependency, False))
            control.spinbox.setEnabled(enabled)

    def refresh_from_object(self):
        self._refreshing_ui = True
        try:
            for name, control in self._widgets.items():
                widget = control.checkbox if control.checkbox is not None else control.spinbox
                with QSignalBlocker(widget):
                    # -----------------------------------------
                    # Checkbox = Optuna lock state
                    # -----------------------------------------
                    if control.checkbox is not None:
                        lock_prop = f"{name}_OptunaLocked"
                        widget.setChecked(bool(getattr(self.obj, lock_prop, False)))
                    # -----------------------------------------
                    # Normal spinbox
                    # -----------------------------------------
                    else:
                        control.spinbox.setProperty("rawValue", float(getattr(self.obj, name)))
                    # -----------------------------------------
                    # Checked-spin also updates value widget
                    # -----------------------------------------
                    if control.spinbox is not None:
                        control.spinbox.setProperty("rawValue", float(getattr(self.obj, name)))
            for name, (widget, unit) in self._display_widgets.items():
                value = float(getattr(self.obj, name))
                widget.setText(f"{value:.4f} {unit}".rstrip())
            self._refresh_property_enablement()
        finally:
            self._refreshing_ui = False

    def refresh_from_object_old(self):
        self._refreshing_ui = True
        try:
            for name, control in self._widgets.items():
                widget = control.checkbox if control.checkbox is not None else control.spinbox
                with QSignalBlocker(widget):
                    if control.checkbox is not None:
                        widget.setChecked(bool(getattr(self.obj, name)))
                    else:
                        widget.setProperty("rawValue", float(getattr(self.obj, name)))
                    if control.checkbox is not None and control.spinbox is not None:
                        control.spinbox.setProperty("rawValue", float(getattr(self.obj, name)))
            for name, (widget, unit) in self._display_widgets.items():
                value = float(getattr(self.obj, name))
                widget.setText(f"{value:.4f} {unit}".rstrip())
            self._refresh_property_enablement()
        finally:
            self._refreshing_ui = False

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

    def export_to_spreadsheet(self, properties=None):
        doc = self.obj.Document
        obj = self.obj

        sheet = doc.getObject("Spreadsheet")
        if sheet is None:
            sheet = doc.addObject("Spreadsheet::Sheet", "Spreadsheet")

        sheet.set("A1", "Property")
        sheet.set("B1", "Value")
        sheet.set("C1", "Min")
        sheet.set("D1", "Max")
        sheet.set("E1", "Locked")
        row = 2

        for prop_def in self._iter_editable_properties(properties, numeric_only=True):
            prop = prop_def["name"]
            unit = prop_def.get("unit", "")

            try:
                value = getattr(obj, prop)
                sheet.set(f"A{row}", prop)
                sheet.set(f"B{row}", str(value))
                locked = bool(getattr(obj, f"{prop}_OptunaLocked", False))
                sheet.set(f"E{row}", "X" if locked else "")

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
            except Exception as exc:
                App.Console.PrintError(f"Spreadsheet export failed: {exc}\n")
            row += 1
        sheet.set(f"A{row}", "END")

        obj.touch()
        doc.recompute()
        self.reopen()

    def clear_spreadsheet_references(self, properties=None):
        for prop_def in self._iter_editable_properties(properties, numeric_only=True):
            self.obj.setExpression(prop_def["name"], None)
        self.obj.Document.recompute()
        self.reopen()

    def set_spreadsheet_references(self, properties=None):
        set_spreadsheet_references(self.obj, properties)
        self.reopen()

    def update_optuna_config(self, properties=None):
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
        for prop_def in self._iter_editable_properties(properties, numeric_only=True):
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

    def _open_optuna_bounds_editor(self):
        try:
            from OPTIMIZER.optuna_bounds_editor import show_optuna_bounds_editor

            self._optuna_sheet_window = show_optuna_bounds_editor()
        except Exception as e:
            App.Console.PrintError(f"[UI] Sheet error: {e}\n")

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

        # lock_value = getattr(self.obj, f"{prop}_OptunaLocked", False)
        # print(prop, lock_value)
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
