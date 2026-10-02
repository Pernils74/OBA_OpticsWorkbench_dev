# -*- coding: utf-8 -*-
"""
xgboost_parameter_optimizer_dialog.py

Inverse XGBoost optimizer for the OBA White Cell.

Purpose
-------
The normal XGBoost training dialog learns:

    White Cell parameters -> metric(s)

This dialog performs the inverse operation:

    locked White Cell parameters
              +
    trained XGBoost surrogate models
              |
              v
    optimize unlocked White Cell parameters
              |
              v
    predicted metric values

The XGBoost models are loaded automatically from the active FreeCAD
document directory.

Expected files:

    xgboost_<metric>.json
    xgboost_<metric>.meta.json

The metadata is produced by xgboost_training_dialog.py.

The White Cell dialog uses:

    <prop>_OptunaLocked

where True means that the parameter is locked/fixed and False means
that the parameter is available for optimization.

This module does NOT modify the White Cell until the user presses
"Apply Best".

The optimization is a small surrogate optimization using Optuna.
The expensive optical simulation is NOT executed during this process.
Only the already-trained XGBoost models are evaluated.

A scatter plot is shown for the first two metrics. If more than two
metrics exist, the plot shows metric 1 vs metric 2 and the remaining
metrics are displayed in the result table.

Entry point:

    OBA_CreateXGBoostParameterOptimizerDialog(white_cell_obj)

Example:

    dialog = OBA_CreateXGBoostParameterOptimizerDialog(obj)
"""

# ======================================================================
# IMPORTS
# ======================================================================

import json
import math
import os
import traceback

import FreeCAD as App

from PySide import QtCore, QtWidgets, QtGui

# ----------------------------------------------------------------------
# Optional numpy
# ----------------------------------------------------------------------

try:
    import numpy as np
except Exception:
    np = None


# ----------------------------------------------------------------------
# Matplotlib
#
# FreeCAD installations differ.  We first try the Qt canvas normally
# used by matplotlib.  If unavailable, the dialog still works and the
# table is available.
# ----------------------------------------------------------------------

MATPLOTLIB_AVAILABLE = False

try:
    import matplotlib

    # Do not force a backend if FreeCAD has already configured one.
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg

    MATPLOTLIB_AVAILABLE = True
except Exception:
    MATPLOTLIB_AVAILABLE = False


# ----------------------------------------------------------------------
# Optuna
# ----------------------------------------------------------------------

OPTUNA_AVAILABLE = False

try:
    import sys

    BASE_DIR = os.path.dirname(os.path.dirname(__file__))
    OPTUNA_DIR = os.path.join(BASE_DIR, "vendor_optuna")

    if OPTUNA_DIR not in sys.path:
        sys.path.insert(0, OPTUNA_DIR)

    import optuna

    optuna.logging.set_verbosity(optuna.logging.ERROR)

    OPTUNA_AVAILABLE = True
except Exception:
    OPTUNA_AVAILABLE = False


# ----------------------------------------------------------------------
# XGBoost
# ----------------------------------------------------------------------

XGBOOST_AVAILABLE = False

try:
    import sys

    BASE_DIR = os.path.dirname(os.path.dirname(__file__))
    XGBOOST_DIR = os.path.join(BASE_DIR, "vendor_xgboost")

    if XGBOOST_DIR not in sys.path:
        sys.path.insert(0, XGBOOST_DIR)

    import xgboost

    XGBOOST_AVAILABLE = True
except Exception:
    XGBOOST_AVAILABLE = False


# ======================================================================
# CONSTANTS
# ======================================================================

DEFAULT_TRIALS = 300

DEFAULT_RANGE_PERCENT = 0.10

MIN_RANGE = 1.0e-9

MODEL_PREFIX = "xgboost_"
MODEL_SUFFIX = ".json"
META_SUFFIX = ".meta.json"


# ======================================================================
# PROPERTY HELPERS
# ======================================================================


def _safe_float(value, default=None):
    """
    Convert a FreeCAD property value to float.
    """
    try:
        return float(value)
    except Exception:
        return default


def _safe_property_value(obj, name):
    """
    Get a numeric value from a FreeCAD object.
    """
    try:
        return _safe_float(getattr(obj, name))
    except Exception:
        return None


def _is_locked(obj, prop_name):
    """
    White Cell checkbox state.

    True:
        parameter is fixed

    False:
        parameter is optimized
    """
    try:
        return bool(getattr(obj, prop_name + "_OptunaLocked"))
    except Exception:
        return False


def _set_property(obj, name, value):
    """
    Set a FreeCAD property while keeping the operation isolated.
    """
    try:
        setattr(obj, name, value)
        return True
    except Exception as exc:
        App.Console.PrintError("[OBA] Could not set White Cell property " f"{name}: {exc}\n")
        return False


def _safe_metric_filename(metric_name):
    """
    Same filename sanitizing logic as the XGBoost training dialog.
    """
    result = str(metric_name)
    for ch in '\\/:*?"<>|':
        result = result.replace(ch, "_")
    return result


# ======================================================================
# MODEL
# ======================================================================


