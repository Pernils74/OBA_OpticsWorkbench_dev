# -*- coding: utf-8 -*-
import optuna
import FreeCAD as App

from PySide import QtCore, QtWidgets
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import matplotlib.pyplot as plt

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

        controls.addWidget(QtWidgets.QLabel("X:"))
        controls.addWidget(self.cmbX)

        controls.addWidget(QtWidgets.QLabel("Y:"))
        controls.addWidget(self.cmbY)

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

    def study_changed_old(self):
        self.current_study_name = self.cmbStudy.currentText()
        self.cmbX.clear()
        self.cmbY.clear()
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

    # ==========================================================
    # DATA
    # ==========================================================

    def _get_trials(self, study):
        ignored = self.ignored_trials if self.chkHide.isChecked() else set()

        if self.chkPareto.isChecked():
            trials = [t for t in study.best_trials if t.number not in ignored]
        else:
            trials = [t for t in study.trials if t.state.name == "COMPLETE" and t.number not in ignored]

        return trials

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

        # ignored = self.ignored_trials if self.chkHide.isChecked() else set()
        # all_trials = [t for t in study.trials if t.state.name == "COMPLETE" and t.number not in ignored]
        # pareto_trials = [t for t in study.best_trials if t.number not in ignored]

        if not trials:
            self.ax.clear()
            self.ax.set_title("No data")
            self.canvas.draw()
            return

        self.plot_trials = trials

        # build metric arrays
        n_metrics = len(trials[0].values)
        ys = [[] for _ in range(n_metrics)]

        for t in trials:
            for i, v in enumerate(t.values):
                ys[i].append(v)

        # metric_names = study.user_attrs.get("metric_names", [f"Metric {i}" for i in range(n_metrics)])
        metric_names = study.user_attrs.get("metric_names")
        if not metric_names:
            # ✅ fallback från trial-data
            sample = trials[0].user_attrs.get("metrics", {})
            metric_names = list(sample.keys())

        self.ax.clear()

        # init combos
        if self.cmbX.count() == 0:
            for name in metric_names:
                self.cmbX.addItem(name)
                self.cmbY.addItem(name)

            if len(metric_names) >= 2:
                self.cmbX.setCurrentIndex(0)
                self.cmbY.setCurrentIndex(1)
        # print(
        #     "combo counts:",
        #     self.cmbX.count(),
        #     self.cmbY.count(),
        # )

        ix = self.cmbX.currentIndex()
        iy = self.cmbY.currentIndex()

        if ix == iy and len(metric_names) > 1:
            iy = (ix + 1) % len(metric_names)
            self.cmbY.blockSignals(True)
            self.cmbY.setCurrentIndex(iy)
            self.cmbY.blockSignals(False)

        xvals = ys[ix]
        yvals = ys[iy]

        # scatter
        self.scatter = self.ax.scatter(
            xvals,
            yvals,
            s=35,
            color="tab:blue",
            alpha=0.7,
            picker=6,
            # picker=True,
            # pickradius=6,
        )

        self.ax.set_xlabel(metric_names[ix])
        self.ax.set_ylabel(metric_names[iy])
        self.ax.set_title(self.current_study_name)

        # highlight selected
        if self.selected_trial and self.selected_trial in self.plot_trials:
            t = self.selected_trial
            self.ax.scatter(
                t.values[ix],
                t.values[iy],
                color="red",
                s=100,
                edgecolors="black",
                linewidths=1.5,
                zorder=10,
            )

        # Pareto line (visual)
        if self.chkPareto.isChecked() and len(xvals) > 2:
            pts = sorted(zip(xvals, yvals))
            xs_sorted = [p[0] for p in pts]
            ys_sorted = [p[1] for p in pts]

            self.ax.plot(xs_sorted, ys_sorted, color="red", linewidth=2)

        self.ax.grid(True)
        self.canvas.draw()

    # ==========================================================
    # INTERACTION
    # ==========================================================

    def apply_trial(self, trial):
        self.selected_trial = trial

        print(f"[plot] Apply trial {trial.number}")
        print("Params:", trial.params)

        try:
            apply_cad_params(trial.params)

            doc = App.ActiveDocument
            if doc:
                doc.recompute()

            self.redraw()

        except Exception as e:
            print("CAD error:", e)

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
