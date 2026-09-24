# -*- coding: utf-8 -*-
# import optuna.visualization as vis
# optuna.visualization.plot_parallel_coordinate()
# optuna.visualization.plot_param_importances()


import optuna
import FreeCAD as App

from PySide import QtCore, QtWidgets
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import matplotlib.pyplot as plt


from vendor_optuna.optuna.testing import trials

from oba_objects.oba_base import _trigger_ray_engine
from .spreadsheet_utils import apply_cad_params
from .optimize_worker import DB_PATH


class OptunaPlotWindow(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Optuna Plot")
        self.resize(1000, 700)

        self._optuna_plot_windows = []

        # state
        self.current_study_name = None
        self.selected_trial = None
        self.ignored_trials = set()
        self.plot_trials = []
        self.scatter = None
        self._saved_run_mode = None

        # ---------------- UI ----------------
        layout = QtWidgets.QVBoxLayout(self)

        # top
        top = QtWidgets.QHBoxLayout()
        # self.cmbStudy = QtWidgets.QComboBox()

        self.cmbStudy = QtWidgets.QComboBox()

        self.btnRefresh = QtWidgets.QPushButton("Refresh")
        self.btnRefresh.setToolTip(f"<b>Storage</b><br>{DB_PATH}")
        self.btnDelete = QtWidgets.QPushButton("Delete")
        self.btnCopy = QtWidgets.QPushButton("Copy")

        self.cmbStudy.setMinimumWidth(600)
        self.cmbStudy.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        self.btnRefresh.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.btnDelete.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.btnCopy.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)

        # self.cmbStudy.setMaximumWidth(400)
        self.btnViz = QtWidgets.QPushButton("Optuna Visualizations")

        top.addWidget(self.cmbStudy, 1)  # stretch = 1
        top.addWidget(self.btnRefresh, 0)
        top.addWidget(self.btnDelete, 0)
        top.addWidget(self.btnCopy, 0)
        top.addWidget(self.btnViz, 0)
        layout.addLayout(top)

        # controls
        controls = QtWidgets.QHBoxLayout()

        self.cmbX = QtWidgets.QComboBox()
        self.cmbY = QtWidgets.QComboBox()

        controls.addWidget(QtWidgets.QLabel("Y:"))
        controls.addWidget(self.cmbY)

        controls.addWidget(QtWidgets.QLabel("X:"))
        controls.addWidget(self.cmbX)

        self.cmbX.setMinimumWidth(150)
        self.cmbY.setMinimumWidth(150)

        self.cmbX.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.cmbY.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        controls.addSpacing(20)

        self.chkPareto = QtWidgets.QCheckBox("Pareto only")
        self.chkHide = QtWidgets.QCheckBox("Hide ignored")
        self.chkHide.setChecked(True)

        controls.addWidget(self.chkPareto)
        controls.addWidget(self.chkHide)

        self.chkRestoreCustom = QtWidgets.QCheckBox("Restore unselect params")
        self.chkRestoreCustom.setChecked(False)
        controls.addWidget(self.chkRestoreCustom)

        controls.addStretch()

        layout.addLayout(controls)

        # plot
        self.fig = plt.Figure()
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)

        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

        # signals
        self.btnViz.clicked.connect(self.open_visualizations)

        self.btnRefresh.clicked.connect(self.reload_studies)
        self.btnDelete.clicked.connect(self._delete_selected)
        self.btnCopy.clicked.connect(self._copy_study)

        self.cmbStudy.currentIndexChanged.connect(self.study_changed)
        self.cmbX.currentIndexChanged.connect(self.redraw)
        self.cmbY.currentIndexChanged.connect(self.redraw)

        self.chkPareto.stateChanged.connect(self.redraw)
        self.chkHide.stateChanged.connect(self.redraw)

        self.canvas.mpl_connect("pick_event", self.on_pick)

        self.reload_studies()

    # ==========================================================
    # STUDIES
    # ==========================================================

    def reload_studies(self):
        try:
            summaries = optuna.study.get_all_study_summaries(storage=DB_PATH)
            names = [s.study_name for s in summaries]
        except Exception:
            names = []

        self.cmbStudy.clear()
        self.cmbStudy.addItems(names)

        if names:
            self.current_study_name = names[0]
            self.redraw()

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
        doc = App.ActiveDocument
        if not doc:
            return
        _trigger_ray_engine(reason="optuna_plot_restore", source=None, force=True)

    def study_changed(self):
        self.cmbX.blockSignals(True)
        self.cmbY.blockSignals(True)

        self.cmbX.clear()
        self.cmbY.clear()

        self.cmbX.blockSignals(False)
        self.cmbY.blockSignals(False)

        self.current_study_name = self.cmbStudy.currentText()
        self.selected_trial = None

        self.redraw()

    def _delete_selected(self):
        name = self.current_study_name
        if not name:
            return

        if (
            QtWidgets.QMessageBox.question(
                self,
                "Confirm",
                f"Delete study:\n{name}?",
            )
            != QtWidgets.QMessageBox.Yes
        ):
            return

        try:
            optuna.delete_study(study_name=name, storage=DB_PATH)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            return

        self.reload_studies()

    def copy_study_to(self, old_name, new_name):
        old = optuna.load_study(study_name=old_name, storage=DB_PATH)
        try:
            optuna.delete_study(study_name=new_name, storage=DB_PATH)
        except:
            pass

        new = optuna.create_study(
            study_name=new_name,
            storage=DB_PATH,
            directions=old.directions,
            sampler=optuna.samplers.NSGAIISampler(),
        )
        for t in old.trials:
            new.add_trial(t)

        for k, v in old.user_attrs.items():
            new.set_user_attr(k, v)

        new.set_user_attr("copied_from", old_name)
        print(f"[study] copied: {old_name} → {new_name}")

    def _copy_study(self):
        old_name = self.current_study_name
        if not old_name:
            return

        new_name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Copy Study",
            "New study name:",
            text=f"{old_name}_copy",
        )

        if not ok or not new_name:
            return

        try:
            self.copy_study_to(old_name, new_name)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            return

        self.reload_studies()
        self.cmbStudy.setCurrentText(new_name)

    def _find_best_compromise_trials(self, trials, pareto_numbers, top_n=5):
        if not trials:
            return []

        n_metrics = len(trials[0].values)  # Notera: lade till [0] här som saknades i förra koden
        mins = [min(t.values[i] for t in trials) for i in range(n_metrics)]
        maxs = [max(t.values[i] for t in trials) for i in range(n_metrics)]

        def score(trial):
            vals = []
            for i, v in enumerate(trial.values):
                rng = maxs[i] - mins[i]
                if rng < 1e-12:
                    vals.append(1.0)
                else:
                    vals.append((v - mins[i]) / rng)
            s = 1.0
            for v in vals:
                s *= v
            return s

        pareto_trials = [t for t in trials if t.number in pareto_numbers]
        if not pareto_trials:
            return []

        # Sortera med högst score först och returnera de N bästa
        return sorted(pareto_trials, key=score, reverse=True)[:top_n]

    # ==========================================================
    # DATA
    # ==========================================================

    def _get_trials(self, study):
        ignored = self.ignored_trials if self.chkHide.isChecked() else set()

        return [t for t in study.trials if t.state.name == "COMPLETE" and t.number not in ignored]

    # ==========================================================
    # DRAW
    # ==========================================================

    def build_arrays(trials):
        n = len(trials[0].values)
        ys = [[] for _ in range(n)]
        for t in trials:
            for i, v in enumerate(t.values):
                ys[i].append(v)
        return ys

    def redraw(self):
        if not self.current_study_name:
            self.ax.clear()
            self.ax.set_title("No data")
            self.canvas.draw()
            return

        try:
            study = optuna.load_study(
                study_name=self.current_study_name,
                storage=DB_PATH,
            )
        except Exception as e:
            self.ax.clear()
            self.ax.set_title(str(e))
            self.canvas.draw()
            return

        trials = self._get_trials(study)
        ignored = self.ignored_trials if self.chkHide.isChecked() else set()
        pareto_numbers = {t.number for t in study.best_trials if t.number not in ignored}

        if not trials:
            self.ax.clear()
            self.ax.set_title("No data")
            self.canvas.draw()
            return

        # ------------------------------------------------------
        # build metric arrays
        # ------------------------------------------------------

        n_metrics = len(trials[0].values)
        ys = [[] for _ in range(n_metrics)]

        for t in trials:
            for i, v in enumerate(t.values):
                ys[i].append(v)

        metric_names = study.user_attrs.get("metric_names")

        if not metric_names:
            sample = trials[0].user_attrs.get("metrics", {})
            metric_names = list(sample.keys())

        self.ax.clear()

        # ------------------------------------------------------
        # init combos
        # ------------------------------------------------------

        if self.cmbX.count() == 0:
            for name in metric_names:
                self.cmbX.addItem(name)
                self.cmbY.addItem(name)

            if len(metric_names) >= 2:
                self.cmbX.setCurrentIndex(0)
                self.cmbY.setCurrentIndex(1)

        ix = self.cmbX.currentIndex()
        iy = self.cmbY.currentIndex()

        if ix == iy and len(metric_names) > 1:
            iy = (ix + 1) % len(metric_names)

            self.cmbY.blockSignals(True)
            self.cmbY.setCurrentIndex(iy)
            self.cmbY.blockSignals(False)

        xvals = ys[ix]
        yvals = ys[iy]

        # ------------------------------------------------------
        # color pareto trials red
        # ------------------------------------------------------

        colors = ["red" if t.number in pareto_numbers else "tab:blue" for t in trials]

        # ------------------------------------------------------
        # pareto only filter
        # ------------------------------------------------------

        if self.chkPareto.isChecked():
            mask = [t.number in pareto_numbers for t in trials]
            trials = [t for t, m in zip(trials, mask) if m]
            xvals = [x for x, m in zip(xvals, mask) if m]
            yvals = [y for y, m in zip(yvals, mask) if m]
            colors = ["red"] * len(trials)
        self.plot_trials = trials

        # ------------------------------------------------------
        # draw points
        # ------------------------------------------------------

        self.scatter = self.ax.scatter(xvals, yvals, s=35, c=colors, alpha=0.7, picker=6)

        self.ax.set_xlabel(metric_names[ix])
        self.ax.set_ylabel(metric_names[iy])
        self.ax.set_title(self.current_study_name)

        # Ändra detta i din redraw-funktion:
        best_trials = self._find_best_compromise_trials(trials, pareto_numbers, top_n=5)

        if best_trials:
            # En färgskala från näst bäst till sämst (orange -> röd -> mörkröd)
            # Du kan ändra dessa färger efter smak
            gradient_colors = ["darkorange", "crimson", "firebrick", "maroon"]

            # Vi loopar bakifrån så att den BÄSTA (index 0) ritas SIST och hamnar överst
            for index, t in reversed(list(enumerate(best_trials))):
                if index == 0:
                    # Den absolut bästa kompromissen (Guldstjärna)
                    color = "gold"
                    size = 450
                    alpha = 1.0
                    linewidth = 2.5  # Lite tjockare kantlinje för att poppa ut
                else:
                    # Välj färg baserat på placering (index 1 får gradient_colors[0], etc.)
                    color_idx = min(index - 1, len(gradient_colors) - 1)
                    color = gradient_colors[color_idx]

                    # Snabbare krympning: 300, 220, 140, 60...
                    size = max(60, 380 - (index * 80))

                    # Progressiv transparens: 2:a plats har 0.6, 5:e plats har 0.3
                    alpha = max(0.2, 0.7 - (index * 0.1))
                    linewidth = 1.0

                self.ax.scatter(
                    t.values[ix],
                    t.values[iy],
                    marker="*",
                    s=size,
                    color=color,
                    alpha=alpha,
                    edgecolors="black",
                    linewidths=linewidth,
                    zorder=50 - index,  # Ser till att guld ligger överst
                    label="Best compromise" if index == 0 else None,
                )

        if len(best_trials) >= 2:

            line_x = [t.values[ix] for t in best_trials]
            line_y = [t.values[iy] for t in best_trials]

            self.ax.plot(line_x, line_y, color="black", linestyle="--", linewidth=1.5, alpha=0.6, zorder=40, label="Compromise ranking")

        # ------------------------------------------------------
        # selected trial
        # ------------------------------------------------------

        if self.selected_trial and self.selected_trial in self.plot_trials:

            t = self.selected_trial

            self.ax.scatter(
                t.values[ix],
                t.values[iy],
                color="yellow",
                s=120,
                edgecolors="black",
                linewidths=2,
                zorder=20,
            )

        self.ax.grid(True)
        self.canvas.draw()

    # ==========================================================
    # INTERACTION
    # ==========================================================

    def apply_trial(self, trial):
        self.selected_trial = trial

        print(f"[plot] Apply trial {trial.number}")

        try:
            params = dict(trial.params)

            if self.chkRestoreCustom.isChecked():
                params.update(trial.user_attrs.get("unselected_params", {}))

            print("Apply params:", params)
            self._enable_manual_raytrace_mode()
            apply_cad_params(params)
            doc = App.ActiveDocument
            if doc:
                doc.recompute()
            self._trigger_manual_ray_trace()
        except Exception as e:
            print("CAD error:", e)
        finally:
            self._restore_manual_raytrace_mode()

        self.redraw()

    def on_pick(self, event):

        if event.artist is not self.scatter:
            return

        if event.ind is None or len(event.ind) == 0:
            return

        idx = int(event.ind[0])

        if idx >= len(self.plot_trials):
            return

        trial = self.plot_trials[idx]

        self.apply_trial(trial)

    # ==========================================================
    # DELETE (ignore)
    # ==========================================================

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Delete:
            self.delete_selected_trial()

    def delete_selected_trial(self):
        if not self.selected_trial:
            return

        t = self.selected_trial
        self.ignored_trials.add(t.number)

        print(f"[plot] Ignored trial {t.number}")

        self.selected_trial = None
        self.redraw()

    # ==========================================================
    # OPTUNA visualistaions plots
    # ==========================================================

    def open_visualizations(self):
        dlg = OptunaVisualizationDialog(self)
        dlg.show()
        self._optuna_plot_windows.append(dlg)


