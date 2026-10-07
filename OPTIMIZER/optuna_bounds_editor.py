# -*- coding: utf-8 -*-
# OptunaBoundsEditor.py
"""
OptunaBoundsEditor.py

Baserad på LiveSheets.py.

Funktioner
----------
- Hela Spreadsheet visas, A..Z
- Alla celler kan redigeras direkt
- Min % och Max % längst ner
- Ändring av Min/Max % uppdaterar Spreadsheet direkt
- B = Value
- C = Min
- D = Max

Formler
-------
Min = Value * (1 + Min% / 100)
Max = Value * (1 + Max% / 100)

Exempel:

    B = 100
    Min % = -10
    Max % = 20

    C = 90
    D = 120

CSV
---
Property,Value,Min,Max

JSON
----
Sparar även:
    global_percent.min
    global_percent.max

Användning
----------
    exec(open(r"C:\\path\\OptunaBoundsEditor.py").read())

sedan:

    OBA_ShowOptunaBoundsEditor()

eller:

    show_optuna_bounds_editor()

"""

import os
import json
import time
import string
import FreeCAD as App

try:
    import FreeCADGui as Gui
except Exception:
    Gui = None


from PySide import QtCore, QtGui, QtWidgets

# except ImportError:
#     from PySide2 import QtCore, QtGui, QtWidgets


# =========================================================
# Configuration
# =========================================================

DOCK_OBJECT_NAME = "OBA_OptunaBoundsEditorDock"
DEFAULT_SHEET = "Spreadsheet"
MAX_SCAN_ROWS = 600
MAX_COLUMNS = 26
COLUMN_NAMES = list(string.ascii_uppercase)[:MAX_COLUMNS]
# Spreadsheet:
#
# A = Property
# B = Value
# C = Min
# D = Max
#
COL_PROPERTY = 0
COL_VALUE = 1
COL_MIN = 2
COL_MAX = 3
COL_LOCKED = 4
DEFAULT_MIN_PERCENT = -10.0
DEFAULT_MAX_PERCENT = 10.0


# =========================================================
# FreeCAD recompute / refresh helpers
# =========================================================


def recompute_doc(doc, iter_index=None, note=None, restore_view=None):
    """
    Recompute document.

    Same basic behavior as LiveSheets.py.
    """
    if doc is None:
        return

    t0 = time.time()
    try:
        doc.recompute()

    except Exception as e:
        try:
            App.Console.PrintError("[OBA] recompute error: {}\n".format(e))

        except Exception:
            pass

    # Uncomment if you want OpticsWorkbench
    # restarted every time.
    # _restart_optics()
    # _refresh_3d_view()
    if restore_view:
        try:
            restore_view()

        except Exception:
            pass

    dt = time.time() - t0
    msg = "[OBA] recompute+optics+refresh {:.3f}s".format(dt)
    if iter_index is not None:
        msg += " | iter={}".format(iter_index)

    if note:
        msg += " | " + str(note)

    try:
        App.Console.PrintMessage(msg + "\n")

    except Exception:
        pass


# =========================================================
# Numeric helpers
# =========================================================


