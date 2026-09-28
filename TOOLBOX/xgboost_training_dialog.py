# -*- coding: utf-8 -*-
"""
xgboost_training_dialog.py

FreeCAD utility dialog for training an XGBoost regression model from
one or more Optuna SQLite databases.

The dialog is intentionally NOT connected to a FeaturePython object.

Main entry point:

    OBA_CreateXGBoostTrainingDialog()

The dialog:
    - loads one or more Optuna SQLite databases
    - discovers metric names from study.user_attrs["metric_names"]
    - discovers parameter names from COMPLETE trials
    - builds a regression dataset
    - trains an XGBoost regression model
    - displays RMSE and R²
    - saves the XGBoost model as JSON
    - saves accompanying metadata as JSON
"""

# ==================================================================
# I M P O R T S
# ==================================================================

import json
import traceback
import os
import sys

import FreeCAD as App
import numpy as np
from PySide import QtCore, QtWidgets


import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
OPTUNA_DIR = os.path.join(BASE_DIR, "vendor_optuna")
if OPTUNA_DIR not in sys.path:
    sys.path.insert(0, OPTUNA_DIR)
import optuna
from optuna.trial import TrialState

XGBOOST_DIR = os.path.join(BASE_DIR, "vendor_xgboost")
if XGBOOST_DIR not in sys.path:
    sys.path.insert(0, XGBOOST_DIR)
import xgboost

# ==================================================================
# M O D U L E   C O N S T A N T S
# ==================================================================

DEFAULT_N_ESTIMATORS = 500
DEFAULT_MAX_DEPTH = 6
DEFAULT_LEARNING_RATE = 0.05
DEFAULT_TEST_SIZE = 0.20

SUPPORTED_DB_FILTER = "Optuna databases (*.db *.sqlite *.sqlite3);;" "SQLite databases (*.db *.sqlite *.sqlite3);;" "All files (*)"


# ==================================================================
# X G B O O S T   T R A I N I N G   D I A L O G
# ==================================================================