class XGBoostSurrogateModel:
    """
    One trained XGBoost model plus its metadata.
    """

    def __init__(self, metric_name, model_path, meta_path):
        self.metric_name = metric_name
        self.model_path = model_path
        self.meta_path = meta_path

        self.model = None
        self.features = []

        self.metadata = {}

        self.rmse = None
        self.r2 = None
        self.samples = None

    # ------------------------------------------------------------------
    # LOAD
    # ------------------------------------------------------------------

    def load(self):
        if not XGBOOST_AVAILABLE:
            raise RuntimeError("XGBoost could not be imported.")

        if not os.path.isfile(self.model_path):
            raise FileNotFoundError(self.model_path)

        if not os.path.isfile(self.meta_path):
            raise FileNotFoundError(self.meta_path)

        with open(
            self.meta_path,
            "r",
            encoding="utf-8",
        ) as handle:
            self.metadata = json.load(handle)

        self.features = list(self.metadata.get("features", []))

        if not self.features:
            raise ValueError("No 'features' entry exists in " f"{self.meta_path}")

        self.metric_name = str(
            self.metadata.get(
                "metric_name",
                self.metric_name,
            )
        )

        self.rmse = self.metadata.get("rmse")
        self.r2 = self.metadata.get("r2")
        self.samples = self.metadata.get("samples")

        self.parameter_bounds = self.metadata.get("parameter_bounds", {})

        self.model = xgboost.Booster()

        self.model.load_model(self.model_path)

        return self

    # ------------------------------------------------------------------
    # PREDICT
    # ------------------------------------------------------------------

    def predict(self, values):
        """
        values:
            dict:
                parameter_name -> numeric value
        """
        if self.model is None:
            raise RuntimeError("Model has not been loaded.")
        if not self.features:
            raise RuntimeError("Model contains no feature list.")
        row = []
        for feature in self.features:
            value = values.get(feature, 0.0)
            number = _safe_float(value, 0.0)
            row.append(number)
        if np is None:
            data = [row]
        else:
            data = np.asarray([row], dtype=float)
        dmatrix = xgboost.DMatrix(data, feature_names=self.features)
        prediction = self.model.predict(dmatrix)
        return float(prediction[0])

    # ======================================================================
    # MODEL DISCOVERY
    # ======================================================================


def find_xgboost_models(directory):
    """
    Find all trained XGBoost models in a directory.
    Supports both:
        xgboost_<metric>.json
    and
        <document>_xgboost_<metric>.json
    """
    if not directory:
        return []
    if not os.path.isdir(directory):
        return []
    models = []
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(MODEL_SUFFIX):
            continue
        if filename.endswith(META_SUFFIX):
            continue
        if "_xgboost_" not in filename and not filename.startswith(MODEL_PREFIX):
            continue
        model_path = os.path.join(directory, filename)
        # ----------------------------------------------------------
        # Remove ".json"
        # ----------------------------------------------------------
        stem = filename[: -len(MODEL_SUFFIX)]
        # ----------------------------------------------------------
        # Extract metric name
        #
        # Examples:
        #
        # xgboost_MetricA.json
        #     -> MetricA
        #
        # WhiteCellLarge_xgboost_MetricA.json
        #     -> MetricA
        # ----------------------------------------------------------
        if "_xgboost_" in stem:
            metric_name = stem.split("_xgboost_", 1)[1]
        elif stem.startswith("xgboost_"):
            metric_name = stem[len("xgboost_") :]
        else:
            continue
        meta_path = model_path[: -len(MODEL_SUFFIX)] + META_SUFFIX
        if not os.path.isfile(meta_path):
            continue
        try:
            model = XGBoostSurrogateModel(metric_name, model_path, meta_path)
            model.load()
            models.append(model)
        except Exception as exc:
            App.Console.PrintError("[OBA] Could not load XGBoost model " f"{filename}: {exc}\n")
    return models


def find_xgboost_models_old(directory):
    """
    Find all trained XGBoost models in a directory.

    Returns:
        list[XGBoostSurrogateModel]
    """
    if not directory:
        return []
    if not os.path.isdir(directory):
        return []
    models = []
    for filename in sorted(os.listdir(directory)):
        if not filename.startswith(MODEL_PREFIX):
            continue
        if not filename.endswith(MODEL_SUFFIX):
            continue
        # Ignore metadata files.
        if filename.endswith(META_SUFFIX):
            continue
        model_path = os.path.join(directory, filename)
        base = filename[len(MODEL_PREFIX) : -len(MODEL_SUFFIX)]
        metric_name = base
        meta_path = os.path.join(directory, filename[: -len(MODEL_SUFFIX)] + META_SUFFIX)
        if not os.path.isfile(meta_path):
            continue
        try:
            model = XGBoostSurrogateModel(metric_name, model_path, meta_path)
            model.load()
            models.append(model)
        except Exception as exc:
            App.Console.PrintError("[OBA] Could not load XGBoost model " f"{filename}: {exc}\n")

    return models


# ======================================================================
# PARAMETER RANGE
# ======================================================================


def _property_range_from_freecad(obj, prop_name):
    """
    Try to obtain the allowed FreeCAD property range.

    FreeCAD's property API differs somewhat between versions, therefore
    this function deliberately has several fallbacks.
    """

    value = _safe_property_value(
        obj,
        prop_name,
    )

    if value is None:
        return None, None

    # --------------------------------------------------------------
    # Try getPropertyStatus / editor information if available.
    # --------------------------------------------------------------

    try:
        editor_mode = obj.getEditorMode(prop_name)

        # A read-only property is not a useful optimization parameter.
        if editor_mode is not None:
            pass
    except Exception:
        pass

    # --------------------------------------------------------------
    # The White Cell properties in oba_white_cell.py define ranges,
    # but those definitions are not necessarily available as runtime
    # property metadata.
    #
    # Therefore use a conservative local range as fallback.
    # --------------------------------------------------------------

    if abs(value) < MIN_RANGE:
        delta = 1.0
    else:
        delta = abs(value) * DEFAULT_RANGE_PERCENT

    low = value - delta
    high = value + delta

    # --------------------------------------------------------------
    # Avoid a zero-width search space.
    # --------------------------------------------------------------

    if abs(high - low) < MIN_RANGE:
        high = low + 1.0

    return float(low), float(high)


