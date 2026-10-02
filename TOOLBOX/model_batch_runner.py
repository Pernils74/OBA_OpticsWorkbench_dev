# model_batch_runner.py

import glob
import json
import os


import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from OPTIMIZER.optimize_config import SPREADSHEET_NAME
from OPTIMIZER.optuna_bounds_editor import load_model_data_into_spreadsheet


class ModelBatchRunner(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setWindowTitle("Model Batch Runner")
        self.setMinimumSize(540, 520)

        self._document_name = None
        self._optimizer = None
        self._selected_models = []
        self._model_index = 0
        self._trial_count = 500
        self._running = False
        self._cancel_requested = False
        self._close_when_finished = False
        self._preferences = App.ParamGet("User parameter:BaseApp/Preferences/OBA/ModelBatchRunner")

        self._build_ui()
        self._load_models()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        info = QtWidgets.QFormLayout()
        self.document_label = QtWidgets.QLabel("No active document")
        self.directory_label = QtWidgets.QLabel("-")
        self.directory_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        info.addRow("Active document:", self.document_label)
        info.addRow("Model directory:", self.directory_label)
        layout.addLayout(info)

        trials_row = QtWidgets.QHBoxLayout()
        trials_row.addWidget(QtWidgets.QLabel("Trials per model:"))
        self.trials_spin = QtWidgets.QSpinBox()
        self.trials_spin.setRange(1, 1_000_000)
        self.trials_spin.setSingleStep(50)
        self.trials_spin.setValue(self._preferences.GetInt("TrialsPerModel", 500))
        trials_row.addWidget(self.trials_spin)
        trials_row.addStretch(1)
        layout.addLayout(trials_row)

        bounds_row = QtWidgets.QHBoxLayout()
        bounds_row.addWidget(QtWidgets.QLabel("Min %:"))
        self.min_percent_spin = QtWidgets.QDoubleSpinBox()
        self.min_percent_spin.setRange(-100000.0, 100000.0)
        self.min_percent_spin.setDecimals(2)
        self.min_percent_spin.setSingleStep(10.0)
        self.min_percent_spin.setValue(self._preferences.GetFloat("MinPercent", -20.0))
        self.min_percent_spin.setSuffix(" %")
        self.min_percent_spin.setMaximumWidth(110)
        bounds_row.addWidget(self.min_percent_spin)
        bounds_row.addSpacing(16)
        bounds_row.addWidget(QtWidgets.QLabel("Max %:"))
        self.max_percent_spin = QtWidgets.QDoubleSpinBox()
        self.max_percent_spin.setRange(-100000.0, 100000.0)
        self.max_percent_spin.setDecimals(2)
        self.max_percent_spin.setSingleStep(10.0)
        self.max_percent_spin.setValue(self._preferences.GetFloat("MaxPercent", 20.0))
        self.max_percent_spin.setSuffix(" %")
        self.max_percent_spin.setMaximumWidth(110)
        bounds_row.addWidget(self.max_percent_spin)
        bounds_row.addStretch(1)
        layout.addLayout(bounds_row)

        self.model_list = QtWidgets.QListWidget()
        layout.addWidget(self.model_list, 1)

        self.status_label = QtWidgets.QLabel("Choose model files to run.")
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)

        buttons = QtWidgets.QHBoxLayout()
        self.select_all_button = QtWidgets.QPushButton("Select All")
        self.select_none_button = QtWidgets.QPushButton("Select None")
        self.run_button = QtWidgets.QPushButton("Run Selected")
        self.close_button = QtWidgets.QPushButton("Close")
        self.run_button.setStyleSheet("QPushButton { background-color: #176b5b; color: white; font-weight: 600; padding: 5px 10px; }")
        buttons.addWidget(self.select_all_button)
        buttons.addWidget(self.select_none_button)
        buttons.addStretch(1)
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.select_all_button.clicked.connect(self._select_all)
        self.select_none_button.clicked.connect(self._select_none)
        self.run_button.clicked.connect(self._run_selected)
        self.close_button.clicked.connect(self._close_or_stop)
        self.trials_spin.valueChanged.connect(self._save_preferences)
        self.min_percent_spin.valueChanged.connect(self._save_preferences)
        self.max_percent_spin.valueChanged.connect(self._save_preferences)

    def _save_preferences(self, *_args):
        self._preferences.SetInt("TrialsPerModel", self.trials_spin.value())
        self._preferences.SetFloat("MinPercent", self.min_percent_spin.value())
        self._preferences.SetFloat("MaxPercent", self.max_percent_spin.value())

    def _load_models(self):
        doc = App.ActiveDocument
        if not doc:
            self.run_button.setEnabled(False)
            self.status_label.setText("Open a FreeCAD document first.")
            return

        self._document_name = doc.Name
        document_path = getattr(doc, "FileName", "")
        directory = os.path.dirname(document_path) if document_path else ""
        document_name = os.path.basename(document_path) if document_path else doc.Label
        self.document_label.setText(document_name)
        self.directory_label.setText(directory or "Save the active document to select its model directory.")

        if not directory:
            self.run_button.setEnabled(False)
            self.status_label.setText("The active document must be saved before scanning for models.")
            return

        paths = sorted(glob.glob(os.path.join(directory, "*.model")), key=str.casefold)
        for path in paths:
            item = QtWidgets.QListWidgetItem(os.path.basename(path))
            item.setData(QtCore.Qt.UserRole, path)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            self.model_list.addItem(item)

        if not paths:
            self.status_label.setText("No .model files found beside the active document.")

    def _select_all(self):
        for row in range(self.model_list.count()):
            self.model_list.item(row).setCheckState(QtCore.Qt.Checked)

    def _select_none(self):
        for row in range(self.model_list.count()):
            self.model_list.item(row).setCheckState(QtCore.Qt.Unchecked)

    def _run_selected(self):
        if self._running:
            return

        self._selected_models = [self.model_list.item(row).data(QtCore.Qt.UserRole) for row in range(self.model_list.count()) if self.model_list.item(row).checkState() == QtCore.Qt.Checked]
        if not self._selected_models:
            self.status_label.setText("Select at least one model file.")
            return

        doc = App.ActiveDocument
        if not doc or doc.Name != self._document_name:
            self.status_label.setText("The active document changed. Reopen the batch runner.")
            return

        from OPTIMIZER import optimize_dialog

        self._optimizer = optimize_dialog.ShowOptimizeDialog()

        from TOOLBOX.oba_toolbox_base import set_spreadsheet_references

        for obj in doc.Objects:
            if hasattr(obj, "OpticalType"):
                set_spreadsheet_references(obj)

        if self._optimizer is None:
            self.status_label.setText("Could not open OptimizeDialog.")
            return
        if self._optimizer._running:
            self.status_label.setText("Stop the active optimization before starting a model batch.")
            return
        selected_params = [self._optimizer.listParams.item(i) for i in range(self._optimizer.listParams.count()) if self._optimizer.listParams.item(i).isSelected()]
        if not selected_params:
            self._optimizer.listParams.blockSignals(True)
            try:
                for i in range(self._optimizer.listParams.count()):
                    item = self._optimizer.listParams.item(i)
                    if item.flags() & QtCore.Qt.ItemIsSelectable:
                        item.setSelected(True)
            finally:
                self._optimizer.listParams.blockSignals(False)
            self._optimizer._on_params_changed()

        if not self._optimizer.listParams.selectedItems():
            self.status_label.setText("No Spreadsheet parameters are available to optimize.")
            return

        active_metrics = [metric for metric in self._optimizer.targetWeights.get_payload().get("entries", []) if metric.get("active", True)]
        if not active_metrics:
            self.status_label.setText("Configure at least one active optimization metric first.")
            return

        self._optimizer.batchProgress.connect(self._on_trial_progress)
        self._optimizer.batchFinished.connect(self._on_model_finished)
        self._trial_count = self.trials_spin.value()
        self._model_index = 0
        self._running = True
        self._cancel_requested = False
        self._set_controls_running(True)
        QtCore.QTimer.singleShot(0, self._run_next_model)

    def _run_next_model(self):
        if self._cancel_requested or self._model_index >= len(self._selected_models):
            self._finish_batch()
            return

        model_path = self._selected_models[self._model_index]
        model_name = os.path.basename(model_path)
        model_number = self._model_index + 1
        self.status_label.setText("Model {} / {}   Running: {}".format(model_number, len(self._selected_models), model_name))
        self.progress_bar.setRange(0, self._trial_count)
        self.progress_bar.setValue(0)

        doc = App.ActiveDocument
        sheet = doc.getObject(SPREADSHEET_NAME) if doc else None
        if not doc or doc.Name != self._document_name or not sheet:
            self._stop_on_error("The active document or Spreadsheet is no longer available.")
            return

        try:
            with open(model_path, "r", encoding="utf-8") as model_file:
                model_data = json.load(model_file)
            loaded, missing_aliases = load_model_data_into_spreadsheet(
                model_data,
                sheet,
                min_percent=self.min_percent_spin.value(),
                max_percent=self.max_percent_spin.value(),
            )
            if not loaded:
                raise ValueError("No model parameters matched the Spreadsheet aliases.")
            doc.recompute()
            if missing_aliases:
                App.Console.PrintWarning("[Model Batch Runner] Unmatched aliases in {}: {}\n".format(model_name, ", ".join(missing_aliases)))

            self._optimizer.spinTrials.setValue(self._trial_count)
            self._optimizer._start_optimization(
                new_study=True,
                study_name_prefix=model_path,
            )
            if not self._optimizer._running:
                raise RuntimeError("Optimization did not start. Check the Optimize panel configuration.")
        except Exception as exc:
            self._stop_on_error("{}: {}".format(model_name, exc))

    def _on_trial_progress(self, info):
        trial_number = int(info.get("trial", -1)) + 1
        self.progress_bar.setValue(min(trial_number, self._trial_count))
        model_name = os.path.basename(self._selected_models[self._model_index])
        self.status_label.setText(
            "Model {} / {}   Running: {}   Trial {} / {}".format(
                self._model_index + 1,
                len(self._selected_models),
                model_name,
                min(trial_number, self._trial_count),
                self._trial_count,
            )
        )

    def _on_model_finished(self, results):
        if self._cancel_requested:
            self._finish_batch()
            return

        try:
            applied = self._optimizer._select_best_trial(None)
            if not applied:
                raise RuntimeError("No completed best trial was available to apply.")
            doc = App.ActiveDocument
            if doc:
                doc.recompute()
        except Exception as exc:
            model_name = os.path.basename(self._selected_models[self._model_index])
            self._stop_on_error("Could not apply the best trial for {}: {}".format(model_name, exc))
            return

        self._model_index += 1
        QtCore.QTimer.singleShot(0, self._run_next_model)

    def _stop_on_error(self, message):
        self.status_label.setText("Batch stopped: {}".format(message))
        self._cancel_requested = True
        if self._optimizer and self._optimizer._running and self._optimizer._worker:
            self._optimizer._worker.request_stop()
        else:
            self._finish_batch()

    def _set_controls_running(self, running):
        self.model_list.setEnabled(not running)
        self.select_all_button.setEnabled(not running)
        self.select_none_button.setEnabled(not running)
        self.trials_spin.setEnabled(not running)
        self.run_button.setEnabled(not running)
        self.close_button.setText("Stop and Close" if running else "Close")

    def _close_or_stop(self):
        if self._running:
            self._cancel_requested = True
            self.status_label.setText("Stopping after the current trial...")
            if self._optimizer and self._optimizer._worker:
                self._optimizer._worker.request_stop()
            self._close_when_finished = True
            return
        self.close()

    def _finish_batch(self):
        if self._optimizer:
            for signal, slot in (
                (self._optimizer.batchProgress, self._on_trial_progress),
                (self._optimizer.batchFinished, self._on_model_finished),
            ):
                try:
                    signal.disconnect(slot)
                except Exception:
                    pass

        self._running = False
        self._set_controls_running(False)
        if self._cancel_requested:
            self.status_label.setText("Batch stopped.")
        else:
            self.progress_bar.setValue(self._trial_count)
            self.status_label.setText("Batch finished: {} model(s).".format(self._model_index))
        if self._close_when_finished:
            self.close()

    def closeEvent(self, event):
        if self._running:
            self._close_when_finished = True
            self._close_or_stop()
            event.ignore()
            return
        super().closeEvent(event)


_model_batch_runner = None


def show_model_batch_runner(parent=None):
    global _model_batch_runner
    if _model_batch_runner is not None and _model_batch_runner.isVisible():
        _model_batch_runner.raise_()
        _model_batch_runner.activateWindow()
        return _model_batch_runner

    _model_batch_runner = ModelBatchRunner(parent=parent)
    _model_batch_runner.show()
    _model_batch_runner.raise_()
    _model_batch_runner.activateWindow()
    return _model_batch_runner
