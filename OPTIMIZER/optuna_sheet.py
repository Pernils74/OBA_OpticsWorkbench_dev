# -*- coding: utf-8 -*-
import optuna
import os
import FreeCAD as App
from PySide import QtCore, QtWidgets, QtGui

from oba_objects.oba_base import _trigger_ray_engine
from .spreadsheet_utils import apply_cad_params
from .optimize_worker import DB_PATH
from .evaluation_service import EvaluationService


class OptunaVerificationSheet(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Optuna Verification Sheet")
        self.resize(1100, 700)

        self.study = None
        self.trials = []
        self.metric_names = []
        self.debug_columns = ["cluster_count", "total_hits", "scene_hash"]

        self._eval_service = EvaluationService()
        self._eval_service.evaluationReady.connect(self._on_evaluation_ready)
        self._eval_service.statusChanged.connect(self._on_status_changed)

        self._waiting_for_evaluation = False
        self._current_trial = None
        self._current_row = None
        self._current_study_name = None
        self._saved_run_mode = None

        self._build_ui()
        self._load_study_list()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QHBoxLayout()
        self.cmbStudy = QtWidgets.QComboBox()
        self.btnReload = QtWidgets.QPushButton("Reload")
        self.btnVerifySelected = QtWidgets.QPushButton("Verify Selected")
        self.btnVerifyAll = QtWidgets.QPushButton("Verify All Trials")
        self.lblStatus = QtWidgets.QLabel("Ready")

        top.addWidget(QtWidgets.QLabel("Study:"))
        top.addWidget(self.cmbStudy)
        top.addWidget(self.btnReload)
        top.addWidget(self.btnVerifySelected)
        top.addWidget(self.btnVerifyAll)
        top.addStretch()
        top.addWidget(self.lblStatus)

        root.addLayout(top)

        self.table = QtWidgets.QTableWidget()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.doubleClicked.connect(self._on_row_double_clicked)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

        self.btnReload.clicked.connect(self._load_study_list)
        self.cmbStudy.currentIndexChanged.connect(self._on_study_changed)
        self.btnVerifySelected.clicked.connect(self._verify_selected)
        self.btnVerifyAll.clicked.connect(self._verify_all)

    def _enable_manual_raytrace_mode(self):
        doc = App.ActiveDocument
        if not doc:
            return
        cfg = doc.getObject("OBARayConfig")
        if not cfg:
            return
        self._saved_run_mode = getattr(cfg, "RunMode", None)
        cfg.RunMode = "MANUAL"

    def _restore_manual_raytrace_mode(self):
        doc = App.ActiveDocument
        if not doc:
            return
        cfg = doc.getObject("OBARayConfig")
        if not cfg:
            return
        if self._saved_run_mode is not None:
            cfg.RunMode = self._saved_run_mode
            self._saved_run_mode = None

    def _trigger_manual_ray_trace(self):
        _trigger_ray_engine(reason="optuna_sheet_restore", source=None, force=True)

    def _load_study_list(self):
        try:
            summaries = optuna.study.get_all_study_summaries(storage=DB_PATH)
            names = [s.study_name for s in summaries]
        except Exception as e:
            names = []
            App.Console.PrintError(f"[OptunaSheet] Failed to load studies: {e}\n")

        self.cmbStudy.blockSignals(True)
        self.cmbStudy.clear()
        self.cmbStudy.addItems(names)
        self.cmbStudy.blockSignals(False)

        if names:
            self.cmbStudy.setCurrentIndex(0)
            self._on_study_changed()
        else:
            self._clear_table()

    def _clear_table(self):
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.trials = []
        self.metric_names = []

    def _on_study_changed(self):
        study_name = self.cmbStudy.currentText()
        if not study_name:
            self._clear_table()
            return

        self._load_study(study_name)

    def _load_study(self, study_name):
        try:
            study = optuna.load_study(study_name=study_name, storage=DB_PATH)
        except Exception as e:
            App.Console.PrintError(f"[OptunaSheet] Failed to open study '{study_name}': {e}\n")
            self._clear_table()
            return

        self.study = study
        self._current_study_name = study_name
        self.metric_names = study.user_attrs.get("metric_names") or []

        if not self.metric_names:
            all_metrics = study.user_attrs.get("all_metrics")
            if all_metrics:
                self.metric_names = all_metrics
            elif study.trials:
                sample = study.trials[0].user_attrs.get("metrics", {})
                self.metric_names = list(sample.keys())

        self.trials = [t for t in study.trials if t.state.name == "COMPLETE"]
        self._populate_table()

    def _populate_table(self):
        headers = [
            "Trial",
            "State",
            "Stored Objective",
            "Stored Params",
        ]

        for name in self.metric_names:
            headers.extend(
                [
                    f"Stored_{name}",
                    f"Actual_{name}",
                    f"Diff_{name}",
                ]
            )

        for debug_key in self.debug_columns:
            headers.extend(
                [
                    f"Stored_{debug_key}",
                    f"Actual_{debug_key}",
                    f"Diff_{debug_key}",
                ]
            )

        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(self.trials))

        for row, trial in enumerate(self.trials):
            self._set_trial_row(row, trial)

        self.table.resizeColumnsToContents()

    def _set_trial_row(self, row, trial, actual=None, diffs=None):
        state = trial.state.name
        objective = tuple(trial.values) if trial.values is not None else None
        params = trial.params or {}
        stored_metrics = trial.user_attrs.get("metrics", {})
        debug_info = trial.user_attrs.get("debug", {})

        self._set_item(row, 0, str(trial.number))
        self._set_item(row, 1, state)
        self._set_item(row, 2, str(objective))
        self._set_item(row, 3, str(params))

        max_diff = 0.0
        for metric_index, name in enumerate(self.metric_names):
            stored_value = stored_metrics.get(name)
            actual_value = None
            diff_value = None
            if actual and name in actual:
                actual_value = actual[name]
                diff_value = self._compute_diff(stored_value, actual_value)
                max_diff = max(max_diff, abs(diff_value) if diff_value is not None else 0.0)

            base = 4 + metric_index * 3
            self._set_item(row, base, self._format_value(stored_value))
            self._set_item(row, base + 1, self._format_value(actual_value))
            self._set_item(row, base + 2, self._format_value(diff_value))

        debug_base = 4 + len(self.metric_names) * 3
        for debug_index, debug_key in enumerate(self.debug_columns):
            stored_value = debug_info.get(debug_key)
            actual_value = None
            diff_value = None
            if actual and debug_key in actual:
                actual_value = actual[debug_key]
                diff_value = self._compute_diff(stored_value, actual_value)
                max_diff = max(max_diff, abs(diff_value) if diff_value is not None else 0.0)

            base = debug_base + debug_index * 3
            self._set_item(row, base, self._format_value(stored_value))
            self._set_item(row, base + 1, self._format_value(actual_value))
            self._set_item(row, base + 2, self._format_value(diff_value))

        self._set_row_color(row, max_diff)

    def _set_item(self, row, col, value):
        item = QtWidgets.QTableWidgetItem("" if value is None else str(value))
        item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
        self.table.setItem(row, col, item)

    def _format_value(self, value):
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)

    def _compute_diff(self, stored, actual):
        if stored is None or actual is None:
            return None
        try:
            stored = float(stored)
            actual = float(actual)
            return actual - stored
        except Exception:
            return 0 if stored == actual else 1

    def _set_row_color(self, row, diff):
        if diff is None:
            return
        color = None
        if abs(diff) < 1e-6:
            color = QtGui.QColor("#c6efce")
        elif abs(diff) < 0.01:
            color = QtGui.QColor("#fff2cc")
        else:
            color = QtGui.QColor("#f8cbad")

        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                item.setBackground(color)

    def _on_row_double_clicked(self, index):
        row = index.row()
        if row < 0 or row >= len(self.trials):
            return
        trial = self.trials[row]
        self._restore_trial(trial)

    def _restore_trial(self, trial):
        params = dict(trial.params)
        params.update(trial.user_attrs.get("unselected_params", {}))
        self._enable_manual_raytrace_mode()
        try:
            apply_cad_params(params)
            doc = App.ActiveDocument
            if doc:
                doc.recompute()
            self._trigger_manual_ray_trace()
            self.lblStatus.setText(f"Restored trial {trial.number}")
        finally:
            self._restore_manual_raytrace_mode()

    def _verify_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.trials):
            return
        self._verify_trial(row)

    def _verify_all(self):
        self._verify_all_trials()

    def _verify_trial(self, row):
        trial = self.trials[row]
        if self._waiting_for_evaluation:
            return
        self._current_trial = trial
        self._current_row = row
        self._evaluate_trial(trial)

    def _verify_all_trials(self):
        if self._waiting_for_evaluation:
            return
        self._pending_rows = list(range(len(self.trials)))
        self._verify_next_pending()

    def _verify_next_pending(self):
        print("remaining:", len(self._pending_rows))
        if not self._pending_rows:
            self.lblStatus.setText("Verify all complete")
            return
        row = self._pending_rows.pop(0)
        print("VERIFYING ROW", row)
        self._verify_trial(row)

    def _evaluate_trial(self, trial):
        try:
            params = dict(trial.params)
            params.update(trial.user_attrs.get("unselected_params", {}))

            metric_config = self.study.user_attrs.get("metric_config", [])

            if not metric_config:
                raise RuntimeError("Missing metric_config on study")

            payload = {
                "trial_id": trial.number,
                "params": params,
                "unselected_params": trial.user_attrs.get("unselected_params", {}),
                "metrics": metric_config,
            }

            self._waiting_for_evaluation = True

            self._enable_manual_raytrace_mode()

            self._eval_service.evaluate(payload)

            self.lblStatus.setText(f"Verifying trial {trial.number}")

        except Exception as e:

            App.Console.PrintError(f"[Verify] Trial {trial.number} failed: {e}\n")

            self._waiting_for_evaluation = False

            self._restore_manual_raytrace_mode()

            if hasattr(self, "_pending_rows") and self._pending_rows:
                QtCore.QTimer.singleShot(
                    0,
                    self._verify_next_pending,
                )

    def _on_evaluation_ready(self, result):

        print(
            "[VERIFY DONE]",
            self._current_trial.number if self._current_trial else "None",
        )

        self._waiting_for_evaluation = False

        try:

            if not self._current_trial or self._current_row is None:
                return

            if result.get("_pruned"):
                print(f"[VERIFY] Trial " f"{self._current_trial.number} " f"returned PRUNED")

            actual_results = result.get("results", {}).copy()
            actual_results.update(result.get("debug", {}))

            self._set_trial_row(
                self._current_row,
                self._current_trial,
                actual=actual_results,
            )

            self.lblStatus.setText(f"Verified trial " f"{self._current_trial.number}")

        except Exception as e:

            App.Console.PrintError(f"[VERIFY] Failed processing result " f"for trial " f"{self._current_trial.number if self._current_trial else 'Unknown'}: " f"{e}\n")

        finally:

            self._restore_manual_raytrace_mode()

            if hasattr(self, "_pending_rows") and self._pending_rows:
                QtCore.QTimer.singleShot(
                    0,
                    self._verify_next_pending,
                )
            else:
                self._current_trial = None
                self._current_row = None
                self.lblStatus.setText("Verify all complete")

    def _on_status_changed(self, status):
        self.lblStatus.setText(status)

    def closeEvent(self, event):
        self._restore_manual_raytrace_mode()
        super().closeEvent(event)


_windows = []


def open_optuna_sheet():
    w = OptunaVerificationSheet()
    _windows.append(w)
    w.show()
    w.raise_()
    return w