def _to_float(value):
    """
    Convert FreeCAD / Spreadsheet value to float.

    Supports for example:

        10
        10.5
        10,5
        "10 mm"
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    # Swedish decimal separator
    text = text.replace(",", ".")
    try:
        return float(text)

    except Exception:
        pass

    try:
        return float(App.Units.Quantity(text).Value)

    except Exception:
        pass

    return None


def _format_number(value):
    """
    Format a number for FreeCAD Spreadsheet.
    """
    if value is None:
        return ""

    try:
        value = float(value)
        if abs(value) < 1e-12:
            value = 0.0

        return "{:.12g}".format(value)

    except Exception:
        return str(value)


def _is_locked(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "locked", "x"}


def load_model_data_into_spreadsheet(data, sheet, min_percent=None, max_percent=None):
    alias_to_row = {}
    for row in range(1, MAX_SCAN_ROWS + 1):
        try:
            alias = sheet.getAlias(f"B{row}")
        except Exception:
            alias = None
        if alias:
            alias_to_row[alias] = row

    loaded = 0
    missing_aliases = []
    global_percent = data.get("global_percent", {})
    if min_percent is None:
        min_percent = global_percent.get("min")
    if max_percent is None:
        max_percent = global_percent.get("max")

    for item in data.get("parameters", []):
        alias = item.get("alias", "")
        if not alias:
            continue
        row = alias_to_row.get(alias)
        if row is None:
            missing_aliases.append(alias)
            continue

        value = item.get("value")
        min_value = item.get("min")
        max_value = item.get("max")
        zero_value = global_percent.get("zero_value", 1.0)
        if min_percent is not None and max_percent is not None and value is not None:
            numeric_value = _to_float(value)
            if numeric_value is not None:
                min_value = _calculate_bound(numeric_value, float(min_percent), float(zero_value))
                max_value = _calculate_bound(numeric_value, float(max_percent), float(zero_value))

        property_name = str(item.get("property", ""))

        if property_name:
            sheet.set(f"A{row}", property_name)
        if value is not None:
            sheet.set(f"B{row}", _format_number(_to_float(value)))
        if min_value is not None:
            sheet.set(f"C{row}", _format_number(_to_float(min_value)))
        if max_value is not None:
            sheet.set(f"D{row}", _format_number(_to_float(max_value)))
        sheet.set(f"E{row}", "X" if _is_locked(item.get("locked", False)) else "")
        loaded += 1

    sheet.touch()
    return loaded, missing_aliases


def calculate_bounds(value, percent_min, percent_max):
    delta = abs(value)

    b1 = value + delta * percent_min / 100.0
    b2 = value + delta * percent_max / 100.0

    return min(b1, b2), max(b1, b2)


def _calculate_bound(value, percent, zero_value=1.0):
    if abs(value) < 1e-12:
        return -zero_value if percent < 0 else zero_value

    return value + abs(value) * percent / 100.0


def _calculate_bound_old(value, percent, zero_value=1.0):
    """
    Calculate Min/Max from Value and percentage.
    """
    if abs(value) < 1e-12:
        return -zero_value if percent < 0 else zero_value
    return value * (1.0 + percent / 100.0)


def _calculate_percent(value, bound):
    """
    Calculate percentage from Value and bound.
    """
    if value is None:
        return None

    if bound is None:
        return None

    if abs(value) < 1e-15:
        return None

    return ((bound / value) - 1.0) * 100.0


# =========================================================
# Spreadsheet helper
# =========================================================


def _get_sheets(doc):
    if doc is None:
        return None, None

    dn = DEFAULT_SHEET.casefold() if DEFAULT_SHEET else None

    def is_default(s):
        return dn and ((s.Name or "").casefold() == dn or (s.Label or "").casefold() == dn)

    def alpha_key(s):
        primary = s.Label if (s.Label and s.Label.strip()) else s.Name
        return ((primary or "").casefold(), (s.Name or "").casefold())

    sheets = [o for o in doc.Objects if o.isDerivedFrom("Spreadsheet::Sheet")]
    if not sheets:
        return None, None

    sorted_sheets = sorted(sheets, key=lambda s: (0 if is_default(s) else 1, alpha_key(s)))
    default_idx = next((i for i, s in enumerate(sorted_sheets) if is_default(s)), None)
    return (sorted_sheets, default_idx)


# =========================================================
# Reloading ComboBox
# =========================================================


class ReloadingComboBox(QtWidgets.QComboBox):

    def __init__(self, reload_fn=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._reload_fn = reload_fn

    def showPopup(self):
        try:
            if callable(self._reload_fn):
                self._reload_fn()
        except Exception as e:
            try:
                App.Console.PrintWarning("Reload sheet list failed: {}\n".format(e))
            except Exception:
                pass
        finally:
            super().showPopup()


# =========================================================
# Main Dock
# =========================================================


class OptunaBoundsEditor(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Optuna Bounds Editor")
        self.setObjectName(DOCK_OBJECT_NAME)
        self._loading = False
        self._create_ui()
        self._load_initial_sheet()

    # =====================================================
    # UI
    # =====================================================

    def _create_ui(self):

        layout = QtWidgets.QVBoxLayout(self)
        # central = QtWidgets.QWidget(self)
        # self.setWidget(central)
        # layout = QtWidgets.QVBoxLayout(central)

        # -------------------------------------------------
        # Spreadsheet selector
        # -------------------------------------------------

        layout.addWidget(QtWidgets.QLabel("Select spreadsheet:"))
        self.cmbSheets = ReloadingComboBox(reload_fn=self._reload_sheet_list)
        layout.addWidget(self.cmbSheets)

        # -------------------------------------------------
        # Controls
        # -------------------------------------------------

        ctrl = QtWidgets.QHBoxLayout()
        self.chkAutoRecompute = QtWidgets.QCheckBox("Auto-recompute")
        self.chkAutoRecompute.setChecked(True)
        ctrl.addWidget(self.chkAutoRecompute)
        ctrl.addStretch(1)
        self.btnRecompute = QtWidgets.QPushButton("Recompute now")
        self.btnRecompute.clicked.connect(self._manual_recompute)
        ctrl.addWidget(self.btnRecompute)
        layout.addLayout(ctrl)

        # -------------------------------------------------
        # Spreadsheet table
        # -------------------------------------------------

        self.tbl = QtWidgets.QTableWidget()
        self.tbl.setColumnCount(MAX_COLUMNS)
        self.tbl.setHorizontalHeaderLabels(COLUMN_NAMES)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        # IMPORTANT:
        # Keep cells editable.
        self.tbl.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers)
        self.tbl.setAlternatingRowColors(True)
        layout.addWidget(self.tbl)

        # -------------------------------------------------
        # Percentage controls
        # -------------------------------------------------

        percent_frame = QtWidgets.QFrame()
        percent_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        percent_layout = QtWidgets.QHBoxLayout(percent_frame)
        # Min %
        percent_layout.addWidget(QtWidgets.QLabel("Min %:"))
        self.min_percent_spin = QtWidgets.QDoubleSpinBox()
        self.min_percent_spin.setRange(-1000000.0, 1000000.0)
        self.min_percent_spin.setDecimals(2)
        self.min_percent_spin.setSingleStep(1.0)
        self.min_percent_spin.setValue(DEFAULT_MIN_PERCENT)
        self.min_percent_spin.setSuffix(" %")
        self.min_percent_spin.setMinimumWidth(110)
        percent_layout.addWidget(self.min_percent_spin)
        # Max %
        percent_layout.addSpacing(25)
        percent_layout.addWidget(QtWidgets.QLabel("Max %:"))
        self.max_percent_spin = QtWidgets.QDoubleSpinBox()
        self.max_percent_spin.setRange(-1000000.0, 1000000.0)
        self.max_percent_spin.setDecimals(2)
        self.max_percent_spin.setSingleStep(1.0)
        self.max_percent_spin.setValue(DEFAULT_MAX_PERCENT)
        self.max_percent_spin.setSuffix(" %")
        self.max_percent_spin.setMinimumWidth(110)
        percent_layout.addWidget(self.max_percent_spin)
        percent_layout.addStretch(1)
        layout.addWidget(percent_frame)

        # -------------------------------------------------
        # File buttons
        # -------------------------------------------------

        buttons = QtWidgets.QHBoxLayout()
        self.btnReload = QtWidgets.QPushButton("Läs om Spreadsheet")
        self.btnApplyPercent = QtWidgets.QPushButton("Uppdatera Min/Max")
        self.btnDecreaseValue = QtWidgets.QPushButton("Value -10%")
        self.btnIncreaseValue = QtWidgets.QPushButton("Value +10%")
        self.btnDecreaseValue.setToolTip("Decrease Value by 10% for every unlocked parameter.")
        self.btnIncreaseValue.setToolTip("Increase Value by 10% for every unlocked parameter.")
        value_button_style = "QPushButton { background-color: #176b5b; color: white; font-weight: 600; padding: 5px 10px; } QPushButton:hover { background-color: #125648; }"
        self.btnDecreaseValue.setStyleSheet(value_button_style)
        self.btnIncreaseValue.setStyleSheet(value_button_style)
        self.btnApplyPercent.setStyleSheet("QPushButton { background-color: #315f91; color: white; font-weight: 600; padding: 5px 10px; } QPushButton:hover { background-color: #264c75; }")
        self.min_percent_spin.setStyleSheet("QDoubleSpinBox { border: 2px solid #315f91; border-radius: 3px; padding: 3px; }")
        self.max_percent_spin.setStyleSheet("QDoubleSpinBox { border: 2px solid #315f91; border-radius: 3px; padding: 3px; }")

        percent_layout.addSpacing(25)
        percent_layout.addWidget(QtWidgets.QLabel("Zero value:"))
        self.zero_value_spin = QtWidgets.QDoubleSpinBox()
        self.zero_value_spin.setRange(0.000001, 1_000_000.0)
        self.zero_value_spin.setDecimals(6)
        self.zero_value_spin.setValue(1.0)
        self.zero_value_spin.setSingleStep(0.1)
        percent_layout.addWidget(self.zero_value_spin)

        self.btnOpen = QtWidgets.QPushButton("Öppna CSV / JSON")
        self.btnSave = QtWidgets.QPushButton("Spara CSV / JSON")
        self.btnClose = QtWidgets.QPushButton("Stäng")
        buttons.addWidget(self.btnReload)
        buttons.addWidget(self.btnApplyPercent)
        buttons.addWidget(self.btnDecreaseValue)
        buttons.addWidget(self.btnIncreaseValue)
        buttons.addStretch(1)
        buttons.addWidget(self.btnOpen)
        buttons.addWidget(self.btnSave)
        buttons.addWidget(self.btnClose)
        layout.addLayout(buttons)

        # -------------------------------------------------
        # Status
        # -------------------------------------------------

        self.statusLabel = QtWidgets.QLabel("")
        layout.addWidget(self.statusLabel)

        # -------------------------------------------------
        # Signals
        # -------------------------------------------------

        self.cmbSheets.currentIndexChanged.connect(self._reload_sheet)
        self.btnReload.clicked.connect(self._reload_sheet)
        self.btnApplyPercent.clicked.connect(self._apply_percent_to_spreadsheet)
        self.btnDecreaseValue.clicked.connect(lambda: self._adjust_all_unlocked_values(-1))
        self.btnIncreaseValue.clicked.connect(lambda: self._adjust_all_unlocked_values(1))
        self.btnOpen.clicked.connect(self._open_file)
        self.btnSave.clicked.connect(self._save_file)
        self.btnClose.clicked.connect(self.close)
        # Cell editing
        self.tbl.itemChanged.connect(self._on_cell_edited)
        # IMPORTANT:
        # Percentage changes are LIVE.
        #
        # Clicking/spinning either box changes
        # C and D in the Spreadsheet immediately.
        self.min_percent_spin.valueChanged.connect(self._global_percent_changed)
        self.max_percent_spin.valueChanged.connect(self._global_percent_changed)

    # =====================================================
    # Initial spreadsheet
    # =====================================================

    def _load_initial_sheet(self):
        doc = App.ActiveDocument
        if not doc:
            self.cmbSheets.addItem("(No active document)")
            self.cmbSheets.setEnabled(False)
            return

        sheets, def_idx = _get_sheets(doc)
        if not sheets:
            self.cmbSheets.addItem("(No spreadsheets found)")
            self.cmbSheets.setEnabled(False)
            return

        for s in sheets:
            self.cmbSheets.addItem(s.Label or s.Name, userData=s)

        if def_idx is not None:
            self.cmbSheets.setCurrentIndex(def_idx)

        else:
            self.cmbSheets.setCurrentIndex(0)

        self._reload_sheet()

    # =====================================================
    # Current spreadsheet
    # =====================================================

    def _current_sheet(self):
        try:
            return self.cmbSheets.currentData()

        except Exception:
            return None

    # =====================================================
    # Number of rows
    # =====================================================

    def _used_rows(self, sheet):
        last = 0
        for r in range(1, MAX_SCAN_ROWS + 1):
            row_has_data = False
            for c in range(self.tbl.columnCount()):
                col = COLUMN_NAMES[c]
                addr = "{}{}".format(col, r)
                try:
                    v = sheet.get(addr)

                except Exception:
                    continue

                if v not in ("", None):
                    row_has_data = True
                    break

            if row_has_data:
                last = r + 5

        return max(last, 10)

    # =====================================================
    # Reload entire spreadsheet
    # =====================================================

    def _reload_sheet(self):
        sheet = self._current_sheet()
        if not sheet:
            return

        doc = App.ActiveDocument
        if not doc:
            return

        if self.chkAutoRecompute.isChecked():
            recompute_doc(doc, note="Reload sheet")

        rows = self._used_rows(sheet)
        self._loading = True
        self.tbl.blockSignals(True)
        try:
            self.tbl.clearContents()
            self.tbl.setRowCount(rows)

            # ---------------------------------------------
            # Load Spreadsheet cells
            # ---------------------------------------------

            for r in range(rows):
                for c in range(self.tbl.columnCount()):
                    col = COLUMN_NAMES[c]
                    try:
                        val = sheet.get("{}{}".format(col, r + 1))

                    except Exception:
                        val = ""

                    item = QtWidgets.QTableWidgetItem("" if val is None else str(val))
                    self.tbl.setItem(r, c, item)

                self.tbl.setVerticalHeaderItem(r, QtWidgets.QTableWidgetItem(str(r + 1)))

        finally:
            self.tbl.blockSignals(False)
            self._loading = False

        # ---------------------------------------------
        # Read current C/D and derive initial %
        # ---------------------------------------------

        self._load_percentages_from_sheet()
        self.statusLabel.setText("Spreadsheet loaded: {}".format(sheet.Label or sheet.Name))

    # =====================================================
    # Read existing percentages
    # =====================================================

    def _load_percentages_from_sheet(self):
        """
        Read existing C/D values and calculate
        the percentage around B.

        Uses the first row where:
            B, C and/or D
        contain numeric values.

        This is only used to initialize the
        spinboxes.

        It does NOT change the Spreadsheet.
        """
        sheet = self._current_sheet()
        if not sheet:
            return

        found_min = None
        found_max = None
        for r in range(1, MAX_SCAN_ROWS + 1):
            try:
                value_raw = sheet.get("B{}".format(r))
                min_raw = sheet.get("C{}".format(r))
                max_raw = sheet.get("D{}".format(r))
                property_raw = sheet.get("A{}".format(r))

            except Exception:
                continue

            property_name = "" if property_raw is None else str(property_raw).strip()
            # END
            if property_name.upper() == "END":
                break

            value = _to_float(value_raw)
            min_value = _to_float(min_raw)
            max_value = _to_float(max_raw)
            if value is None:
                continue

            min_percent = _calculate_percent(value, min_value)
            max_percent = _calculate_percent(value, max_value)
            if found_min is None and min_percent is not None:
                found_min = min_percent

            if found_max is None and max_percent is not None:
                found_max = max_percent

            if found_min is not None and found_max is not None:
                break

        # Only update spinboxes if something
        # useful was actually found.
        if found_min is not None:
            self.min_percent_spin.blockSignals(True)
            self.min_percent_spin.setValue(found_min)
            self.min_percent_spin.blockSignals(False)

        if found_max is not None:
            self.max_percent_spin.blockSignals(True)
            self.max_percent_spin.setValue(found_max)
            self.max_percent_spin.blockSignals(False)

    # =====================================================
    # Global percentage changed
    # =====================================================

    def _global_percent_changed(self):
        """
        LIVE update.

        When either percentage spinbox changes:

            B -> Value
            C -> Min
            D -> Max

        C and D are written directly into
        the active Spreadsheet.
        """
        if self._loading:
            return

        sheet = self._current_sheet()
        if not sheet:
            return

        doc = App.ActiveDocument
        if not doc:
            return

        min_percent = self.min_percent_spin.value()
        max_percent = self.max_percent_spin.value()
        changed = 0
        self._loading = True
        try:
            self.tbl.blockSignals(True)

            # ---------------------------------------------
            # Scan spreadsheet
            # ---------------------------------------------

            for r in range(1, MAX_SCAN_ROWS + 1):
                try:
                    property_raw = sheet.get("A{}".format(r))
                    value_raw = sheet.get("B{}".format(r))
                except Exception:
                    continue
                property_name = "" if property_raw is None else str(property_raw).strip()
                # END stops processing
                if property_name.upper() == "END":
                    break
                value = _to_float(value_raw)
                # -----------------------------------------
                # Only rows with numeric B are parameters
                #
                # This automatically skips category rows.
                # -----------------------------------------
                if value is None:
                    continue
                zero_value = self.zero_value_spin.value()
                min_value = _calculate_bound(value, min_percent, zero_value)
                max_value = _calculate_bound(value, max_percent, zero_value)
                min_text = _format_number(min_value)
                max_text = _format_number(max_value)

                # -----------------------------------------
                # Write directly to Spreadsheet
                # -----------------------------------------

                sheet.set("C{}".format(r), min_text)
                sheet.set("D{}".format(r), max_text)

                # -----------------------------------------
                # Update table immediately
                # -----------------------------------------

                table_row = r - 1
                if 0 <= table_row < self.tbl.rowCount():
                    min_item = self.tbl.item(table_row, COL_MIN)
                    if min_item is None:
                        min_item = QtWidgets.QTableWidgetItem()
                        self.tbl.setItem(table_row, COL_MIN, min_item)

                    min_item.setText(min_text)
                    max_item = self.tbl.item(table_row, COL_MAX)
                    if max_item is None:
                        max_item = QtWidgets.QTableWidgetItem()
                        self.tbl.setItem(table_row, COL_MAX, max_item)

                    max_item.setText(max_text)

                changed += 1

            # ---------------------------------------------
            # Spreadsheet recompute
            # ---------------------------------------------

            try:
                sheet.touch()
            except Exception:
                pass

            if self.chkAutoRecompute.isChecked():
                try:
                    doc.recompute()
                except Exception:
                    pass
                recompute_doc(doc, note="Optuna % change")
        except Exception as e:
            try:
                App.Console.PrintError("Optuna % update error: {}\n".format(e))
            except Exception:
                pass
            self.statusLabel.setText("Error: {}".format(e))
        finally:
            self.tbl.blockSignals(False)
            self._loading = False
        self.statusLabel.setText("Min {:.2f}% / Max {:.2f}% -> " "{} rows updated directly.".format(min_percent, max_percent, changed))

    # =====================================================
    # Manual percentage update button
    # =====================================================

    def _apply_percent_to_spreadsheet(self):
        """
        Same operation as changing a spinbox.

        Useful if the user wants to force an
        explicit update without moving a spinbox.
        """
        self._global_percent_changed()

    def _safe_get(self, sheet, addr, default=""):
        try:
            return sheet.get(addr)
        except Exception:
            return default

    def _adjust_all_unlocked_values(self, direction):
        sheet = self._current_sheet()
        doc = App.ActiveDocument
        if not sheet or not doc:
            return

        changed = 0
        skipped_locked = 0
        skipped_zero = 0
        self._loading = True
        self.tbl.blockSignals(True)
        try:
            locked_column = COLUMN_NAMES[COL_LOCKED]
            for spreadsheet_row in range(1, MAX_SCAN_ROWS + 1):
                property_name = str(self._safe_get(sheet, f"A{spreadsheet_row}") or "").strip()
                if property_name.upper() == "END":
                    break
                if not property_name:
                    continue
                if _is_locked(self._safe_get(sheet, f"{locked_column}{spreadsheet_row}")):
                    skipped_locked += 1
                    continue

                value = _to_float(self._safe_get(sheet, f"B{spreadsheet_row}"))
                if value is None:
                    continue
                if abs(value) < 1e-15:
                    skipped_zero += 1
                    continue

                new_value = value * (1.0 + direction * 0.1)
                sheet.set(f"B{spreadsheet_row}", _format_number(new_value))
                sheet.set(f"C{spreadsheet_row}", _format_number(_calculate_bound(new_value, self.min_percent_spin.value())))
                sheet.set(f"D{spreadsheet_row}", _format_number(_calculate_bound(new_value, self.max_percent_spin.value())))
                changed += 1

            if changed:
                sheet.touch()
                # if self.chkAutoRecompute.isChecked():
                #     recompute_doc(doc, note=f"Value {'+' if direction > 0 else '-'}10%")

                # self._reload_sheet()

        except Exception as exc:
            App.Console.PrintError("Optuna Value adjustment failed: {}\n".format(exc))
            self.statusLabel.setText("Adjustment failed: {}".format(exc))
            return
        finally:
            self.tbl.blockSignals(False)
            self._loading = False

        if changed:
            self._reload_sheet()
        self.statusLabel.setText("Value {}10%: {} updated, {} locked, {} zero values unchanged.".format("+" if direction > 0 else "-", changed, skipped_locked, skipped_zero))

    # =====================================================
    # Cell editing
    # =====================================================

    def _on_cell_edited(self, item):
        if self._loading:
            return

        sheet = self._current_sheet()
        if not sheet:
            return

        doc = App.ActiveDocument
        if not doc:
            return

        r = item.row()
        c = item.column()
        if c < 0 or c >= len(COLUMN_NAMES):
            return

        col = COLUMN_NAMES[c]
        val = item.text()
        addr = "{}{}".format(col, r + 1)
        try:

            # ---------------------------------------------
            # Swedish decimal comma -> dot
            # ---------------------------------------------

            txt = val.strip().replace(",", ".")

            # ---------------------------------------------
            # Expression
            #
            # User can type:
            #
            # =Spreadsheet.B2
            #
            # and the "=" is removed before setExpression.
            # ---------------------------------------------

            if txt.startswith("="):
                sheet.setExpression(addr, txt[1:])

            else:
                sheet.set(addr, txt)
                # print(addr, repr(txt))

            # ---------------------------------------------
            # If B (Value) is edited:
            #
            # Do NOT automatically overwrite C/D here.
            #
            # This keeps normal LiveSheets behavior.
            #
            # The user can then use the percentage controls
            # to regenerate C/D from the new B.
            # ---------------------------------------------

            if self.chkAutoRecompute.isChecked():
                try:
                    sheet.touch()
                    doc.recompute()
                    sheet.recompute()

                except Exception:
                    pass

                recompute_doc(doc, note="OBA_OptunaBounds cell edit")

                # -----------------------------------------
                # Refresh table after formula calculations
                # -----------------------------------------

                self._reload_sheet()

        except Exception as e:
            try:
                QtWidgets.QMessageBox.warning(self, "Spreadsheet", "Could not write:\n{}".format(e))

            except Exception:
                pass

    # =====================================================
    # Visible cell refresh
    # =====================================================

    def _refresh_visible_cells(self, sheet):
        self._loading = True
        try:
            viewport = self.tbl.viewport()
            rect = viewport.rect()
            top_left = self.tbl.indexAt(rect.topLeft())
            bottom_right = self.tbl.indexAt(rect.bottomRight())
            if not top_left.isValid() or not bottom_right.isValid():
                return

            r0 = top_left.row()
            r1 = bottom_right.row()
            c0 = top_left.column()
            c1 = bottom_right.column()
            # Small preload buffer
            r0 = max(0, r0 - 2)
            c0 = max(0, c0 - 1)
            r1 = min(self.tbl.rowCount() - 1, r1 + 2)
            c1 = min(self.tbl.columnCount() - 1, c1 + 1)
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    col = COLUMN_NAMES[c]
                    addr = "{}{}".format(col, r + 1)
                    try:
                        val = sheet.getDisplayString(addr)

                    except Exception:
                        val = ""

                    item = self.tbl.item(r, c)
                    if item is None:
                        item = QtWidgets.QTableWidgetItem()
                        self.tbl.setItem(r, c, item)

                    txt = "" if val is None else str(val)
                    if item.text() != txt:
                        item.setText(txt)

        finally:
            self._loading = False

    # =====================================================
    # Manual recompute
    # =====================================================

    def _manual_recompute(self):
        doc = App.ActiveDocument
        if not doc:
            return

        recompute_doc(doc, note="Manual recompute")
        self._reload_sheet()

    # =====================================================
    # Save CSV / JSON
    # =====================================================

    def _get_default_path(self):
        doc = App.ActiveDocument
        if doc and getattr(doc, "FileName", ""):
            return os.path.dirname(doc.FileName)
        return ""

    def _get_default_save_name(self, ext="json"):
        doc = App.ActiveDocument
        if doc and getattr(doc, "FileName", ""):
            folder = os.path.dirname(doc.FileName)
            name = os.path.splitext(os.path.basename(doc.FileName))[0]
            return os.path.join(folder, f"{name}_optuna_bounds.{ext}")

        return ""

    def _save_file(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Optuna bounds",
            self._get_default_save_name(),
            "OBA model (*.model)",
        )

        if not path:
            return

        if not path.lower().endswith(".model"):
            path += ".model"

        self._save_json(path)
        self.statusLabel.setText(f"Saved: {path}")

    # =====================================================
    # Save JSON
    # =====================================================

    def _save_json(self, path):
        sheet = self._current_sheet()
        if not sheet:
            return
        data = {
            "format": "OptunaBoundsEditor",
            "version": 2,
            "spreadsheet": sheet.Label or sheet.Name,
            "spreadsheet_columns": {
                "property": "A",
                "value": "B",
                "min": "C",
                "max": "D",
                "locked": "E",
            },
            "global_percent": {
                "min": self.min_percent_spin.value(),
                "max": self.max_percent_spin.value(),
                "zero_value": self.zero_value_spin.value(),
            },
            "parameters": [],
        }

        for r in range(1, MAX_SCAN_ROWS + 1):
            property_raw = self._safe_get(sheet, f"A{r}")
            value_raw = self._safe_get(sheet, f"B{r}")
            min_raw = self._safe_get(sheet, f"C{r}")
            max_raw = self._safe_get(sheet, f"D{r}")
            locked_raw = self._safe_get(sheet, f"E{r}")
            try:
                alias = sheet.getAlias(f"B{r}")
            except Exception:
                alias = ""
            property_name = "" if property_raw is None else str(property_raw).strip()
            if property_name.upper() == "END":
                break
            value = _to_float(value_raw)
            # hoppa över kategorirader
            if value is None:
                continue
            min_value = _to_float(min_raw)
            max_value = _to_float(max_raw)
            data["parameters"].append(
                {
                    "alias": alias,
                    "property": property_name,
                    "value": value,
                    "min": min_value,
                    "max": max_value,
                    "locked": _is_locked(locked_raw),
                    "min_percent": _calculate_percent(value, min_value),
                    "max_percent": _calculate_percent(value, max_value),
                }
            )
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    # =====================================================
    # Open  JSON
    # =====================================================

    def _open_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open OBA model",
            self._get_default_path(),
            "OBA model (*.model)",
        )
        if not path:
            return
        self._load_json(path)
        self.statusLabel.setText(f"Opened: {path}")

    # =====================================================
    # Load JSON
    # =====================================================
    def _load_json(self, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        global_percent = data.get("global_percent", {})

        # -------------------------------------------------
        # Set spinboxes
        # -------------------------------------------------

        min_percent = global_percent.get("min")
        if min_percent is not None:
            self.min_percent_spin.blockSignals(True)
            self.min_percent_spin.setValue(float(min_percent))
            self.min_percent_spin.blockSignals(False)

        max_percent = global_percent.get("max")
        if max_percent is not None:
            self.max_percent_spin.blockSignals(True)
            self.max_percent_spin.setValue(float(max_percent))
            self.max_percent_spin.blockSignals(False)

        zero_value = global_percent.get("zero_value")
        if zero_value is not None:
            self.zero_value_spin.blockSignals(True)
            self.zero_value_spin.setValue(float(zero_value))
            self.zero_value_spin.blockSignals(False)

        sheet = self._current_sheet()
        if not sheet:
            return

        loaded, missing_aliases = load_model_data_into_spreadsheet(data, sheet)
        if missing_aliases:
            App.Console.PrintWarning("Model parameters with unmatched aliases: {}\n".format(", ".join(missing_aliases)))
        if not loaded:
            self.statusLabel.setText("No model parameters matched Spreadsheet aliases.")
            return
        if self.chkAutoRecompute.isChecked():
            recompute_doc(App.ActiveDocument, note="Open JSON")
        self._reload_sheet()

    # =====================================================
    # Sheet list
    # =====================================================

    def _reload_sheet_list(self):
        doc = App.ActiveDocument
        if not doc:
            return

        old = self._current_sheet()
        old_key = (old.Label or old.Name).casefold() if old else None
        sheets, def_idx = _get_sheets(doc)
        self.cmbSheets.blockSignals(True)
        try:
            self.cmbSheets.clear()
            if not sheets:
                self.cmbSheets.addItem("(No spreadsheets found)")
                self.cmbSheets.setEnabled(False)

            else:
                self.cmbSheets.setEnabled(True)
                match_idx = None
                for i, s in enumerate(sheets):
                    label = s.Label or s.Name
                    self.cmbSheets.addItem(label, userData=s)
                    if old_key and label.casefold() == old_key:
                        match_idx = i

                if match_idx is not None:
                    self.cmbSheets.setCurrentIndex(match_idx)

                elif def_idx is not None:
                    self.cmbSheets.setCurrentIndex(def_idx)

                else:
                    self.cmbSheets.setCurrentIndex(0)

        finally:
            self.cmbSheets.blockSignals(False)

        self._reload_sheet()

    # =====================================================
    # Static show
    # =====================================================

    @staticmethod
    def show_dialog():
        return OBA_ShowOptunaBoundsEditor()


# =========================================================
# Show dock
# =========================================================


_optuna_bounds_editor_ref = None


def OBA_CreateOptunaBoundsEditor(parent=None, show_dialog=True):

    global _optuna_bounds_editor_ref

    if parent is None:
        try:
            if App.GuiUp:
                import FreeCADGui as Gui

                parent = Gui.getMainWindow()
        except Exception:
            parent = None

    # återanvänd befintligt fönster
    if _optuna_bounds_editor_ref is not None and _optuna_bounds_editor_ref.isVisible():
        _optuna_bounds_editor_ref.raise_()
        _optuna_bounds_editor_ref.activateWindow()
        return _optuna_bounds_editor_ref

    dialog = OptunaBoundsEditor(parent=parent)

    dialog.setAttribute(
        QtCore.Qt.WA_DeleteOnClose,
        True,
    )

    def _clear_ref():
        global _optuna_bounds_editor_ref
        _optuna_bounds_editor_ref = None

    dialog.destroyed.connect(_clear_ref)

    _optuna_bounds_editor_ref = dialog

    if show_dialog:
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    return dialog


# =========================================================
# Aliases
# =========================================================


def OBA_ShowOptunaBoundsEditor():
    return OBA_CreateOptunaBoundsEditor(show_dialog=True)


def show_optuna_bounds_editor():
    return OBA_ShowOptunaBoundsEditor()


def show_dialog():
    return OBA_ShowOptunaBoundsEditor()