# ==========================================================
# OPTUNA VISUALIZATIONS
# ==========================================================

from functools import partial

from optuna.visualization.matplotlib import (
    plot_param_importances,
    plot_slice,
    plot_parallel_coordinate,
    plot_optimization_history,
)


class OptunaVisualizationDialog(QtWidgets.QDialog):
    """
    Gemensam dialog för Optunas visualiseringar.

    Stödjer:
        - Parameter Importance
        - Slice
        - Parallel Coordinate
        - Optimization History

    Multi-objective:
        - Val av target/metric
        - Automatisk hantering av objective-index
        - Val av parametrar för relevanta diagram
    """

    GRAPH_PARAMETER_IMPORTANCE = "Parameter Importance"
    GRAPH_SLICE = "Slice"
    GRAPH_PARALLEL = "Parallel Coordinate"
    GRAPH_HISTORY = "Optimization History"

    GRAPH_NAMES = (
        GRAPH_PARAMETER_IMPORTANCE,
        GRAPH_SLICE,
        GRAPH_PARALLEL,
        GRAPH_HISTORY,
    )

    def __init__(self, parent_plot):
        super().__init__(parent_plot)

        self.parent_plot = parent_plot
        self._plot_windows = []

        self.study = None
        self.metric_names = []
        self.parameter_names = []

        self.setWindowTitle("Optuna Visualizations")
        self.resize(560, 420)
        self.setMinimumSize(480, 340)

        self._build_ui()
        self._connect_signals()

        self._load_current_study()
        self._update_controls()

    # ======================================================
    # UI
    # ======================================================

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # --------------------------------------------------
        # Header
        # --------------------------------------------------

        header = QtWidgets.QLabel("Optuna Visualizations")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        self.lblStudy = QtWidgets.QLabel()
        self.lblStudy.setWordWrap(True)
        self.lblStudy.setStyleSheet("color: gray;")
        layout.addWidget(self.lblStudy)

        # --------------------------------------------------
        # Graph type
        # --------------------------------------------------

        graph_group = QtWidgets.QGroupBox("Visualization")
        graph_layout = QtWidgets.QVBoxLayout(graph_group)

        self.cmbGraph = QtWidgets.QComboBox()
        self.cmbGraph.addItems(self.GRAPH_NAMES)
        self.cmbGraph.setCurrentText(self.GRAPH_PARALLEL)

        graph_layout.addWidget(self.cmbGraph)
        layout.addWidget(graph_group)

        # --------------------------------------------------
        # Target / metric
        # --------------------------------------------------

        self.target_group = QtWidgets.QGroupBox("Target / Objective")
        target_layout = QtWidgets.QFormLayout(self.target_group)

        self.cmbTarget = QtWidgets.QComboBox()
        self.cmbTarget.setMinimumWidth(260)

        self.lblTargetInfo = QtWidgets.QLabel()
        self.lblTargetInfo.setWordWrap(True)
        self.lblTargetInfo.setStyleSheet("color: gray;")

        target_layout.addRow("Target:", self.cmbTarget)
        target_layout.addRow("", self.lblTargetInfo)

        layout.addWidget(self.target_group)

        # --------------------------------------------------
        # Parameters
        # --------------------------------------------------

        self.parameter_group = QtWidgets.QGroupBox("Parameters")
        parameter_layout = QtWidgets.QVBoxLayout(self.parameter_group)

        self.lstParameters = QtWidgets.QListWidget()
        self.lstParameters.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.lstParameters.setMinimumHeight(100)

        parameter_buttons = QtWidgets.QHBoxLayout()

        self.btnSelectAll = QtWidgets.QPushButton("Select all")
        self.btnClearAll = QtWidgets.QPushButton("Clear")

        parameter_buttons.addWidget(self.btnSelectAll)
        parameter_buttons.addWidget(self.btnClearAll)
        parameter_buttons.addStretch()

        parameter_layout.addWidget(self.lstParameters)
        parameter_layout.addLayout(parameter_buttons)

        layout.addWidget(self.parameter_group)

        # --------------------------------------------------
        # Actions
        # --------------------------------------------------

        layout.addStretch()

        self.lblStatus = QtWidgets.QLabel()
        self.lblStatus.setWordWrap(True)
        self.lblStatus.setStyleSheet("color: gray;")
        layout.addWidget(self.lblStatus)

        actions = QtWidgets.QHBoxLayout()

        self.btnShow = QtWidgets.QPushButton("Show visualization")
        self.btnClose = QtWidgets.QPushButton("Close")

        self.btnShow.setDefault(True)

        actions.addStretch()
        actions.addWidget(self.btnShow)
        actions.addWidget(self.btnClose)

        layout.addLayout(actions)

    def _connect_signals(self):
        self.cmbGraph.currentIndexChanged.connect(self._update_controls)
        self.cmbTarget.currentIndexChanged.connect(self._target_changed)
        self.btnSelectAll.clicked.connect(self._select_all_parameters)
        self.btnClearAll.clicked.connect(self._clear_parameters)
        self.btnShow.clicked.connect(self.show_graph)
        self.btnClose.clicked.connect(self.close)

    # ======================================================
    # STUDY
    # ======================================================

    def _load_current_study(self):
        study_name = self.parent_plot.current_study_name

        if not study_name:
            self.study = None
            self.lblStudy.setText("No study selected.")
            return
        try:
            self.study = optuna.load_study(study_name=study_name, storage=DB_PATH)
        except Exception as exc:
            self.study = None
            self.lblStudy.setText(f"Could not load study:\n{exc}")
            return

        self.lblStudy.setText(f"Study: {self.study.study_name}")

        self._read_metric_names()
        self._read_parameter_names()
        self._populate_targets()
        self._populate_parameters()

    def _read_metric_names(self):
        """
        Hämtar metric-namn från study.user_attrs.
        Fallback:
            objective_0, objective_1, ...
        """
        self.metric_names = []

        if self.study is None:
            return

        attrs = self.study.user_attrs
        names = attrs.get("metric_names")
        if isinstance(names, (list, tuple)):
            self.metric_names = [str(name) for name in names]

        # Om metric_names saknas, försök hitta namnen
        # från en trial med metrics-attribut.
        if not self.metric_names:
            for trial in self.study.trials:
                metrics = trial.user_attrs.get("metrics")

                if isinstance(metrics, dict) and metrics:
                    self.metric_names = list(metrics.keys())
                    break

        n_objectives = len(self.study.directions)

        # Säkerställ att vi har rätt antal mål.
        if len(self.metric_names) != n_objectives:
            self.metric_names = [f"Objective {i}" for i in range(n_objectives)]

    def _read_parameter_names(self):
        if self.study is None:
            self.parameter_names = []
            return
        names = set()
        for trial in self.study.trials:
            names.update(trial.params.keys())
        self.parameter_names = sorted(names)

    # ======================================================
    # TARGETS
    # ======================================================

    def _populate_targets(self):
        self.cmbTarget.blockSignals(True)
        self.cmbTarget.clear()
        if self.study is None:
            self.cmbTarget.blockSignals(False)
            return

        n_objectives = len(self.study.directions)
        if n_objectives <= 1:
            self.cmbTarget.addItem("Objective 0", userData=0)
        else:
            for index, name in enumerate(self.metric_names):
                direction = self.study.directions[index].name
                label = f"{index}: {name} " f"({direction.lower()})"
                self.cmbTarget.addItem(label, userData=index)

        self.cmbTarget.blockSignals(False)
        self._update_target_info()

    def _target_changed(self):
        self._update_target_info()

    def _update_target_info(self):
        if self.study is None:
            self.lblTargetInfo.setText("")
            return

        if len(self.study.directions) <= 1:
            self.lblTargetInfo.setText("Single-objective study.")
            return

        index = self._selected_target_index()
        name = self._target_name(index)

        self.lblTargetInfo.setText(f"Selected objective: {name}\n" "This target is used for the selected visualization.")

    def _selected_target_index(self):
        value = self.cmbTarget.currentData()
        if value is None:
            return 0
        return int(value)

    def _selected_target_name(self):
        if self.study is None:
            return "Objective"
        return self._target_name(self._selected_target_index())

    def _target_name(self, index):
        if 0 <= index < len(self.metric_names):
            return self.metric_names[index]
        return f"Objective {index}"

    def _target_callable(self):
        """
        Optuna matplotlib API använder target=callable
        för multi-objective.
        För single-objective används None.
        """

        if self.study is None:
            return None

        if len(self.study.directions) <= 1:
            return None
        index = self._selected_target_index()
        return partial(self._trial_target, objective_index=index)

    @staticmethod
    def _trial_target(trial, objective_index=0):
        values = trial.values
        if values is None:
            return float("nan")
        if objective_index >= len(values):
            return float("nan")
        return values[objective_index]

    # ======================================================
    # PARAMETERS
    # ======================================================

    def _populate_parameters(self):
        self.lstParameters.clear()

        for name in self.parameter_names:
            item = QtWidgets.QListWidgetItem(name)
            item.setData(QtCore.Qt.UserRole, name)
            self.lstParameters.addItem(item)

        self._select_all_parameters()

    def _selected_parameters(self):
        return [item.data(QtCore.Qt.UserRole) for item in self.lstParameters.selectedItems()]

    def _select_all_parameters(self):
        self.lstParameters.selectAll()

    def _clear_parameters(self):
        self.lstParameters.clearSelection()

    # ======================================================
    # CONTROL VISIBILITY
    # ======================================================

    def _update_controls(self):
        graph_name = self.cmbGraph.currentText()

        is_history = graph_name == self.GRAPH_HISTORY

        is_parameter_plot = graph_name in (self.GRAPH_PARAMETER_IMPORTANCE, self.GRAPH_SLICE, self.GRAPH_PARALLEL)

        # Target behövs inte i single-objective.
        # För multi-objective visas det alltid.
        self.target_group.setVisible(self.study is not None and len(self.study.directions) > 1)

        # Parameter Importance kan använda valda parametrar.
        # Slice och Parallel Coordinate behöver parametrar.
        self.parameter_group.setVisible(is_parameter_plot)

        self.btnSelectAll.setEnabled(is_parameter_plot)

        self.btnClearAll.setEnabled(is_parameter_plot)

        if is_history:
            self.lblStatus.setText("Optimization history for the selected target.")
        elif graph_name == self.GRAPH_PARAMETER_IMPORTANCE:
            self.lblStatus.setText("Select parameters to include in the importance plot.")
        elif graph_name == self.GRAPH_SLICE:
            self.lblStatus.setText("Select one or more parameters for the slice plot.")
        elif graph_name == self.GRAPH_PARALLEL:
            self.lblStatus.setText("Select parameters for the parallel coordinate plot.")
        else:
            self.lblStatus.setText("")

    # ======================================================
    # PLOT DISPATCH
    # ======================================================

    def show_graph(self):
        """
        Skapar exakt en figur per knapptryckning.
        Alla plot-funktioner går genom samma väg.
        """

        if self.study is None:
            self._show_error("No study is loaded.")
            return

        graph_name = self.cmbGraph.currentText()
        target = self._target_callable()
        parameters = self._selected_parameters()

        try:
            if graph_name == self.GRAPH_PARAMETER_IMPORTANCE:
                fig = self._create_parameter_importance(target=target, parameters=parameters)
            elif graph_name == self.GRAPH_SLICE:
                fig = self._create_slice(target=target, parameters=parameters)
            elif graph_name == self.GRAPH_PARALLEL:
                fig = self._create_parallel_coordinate(target=target, parameters=parameters)
            elif graph_name == self.GRAPH_HISTORY:
                fig = self._create_optimization_history(target=target)
            else:
                raise ValueError(f"Unknown visualization: {graph_name}")
        except Exception as exc:
            self._show_error(f"Could not create {graph_name}:\n\n{exc}")
            return

        self._show_figure(fig=fig, title=graph_name)

    # ======================================================
    # FIGURE CREATION
    # ======================================================

    def _create_parameter_importance(self, target=None, parameters=None):

        kwargs = {}
        if target is not None:
            kwargs["target"] = target
        if parameters:
            kwargs["params"] = parameters
        try:
            ax = plot_param_importances(self.study, **kwargs)
        except AssertionError:
            raise RuntimeError("Parameter Importance is not supported by this Optuna build.")
        return ax.figure

    def _create_slice(self, target=None, parameters=None):
        kwargs = {}
        if target is not None:
            kwargs["target"] = target
        if parameters:
            kwargs["params"] = parameters
        ax = plot_slice(self.study, **kwargs)
        return ax.figure

    def _create_parallel_coordinate(self, target=None, parameters=None):
        kwargs = {}
        if target is not None:
            kwargs["target"] = target
        if parameters:
            kwargs["params"] = parameters
        ax = plot_parallel_coordinate(self.study, **kwargs)
        return ax.figure

    def _create_optimization_history(self, target=None):
        kwargs = {}
        if target is not None:
            kwargs["target"] = target
            kwargs["target_name"] = self._selected_target_name()
        ax = plot_optimization_history(self.study, **kwargs)
        return ax.figure

    # ======================================================
    # FIGURE WINDOW
    # ======================================================

    def _show_figure(self, fig, title):
        """
        Visar figuren i ett separat fönster.
        Figuren skapas bara en gång.
        """

        dlg = QtWidgets.QDialog(self)
        dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose)

        dlg.setWindowTitle(title)
        dlg.resize(1200, 800)

        layout = QtWidgets.QVBoxLayout(dlg)

        canvas = FigureCanvas(fig)
        toolbar = NavigationToolbar(canvas, dlg)
        layout.addWidget(toolbar)
        layout.addWidget(canvas)

        dlg.finished.connect(lambda: self._remove_plot_window(dlg))
        self._plot_windows.append(dlg)

        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _remove_plot_window(self, dlg):
        if dlg in self._plot_windows:
            self._plot_windows.remove(dlg)

    # ======================================================
    # ERRORS
    # ======================================================

    def _show_error(self, message):
        QtWidgets.QMessageBox.critical(self, "Optuna Visualization", message)

    # ======================================================
    # CLOSE
    # ======================================================

    def closeEvent(self, event):
        """
        Stäng underfönstren när visualiseringsdialogen stängs.
        """
        for dlg in list(self._plot_windows):
            try:
                dlg.close()
            except RuntimeError:
                pass

        self._plot_windows.clear()
        super().closeEvent(event)


# ==========================================================
# OPEN WINDOW
# ==========================================================

_windows = []


def open_optuna_plot_window():
    w = OptunaPlotWindow()
    _windows.append(w)
    w.show()
    w.raise_()
    return w