class XGBoostTrainingDialog(QtWidgets.QDialog):

    # ==============================================================
    # C O N S T R U C T O R
    # ==============================================================

    def __init__(self, parent=None):
        super().__init__(parent)

        # ----------------------------------------------------------
        # State
        # ----------------------------------------------------------
        self.database_paths = []
        self.studies = []
        self.metric_names = []
        self.parameter_names = []

        self.models = {}

        self.created_from_databases = []

        # ----------------------------------------------------------
        # Window
        # ----------------------------------------------------------

        self.setWindowTitle("XGBoost Training")
        self.resize(760, 820)
        self.setMinimumSize(680, 700)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)

        # ----------------------------------------------------------
        # UI
        # ----------------------------------------------------------

        self._build_ui()
        self._connect_signals()

        # ----------------------------------------------------------
        # Initial state
        # ----------------------------------------------------------

        self._update_statistics()
        self._update_button_state()

    # ==============================================================
    # U I
    # ==============================================================

    def _build_ui(self):

        layout = QtWidgets.QVBoxLayout(self)

        layout.setContentsMargins(12, 12, 12, 12)

        layout.setSpacing(10)

        # ==========================================================
        # S T U D Y   D A T A B A S E S
        # ==========================================================

        self.grpDatabases = QtWidgets.QGroupBox("Study Databases")
        db_layout = QtWidgets.QVBoxLayout(self.grpDatabases)
        self.lstDatabases = QtWidgets.QListWidget()
        self.lstDatabases.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.lstDatabases.setMinimumHeight(100)
        db_layout.addWidget(self.lstDatabases)
        db_buttons = QtWidgets.QHBoxLayout()
        self.btnAddDB = QtWidgets.QPushButton("Add DB")
        self.btnRemoveDB = QtWidgets.QPushButton("Remove Selected")
        self.btnClearDB = QtWidgets.QPushButton("Clear")
        db_buttons.addWidget(self.btnAddDB)
        db_buttons.addWidget(self.btnRemoveDB)
        db_buttons.addWidget(self.btnClearDB)
        db_buttons.addStretch()
        db_layout.addLayout(db_buttons)
        layout.addWidget(self.grpDatabases)

        # ==========================================================
        # P A R A M E T E R S
        # ==========================================================

        self.grpParameters = QtWidgets.QGroupBox("Parameters")
        parameter_layout = QtWidgets.QVBoxLayout(self.grpParameters)
        self.lstParameters = QtWidgets.QListWidget()
        self.lstParameters.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.lstParameters.setMinimumHeight(150)
        parameter_layout.addWidget(self.lstParameters)
        parameter_buttons = QtWidgets.QHBoxLayout()
        self.btnSelectAll = QtWidgets.QPushButton("Select All")
        self.btnClearParameters = QtWidgets.QPushButton("Clear")
        parameter_buttons.addWidget(self.btnSelectAll)
        parameter_buttons.addWidget(self.btnClearParameters)
        parameter_buttons.addStretch()
        parameter_layout.addLayout(parameter_buttons)
        layout.addWidget(self.grpParameters)

        # ==========================================================
        # M O D E L   S E T T I N G S
        # ==========================================================

        self.grpModel = QtWidgets.QGroupBox("Model Settings")
        model_layout = QtWidgets.QFormLayout(self.grpModel)
        self.spinTrees = QtWidgets.QSpinBox()
        self.spinTrees.setRange(1, 100000)
        self.spinTrees.setValue(DEFAULT_N_ESTIMATORS)
        self.spinTrees.setSingleStep(50)
        model_layout.addRow("Number of trees:", self.spinTrees)
        self.spinDepth = QtWidgets.QSpinBox()
        self.spinDepth.setRange(1, 100)
        self.spinDepth.setValue(DEFAULT_MAX_DEPTH)
        model_layout.addRow("Max depth:", self.spinDepth)
        self.spinLearningRate = QtWidgets.QDoubleSpinBox()
        self.spinLearningRate.setRange(0.000001, 10.0)
        self.spinLearningRate.setDecimals(6)
        self.spinLearningRate.setSingleStep(0.01)
        self.spinLearningRate.setValue(DEFAULT_LEARNING_RATE)
        self.spinLearningRate.setToolTip(
            "Learning rate (eta).\n\n"
            "Lower values learn more slowly but usually generalize better.\n"
            "Higher values learn faster but increase the risk of overfitting.\n\n"
            "Typical values:\n"
            "0.01 - Very conservative\n"
            "0.05 - Good default\n"
            "0.10 - Faster training\n"
            "0.30+ - Aggressive, often needs fewer trees\n\n"
            "When lowering learning rate, it is often beneficial to increase the number of trees."
        )
        model_layout.addRow("Learning rate:", self.spinLearningRate)
        self.spinTestFraction = QtWidgets.QDoubleSpinBox()
        self.spinTestFraction.setRange(0.01, 0.99)
        self.spinTestFraction.setDecimals(2)
        self.spinTestFraction.setSingleStep(0.05)
        self.spinTestFraction.setValue(DEFAULT_TEST_SIZE)
        model_layout.addRow("Test fraction:", self.spinTestFraction)
        layout.addWidget(self.grpModel)

        # ==========================================================
        # S T A T I S T I C S
        # ==========================================================
        self.grpStatistics = QtWidgets.QGroupBox("Statistics")
        statistics_layout = QtWidgets.QFormLayout(self.grpStatistics)
        self.lblSamples = QtWidgets.QLabel("0")
        self.lblFeatures = QtWidgets.QLabel("0")
        self.lblTrainRows = QtWidgets.QLabel("0")
        self.lblTestRows = QtWidgets.QLabel("0")
        statistics_layout.addRow("Samples:", self.lblSamples)
        statistics_layout.addRow("Features:", self.lblFeatures)
        statistics_layout.addRow("Train rows:", self.lblTrainRows)
        statistics_layout.addRow("Test rows:", self.lblTestRows)
        layout.addWidget(self.grpStatistics)

        # ==========================================================
        # R E S U L T S
        # ==========================================================

        self.grpResults = QtWidgets.QGroupBox("Results")
        results_layout = QtWidgets.QFormLayout(self.grpResults)
        self.lblRMSE = QtWidgets.QLabel("-")
        self.lblR2 = QtWidgets.QLabel("-")
        results_layout.addRow("RMSE:", self.lblRMSE)
        results_layout.addRow("R²:", self.lblR2)
        layout.addWidget(self.grpResults)

        # ==========================================================
        # S T A T U S
        # ==========================================================

        self.lblStatus = QtWidgets.QLabel()
        self.lblStatus.setWordWrap(True)
        self.lblStatus.setStyleSheet("color: gray;")
        layout.addWidget(self.lblStatus)
        layout.addStretch()

        # ==========================================================
        # A C T I O N S
        # ==========================================================

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        self.btnTrainAll = QtWidgets.QPushButton("Train All")

        self.btnSave = QtWidgets.QPushButton("Save Model")
        self.btnClose = QtWidgets.QPushButton("Close")
        buttons.addWidget(self.btnTrainAll)
        buttons.addWidget(self.btnSave)
        buttons.addWidget(self.btnClose)
        layout.addLayout(buttons)

    # ==============================================================
    # S I G N A L S
    # ==============================================================

    def _connect_signals(self):

        self.btnAddDB.clicked.connect(self._add_databases)
        self.btnRemoveDB.clicked.connect(self._remove_selected_databases)
        self.btnClearDB.clicked.connect(self._clear_databases)
        self.btnSelectAll.clicked.connect(self.lstParameters.selectAll)
        self.btnClearParameters.clicked.connect(self.lstParameters.clearSelection)
        self.btnTrainAll.clicked.connect(self._train_all_models)

        self.btnSave.clicked.connect(self._save_models)
        self.btnClose.clicked.connect(self.close)

    # ==============================================================
    # D A T A B A S E S
    # ==============================================================

    def _add_databases(self):
        # ----------------------------------------------------------
        # Start in active document folder if document is saved
        # ----------------------------------------------------------
        start_dir = os.path.expanduser("~")
        try:
            doc = App.ActiveDocument
            if doc and doc.FileName:
                start_dir = os.path.dirname(doc.FileName)
        except Exception:
            pass
        # ----------------------------------------------------------
        # File dialog
        # ----------------------------------------------------------
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Select Optuna Databases", start_dir, SUPPORTED_DB_FILTER)
        if not paths:
            return
        # ----------------------------------------------------------
        # Add unique databases
        # ----------------------------------------------------------
        existing = set(self.database_paths)
        added = False
        for path in paths:
            path = os.path.abspath(path)
            if path in existing:
                continue
            if not os.path.isfile(path):
                continue
            self.database_paths.append(path)
            existing.add(path)
            added = True
        if not added:
            return
        # ----------------------------------------------------------
        # Refresh UI
        # ----------------------------------------------------------
        self._refresh_database_list()

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self._load_metadata()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _remove_selected_databases(self):
        selected_items = self.lstDatabases.selectedItems()
        if not selected_items:
            return
        selected_paths = {item.data(QtCore.Qt.UserRole) for item in selected_items}
        self.database_paths = [path for path in self.database_paths if path not in selected_paths]
        self._refresh_database_list()
        self._load_metadata()

    def _clear_databases(self):
        self.database_paths.clear()

        self.studies.clear()
        self.metric_names.clear()
        self.parameter_names.clear()

        self.lstDatabases.clear()
        self.lstParameters.clear()

        self.models = {}

        self.lblRMSE.setText("-")
        self.lblR2.setText("-")

        self._update_statistics()
        self._update_button_state()

        self._set_status("No databases loaded.")

    def _refresh_database_list(self):

        self.lstDatabases.clear()
        for path in self.database_paths:
            item = QtWidgets.QListWidgetItem(os.path.basename(path))
            item.setToolTip(path)
            item.setData(QtCore.Qt.UserRole, path)
            self.lstDatabases.addItem(item)

    # ==============================================================
    # M E T A D A T A
    # ==============================================================

    def _storage_url(self, database_path):
        path = os.path.abspath(database_path).replace("\\", "/")
        return f"sqlite:///{path}"

    def _load_metadata(self):

        self.studies.clear()
        self.metric_names.clear()
        self.parameter_names.clear()

        # ----------------------------------------------------------
        # Load every database
        # ----------------------------------------------------------
        errors = []
        for database_path in self.database_paths:
            storage = self._storage_url(database_path)
            try:
                # study_names = optuna.study.get_all_study_summaries(storage=database_path)
                study_names = optuna.study.get_all_study_summaries(storage=storage)
            except Exception as exc:
                errors.append(f"{database_path}\n{exc}")
                continue
            for summary in study_names:
                try:
                    # study = optuna.load_study(study_name=summary.study_name, storage=database_path)
                    study = optuna.load_study(study_name=summary.study_name, storage=storage)

                    self.studies.append((database_path, study))
                except Exception as exc:
                    errors.append(f"{database_path} / " f"{summary.study_name}\n" f"{exc}")

        # ----------------------------------------------------------
        # Metrics
        # ----------------------------------------------------------

        metric_names = []

        for _, study in self.studies:
            names = study.user_attrs.get("metric_names")
            if not isinstance(names, (list, tuple)):
                continue
            for name in names:
                name = str(name)
                if name not in metric_names:
                    metric_names.append(name)

        self.metric_names = metric_names

        # ----------------------------------------------------------
        # Parameters
        # ----------------------------------------------------------

        parameter_names = set()
        for _, study in self.studies:

            # Collect parameter names from COMPLETE trials only.
            for trial in study.trials:
                if trial.state != TrialState.COMPLETE:
                    continue
                parameter_names.update(trial.params.keys())
        self.parameter_names = sorted(parameter_names)
        self.lstParameters.clear()
        for name in self.parameter_names:
            item = QtWidgets.QListWidgetItem(name)
            item.setData(QtCore.Qt.UserRole, name)
            self.lstParameters.addItem(item)

        # ----------------------------------------------------------
        # Select all parameters by default
        # ----------------------------------------------------------

        if self.parameter_names:
            self.lstParameters.selectAll()

        # ----------------------------------------------------------
        # Status
        # ----------------------------------------------------------
        self._set_status(f"Loaded " f"{len(self.studies)} studies\n" f"{len(self.metric_names)} metrics\n" f"{len(self.parameter_names)} parameters")  # debugg

        if errors:
            self._set_status("Some databases could not be loaded:\n" + "\n".join(errors))
        else:
            self._set_status(f"Loaded {len(self.studies)} study/studies. " f"Found {len(self.metric_names)} metric(s) " f"and {len(self.parameter_names)} parameter(s).")

        self._update_statistics()
        self._update_button_state()

        # ==============================================================
        # T R I A L S
        # ==============================================================

    def _collect_trials(self, metric_name):
        """
        Collect COMPLETE trials from all loaded studies.

        Returns a list of dictionaries containing:

            database
            study
            trial
            metric_index
            metric_name
        """
        if not self.studies:
            return []
        if not metric_name:
            return []

        records = []
        for database_path, study in self.studies:
            # ------------------------------------------------------
            # Each study can have its own metric ordering.
            # ------------------------------------------------------
            study_metric_names = study.user_attrs.get("metric_names")
            if not isinstance(study_metric_names, (list, tuple)):
                continue
            study_metric_names = [str(name) for name in study_metric_names]
            if metric_name not in study_metric_names:
                continue
            metric_index = study_metric_names.index(metric_name)
            # ------------------------------------------------------
            # COMPLETE trials only
            # ------------------------------------------------------
            for trial in study.trials:
                if trial.state != TrialState.COMPLETE:
                    continue
                if trial.values is None:
                    continue
                if metric_index >= len(trial.values):
                    continue
                value = trial.values[metric_index]

                if value is None:
                    continue
                records.append(
                    {
                        "database": database_path,
                        "study": study,
                        "trial": trial,
                        "metric_index": metric_index,
                        "metric_name": metric_name,
                    }
                )
        return records

    def _selected_parameters(self):
        return [self.lstParameters.item(i).data(QtCore.Qt.UserRole) for i in range(self.lstParameters.count()) if self.lstParameters.item(i).isSelected()]

    # ==============================================================
    # D A T A F R A M E
    # ==============================================================

    def _build_dataframe(self, metric_name, records=None):

        if records is None:
            records = self._collect_trials(metric_name)
        if not records:
            raise ValueError("No COMPLETE trials were found " "for the selected metric.")
        selected_parameters = self._selected_parameters()
        if not selected_parameters:
            raise ValueError("Select at least one parameter.")

        rows = []
        # ----------------------------------------------------------
        # Build one row per trial
        # ----------------------------------------------------------

        for record in records:
            trial = record["trial"]
            row = {}

            # ------------------------------------------------------
            # Features
            #
            # Missing parameters are deliberately left as NaN.
            # They are converted later during dataframe cleanup.
            # ------------------------------------------------------
            for parameter_name in selected_parameters:
                row[parameter_name] = trial.params.get(parameter_name, float("nan"))
            # ------------------------------------------------------
            # Target
            # ------------------------------------------------------
            metric_index = record["metric_index"]
            row[metric_name] = trial.values[metric_index]
            rows.append(row)
        dataframe = pd.DataFrame(rows)

        if dataframe.empty:
            raise ValueError("The generated dataframe is empty.")

        # ----------------------------------------------------------
        # Convert feature columns to numeric values.
        #
        # XGBoost regression requires numeric features.
        #
        # Numeric Optuna parameters remain unchanged.
        # Non-numeric values are converted to NaN and subsequently
        # replaced with 0.0 as required by the dataset workflow.
        # ----------------------------------------------------------

        feature_columns = [name for name in selected_parameters]

        for column in feature_columns:
            dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")
        dataframe[metric_name] = pd.to_numeric(dataframe[metric_name], errors="coerce")

        # ----------------------------------------------------------
        # Fill missing values
        # ----------------------------------------------------------

        dataframe = dataframe.fillna(0.0)

        # ----------------------------------------------------------
        # Remove rows with invalid target values.
        #
        # Target cannot meaningfully be NaN or infinite.
        # ----------------------------------------------------------

        dataframe = dataframe[dataframe[metric_name].notna()]

        dataframe = dataframe[dataframe[metric_name].replace([float("inf"), float("-inf")], float("nan")).notna()]
        if dataframe.empty:
            raise ValueError("No valid target values remain " "after dataframe cleanup.")
        return dataframe

    # ==============================================================
    # T R A I N
    # ==============================================================

    def calculate_r2(y_true, y_pred):
        ss_res = np.sum((y_true - y_pred) ** 2)
        ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)

        if ss_tot <= 1e-12:
            return 0.0

        return 1.0 - (ss_res / ss_tot)

    def _train_all_models(self):
        self.models = {}
        summary = []

        progress = QtWidgets.QProgressDialog("Training models...", "Cancel", 0, len(self.metric_names), self)
        progress.setWindowTitle("XGBoost")
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.show()

        for i, metric_name in enumerate(self.metric_names):
            progress.setValue(i)
            progress.setLabelText(f"Training:\n{metric_name}")
            QtWidgets.QApplication.processEvents()

            result = self._train_model(metric_name)
            if progress.wasCanceled():
                break

            if result is not None:
                top_features = sorted(result["feature_importance"].items(), key=lambda x: x[1], reverse=True)[:5]
                top_text = "\n".join(f"  {name}:        {value:.1f}%" for name, value in top_features)

                summary.append(
                    f"{metric_name}\n"
                    f"Samples: {result['samples']}\n"
                    f"Features: {len(result['feature_names'])}\n"
                    f"Train/Test: {result['train_rows']} / {result['test_rows']}\n"
                    f"R²: {result['r2']:.4f}\n"
                    f"RMSE: {result['rmse']:.6g}\n"
                    f"Top Features:\n{top_text}"
                )

        progress.setValue(len(self.metric_names))

        if summary:
            QtWidgets.QMessageBox.information(
                self,
                "Training Complete",
                "\n\n".join(summary),
            )

    def _train_model(self, metric_name):
        try:

            # ------------------------------------------------------
            # Validate
            # ------------------------------------------------------
            if not self.database_paths:
                raise ValueError("Add at least one Optuna database.")
            if not self.studies:
                raise ValueError("No Optuna studies are loaded.")

            if not metric_name:
                raise ValueError("Select a training metric.")

            selected_parameters = self._selected_parameters()
            if not selected_parameters:
                raise ValueError("Select at least one parameter.")

            # ------------------------------------------------------
            # Collect trials
            # ------------------------------------------------------

            records = self._collect_trials(metric_name)

            if not records:
                raise ValueError("No COMPLETE trials were found " "for the selected metric.")

            # ------------------------------------------------------
            # Build dataframe
            # ------------------------------------------------------
            dataframe = self._build_dataframe(metric_name, records)
            feature_names = list(selected_parameters)
            X = dataframe[feature_names]
            y = dataframe[metric_name]
            # ------------------------------------------------------
            # Check sample count
            # ------------------------------------------------------
            if len(dataframe) < 2:
                raise ValueError("At least two samples are required " "for train/test splitting.")
            test_fraction = self.spinTestFraction.value()
            if len(dataframe) * (1.0 - test_fraction) < 1:
                raise ValueError("Test fraction leaves no training rows.")
            if len(dataframe) * test_fraction < 1:
                raise ValueError("Test fraction leaves no test rows.")

            # ------------------------------------------------------
            # ------------------------------------------------------
            # Shuffle dataset
            # ------------------------------------------------------

            df = dataframe.sample(frac=1.0, random_state=42).reset_index(drop=True)
            # ------------------------------------------------------
            # Split index
            # ------------------------------------------------------
            split_index = int(len(df) * (1.0 - test_fraction))
            if split_index <= 0:
                raise ValueError("No training rows.")
            if split_index >= len(df):
                raise ValueError("No test rows.")
            # ------------------------------------------------------
            # Train dataframe
            # ------------------------------------------------------
            train_df = df.iloc[:split_index]
            # ------------------------------------------------------
            # Test dataframe
            # ------------------------------------------------------
            test_df = df.iloc[split_index:]
            # ------------------------------------------------------
            # Build X/y
            # ------------------------------------------------------
            X_train = train_df[feature_names]
            y_train = train_df[metric_name]

            X_test = test_df[feature_names]
            y_test = test_df[metric_name]

            # ------------------------------------------------------
            # XGBoost
            # ------------------------------------------------------

            dtrain = xgboost.DMatrix(
                X_train,
                label=y_train,
                feature_names=feature_names,
            )
            dtest = xgboost.DMatrix(
                X_test,
                label=y_test,
                feature_names=feature_names,
            )

            params = {
                "objective": "reg:squarederror",
                "max_depth": self.spinDepth.value(),
                "eta": self.spinLearningRate.value(),
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "min_child_weight": 3,
                "seed": 42,
            }

            # evals = [
            #     (dtrain, "train"),
            #     (dtest, "test"),
            # ]

            evals = [(dtest, "validation")]

            model = xgboost.train(
                params,
                dtrain,
                num_boost_round=self.spinTrees.value(),
                evals=evals,
                early_stopping_rounds=50,
                verbose_eval=False,
            )

            self._set_status("Training XGBoost model...")
            QtWidgets.QApplication.processEvents()

            predictions = model.predict(dtest)
            # RMSE
            rmse = np.sqrt(np.mean((y_test.to_numpy() - predictions) ** 2))
            # R²
            y_true = y_test.to_numpy()
            ss_res = np.sum((y_true - predictions) ** 2)
            ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
            if ss_tot <= 1e-12:
                r2 = 0.0
            else:
                r2 = 1.0 - (ss_res / ss_tot)

            # ------------------------------------------------------
            # Store model state
            # ------------------------------------------------------

            self.created_from_databases = [os.path.abspath(path) for path in self.database_paths]

            importance = model.get_score(importance_type="gain")
            if importance:
                total = sum(importance.values())
                importance_percent = {feature: 100.0 * importance.get(feature, 0.0) / total if total > 0.0 else 0.0 for feature in feature_names}
            else:
                importance_percent = {feature: 0.0 for feature in feature_names}

            # ------------------------------------------------------
            # Top 20% trials
            # ------------------------------------------------------

            top_fraction = 0.20
            sorted_df = dataframe.sort_values(
                by=metric_name,
                ascending=False,  # maximera metric
            )

            top_count = max(1, int(len(sorted_df) * top_fraction))
            top_df = sorted_df.iloc[:top_count]

            # ------------------------------------------------------
            # Bounds från bästa 20%
            # ------------------------------------------------------
            parameter_bounds = {}
            for feature in feature_names:
                parameter_bounds[feature] = {
                    "global_min": float(dataframe[feature].min()),
                    "global_max": float(dataframe[feature].max()),
                    "top20_min": float(top_df[feature].quantile(0.05)),
                    "top20_max": float(top_df[feature].quantile(0.95)),
                }

            model_info = {
                "metric_name": metric_name,
                "model": model,
                "rmse": rmse,
                "r2": r2,
                "samples": len(dataframe),
                "train_rows": len(X_train),
                "test_rows": len(X_test),
                "feature_names": feature_names,
                "feature_importance": importance_percent,
                "parameter_bounds": parameter_bounds,
            }
            self.models[metric_name] = model_info

            # ------------------------------------------------------
            # Results
            # ------------------------------------------------------

            self.lblRMSE.setText(f"{rmse:.8g}")
            self.lblR2.setText(f"{r2:.8g}")
            self._update_statistics(model_info)
            self._set_status("Model training completed successfully.")
            self._update_button_state()

            return model_info

        except Exception as exc:
            self._show_error("Model training failed.", exc)
            return None

    # ==============================================================
    # S A V E   M O D E L
    # ==============================================================

    def _save_models(self):
        if not self.models:
            self._show_error("No trained models are available.\n\n" "Train one or more models before saving.")
            return
        try:

            # --------------------------------------------------
            # Active document must be saved
            # --------------------------------------------------
            doc = App.ActiveDocument
            if not doc or not doc.FileName:
                raise ValueError("Please save the FreeCAD document first.")
            # --------------------------------------------------
            # Output folder = document folder
            # --------------------------------------------------
            output_dir = os.path.dirname(doc.FileName)
            saved_files = []
            # --------------------------------------------------
            # Save every trained model
            # --------------------------------------------------
            for metric_name, model_info in self.models.items():
                model = model_info["model"]
                safe_name = metric_name
                for ch in '\\/:*?"<>|':
                    safe_name = safe_name.replace(ch, "_")

                doc_name = os.path.splitext(os.path.basename(doc.FileName))[0]
                model_path = os.path.join(output_dir, f"{doc_name}_xgboost_{safe_name}.json")
                meta_path = os.path.join(output_dir, f"{doc_name}_xgboost_{safe_name}.meta.json")

                # model_path = os.path.join(output_dir, f"xgboost_{safe_name}.json")
                # meta_path = os.path.join(output_dir, f"xgboost_{safe_name}.meta.json")
                # ----------------------------------------------
                # Save model
                # ----------------------------------------------

                model.save_model(model_path)

                # ----------------------------------------------
                # Metadata
                # ----------------------------------------------

                metadata = {
                    "metric_name": metric_name,
                    "features": model_info["feature_names"],
                    "created_from_databases": list(self.created_from_databases),
                    "samples": model_info["samples"],
                    "train_rows": model_info["train_rows"],
                    "test_rows": model_info["test_rows"],
                    "rmse": model_info["rmse"],
                    "r2": model_info["r2"],
                    "feature_importance_percent": model_info["feature_importance"],
                    "xgboost_version": getattr(xgboost, "__version__", None),
                    "model_settings": {
                        "n_estimators": self.spinTrees.value(),
                        "max_depth": self.spinDepth.value(),
                        "learning_rate": self.spinLearningRate.value(),
                        "test_fraction": self.spinTestFraction.value(),
                    },
                    "parameter_bounds": model_info["parameter_bounds"],
                }

                with open(meta_path, "w", encoding="utf-8") as handle:
                    json.dump(metadata, handle, indent=4, ensure_ascii=False)
                saved_files.append(os.path.basename(model_path))
            # --------------------------------------------------
            # Finished
            # --------------------------------------------------
            self._set_status(f"Saved {len(saved_files)} model(s)\n" f"{output_dir}")
            QtWidgets.QMessageBox.information(
                self,
                "Models Saved",
                (f"Saved {len(saved_files)} model(s)\n\n" f"Folder:\n{output_dir}"),
            )

        except Exception as exc:
            self._show_error(
                "Could not save models.",
                exc,
            )

    # ==============================================================
    # H E L P E R S
    # ==============================================================

    @staticmethod
    def _float_from_label(text):

        if not text or text == "-":
            return None

        try:
            return float(text)

        except (TypeError, ValueError):
            return None

    def _update_statistics(self, model_info=None):
        if model_info is None:
            self.lblSamples.setText("0")
            self.lblFeatures.setText(str(len(self._selected_parameters())))
            self.lblTrainRows.setText("0")
            self.lblTestRows.setText("0")
            return

        self.lblSamples.setText(str(model_info["samples"]))
        self.lblFeatures.setText(str(len(model_info["feature_names"])))
        self.lblTrainRows.setText(str(model_info["train_rows"]))
        self.lblTestRows.setText(str(model_info["test_rows"]))

    def _update_button_state(self):
        has_databases = bool(self.database_paths)
        has_studies = bool(self.studies)
        has_parameters = bool(self._selected_parameters())

        self.btnTrainAll.setEnabled(has_databases and has_studies and has_parameters)
        self.btnSave.setEnabled(bool(self.models))
        self.btnRemoveDB.setEnabled(self.lstDatabases.count() > 0)
        self.btnClearDB.setEnabled(self.lstDatabases.count() > 0)
        self.btnSelectAll.setEnabled(self.lstParameters.count() > 0)
        self.btnClearParameters.setEnabled(self.lstParameters.count() > 0)

    def _set_status(self, text):
        self.lblStatus.setText(str(text))

    def _show_error(self, message, exc=None):
        if exc is not None:
            details = f"{message}\n\n" f"{exc}"
            # Logga detaljer till FreeCAD console
            try:
                App.Console.PrintError(f"{message}\n{exc}\n")
                App.Console.PrintError(traceback.format_exc())
            except Exception:
                pass
        else:
            details = message

        QtWidgets.QMessageBox.critical(self, "XGBoost Training", details)