def build_parameter_ranges(obj, free_parameters):
    """
    Build optimization ranges around current White Cell values.

    The range is deliberately conservative:

        current +/- 10%

    For zero:

        -1 ... +1

    The function can later be replaced with the exact min/max values
    from WHITE_CELL_PROPERTIES if desired.
    """

    ranges = {}

    for name in free_parameters:

        value = _safe_property_value(
            obj,
            name,
        )

        if value is None:
            continue

        low, high = _property_range_from_freecad(
            obj,
            name,
        )

        if low is None or high is None:
            continue

        ranges[name] = (
            float(low),
            float(high),
        )

    return ranges


# ======================================================================
# OBJECT PARAMETER DISCOVERY
# ======================================================================


def discover_white_cell_parameters(obj):
    """
    Discover all numeric properties from the White Cell object.

    Only properties which have the corresponding _OptunaLocked flag
    are considered.

    Returns:

        {
            "locked": [...],
            "free": [...]
        }
    """

    locked = []
    free = []

    try:
        properties = list(obj.PropertiesList)
    except Exception:
        properties = []

    for prop in properties:

        if prop.endswith("_OptunaLocked"):
            continue

        # We only care about properties that
        # actually have a lock state.
        try:
            getattr(obj, prop + "_OptunaLocked")
        except Exception:
            continue

        value = _safe_property_value(
            obj,
            prop,
        )

        if value is None:
            continue

        if _is_locked(
            obj,
            prop,
        ):
            locked.append(prop)
        else:
            free.append(prop)

    return {
        "locked": sorted(locked),
        "free": sorted(free),
    }


# ======================================================================
# OPTIMIZATION RESULT
# ======================================================================


class OptimizationResult:
    """
    Simple container for one candidate.
    """

    def __init__(
        self,
        trial_number,
        parameters,
        metrics,
    ):
        self.trial_number = trial_number
        self.parameters = dict(parameters)
        self.metrics = dict(metrics)

        self.score = None
        self.feasible = True


# ======================================================================
# MAIN DIALOG
# ======================================================================


