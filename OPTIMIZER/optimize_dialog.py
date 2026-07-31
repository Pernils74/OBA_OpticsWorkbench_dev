# -*- coding: utf-8 -*-

# optimize_dialog.py


import os


import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets, QtGui

import json

import numpy as np

from .optimize_worker import OptimizationWorker
from .spreadsheet_utils import read_param_bounds, get_param_info

# from oba_plots.cluster_plot import ShowClusterPlotDialog
# from .optimize_dialog_edit_targets import EditTargetsDialog

from oba_objects.oba_base import _trigger_ray_engine
from .spreadsheet_utils import apply_cad_params
from oba_rayengine.oba_ray_analyser import aggregate_interaction_clusters

from .target_weights_widget import TargetWeightsWidget
from .optimize_config import SPREADSHEET_NAME

# from .evaluation_service import EvaluationService

icon_path = os.path.join(os.path.dirname(__file__), "..", "icons")


import optuna
from .optimize_worker import DB_PATH  # ✅ också

DOCK_OBJECT_NAME = "OptimizeDialogDock"
_optimize_dock_instance = None

from .evaluation_service import EvaluationService, compute_baseline


class OptimizeDialogDock(QtWidgets.QDockWidget):

    startRequested = QtCore.Signal(dict)
    studyCreated = QtCore.Signal(dict)

    def __init__(self, parent=None, params_info=None):
        super().__init__("Optimize", parent)
        self._thread = None
        self._worker = None

        self._running = False
        self._paused = False

        self._dirty = False

        self._current_study_name = None
        self._cached_study = None
        self._last_study_name = None
        self._last_applied_trial = None

        self._debounce_timer = QtCore.QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._run_debounced_selection)

        self._pending_payload = None

        self._evaluation_active = False
        self._optuna_plot_window = None

        self._build_ui(params_info)
        self._refresh_config_list()

        config = self._load_config()
        if config:
            self._apply_config(config)

    def _setup_worker(self):
        print("SETUP WORKER")
        print("connect stop ->", id(self._worker))

        self._thread = QtCore.QThread(self)

        self._worker = OptimizationWorker()
        self._worker.moveToThread(self._thread)

        print("CONNECT STOP")

        self.startRequested.connect(self._worker.start)
        # self.stopRequested.connect(self._worker.stop)
        self._worker.requestEvaluate.connect(self._evaluate_main)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def _build_ui(self, params_info):
        w = QtWidgets.QWidget()
        self.setWidget(w)

        layout = QtWidgets.QVBoxLayout(w)

        # --- parametrar ---
        self._build_param_list(layout, params_info)

        self.lblActiveStudy = QtWidgets.QLabel("Active study: —")
        self.lblActiveStudy.setWordWrap(True)
        self.lblActiveStudy.setMaximumWidth(300)
        layout.addWidget(self.lblActiveStudy)

        # --- sampler / parallel options ---
        samplerLayout = QtWidgets.QHBoxLayout()
        self.chkConstantLiar = QtWidgets.QCheckBox("Constant liar")
        self.chkConstantLiar.setChecked(True)
        self.cmbSampler = QtWidgets.QComboBox()
        self.cmbSampler.addItems(
            [
                "TPESampler",
                "RandomSampler",
                "CmaEsSampler",
                "NSGAIISampler",  # ✅ needed for multi-objective
            ]
        )
        samplerLayout.addWidget(QtWidgets.QLabel("Sampler:"))
        samplerLayout.addWidget(self.cmbSampler)
        samplerLayout.addSpacing(20)
        samplerLayout.addWidget(self.chkConstantLiar)
        samplerLayout.addStretch()
        layout.addLayout(samplerLayout)

        # --- trials control ---
        self.spinTrials = QtWidgets.QSpinBox()
        self.spinTrials.setRange(-1, 1_000_000)
        self.spinTrials.setValue(500)
        self.spinTrials.setSingleStep(50)

        # ✅ visa "∞" när -1
        self.spinTrials.setSpecialValueText("∞")

        samplerLayout.addWidget(QtWidgets.QLabel("Trials:"))
        samplerLayout.addWidget(self.spinTrials)
        samplerLayout.addStretch()

        # ✅ tillbaka med widget
        self.targetWeights = TargetWeightsWidget(self)
        self.targetWeights.configChanged.connect(self._on_metric_config_changed)
        layout.addWidget(self.targetWeights)

        self.btnOptunaPlot = self._make_button("Optuna-plot", "optuna_plot.svg")

        self.lblStatus = QtWidgets.QLabel("Status: idle")
        self.lblStatus.setStyleSheet("color: gray;")

        self.cmbConfig = QtWidgets.QComboBox()
        self.btnDeleteConfig = QtWidgets.QPushButton("🗑️")
        self.btnSaveConfig = QtWidgets.QPushButton("💾")
        self.btnNewConfig = QtWidgets.QPushButton("+")

        configRow = QtWidgets.QHBoxLayout()
        configRow.addWidget(QtWidgets.QLabel("Preset:"))
        configRow.addWidget(self.cmbConfig)
        configRow.addWidget(self.btnNewConfig)
        configRow.addWidget(self.btnDeleteConfig)
        configRow.addWidget(self.btnSaveConfig)
        configRow.addStretch()

        layout.insertLayout(0, configRow)

        self.btnStart = QtWidgets.QPushButton("Start")
        self.btnStart_new = QtWidgets.QPushButton("Start new")

        row = QtWidgets.QHBoxLayout()

        row.addWidget(self.btnOptunaPlot)
        row.addWidget(self.lblStatus)

        row.addStretch()
        row.addWidget(self.btnStart)
        row.addWidget(self.btnStart_new)

        layout.addLayout(row)

        self.btnStart.clicked.connect(self._on_start_stop)
        self.btnStart_new.clicked.connect(self._on_start_new)
        self.btnOptunaPlot.clicked.connect(self._open_optuna_plot_window)

        self.cmbConfig.currentTextChanged.connect(self._on_config_changed)
        self.btnNewConfig.clicked.connect(self._create_new_config)
        self.btnSaveConfig.clicked.connect(self._on_save_clicked)
        self.btnDeleteConfig.clicked.connect(self._delete_current_config)

    def _make_button(self, text, icon):
        btn = QtWidgets.QPushButton(text)
        p = os.path.join(os.path.dirname(__file__), "..", "icons", icon)
        btn.setIcon(QtGui.QIcon(p))
        return btn

    def _build_param_list(self, layout, params_info):
        self.listParams = QtWidgets.QListWidget()
        self.listParams.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.listParams.itemSelectionChanged.connect(self._on_params_changed)

        self.listParams.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.listParams.customContextMenuRequested.connect(self._on_param_context_menu)

        layout.addWidget(self.listParams)

        if params_info:
            for item in params_info:
                # ✅ stöd för nya dict-formatet
                if isinstance(item, dict):
                    name = item["name"]
                    row_type = item.get("type", "param")

                    if row_type == "header":
                        list_item = QtWidgets.QListWidgetItem(name)
                        list_item.setFlags(QtCore.Qt.NoItemFlags)  # ❌ ej valbar
                        list_item.setForeground(QtGui.QBrush(QtGui.QColor("gray")))
                        list_item.setForeground(QtGui.QBrush(QtGui.QColor("blue")))
                        font = list_item.font()
                        font.setBold(True)
                        font.setPointSize(12)
                        list_item.setFont(font)
                        self.listParams.addItem(list_item)
                    else:
                        self.listParams.addItem(name)

                else:
                    # fallback (gammalt tuple-format)
                    name = item[0]
                    self.listParams.addItem(name)

        # ✅ sizing
        row_height = self.listParams.sizeHintForRow(0)
        row_height = row_height if row_height > 0 else 20
        self.listParams.setMinimumHeight(row_height * 10)

    def _on_param_context_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        clear_action = menu.addAction("Rensa val")
        select_all_action = menu.addAction("Välj alla")

        action = menu.exec_(self.listParams.mapToGlobal(pos))

        if action == clear_action:
            self.listParams.clearSelection()
        elif action == select_all_action:
            for i in range(self.listParams.count()):
                self.listParams.item(i).setSelected(True)

    def _build_metrics_config(self, payload):
        metrics = []

        for e in payload["entries"]:
            name = e["base_metric"]
            plane = e["plane"]

            # ✅ unikt metric-id (väldigt viktigt senare)

            metric_name = f"{name}_{plane}"

            metrics.append(
                {
                    "name": metric_name,
                    "base_metric": name,
                    "type": e.get("type"),
                    "plane": plane,
                    "targets": e["targets"],
                    "direction": "maximize",  # default
                    "active": e.get("active", True),  # ✅ default active
                    "value": e.get("value", None),
                    "percent": e.get("percent", None),
                    "axis": e.get("axis", None),
                    "min": e.get("min", None),
                    "max": e.get("max", None),
                    "step_id": e.get("step_id", None),  # ✅ för scanner-metrics
                }
            )
        return metrics

    def _on_eval_status(self, text):
        self.lblStatus.setText(text)
        self.lblStatus.setStyleSheet("color: blue;")

    def _on_params_changed(self):

        params = [i.text() for i in self.listParams.selectedItems() if i.flags() & QtCore.Qt.ItemIsSelectable]
        # params = [i.text() for i in self.listParams.selectedItems()]

        if not params:
            self._current_study_name = None
            self.lblActiveStudy.setText("No params selected")
            return

        # ✅ generera study_name exakt som worker gör

        payload = self.targetWeights.get_payload()
        metrics = self._build_metrics_config(payload)

        study_name = self._make_study_name(params, metrics)
        self._current_study_name = study_name

        # ✅ kolla om study finns i DB
        try:
            study = optuna.load_study(
                study_name=study_name,
                storage=DB_PATH,
            )
            exists = True
            n_trials = len(study.trials)
        except Exception:
            exists = False
            n_trials = 0
        # ✅ uppdatera label
        if exists:
            self.lblActiveStudy.setText(f"Params: [{', '.join(params)}]  ✅ ({n_trials} trials)")
        else:
            self.lblActiveStudy.setText(f"Params: [{', '.join(params)}]  ❌ no study")

    def _on_progress(self, info):
        print("Progress:", info)

        if self._optuna_plot_window:
            try:
                self._optuna_plot_window.redraw()
            except RuntimeError:
                # fönster stängt
                self._optuna_plot_window = None

    def _on_finished(self, results):
        print("Finished:", len(results))

        self._evaluation_active = False

        self._thread = None
        self._worker = None

        self._running = False

        self.btnStart.setEnabled(True)
        self.btnStart.setText("Start")

        self.listParams.setEnabled(True)
        self.targetWeights.setEnabled(True)

        # ✅ cleanup eval service
        if self._eval_service:
            try:
                self._eval_service.evaluationReady.disconnect(self._on_evaluation_ready)
            except Exception:
                pass

            self._eval_service.deleteLater()
            self._eval_service = None

        self.lblStatus.setText("Finished")
        self.lblStatus.setStyleSheet("color: green;")

    # ev.
    # open_optuna_plot_window(...)

    def _on_evaluation_ready(self, result):

        worker = self._worker
        if not worker:
            return

        worker.on_evaluated(result)

        self._evaluation_active = False

    def _evaluate_main(self, params, unselected_params):  # , unselected_params=None ):

        if self._evaluation_active:
            return

        worker = self._worker
        if not worker:
            return

        self._evaluation_active = True

        # # 🔥 NYTT: Hämta ut de låsta parametrarna som sparades i din workers konfiguration
        # unselected_params = getattr(worker, "unselected_params", {})

        payload = {
            "trial_id": worker.current_trial_id,
            "params": params,
            # 🔥 NYTT: Skicka med till EvaluationService.evaluate()
            "unselected_params": unselected_params,
            "metrics": worker.metrics,
            "baseline": getattr(self, "_baseline", None),
        }

        # ✅ skicka till EvaluationService
        self._eval_service.evaluate(payload)

    def _start_optimization(self, new_study=False):

        self._eval_service = EvaluationService()
        self._eval_service.evaluationReady.connect(self._on_evaluation_ready)
        self._eval_service.statusChanged.connect(self._on_eval_status)

        # 1. Hämta de parametrar som faktiskt ska optimeras (valda i listan)
        selected_params = [i.text() for i in self.listParams.selectedItems()]
        if not selected_params:
            QtWidgets.QMessageBox.warning(self, "Optimize", "Select params")
            return

        # doc = App.ActiveDocument

        # 2. 🔥 NYTT: Identifiera alla parametrar som INTE är valda
        all_items = [self.listParams.item(i).text() for i in range(self.listParams.count())]
        unselected_params = [p for p in all_items if p not in selected_params]

        selected_info = self._read_params_info(selected_params)
        unselected_info = self._read_params_info(unselected_params)

        current_params = {n: d["value"] for n, d in selected_info.items()}
        bounds = {n: d["bounds"] for n, d in selected_info.items()}

        unselected_params = {n: d["value"] for n, d in unselected_info.items()}

        # bounds = self._read_bounds(doc, selected_params)
        payload = self.targetWeights.get_payload()
        metrics = self._build_metrics_config(payload)

        sampler_name = self.cmbSampler.currentText()
        use_constant_liar = self.chkConstantLiar.isChecked()

        # ✅ detect multi-objective automatically
        active_metrics = [m for m in metrics if m.get("active", True)]
        multi_objective = len(active_metrics) > 1

        n_trials = self.spinTrials.value()
        # print("Metrics config:", metrics)
        # ✅ ONLY compute baseline when new study

        if new_study or not hasattr(self, "_baseline"):
            self._baseline = compute_baseline()

        study_name = self._make_study_name(selected_params, metrics)

        config = {
            "metrics": metrics,
            "params": selected_params,
            "bounds": bounds,
            "unselected_params": unselected_params,
            "n_trials": n_trials,
            "study_name": study_name,
            "new_study": new_study,
            "baseline": self._baseline,
            "initial_params": current_params,  # ✅ för att kunna köra enque trials å default
            # ✅ NEW
            "sampler": sampler_name,
            "constant_liar": use_constant_liar,
            "multi_objective": multi_objective,
        }

        print("🚀 Start", "NEW" if new_study else "RESUME")

        self._setup_worker()
        self.startRequested.emit(config)
        self._running = True
        self.btnStart.setText("Stop")

        self.listParams.setEnabled(False)
        self.targetWeights.setEnabled(False)

    def _read_params_info(self, param_names):
        doc = App.ActiveDocument

        ss = doc.getObject(SPREADSHEET_NAME)

        if not ss:
            return {}

        return get_param_info(ss, param_names)

    def _on_start_stop(self):

        print(
            "running:",
            self._running,
            "worker:",
            self._worker,
            "thread:",
            self._thread,
        )

        if self._running:
            print("🛑 Stop")
            if self._worker:
                self._worker.request_stop()
            self.btnStart.setEnabled(False)
            return
        self._start_optimization(new_study=False)

    def _on_start_new(self):
        if self._running:
            QtWidgets.QMessageBox.information(self, "Optimization", "Stop current optimization first.")
            return
        self._start_optimization(new_study=True)

    def _reset_ui(self):
        self._running = False
        self.btnStart.setText("Start")

        self.listParams.setEnabled(True)
        self.targetWeights.setEnabled(True)

    def _build_label_to_name_map(self):
        doc = App.ActiveDocument
        mapping = {}
        for obj in doc.Objects:
            if hasattr(obj, "OpticalType"):
                mapping[obj.Label] = obj.Name
        return mapping

    def _open_optuna_plot_window(self):
        try:

            from .optuna_plotting import open_optuna_plot_window

            # open_optuna_plot_window(db_uri=DB_PATH, ma_window=3, show_global=True)
            self._optuna_plot_window = open_optuna_plot_window()
            # self.lblStatus.setText("Optuna-plotfönster öppnades.")
        except Exception as e:
            App.Console.PrintError(f"[UI] Plot error: {e}\n")
            # self.lblStatus.setText(f"Kunde inte öppna plot: {e}")

    def _on_metric_config_changed(self, payload):
        self._pending_payload = payload

        self._dirty = True
        self.lblStatus.setText("Unsaved changes")
        self.lblStatus.setStyleSheet("color: orange;")

        # ✅ restart timer (cancel previous)
        self._debounce_timer.start(120)  # justera delay

    def _run_debounced_selection(self):
        if not self._pending_payload:
            return
        self._select_best_trial(self._pending_payload)

    def _select_best_trial(self, payload):
        study_name = getattr(self, "_current_study_name", None)
        if not study_name:
            return

        try:
            study = optuna.load_study(
                study_name=study_name,
                storage=DB_PATH,
            )
        except Exception:
            return

        trials = study.best_trials
        if not trials:
            return

        # ✅ välj balanserad lösning
        def score(t):
            vals = list(t.user_attrs.get("metrics", {}).values())
            return np.std(vals) if vals else 999

        best_trial = min(trials, key=score)

        apply_cad_params(best_trial.params)
        App.ActiveDocument.recompute()

    def _make_study_name(self, params, metrics):
        # ✅ metrics
        metric_parts = []
        for m in metrics:
            if not m.get("active", True):
                continue
            metric_parts.append(f"{m['base_metric']}_{m['plane']}")
        metric_part = "__".join(sorted(metric_parts))
        # ✅ params
        param_part = "__".join(sorted(params))
        return f"{param_part}"  # eller inkludera metric_part senare

    # --- config sparandet ----------

    def _get_or_create_config_object(self):
        doc = App.ActiveDocument
        obj = doc.getObject("OptimizeConfig")

        if obj:
            return obj

        obj = doc.addObject("App::FeaturePython", "OptimizeConfig")
        obj.addProperty("App::PropertyString", "json", "Config")

        return obj

    def _on_config_changed(self):

        if getattr(self, "_dirty", False):
            reply = QtWidgets.QMessageBox.question(self, "Unsaved changes", "You have unsaved changes. Continue without saving?", QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if reply == QtWidgets.QMessageBox.No:
                return

        name = self.cmbConfig.currentText()

        print("[_on_config_chnaged] Switching to config:", name)

        obj = App.ActiveDocument.getObject("OptimizeConfig")
        if not obj:
            return

        data = json.loads(obj.json)

        data["active"] = name
        obj.json = json.dumps(data)

        config = data.get("configs", {}).get(name)
        if config:
            self._apply_config(config)

        self._dirty = False

    def _refresh_config_list(self):
        obj = App.ActiveDocument.getObject("OptimizeConfig")
        self.cmbConfig.blockSignals(True)
        self.cmbConfig.clear()

        if not obj or not obj.json:
            obj = self._get_or_create_config_object()
            data = {
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
            }
            obj.json = json.dumps(data)

        data = json.loads(obj.json)
        for name in data.get("configs", {}).keys():
            self.cmbConfig.addItem(name)

        active = data.get("active", "default")
        idx = self.cmbConfig.findText(active)
        if idx >= 0:
            self.cmbConfig.setCurrentIndex(idx)
        self.cmbConfig.blockSignals(False)

    def _create_new_config(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "New preset", "Name:")
        if not ok or not name:
            return

        obj = self._get_or_create_config_object()

        try:
            data = json.loads(obj.json) if obj.json else {}
        except:
            data = {}

        configs = data.get("configs", {})
        configs[name] = {
            "entries": [],
            "selected_params": [],
            "sampler": "TPESampler",
            "trials": 500,
            "constant_liar": True,
        }
        data["configs"] = configs
        data["active"] = name

        obj.json = json.dumps(data)

        self._refresh_config_list()
        self.cmbConfig.setCurrentText(name)

    def _save_config(self, payload):
        obj = self._get_or_create_config_object()

        selected_params = [i.text() for i in self.listParams.selectedItems() if i.flags() & QtCore.Qt.ItemIsSelectable]

        try:
            data = json.loads(obj.json) if obj.json else {}
        except:
            data = {}

        configs = data.get("configs", {})

        active_name = data.get("active", "default")

        configs[active_name] = {
            "entries": payload.get("entries", []),
            "selected_params": selected_params,
            "sampler": self.cmbSampler.currentText(),
            "trials": self.spinTrials.value(),
            "constant_liar": self.chkConstantLiar.isChecked(),
        }

        data["configs"] = configs
        data["active"] = active_name

        obj.json = json.dumps(data)
        self._refresh_config_list()

    def _on_save_clicked(self):
        payload = self.targetWeights.get_payload()
        self._save_config(payload)

        self._dirty = False
        self.lblStatus.setText("Saved ✅")
        self.lblStatus.setStyleSheet("color: green;")

    def _delete_current_config(self):
        name = self.cmbConfig.currentText()

        if not name:
            return

        # ❗ skydda default
        if name == "default":
            QtWidgets.QMessageBox.warning(self, "Delete", "Cannot delete default preset")
            return

        # confirm
        reply = QtWidgets.QMessageBox.question(self, "Delete preset", f"Delete preset '{name}'?", QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if reply != QtWidgets.QMessageBox.Yes:
            return

        obj = App.ActiveDocument.getObject("OptimizeConfig")
        if not obj:
            return

        data = json.loads(obj.json)

        configs = data.get("configs", {})
        if name in configs:
            del configs[name]

        # ✅ välj fallback config
        remaining = list(configs.keys())
        if not remaining:
            remaining = ["default"]
            configs["default"] = {
                "entries": [],
                "selected_params": [],
                "sampler": "TPESampler",
                "trials": 500,
                "constant_liar": True,
            }

        data["active"] = remaining[0]
        data["configs"] = configs

        obj.json = json.dumps(data)

        # ✅ refresh UI
        self._refresh_config_list()

        # ✅ ladda ny config
        new_config = data["configs"].get(data["active"])
        if new_config:
            self._apply_config(new_config)
        self._dirty = False

    def _load_config(self):
        obj = App.ActiveDocument.getObject("OptimizeConfig")
        if not obj or not obj.json:
            return None

        try:
            data = json.loads(obj.json)
            active = data.get("active", "default")
            return data.get("configs", {}).get(active)
        except Exception as e:
            print("[CONFIG LOAD ERROR]", e)
            return None

    def _apply_config(self, payload):

        # ✅ restore selected params
        selected = payload.get("selected_params", [])

        self.listParams.blockSignals(True)
        for i in range(self.listParams.count()):
            item = self.listParams.item(i)
            if item.flags() & QtCore.Qt.ItemIsSelectable:
                item.setSelected(item.text() in selected)
        self.listParams.blockSignals(False)
        # ✅ uppdatera study-name etc
        self._on_params_changed()

        if "sampler" in payload:
            self.cmbSampler.setCurrentText(payload["sampler"])
        if "trials" in payload:
            self.spinTrials.setValue(payload["trials"])

        if "constant_liar" in payload:
            self.chkConstantLiar.setChecked(payload["constant_liar"])

        entries = payload.get("entries", [])

        self.targetWeights.blockSignals(True)
        # clear rows
        for r in self.targetWeights.rows[:]:
            r.setParent(None)
            r.deleteLater()
        self.targetWeights.rows.clear()

        # lägg tillbaka metrics
        for e in entries:
            row = self.targetWeights.add_row(e["base_metric"])
            row = self.targetWeights.rows[-1]

            row.cmb.setCurrentText(e["base_metric"])
            row.cmbPlane.setCurrentText(e["plane"])
            row.chkActive.setChecked(e.get("active", True))

            row.targets = e.get("targets", [])
            row._update_targets_button()

            if "threshold" in e and hasattr(row, "percentWidget"):
                row.percentWidget.spin.setValue(int(e["threshold"] * 100))

            if "value" in e and hasattr(row, "valueWidget"):
                row.valueWidget.spin.setValue(e["value"])

            if "min" in e and hasattr(row, "rangeWidget"):
                row.rangeWidget.min.setValue(e["min"])
                row.rangeWidget.max.setValue(e.get("max", e["min"]))

            if "axis" in e and hasattr(row, "axisWidget"):
                row.axisWidget.setCurrentText(e["axis"])

        self.targetWeights.blockSignals(False)
        self.targetWeights._update()


import math

# -------------------------------------------------------


def ShowOptimizeDialog():
    global _optimize_dock_instance

    mw = Gui.getMainWindow()

    # ✅ redan öppen → bara visa och fokusera
    if _optimize_dock_instance is not None:
        _optimize_dock_instance.show()
        _optimize_dock_instance.raise_()
        return

    doc = App.ActiveDocument
    ss = doc.getObject(SPREADSHEET_NAME) if doc else None
    params_info = read_param_bounds(ss) if ss else None

    dock = OptimizeDialogDock(mw, params_info)
    dock.setObjectName(DOCK_OBJECT_NAME)

    # ✅ när den stängs → nollställ
    def _on_closed():
        global _optimize_dock_instance
        _optimize_dock_instance = None

    dock.destroyed.connect(_on_closed)

    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.show()

    _optimize_dock_instance = dock


# -------------------------------------------------------
