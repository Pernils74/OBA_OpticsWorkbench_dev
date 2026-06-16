# -*- coding: utf-8 -*-

# optimize_dialog.py


import os
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets, QtGui

import json

import numpy as np

from .optimize_worker import OptimizationWorker
from .spreadsheet_utils import read_param_bounds

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
                        font = list_item.font()
                        font.setBold(True)
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

    def _get_current_cad_params(self, param_names, bounds):
        doc = App.ActiveDocument
        ss = doc.getObject(SPREADSHEET_NAME)
        result = {}
        for name in param_names:
            lo, hi = bounds.get(name, (None, None))
            try:
                v = float(ss.get(name))  # ✅ exakt värde från CAD
            except Exception:
                print(f"[WARN] missing param {name}, fallback to midpoint")
                if lo is not None and hi is not None:
                    v = 0.5 * (lo + hi)  # fallback om saknas
                else:
                    v = 0.0
            # ✅ safety ONLY (ska normalt inte triggas)
            if lo is not None and v < lo:
                print(f"[CLAMP] {name}: {v} -> {lo}")
                v = lo
            if hi is not None and v > hi:
                print(f"[CLAMP] {name}: {v} -> {hi}")
                v = hi
            result[name] = v
        return result

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
                }
            )
        return metrics

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

        self.lblStatus.setText("Finished")
        self.lblStatus.setStyleSheet("color: green;")

    # ev.
    # open_optuna_plot_window(...)

    def _evaluated_debug(self, clusters, label_map):
        print("\n================ EVAL DEBUG ================")
        print("Total clusters:", len(clusters))
        # ✅ vilka objekt finns i clusters
        cluster_objects = list({c.get("object") for c in clusters.values()})
        print("Cluster objects (unique):", cluster_objects)

        print("\n--- Per Metric ---")

        for metric in self._worker.metrics:
            name = metric["name"]
            plane = metric["plane"]
            targets = metric["targets"]

            print("\n-------------------------------------------")
            print("Metric:", name)
            print("Plane:", plane)

            print("Targets (UI labels):", targets)
            # ✅ mapping
            target_names = []
            for t in targets:
                mapped = label_map.get(t)
                if mapped is None:
                    print("[WARN] No mapping for:", t)
                else:
                    target_names.append(mapped)
            print("Mapped target names:", target_names)
            # ✅ filtering
            filtered = {k: c for k, c in clusters.items() if c.get("object") in target_names}
            print("Filtered cluster count:", len(filtered))
            # ✅ show some clusters
            for cid, c in list(filtered.items())[:3]:
                print("  cluster:", cid)
                print("    object:", c.get("object"))
                print("    hits:", c.get("hit_count"))

            # ✅ compute preview values
            if metric["base_metric"] == "density":
                val = compute_density(filtered, plane, self._baseline)
            elif metric["base_metric"] == "roundness":
                val = compute_roundness(filtered, plane, self._baseline)
            elif metric["base_metric"] == "equal_distance":
                val = compute_distance(filtered, plane, self._baseline)
            else:
                val = None
            print("Computed value:", val)
        print("============================================\n")

    def _is_model_valid(self, doc):
        for obj in doc.Objects:

            # 1. Kontrollera skisser
            if obj.TypeId == "Sketcher::SketchObject":
                # obj.solve()

                # Hämtar DoF (standard 0 om det mot förmodan saknas)
                dof = getattr(obj, "DoF", 0)
                if dof < 0:
                    print("[FAIL] negative DOF (over-constrained):", obj.Name)
                    return False

                # Hämtar externa referenser säkert
                ext_geo = getattr(obj, "ExternalGeometry", [])
                for ext in ext_geo:
                    if ext is None:
                        print("[FAIL] missing external ref:", obj.Name)
                        return False

            # 2. Kontrollera geometri (endast objekt som faktiskt har en Shape)
            # if hasattr(obj, "Shape"):
            if obj.TypeId.startswith("PartDesign::"):
                shape = obj.Shape
                if not shape or shape.isNull():
                    print("[FAIL] null shape:", obj.Name)
                    return False

                if shape.ShapeType == "Solid" and len(shape.Faces) == 0:
                    print("[FAIL] no faces:", obj.Name)
                    return False

            # 3. Kontrollera FreeCADs inbyggda felsignaler
            if "Invalid" in obj.State:
                print("[FAIL] state:", obj.Name, obj.State)
                return False

            # Hämtar ErrorStatus säkert (returnerar tom sträng om attributet saknas)

            if hasattr(obj, "ErrorStatus"):
                try:
                    error_status = obj.ErrorStatus
                except Exception as e:
                    print("[API WARN] ErrorStatus access failed:", obj.Name, e)
                    error_status = None

                if error_status and error_status != "OK":
                    print("[FAIL] error status:", obj.Name, error_status)
                    return False

        return True

    def _evaluate_main(self, params):
        from .target_weights_widget import METRICS

        worker = self._worker
        if not worker:
            raise RuntimeError("No worker instance")

        if self._evaluation_active:
            return

        self._evaluation_active = True
        doc = App.ActiveDocument

        doc.openTransaction("optuna")
        label_map = self._build_label_to_name_map()

        try:
            apply_cad_params(params)
            doc.recompute()

            if not self._is_model_valid(doc):
                raise RuntimeError("Invalid geometry")

            _trigger_ray_engine(reason="optuna", source=None, force=True)
            clusters = aggregate_interaction_clusters(mode="final", min_hits=1)

            results = {}
            baseline = getattr(worker, "_baseline", None)

            for metric in worker.metrics:
                base = metric["base_metric"]
                plane = metric["plane"]
                targets = metric["targets"]

                target_names = [label_map.get(t, t) for t in targets]

                filtered = {k: c for k, c in clusters.items() if c.get("object") in target_names}

                # self.lblStatus.setText(f"Processar...: {base}")
                # self.lblStatus.setStyleSheet("color: orange;")

                # ✅ clean dispatch
                if base == "threshold_power":
                    value = compute_power(filtered, target_names, None)

                elif base == "power":
                    value = compute_power(filtered, target_names, baseline)

                elif base == "threshold_cluster_count":
                    value = compute_cluster_count(filtered, target_names, None)
                    # value = float(len(filtered))

                elif base == "cluster_count":
                    value = compute_cluster_count(filtered, target_names, baseline)

                elif base == "density":
                    value = compute_density(filtered, plane, baseline)

                elif base == "roundness":
                    value = compute_roundness(filtered, plane, baseline)

                elif base == "equal_distance":
                    value = compute_distance(filtered, plane, baseline)

                elif base == "equal_ray_hits_count":
                    value = compute_equal_ray_hits_count(filtered, plane, baseline)

                elif base == "cluster_axis_alignment":
                    value = compute_cluster_axis_alignment(filtered, metric.get("axis"), plane, baseline)

                else:
                    value = 0.0

                results[metric["name"]] = value

                # ✅ pruning
                # threshold = METRICS.get(base, {}).get("threshold")
                metric_type = METRICS.get(base, {}).get("type")
                if metric_type == "threshold":

                    print("Threasholdd uppnått på :", base, " för ", value, "  metric ", metric_type)
                    # ✅ percent threshold
                    target = metric.get("percent")
                    if target is not None:
                        if value < target:
                            self.lblStatus.setText(f"Threshold: {base} {value:.3f} < {target}")
                            QtWidgets.QApplication.processEvents()
                            results["_pruned"] = True
                            break

                    # ✅ exact value threshold
                    target = metric.get("value")
                    if target is not None:
                        if abs(value - target) > 1e-6:
                            self.lblStatus.setText(f"Threshold: {base} {value:.3f} != {target}")
                            QtWidgets.QApplication.processEvents()
                            results["_pruned"] = True
                            break

                # threshold = metric.get("threshold")
                # if threshold is not None and value < threshold:
                #     self.lblStatus.setText(f"Threashold uppnått på : {base}")
                #     results["_pruned"] = True
                #     break

            worker.on_evaluated(results)
            doc.commitTransaction()

            # self.lblStatus.setText("Finished")
            # self.lblStatus.setStyleSheet("color: green;")

        except Exception as e:
            print("[EVAL FAIL]", e)

            try:
                doc.abortTransaction()
            except Exception as rollback_error:
                print("[ROLLBACK FAIL]", rollback_error)

            worker.on_evaluated({"_pruned": True})

        finally:
            self._evaluation_active = False

    def _start_optimization(self, new_study=False):
        params = [i.text() for i in self.listParams.selectedItems()]
        if not params:
            QtWidgets.QMessageBox.warning(self, "Optimize", "Select params")
            return
        doc = App.ActiveDocument
        bounds = self._read_bounds(doc, params)
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

        study_name = self._make_study_name(params, metrics)
        current_params = self._get_current_cad_params(params, bounds)

        config = {
            "metrics": metrics,
            "params": params,
            "bounds": bounds,
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

    def _read_bounds(self, doc, param_names):
        ss = doc.getObject(SPREADSHEET_NAME)
        info = read_param_bounds(ss) if ss else []

        m = {item["name"]: item["bounds"] for item in info if item["type"] == "param"}

        return {p: m.get(p, (0.0, 1.0)) for p in param_names}

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

    # --- config sparandet

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


def compute_baseline():
    clusters = aggregate_interaction_clusters(mode="final", min_hits=1)

    baseline = {}

    baseline["cluster_count"] = len(clusters)
    baseline["total_hits"] = sum(c.get("hit_count", 0) for c in clusters.values())

    # ✅ power per object
    object_power = {}
    object_hits = {}

    for c in clusters.values():
        obj = c.get("object")

        object_power[obj] = object_power.get(obj, 0.0) + c.get("power", {}).get("in", 0.0)
        object_hits[obj] = object_hits.get(obj, 0) + c.get("hit_count", 0)

    baseline["object_power"] = object_power
    baseline["object_hits"] = object_hits

    # density
    for plane in ("3D", "XY", "XZ", "YZ"):
        vals = [c.get("density", {}).get(plane) for c in clusters.values() if c.get("density", {}).get(plane) is not None]
        baseline[f"density_{plane}"] = sum(vals) / len(vals) if vals else 0.0

    cluster_count_per_object = {}
    for c in clusters.values():
        obj = c.get("object")
        cluster_count_per_object[obj] = cluster_count_per_object.get(obj, 0) + 1

    baseline["cluster_count_per_object"] = cluster_count_per_object

    return baseline


def compute_power(clusters, targets, baseline=None):
    if not clusters:
        return 0.0

    current = sum(c.get("power", {}).get("in", 0.0) for c in clusters.values() if c.get("object") in targets)

    if baseline:
        base = sum(baseline.get("object_power", {}).get(obj, 0.0) for obj in targets)
        return current / base if base > 1e-6 else 0.0

    return current


def compute_cluster_count(clusters, targets, baseline=None):
    if not clusters:
        return 0.0

    count = sum(1 for c in clusters.values() if c.get("object") in targets)

    if baseline:
        base = 0
        base_clusters = baseline.get("cluster_count_per_object", {})

        for t in targets:
            base += base_clusters.get(t, 0)

        return count / base if base > 1e-6 else 0.0

    return float(count)


def compute_maximize_power(clusters, targets, baseline):
    if not clusters:
        return 0.0
    current = 0.0
    for c in clusters.values():
        if c.get("object") in targets:
            current += c.get("hit_count", 0)

    # ✅ använd baseline som referens (viktigt!)
    if baseline:
        base_hits = baseline.get("object_hits", {})
        base = sum(base_hits.get(obj, 0.0) for obj in targets)
        if base > 1e-6:
            return current / base  # ✅ ratio → maximize
        else:
            return 0.0
    return current  # fallback


def compute_cluster_axis_alignment(clusters, axis, plane=None, baseline=None):
    if not clusters or not axis:
        return 0.0

    vals = []

    for c in clusters.values():

        centroid = c.get("centroid", {}).get("3D")

        if centroid is None:
            continue

        if axis == "X":
            vals.append(centroid[0])
        elif axis == "Y":
            vals.append(centroid[1])
        elif axis == "Z":
            vals.append(centroid[2])

    if len(vals) < 2:
        return 0.0

    std = np.std(vals)

    # ✅ låg spridning = bra
    score = 1.0 / (1.0 + std)

    return score


def compute_equal_ray_hits_count(clusters, plane, baseline=None):
    # ✅ behålla rays
    # ✅ fördela dem jämnt
    # ✅ inte skapa döda kluster

    import numpy as np

    hits = np.array([c.get("hit_count", 0) for c in clusters.values()])

    if len(hits) == 0:
        return 0.0

    total = hits.sum()
    mean = hits.mean()
    std = hits.std()

    if total == 0:
        return 0.0

    # ✅ jämnhet
    uniformity = 1.0 / (1.0 + std / (mean + 1e-6))

    # ✅ total effekt
    if baseline:
        base_total = baseline.get("total_hits", 1e-6)
        efficiency = total / (base_total + 1e-6)
    else:
        efficiency = total

    return uniformity * efficiency


def compute_density(clusters, plane, baseline=None):
    if not clusters:
        return 0.0

    vals = []
    weights = []

    for c in clusters.values():
        raw = c.get("density", {}).get(plane)
        w = c.get("hit_count", 1)

        if raw is not None:
            vals.append(raw * w)
            weights.append(w)

    if not vals:
        return 0.0

    # ✅ INGEN normalisering
    return sum(vals) / sum(weights)


def compute_roundness(clusters, plane, baseline=None):
    if not clusters:
        return 0.0

    vals = []
    for c in clusters.values():
        r = c.get("roundness", {}).get(plane)
        if r is not None:
            vals.append(r)

    if not vals:
        return 0.0

    return sum(vals) / len(vals)


import math


def compute_distance(clusters, plane, baseline=None):

    if not clusters:
        return 0.0

    vals = []

    for c in clusters.values():

        if plane == "3D":
            r = c.get("spread", {}).get("3D", {}).get("radius")
        else:
            cov = c.get("spread", {}).get(plane, {}).get("cov")
            if cov is None:
                continue

            try:
                import numpy as np

                eig = np.linalg.eigvals(cov)
                r = float(max(eig)) ** 0.5
            except:
                continue

        if r is None:
            continue

        # ✅ bättre scaling
        score = 1.0 / (1.0 + r * 10.0)
        vals.append(score)

    if not vals:
        return 0.0

    return sum(vals) / len(vals)


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
