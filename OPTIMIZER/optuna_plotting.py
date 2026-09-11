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
        self.cmbStudy = QtWidgets.QComboBox()
        self.btnRefresh = QtWidgets.QPushButton("Refresh")
        self.btnDelete = QtWidgets.QPushButton("Delete")

        self.btnCopy = QtWidgets.QPushButton("Copy")

        top.addWidget(self.cmbStudy)
        top.addWidget(self.btnRefresh)
        top.addWidget(self.btnDelete)
        top.addWidget(self.btnCopy)
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

        self.scatter = self.ax.scatter(
            xvals,
            yvals,
            s=35,
            c=colors,
            alpha=0.7,
            picker=6,
        )

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
# OPEN WINDOW
# ==========================================================

_windows = []


def open_optuna_plot_window():
    w = OptunaPlotWindow()
    _windows.append(w)
    w.show()
    w.raise_()
    return w