class XGBoostParameterOptimizerDialog(QtWidgets.QDialog):

    _window_count = 0

    @classmethod
    def is_open(cls):
        return cls._window_count > 0

    def closeEvent(self, event):
        XGBoostParameterOptimizerDialog._window_count = max(0, XGBoostParameterOptimizerDialog._window_count - 1)
        super().closeEvent(event)

    def __init__(self, white_cell_obj, parent=None):
        super().__init__(parent)
        self.obj = white_cell_obj
        self.models = []
        self.results = []
        self.best_result = None
        self.ranges = {}
        self._running = False
        self.best_guess = None

        XGBoostParameterOptimizerDialog._window_count += 1

        self.setWindowTitle("XGBoost Parameter Optimizer")

        self.resize(
            1050,
            850,
        )
        self.setMinimumSize(900, 700)
        self._build_ui()
        self._load_models()
        self._refresh_parameters()

    # ==================================================================
    # UI
    # ==================================================================

    def _build_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # --------------------------------------------------------------
        # Information
        # --------------------------------------------------------------
        info = QtWidgets.QLabel("Locked parameters are fixed. " "Unlocked parameters are optimized using " "the trained XGBoost surrogate models.")
        info.setWordWrap(True)
        main_layout.addWidget(info)

        # --------------------------------------------------------------
        # Models
        # --------------------------------------------------------------

        model_group = QtWidgets.QGroupBox("Trained XGBoost metrics")
        model_layout = QtWidgets.QVBoxLayout(model_group)
        self.model_table = QtWidgets.QTableWidget()
        self.model_table.setColumnCount(7)

        self.model_table.setHorizontalHeaderLabels(["Use", "Metric", "Direction", "Features", "Samples", "RMSE", "R²"])
        self.model_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.model_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.model_table.horizontalHeader().setStretchLastSection(True)
        model_layout.addWidget(self.model_table)
        main_layout.addWidget(model_group)

        # --------------------------------------------------------------
        # Parameters
        # --------------------------------------------------------------

        parameter_group = QtWidgets.QGroupBox("White Cell parameters")
        parameter_layout = QtWidgets.QVBoxLayout(parameter_group)
        self.parameter_table = QtWidgets.QTableWidget()
        self.parameter_table.setColumnCount(4)

        self.parameter_table.setHorizontalHeaderLabels(["Parameter", "State", "Current", "Optimization range"])
        self.parameter_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.parameter_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        parameter_layout.addWidget(self.parameter_table)
        main_layout.addWidget(parameter_group)

        # --------------------------------------------------------------
        # Optimization settings
        # --------------------------------------------------------------
        settings_group = QtWidgets.QGroupBox("Optimization")
        settings_layout = QtWidgets.QFormLayout(settings_group)
        self.spin_trials = QtWidgets.QSpinBox()
        self.spin_trials.setRange(10, 10000)
        self.spin_trials.setSingleStep(50)
        self.spin_trials.setValue(DEFAULT_TRIALS)
        settings_layout.addRow("Surrogate trials:", self.spin_trials)

        self.spin_range = QtWidgets.QDoubleSpinBox()
        self.spin_range.setRange(0.001, 10.0)
        self.spin_range.setDecimals(3)
        self.spin_range.setSingleStep(0.05)
        self.spin_range.setValue(DEFAULT_RANGE_PERCENT)
        self.spin_range.setToolTip("Search range around the current value. " "0.10 means ±10%.")
        settings_layout.addRow("Range fraction:", self.spin_range)

        # --------------------------------------------------------------
        # Horisontell linje (Avskiljare)
        # --------------------------------------------------------------
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Sunken)
        settings_layout.addRow(separator)  # Läggs till över båda kolumnerna i form_layout

        self.spin_guesses = QtWidgets.QSpinBox()
        self.spin_guesses.setRange(1000, 10000000)
        self.spin_guesses.setSingleStep(5000)  # Valfritt: gör det enklare att klicka sig fram i stora steg
        self.spin_guesses.setValue(200000)
        settings_layout.addRow("Initial guesses:", self.spin_guesses)  # Lade till denna rad

        main_layout.addWidget(settings_group)

        # --------------------------------------------------------------
        # Plot
        # --------------------------------------------------------------

        plot_group = QtWidgets.QGroupBox("Metric scatter plot")
        plot_layout = QtWidgets.QVBoxLayout(plot_group)
        if MATPLOTLIB_AVAILABLE:
            self.figure = Figure(figsize=(6, 4))
            self.canvas = FigureCanvasQTAgg(self.figure)
            plot_layout.addWidget(self.canvas)

        else:
            self.figure = None
            self.canvas = None
            label = QtWidgets.QLabel("Matplotlib is not available. " "The optimization table will still work.")
            label.setWordWrap(True)
            plot_layout.addWidget(label)

        main_layout.addWidget(plot_group, 1)

        # --------------------------------------------------------------
        # Results
        # --------------------------------------------------------------
        result_group = QtWidgets.QGroupBox("Best candidate")
        result_layout = QtWidgets.QVBoxLayout(result_group)
        self.result_table = QtWidgets.QTableWidget()
        self.result_table.setColumnCount(3)
        self.result_table.setHorizontalHeaderLabels(["Parameter / Metric", "Value", "Type"])
        self.result_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        result_layout.addWidget(self.result_table)
        main_layout.addWidget(result_group)

        # --------------------------------------------------------------
        # Status
        # --------------------------------------------------------------
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: gray;")
        main_layout.addWidget(self.status_label)
        # --------------------------------------------------------------
        # Buttons
        # --------------------------------------------------------------
        button_layout = QtWidgets.QHBoxLayout()
        self.btn_reload = QtWidgets.QPushButton("Reload Models")

        self.btn_guess = QtWidgets.QPushButton("Generate Guess")
        self.btn_apply_guess = QtWidgets.QPushButton("Apply Guess")
        self.btn_apply_guess.setEnabled(False)
        self.btn_run_optuna = QtWidgets.QPushButton("Run Mini Optuna")
        self.btn_apply = QtWidgets.QPushButton("Apply Best")
        self.btn_close = QtWidgets.QPushButton("Close")
        button_layout.addWidget(self.btn_reload)
        button_layout.addStretch()

        button_layout.addWidget(self.btn_guess)
        button_layout.addWidget(self.btn_apply_guess)

        button_layout.addWidget(self.btn_run_optuna)
        button_layout.addWidget(self.btn_apply)
        button_layout.addWidget(self.btn_close)
        main_layout.addLayout(button_layout)

        # --------------------------------------------------------------
        # Signals
        # --------------------------------------------------------------
        self.btn_reload.clicked.connect(self._reload)
        self.btn_guess.clicked.connect(self._generate_guess)
        self.btn_apply_guess.clicked.connect(self._apply_guess)

        self.btn_run_optuna.clicked.connect(self._run_optimization)
        self.btn_apply.clicked.connect(self._apply_best)
        self.btn_close.clicked.connect(self.close)
        self.btn_apply.setEnabled(False)

    # ==================================================================
    # ACTIVE DOCUMENT
    # ==================================================================

    def _document_directory(self):

        try:
            doc = self.obj.Document

            if doc is None:
                return None

            if not doc.FileName:
                return None

            return os.path.dirname(os.path.abspath(doc.FileName))

        except Exception:
            return None

    # ==================================================================
    # MODEL LOADING
    # ==================================================================

    def _load_models(self):

        self.models = []
        directory = self._document_directory()
        if not directory:
            self._set_status("The active FreeCAD document must be saved " "before XGBoost models can be loaded.")
            return

        if not XGBOOST_AVAILABLE:
            self._set_status("XGBoost is not available.")
            return
        try:
            self.models = find_xgboost_models(directory)
        except Exception as exc:
            self._show_error("Could not load XGBoost models.", exc)
            return

        self._populate_model_table()
        if not self.models:
            self._set_status("No xgboost_<metric>.json models were found in:\n" + directory)
        else:

            self._set_status(f"Loaded {len(self.models)} trained XGBoost model(s).\n" f"{directory}")

    def _populate_model_table(self):
        self.model_table.setRowCount(len(self.models))
        for row, model in enumerate(self.models):
            direction = self._direction_for_metric(model.metric_name)
            checkbox = QtWidgets.QTableWidgetItem()
            checkbox.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable)
            r2 = float(model.r2 or 0)
            checked = QtCore.Qt.Checked if r2 >= 0.8 else QtCore.Qt.Unchecked
            # checked = QtCore.Qt.Checked if r2_value >= 0.8 else QtCore.Qt.Unchecked
            checkbox.setCheckState(checked)

            self.model_table.setItem(row, 0, checkbox)

            self.model_table.setItem(row, 1, QtWidgets.QTableWidgetItem(model.metric_name))

            self.model_table.setItem(row, 2, QtWidgets.QTableWidgetItem(direction))

            self.model_table.setItem(row, 3, QtWidgets.QTableWidgetItem(str(len(model.features))))

            self.model_table.setItem(row, 4, QtWidgets.QTableWidgetItem(str(model.samples or 0)))

            self.model_table.setItem(row, 5, QtWidgets.QTableWidgetItem(self._format_number(model.rmse)))

            r2_value = float(model.r2 or 0.0)
            # r2_item = QtWidgets.QTableWidgetItem(self._format_number(r2_value))

            r2_item = QtWidgets.QTableWidgetItem()
            r2_item.setData(QtCore.Qt.DisplayRole, r2_value)

            if r2_value >= 0.90:
                r2_item.setBackground(QtGui.QColor(170, 255, 170))  # grön
            elif r2_value >= 0.80:
                r2_item.setBackground(QtGui.QColor(220, 255, 180))  # ljusgrön
            elif r2_value >= 0.60:
                r2_item.setBackground(QtGui.QColor(255, 255, 180))  # gul
            elif r2_value >= 0.40:
                r2_item.setBackground(QtGui.QColor(255, 220, 150))  # orange
            else:
                r2_item.setBackground(QtGui.QColor(255, 180, 180))  # röd

            self.model_table.setItem(row, 6, r2_item)

        # self.model_table.setItem(row, 5, QtWidgets.QTableWidgetItem(self._format_number(model.r2)))

        self.model_table.setSortingEnabled(True)  # sortering
        self.model_table.sortItems(6, QtCore.Qt.DescendingOrder)

        self.model_table.resizeColumnsToContents()  # lägger till

    # ==================================================================
    # METRIC DIRECTION
    # ==================================================================

    def _direction_for_metric(self, metric_name):
        """
        Determine a default metric direction.

        This is deliberately conservative.

        Explicit metadata is preferred if available.

        Otherwise common error-like metric names are minimized and
        common score-like names are maximized.

        The user can change the direction by double-clicking the
        Direction cell.
        """

        model = None

        for item in self.models:
            if item.metric_name == metric_name:
                model = item
                break

        if model is not None:
            value = model.metadata.get("direction")
            if value:
                value = str(value).lower()

                if value in ("minimize", "min"):
                    return "Minimize"

                if value in ("maximize", "max"):
                    return "Maximize"

        text = str(metric_name).lower()

        minimize_tokens = (
            "rmse",
            "mse",
            "mae",
            "loss",
            "error",
            "deviation",
            "distance",
            "cost",
        )

        for token in minimize_tokens:

            if token in text:
                return "Minimize"

        return "Maximize"

    # ==================================================================
    # PARAMETER TABLE
    # ==================================================================

    def _refresh_parameters(self):

        info = discover_white_cell_parameters(self.obj)

        locked = info["locked"]
        free = info["free"]
        all_parameters = locked + free
        self.parameter_table.setRowCount(len(all_parameters))
        self.ranges = build_parameter_ranges(self.obj, free)

        # Apply current UI range fraction.
        self._rebuild_ranges()

        for row, name in enumerate(all_parameters):
            is_locked = name in locked
            value = _safe_property_value(self.obj, name)

            if is_locked:
                state = "LOCKED"
                range_text = "fixed"

            else:
                state = "FREE"
                if name in self.ranges:
                    low, high = self.ranges[name]
                    range_text = f"{low:.6g} ... " f"{high:.6g}"
                else:
                    range_text = "n/a"

            self.parameter_table.setItem(row, 0, QtWidgets.QTableWidgetItem(name))
            self.parameter_table.setItem(row, 1, QtWidgets.QTableWidgetItem(state))
            self.parameter_table.setItem(row, 2, QtWidgets.QTableWidgetItem(self._format_number(value)))
            self.parameter_table.setItem(row, 3, QtWidgets.QTableWidgetItem(range_text))

        self.parameter_table.resizeColumnsToContents()

    def _rebuild_ranges(self):

        info = discover_white_cell_parameters(self.obj)

        fraction = float(self.spin_range.value())

        new_ranges = {}

        for name in info["free"]:

            value = _safe_property_value(
                self.obj,
                name,
            )

            if value is None:
                continue

            if abs(value) < MIN_RANGE:

                delta = 1.0

            else:

                delta = abs(value) * fraction

            low = value - delta
            high = value + delta

            if abs(high - low) < MIN_RANGE:

                high = low + 1.0

            new_ranges[name] = (
                float(low),
                float(high),
            )

        self.ranges = new_ranges

    # ==================================================================
    # OPTIMIZATION
    # ==================================================================

    def _generate_guess(self):

        active_models = self._selected_models()

        if not active_models:
            self._show_error("Select at least one XGBoost model.")
            return

        if np is None:
            self._show_error("NumPy is required.")
            return

        n_samples = int(self.spin_guesses.value())

        progress = QtWidgets.QProgressDialog("Generating guesses...", "Cancel", 0, 100, self)
        progress.setWindowTitle("XGBoost Guess")
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.show()

        try:

            info = discover_white_cell_parameters(self.obj)
            locked = info["locked"]
            free = info["free"]
            # --------------------------------------------------
            # Fixed parameters
            # --------------------------------------------------
            fixed_values = {}
            for name in locked:
                value = _safe_property_value(self.obj, name)
                if value is not None:
                    fixed_values[name] = value
            # --------------------------------------------------
            # Union of all model features
            # --------------------------------------------------
            all_features = []
            for model in active_models:
                for feature in model.features:
                    if feature not in all_features:
                        all_features.append(feature)

            if not all_features:
                self._show_error("No model features found.")
                return

            # --------------------------------------------------
            # Build candidate matrix
            # --------------------------------------------------

            progress.setValue(5)
            progress.setLabelText("Building candidate matrix...")
            QtWidgets.QApplication.processEvents()

            feature_index = {name: idx for idx, name in enumerate(all_features)}

            grid = np.zeros((n_samples, len(all_features)), dtype=np.float32)
            # --------------------------------------------------
            # Locked params
            # --------------------------------------------------
            for name, value in fixed_values.items():
                if name not in feature_index:
                    continue
                grid[:, feature_index[name]] = value

            # --------------------------------------------------
            # Random free params
            # --------------------------------------------------
            for name in free:
                bounds = None
                for model in active_models:
                    bounds = model.parameter_bounds.get(name)
                    if bounds:
                        break

                if not bounds:
                    continue

                low = float(bounds["top20_min"])
                high = float(bounds["top20_max"])
                idx = feature_index[name]
                grid[:, idx] = np.random.uniform(low, high, size=n_samples)
            progress.setValue(25)
            progress.setLabelText("Evaluating XGBoost models...")
            QtWidgets.QApplication.processEvents()

            # --------------------------------------------------
            # Combined score
            # --------------------------------------------------
            scores = np.zeros(n_samples, dtype=np.float64)
            # --------------------------------------------------
            # Predict once per model
            # --------------------------------------------------

            for model_index, model in enumerate(active_models):
                if progress.wasCanceled():
                    return

                cols = [feature_index[name] for name in model.features]
                model_grid = grid[:, cols]
                dmatrix = xgboost.DMatrix(
                    model_grid,
                    feature_names=model.features,
                )
                predictions = model.model.predict(dmatrix)
                direction = self._direction_for_metric(model.metric_name)
                if direction == "Maximize":
                    scores += predictions
                else:
                    scores -= predictions

                progress.setValue(25 + int(60.0 * (model_index + 1) / len(active_models)))
                progress.setLabelText(f"Evaluating model {model_index + 1} / {len(active_models)}")
                QtWidgets.QApplication.processEvents()

            # --------------------------------------------------
            # Best candidate
            # --------------------------------------------------
            best_idx = int(np.argmax(scores))

            best_candidate = {}
            for feature in all_features:
                idx = feature_index[feature]
                best_candidate[feature] = float(grid[best_idx, idx])

            progress.setValue(100)
            self.best_guess = best_candidate
            self.btn_apply_guess.setEnabled(best_candidate is not None)

            # KORRIGERAD RAD: Ändrat till scores[best_idx] och fixat strängformateringen
            self._set_status(f"Generated {n_samples:,} guesses.\nBest score: {scores[best_idx]:.6g}")
        finally:
            progress.close()

    def _generate_guess_old(self):
        active_models = self._selected_models()
        if not active_models:
            self._show_error("Select at least one XGBoost model.")
            return
        n_samples = int(self.spin_guesses.value())

        progress = QtWidgets.QProgressDialog(
            "Generating guesses...",
            "Cancel",
            0,
            n_samples,
            self,
        )
        progress.setWindowTitle("XGBoost Guess")
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.show()

        fixed_values = {}
        free_values = []
        info = discover_white_cell_parameters(self.obj)

        for name in info["locked"]:
            value = _safe_property_value(self.obj, name)
            if value is not None:
                fixed_values[name] = value

        for name in info["free"]:
            free_values.append(name)

        best_score = None
        best_candidate = None

        for i in range(n_samples):

            if i % 100 == 0:
                progress.setValue(i)
                progress.setLabelText(f"Generating guesses...\n" f"{i:,} / {n_samples:,}\n\n" f"Best score: {best_score:.6g}" if best_score is not None else f"{i:,} / {n_samples:,}")

            candidate = dict(fixed_values)
            for name in free_values:
                bounds = None
                for model in active_models:
                    bounds = model.parameter_bounds.get(name)
                    if bounds:
                        break

                if not bounds:
                    continue

                low = bounds["top20_min"]
                high = bounds["top20_max"]

                candidate[name] = np.random.uniform(low, high)

            score = 0.0
            for model in active_models:
                prediction = model.predict(candidate)
                direction = self._direction_for_metric(model.metric_name)
                if direction == "Maximize":
                    score += prediction
                else:
                    score -= prediction

            if best_score is None or score > best_score:
                best_score = score
                best_candidate = candidate

        progress.setValue(n_samples)
        self.best_guess = best_candidate
        self.btn_apply_guess.setEnabled(best_candidate is not None)
        self._set_status(f"Best guess score: {best_score:.6g}")

    def _apply_guess(self):

        if not self.best_guess:
            return
        info = discover_white_cell_parameters(self.obj)
        for name in info["free"]:
            if name not in self.best_guess:
                continue
            _set_property(
                self.obj,
                name,
                self.best_guess[name],
            )
        self.obj.Document.recompute()

    def _run_optimization(self):

        if self._running:
            return
        if not OPTUNA_AVAILABLE:
            self._show_error("Optuna is not available.")
            return
        if not self.models:
            self._show_error("No trained XGBoost models were found.")
            return

        info = discover_white_cell_parameters(self.obj)

        locked = info["locked"]
        free = info["free"]
        if not free:
            self._show_error("There are no unlocked parameters.\n\n" "Uncheck at least one parameter in the " "White Cell dialog.")
            return

        # --------------------------------------------------------------
        # Ensure the XGBoost models actually support the parameters.
        # --------------------------------------------------------------

        supported_free = set()
        for model in self.models:
            supported_free.update(model.features)
        free_supported = [name for name in free if name in supported_free]
        if not free_supported:
            self._show_error("None of the unlocked White Cell parameters " "are present in the trained XGBoost models.")
            return

        # --------------------------------------------------------------
        # Build ranges.
        # --------------------------------------------------------------

        self._rebuild_ranges()
        missing_ranges = [name for name in free_supported if name not in self.ranges]
        if missing_ranges:
            self._show_error("Could not determine optimization ranges for:\n\n" + "\n".join(missing_ranges))
            return

        # --------------------------------------------------------------
        # Fixed values.
        # --------------------------------------------------------------
        fixed_values = {}
        for name in locked:
            value = _safe_property_value(self.obj, name)
            if value is not None:
                fixed_values[name] = value

        # --------------------------------------------------------------
        # Optimization.
        # --------------------------------------------------------------
        self._running = True
        self.btn_run_optuna.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.results = []

        try:
            self._set_status("Running surrogate optimization...")
            QtWidgets.QApplication.processEvents()
            sampler = optuna.samplers.TPESampler(seed=42)

            active_models = self._selected_models()

            study = optuna.create_study(
                directions=["minimize" if self._direction_for_metric(model.metric_name) == "Minimize" else "maximize" for model in active_models],
                sampler=sampler,
            )
            trial_count = int(self.spin_trials.value())

            # ----------------------------------------------------------
            # Multi-objective Optuna objective.
            # ----------------------------------------------------------

            trial_count = int(self.spin_trials.value())
            progress = QtWidgets.QProgressDialog("Running surrogate optimization...", "Cancel", 0, trial_count, self)
            progress.setWindowTitle("Mini Optuna")
            progress.setWindowModality(QtCore.Qt.WindowModal)
            progress.show()

            def objective(trial):
                progress.setValue(trial.number)
                progress.setLabelText(f"Optimizing...\n" f"Trial {trial.number + 1} / {trial_count}")

                QtWidgets.QApplication.processEvents()
                if progress.wasCanceled():
                    raise KeyboardInterrupt()
                candidate = dict(fixed_values)
                for name in free_supported:
                    low, high = self.ranges[name]
                    candidate[name] = trial.suggest_float(name, low, high)

                metrics = {}
                values = []

                active_models = self._selected_models()

                for model in active_models:
                    prediction = model.predict(candidate)
                    metrics[model.metric_name] = prediction
                    values.append(prediction)
                result = OptimizationResult(trial.number, candidate, metrics)
                self.results.append(result)
                return values

            # def objective(trial):
            #     candidate = dict(fixed_values)
            #     for name in free_supported:
            #         low, high = self.ranges[name]
            #         # XGBoost models are regression models. Continuous
            #         # search is therefore appropriate for all numeric
            #         # White Cell parameters.
            #         candidate[name] = trial.suggest_float(name, low, high)
            #     metrics = {}
            #     values = []
            #     for model in self.models:
            #         prediction = model.predict(candidate)
            #         metrics[model.metric_name] = prediction
            #         direction = self._direction_for_metric(model.metric_name)
            #         if direction == "Minimize":
            #             values.append(prediction)
            #         else:
            #             values.append(prediction)

            #     result = OptimizationResult(trial.number, candidate, metrics)
            #     self.results.append(result)
            #     return values

            # ----------------------------------------------------------
            # Run.
            # ----------------------------------------------------------

            study.optimize(objective, n_trials=trial_count, show_progress_bar=False)

            progress.setValue(trial_count)
            # ----------------------------------------------------------
            # Select a representative candidate.
            #
            # Multi-objective studies normally produce a Pareto front.
            # For "Apply Best" we need one candidate.
            #
            # We therefore normalize all objectives and select the
            # candidate with the smallest total normalized distance
            # from the ideal point.
            # ----------------------------------------------------------

            self.best_result = self._select_representative_result(study, fixed_values)
            self._show_results()
            self._plot_results()
            self.btn_apply.setEnabled(self.best_result is not None)
            self._set_status(f"Completed {trial_count} surrogate trials. " f"Generated {len(self.results)} candidates.")

        except KeyboardInterrupt:
            self._set_status("Optimization cancelled by user.")
            return
        except Exception as exc:
            self._show_error("Surrogate optimization failed.", exc)
        finally:
            self._running = False
            self.btn_run_optuna.setEnabled(True)

    # ==================================================================
    # REPRESENTATIVE RESULT
    # ==================================================================

    def _select_representative_result(self, study, fixed_values):
        if not study.best_trials:
            return None

        candidates = []
        for trial in study.best_trials:
            metrics = {}
            for index, model in enumerate(self.models):
                try:
                    metrics[model.metric_name] = float(trial.values[index])
                except Exception:
                    metrics[model.metric_name] = float("nan")
            parameters = dict(fixed_values)
            for name in trial.params:
                parameters[name] = trial.params[name]

            candidates.append(OptimizationResult(trial.number, parameters, metrics))
        if not candidates:
            return None

        # --------------------------------------------------------------
        # Normalize every metric across the Pareto candidates.
        # --------------------------------------------------------------

        metric_names = [model.metric_name for model in self.models]
        normalized = {name: [] for name in metric_names}
        for candidate in candidates:
            for name in metric_names:
                normalized[name].append(candidate.metrics.get(name, float("nan")))

        ranges = {}
        for name in metric_names:
            values = [value for value in normalized[name] if math.isfinite(value)]
            if not values:
                ranges[name] = (0.0, 1.0)
                continue
            low = min(values)
            high = max(values)

            if abs(high - low) < MIN_RANGE:
                high = low + 1.0
            ranges[name] = (low, high)
        # --------------------------------------------------------------
        # Ideal-point distance.
        # --------------------------------------------------------------

        best = None
        best_distance = None
        for candidate in candidates:
            distance = 0.0
            for model in self.models:
                name = model.metric_name
                value = candidate.metrics.get(name)
                low, high = ranges[name]
                if not math.isfinite(value):
                    continue
                normalized_value = (value - low) / (high - low)
                direction = self._direction_for_metric(name)
                if direction == "Maximize":
                    normalized_value = 1.0 - normalized_value
                distance += normalized_value * normalized_value
            distance = math.sqrt(distance)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best = candidate
        return best

    # ==================================================================
    # RESULTS
    # ==================================================================

    def _show_results(self):
        result = self.best_result
        if result is None:
            self.result_table.setRowCount(0)
            return
        rows = []

        # --------------------------------------------------------------
        # Parameters
        # --------------------------------------------------------------

        info = discover_white_cell_parameters(self.obj)
        free = set(info["free"])
        for name, value in sorted(result.parameters.items()):
            if name in free:
                rows.append((name, value, "OPTIMIZED"))
        # --------------------------------------------------------------
        # Metrics
        # --------------------------------------------------------------
        for name, value in result.metrics.items():
            rows.append((name, value, self._direction_for_metric(name)))
        self.result_table.setRowCount(len(rows))
        for row, (name, value, kind) in enumerate(rows):

            self.result_table.setItem(row, 0, QtWidgets.QTableWidgetItem(name))
            self.result_table.setItem(row, 1, QtWidgets.QTableWidgetItem(self._format_number(value)))
            self.result_table.setItem(row, 2, QtWidgets.QTableWidgetItem(kind))
        self.result_table.resizeColumnsToContents()

    # ==================================================================
    # SCATTER PLOT
    # ==================================================================

    def _plot_results(self):
        if not MATPLOTLIB_AVAILABLE:
            return
        if self.figure is None:
            return
        self.figure.clear()
        axis = self.figure.add_subplot(111)
        if not self.results:
            self.canvas.draw()
            return
        if len(self.models) < 2:
            model = self.models[0]
            x_name = model.metric_name
            x_values = [
                result.metrics.get(
                    x_name,
                    float("nan"),
                )
                for result in self.results
            ]

            y_values = list(range(len(x_values)))
            axis.scatter(x_values, y_values, s=18, alpha=0.65)
            axis.set_xlabel(x_name)
            axis.set_ylabel("Trial")
            axis.set_title("Surrogate optimization")
        else:
            model_x = self.models[0]
            model_y = self.models[1]

            x_name = model_x.metric_name
            y_name = model_y.metric_name

            x_values = []
            y_values = []

            for result in self.results:

                x_values.append(result.metrics.get(x_name, float("nan")))

                y_values.append(result.metrics.get(y_name, float("nan")))

            axis.scatter(x_values, y_values, s=18, alpha=0.45)

            # ----------------------------------------------------------
            # Representative candidate.
            # ----------------------------------------------------------
            if self.best_result is not None:
                bx = self.best_result.metrics.get(x_name)
                by = self.best_result.metrics.get(y_name)
                axis.scatter([bx], [by], s=90, marker="*", label="Selected candidate")
                axis.legend()
            axis.set_xlabel(x_name)
            axis.set_ylabel(y_name)
            axis.set_title("Multi-metric surrogate search")

        axis.grid(True, alpha=0.25)
        self.figure.tight_layout()
        self.canvas.draw()

    # ==================================================================
    # APPLY
    # ==================================================================

    def _apply_best(self):
        if self.best_result is None:
            self._show_error("No optimization result is available.")
            return
        info = discover_white_cell_parameters(self.obj)
        free = set(info["free"])
        parameters = self.best_result.parameters
        changed = []
        for name in free:
            if name not in parameters:
                continue
            value = parameters[name]
            if _set_property(self.obj, name, value):
                changed.append(name)
        try:
            self.obj.Document.recompute()
        except Exception as exc:
            App.Console.PrintError("[OBA] Recompute after XGBoost " f"optimization failed: {exc}\n")
        self._set_status("Applied optimized parameters:\n" + ("\n".join(changed) if changed else "No parameters changed."))

        # Refresh the White Cell dialog if it is open.
        try:

            proxy = getattr(self.obj, "Proxy", None)
            dialog = getattr(proxy, "_dialog", None)
            if dialog is not None:
                dialog.refresh_from_object()
        except Exception:
            pass
        QtWidgets.QMessageBox.information(
            self,
            "XGBoost Optimization",
            (f"Applied {len(changed)} " "optimized parameter(s)."),
        )

    # ==================================================================
    # RELOAD
    # ==================================================================

    def _reload(self):

        self.best_result = None

        self.results = []

        self.btn_apply.setEnabled(False)

        self._load_models()

        self._refresh_parameters()

        if self.figure is not None:

            self.figure.clear()

            self.canvas.draw()

    # ==================================================================
    # HELPERS
    # ==================================================================

    def _selected_models(self):
        models = []
        for row, model in enumerate(self.models):
            item = self.model_table.item(row, 0)
            if item.checkState() == QtCore.Qt.Checked:
                models.append(model)
        return models

    def _set_status(self, text):
        self.status_label.setText(str(text))

    @staticmethod
    def _format_number(value):
        if value is None:
            return "-"
        try:
            value = float(value)
            if not math.isfinite(value):
                return "-"
            return f"{value:.8g}"
        except Exception:
            return str(value)

    def _show_error(self, message, exc=None):
        if exc is not None:
            details = f"{message}\n\n" f"{exc}"
            try:
                App.Console.PrintError(f"{message}\n" f"{exc}\n")
                App.Console.PrintError(traceback.format_exc())
            except Exception:
                pass
        else:
            details = message

        QtWidgets.QMessageBox.critical(
            self,
            "XGBoost Parameter Optimizer",
            details,
        )


# ======================================================================
# CREATOR
# ======================================================================


def OBA_CreateXGBoostParameterOptimizerDialog(white_cell_obj, parent=None, show_dialog=True):
    """
    Create the inverse XGBoost optimizer dialog.

    Parameters
    ----------
    white_cell_obj:
        The actual White Cell FeaturePython object.

    parent:
        Optional Qt parent.

    show_dialog:
        If True, show immediately.
    """

    if white_cell_obj is None:
        raise ValueError("A White Cell object is required.")
    if parent is None:
        try:
            if App.GuiUp:
                import FreeCADGui as Gui

                parent = Gui.getMainWindow()
        except Exception:
            parent = None

    dialog = XGBoostParameterOptimizerDialog(white_cell_obj, parent=parent)

    if show_dialog:
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
    return dialog


# ======================================================================
# CONVENIENCE FUNCTION
# ======================================================================


def open_xgboost_parameter_optimizer(
    white_cell_obj,
):
    """
    Convenience function for the White Cell dialog.
    """

    return OBA_CreateXGBoostParameterOptimizerDialog(white_cell_obj)