# ==================================================================
# C R E A T O R
# ==================================================================


def OBA_CreateXGBoostTrainingDialog(parent=None, show_dialog=True):
    """
    Create and optionally show the standalone XGBoost training dialog.
    This function does NOT create a FeaturePython object.
    Example from a FreeCAD workbench command:
        dialog = OBA_CreateXGBoostTrainingDialog()
    Or:
        dialog = OBA_CreateXGBoostTrainingDialog(
            parent=Gui.getMainWindow()
        )
    """

    # --------------------------------------------------------------
    # Use FreeCAD main window when available.
    # --------------------------------------------------------------

    if parent is None:
        try:
            if App.GuiUp:
                import FreeCADGui as Gui

                parent = Gui.getMainWindow()
        except Exception:
            parent = None

    # --------------------------------------------------------------
    # Create dialog
    # --------------------------------------------------------------

    dialog = XGBoostTrainingDialog(parent=parent)

    # --------------------------------------------------------------
    # Show
    # --------------------------------------------------------------

    if show_dialog:
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
    return dialog


# ==================================================================
# O P E N   W I N D O W
# ==================================================================


def open_xgboost_training_dialog():
    """
    Convenience function for a FreeCAD workbench command.

    Example:

        open_xgboost_training_dialog()
    """

    return OBA_CreateXGBoostTrainingDialog(show_dialog=True)
