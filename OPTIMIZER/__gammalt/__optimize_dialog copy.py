# -*- coding: utf-8 -*-

# optimize_dialog.py

from logging import root
import os
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets, QtGui

from .optimize_worker import OptimizationWorker
from .optimize_state import OptimizationState
from .spreadsheet_utils import read_param_bounds

from oba_plots.cluster_plot import ShowClusterPlotDialog
from .__gammalt.__optimize_dialog_edit_targets import EditTargetsDialog

from .optimize_config import SPREADSHEET_NAME

from .optuna_plotting import open_optuna_plot_window

from .evaluation_service import EvaluationService

from .__gammalt.__scoring_panel import ScoringPanel

icon_path = os.path.join(os.path.dirname(__file__), "..", "icons")


DOCK_OBJECT_NAME = "OptimizeDialogDock"


class OptimizeDialogDock(QtWidgets.QDockWidget):

    weightsChanged = QtCore.Signal(float, float, float, float)
    planeChanged = QtCore.Signal(str)
    equalDistanceModeChanged = QtCore.Signal(str)

    pauseRequested = QtCore.Signal()
    resumeRequested = QtCore.Signal()

    requestStop = QtCore.Signal()

    def __init__(self, parent=None, params_info=None):
        super().__init__("Optimering", parent)
        self.setObjectName(DOCK_OBJECT_NAME)

        self.state = OptimizationState()

        self._prev_disabledebounce = None

        self.state.metric_targets = {
            "density": ["ALL"],
            "roundness": ["ALL"],
            "equal_distance": ["ALL"],
        }

        # threading
        self._thread = None
        self._worker = None
        self._running = False

        # slider debounce
        self._slider_timer = QtCore.QTimer(self)
        self._slider_timer.setSingleShot(True)
        self._slider_timer.timeout.connect(self._emit_weights)

        self._slider_active = False
        self._pending_weights = (0.25, 0.25, 0.25, 0.25)

        self._build_ui(params_info)
        self._connect_ui()

    # -------------------------------------------------------
    # UI
    # -------------------------------------------------------

    def _build_ui(self, params_info):
        central = QtWidgets.QWidget(self)
        self.setWidget(central)

        root = QtWidgets.QVBoxLayout(central)

        self.lblStatus = QtWidgets.QLabel("")
        self.lblWeights = QtWidgets.QLabel("")

        root.addWidget(self.lblStatus)
        root.addWidget(self.lblWeights)

        self._build_header(root)
        self._build_param_list(root, params_info)

        # self._build_sliders(root)

        self.scoringPanel = ScoringPanel(self)
        root.addWidget(self.scoringPanel)

        self._build_buttons(root)

    # -------------------------------------------------------

    def _build_header(self, root):
        row = QtWidgets.QHBoxLayout()

        self.comboPlane = QtWidgets.QComboBox()
        self.comboPlane.addItems(["XY", "XZ", "YZ"])

        self.comboEqMode = QtWidgets.QComboBox()
        self.comboEqMode.addItems(["2D", "3D"])
        self.comboEqMode.setCurrentIndex(1)

        row.addWidget(QtWidgets.QLabel("Plan:"))
        row.addWidget(self.comboPlane)

        row.addStretch()

        row.addWidget(QtWidgets.QLabel("Equal-distance:"))
        row.addWidget(self.comboEqMode)

        root.addLayout(row)

    # -------------------------------------------------------

    def _build_param_list(self, root, params_info):
        self.listParams = QtWidgets.QListWidget()
        self.listParams.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        root.addWidget(self.listParams)

        if params_info:
            for name, *_ in params_info:
                self.listParams.addItem(name)

    # -------------------------------------------------------
    # SLIDERS (FULL)
    # -------------------------------------------------------

    def _build_sliders(self, root):
        grp = QtWidgets.QGroupBox("Målvikter")
        grid = QtWidgets.QGridLayout()

        def make_row(metric_key, label, row):
            lbl = QtWidgets.QLabel(label)

            btnTargets = QtWidgets.QPushButton("ALL")
            btnTargets.setMinimumWidth(100)
            btnTargets.clicked.connect(lambda _, k=metric_key: self._edit_targets(k))

            sld = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            sld.setRange(0, 100)
            sld.setValue(50)

            val = QtWidgets.QLabel("0.25")

            grid.addWidget(lbl, row, 0)
            grid.addWidget(btnTargets, row, 1)
            grid.addWidget(sld, row, 2)
            grid.addWidget(val, row, 3)

            return sld, val, btnTargets

        self.sldCluster, self.lblCluster, self.btnClusterTargets = make_row("cluster_count", "Studs", 0)
        self.sldDensity, self.lblDensity, self.btnDensityTargets = make_row("density", "Densitet", 1)
        self.sldRoundness, self.lblRoundness, self.btnRoundTargets = make_row("roundness", "Rundhet", 2)
        self.sldEqual, self.lblEqual, self.btnEqualTargets = make_row("equal_distance", "Avstånd", 3)

        # self.sldCluster, self.lblCluster = make_row("cluster_count", "Studs", 0)
        # self.sldDensity, self.lblDensity = make_row("density", "Densitet", 1)
        # self.sldRoundness, self.lblRoundness = make_row("roundness", "Rundhet", 2)
        # self.sldEqual, self.lblEqual = make_row("equal_distance", "Avstånd", 3)

        for s in (self.sldCluster, self.sldDensity, self.sldRoundness, self.sldEqual):
            s.valueChanged.connect(self._update_weights)
            s.sliderPressed.connect(self._slider_pressed)
            s.sliderReleased.connect(self._slider_released)

        grp.setLayout(grid)
        root.addWidget(grp)

        for k in self.state.metric_targets.keys():
            self._update_target_button(k)

        self._update_weights()

    # -------------------------------------------------------
    # SLIDER LOGIK (DEBOUNCE + PAUSE)
    # -------------------------------------------------------

    def _slider_pressed(self):
        self.lblStatus.setText("Pause – justerar vikter")
        print("DEBUG: Slider pressed, pausing optimization")
        self._slider_active = True
        self._slider_timer.stop()

        # if self._running:
        #     self.pauseRequested.emit()

    def _slider_released(self):
        self.lblStatus.setText("Kör...")
        print("DEBUG: Slider released, resuming optimization with new weights")
        self._slider_active = False
        self._slider_timer.stop()

        if self._running:
            self.pauseRequested.emit()
            self._emit_weights()
            self.resumeRequested.emit()

    def _update_weights(self):
        d = self.sldDensity.value()
        r = self.sldRoundness.value()
        e = self.sldEqual.value()
        c = self.sldCluster.value()

        S = max(1e-6, d + r + e + c)

        wD, wR, wE, wC = d / S, r / S, e / S, c / S
        self._pending_weights = (wC, wD, wR, wE)

        self.lblDensity.setText(f"{wD:.2f}")
        self.lblRoundness.setText(f"{wR:.2f}")
        self.lblEqual.setText(f"{wE:.2f}")
        self.lblCluster.setText(f"{wC:.2f}")

        self.lblWeights.setText(f"C:{wC:.2f} D:{wD:.2f} R:{wR:.2f} E:{wE:.2f}")

        if self._running and not self._slider_active:
            self._slider_timer.start(120)

    def _emit_weights(self):
        if not self._running:
            return

        wC, wD, wR, wE = self._pending_weights
        self.weightsChanged.emit(wC, wD, wR, wE)

    # -------------------------------------------------------
    # TARGETS (LIVE UPDATE)
    # -------------------------------------------------------

    def _update_target_button(self, metric_key):
        targets = self.state.metric_targets.get(metric_key, ["ALL"])

        if targets == ["ALL"]:
            text = "ALL"
        else:
            text = "; ".join(targets)
            if len(text) > 25:
                text = text[:25] + "..."

        mapping = {
            "cluster_count": getattr(self, "btnClusterTargets", None),
            "density": getattr(self, "btnDensityTargets", None),
            "roundness": getattr(self, "btnRoundTargets", None),
            "equal_distance": getattr(self, "btnEqualTargets", None),
        }

        btn = mapping.get(metric_key)
        if not btn:
            return

        btn.setText(text)

        # ✅ tooltip med full lista
        btn.setToolTip("; ".join(targets))

        # ✅ visuellt highlight om inte ALL
        if targets != ["ALL"]:
            btn.setStyleSheet("background-color:#ffeaa7")
        else:
            btn.setStyleSheet("")

    def _edit_targets(self, metric_key):
        doc = App.ActiveDocument
        if not doc:
            return

        available = ["ALL"]
        for obj in doc.Objects:
            if hasattr(obj, "OpticalType"):
                available.append(obj.Label)

        dlg = EditTargetsDialog(
            self,
            metric_key,
            available,
            self.state.metric_targets.get(metric_key, ["ALL"]),
        )

        if dlg.exec_():
            selected = dlg.selected_targets() or ["ALL"]
            self.state.metric_targets[metric_key] = selected
            self._update_target_button(metric_key)

            if self._running and self._worker:
                self.pauseRequested.emit()
                self._worker.update_metric_targets(metric_key, selected)
                self.resumeRequested.emit()

    # -------------------------------------------------------
    # BUTTONS
    # -------------------------------------------------------

    def _build_buttons(self, root):
        row = QtWidgets.QHBoxLayout()

        self.btnOptunaPlot = self._make_button("Optuna-plot", "optuna_plot.svg")

        self.btnStart = self._make_button("Start", "run.svg")
        self.btnClusterPlot = self._make_button("Cluster Plot", "plot_ray_cluster.svg")

        # self.btnPlot = QtWidgets.QPushButton("Plot")

        row.addStretch()
        row.addWidget(self.btnOptunaPlot)
        row.addWidget(self.btnClusterPlot)
        row.addWidget(self.btnStart)

        root.addLayout(row)

    def _make_button(self, text, icon):
        btn = QtWidgets.QPushButton(text)
        p = os.path.join(icon_path, icon)
        btn.setIcon(QtGui.QIcon(p))
        return btn

    def _connect_ui(self):
        self.btnStart.clicked.connect(self._toggle)
        self.comboPlane.currentTextChanged.connect(self._on_plane)
        self.comboEqMode.currentIndexChanged.connect(self._on_eq)
        self.btnClusterPlot.clicked.connect(ShowClusterPlotDialog)
        self.btnOptunaPlot.clicked.connect(lambda: open_optuna_plot_window(ma_window=3, show_global=True))

    # -------------------------------------------------------
    # START / STOP
    # -------------------------------------------------------

    def _toggle(self):
        if not self._running:
            self._start()
        else:
            self._stop()

    def _start(self):
        doc = App.ActiveDocument
        if not doc:
            print("DEBUG: No active document")
            return

        params = [i.text() for i in self.listParams.selectedItems()]
        print(f"DEBUG: Selected params: {params}")
        if not params:
            print("DEBUG: No params selected, showing warning")
            QtWidgets.QMessageBox.warning(self, "Optimering", "Välj parametrar")
            return

        # Reset state for fresh run
        self.state.target_cluster_count = None
        self.state.best_score = -float("inf")
        self.state.best_params = None
        self.state.best_metrics = None
        self.state.history = []
        self.state.optimizer_state = None
        self.state.running = False
        self.state.paused = False

        # ✅ spara + sätt
        rc = doc.OBARayConfig
        self._prev_disabledebounce = rc.DisableDebounce
        rc.DisableDebounce = True

        bounds = self._read_bounds(doc, params)
        print(f"DEBUG: Bounds read: {bounds}")

        # ----------------------------
        # THREAD + WORKER
        # ----------------------------
        self._thread = QtCore.QThread(self)  # 🔥 parent viktigt

        self._worker = OptimizationWorker(self.state, params, bounds)
        self._worker.moveToThread(self._thread)

        # ----------------------------
        # EVALUATION SERVICE
        # ----------------------------
        self._eval_service = EvaluationService(self)  # 🔥 parent viktigt
        # self._eval_service = EvaluationService()
        # self._eval_service.moveToThread(self._thread)

        self._worker.requestEvaluate.connect(self._eval_service.evaluate)
        self._eval_service.evaluationReady.connect(self._worker.on_evaluated)

        # ----------------------------
        # THREAD LIFECYCLE
        # ----------------------------
        self._thread.started.connect(self._worker.start)

        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)

        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_finished)  # 🔥 VIKTIG

        # ----------------------------
        # UI SIGNALS
        # ----------------------------
        self.weightsChanged.connect(self._worker.update_weights)
        self.requestStop.connect(self._worker.stop)

        self.pauseRequested.connect(self._worker.pause)
        self.resumeRequested.connect(self._worker.resume)

        self.planeChanged.connect(self._worker.update_plane)
        self.equalDistanceModeChanged.connect(self._worker.update_equal_distance_mode)

        self._worker.progress.connect(self._on_progress)

        # ----------------------------
        # START
        # ----------------------------
        print("DEBUG: Starting thread")
        self._thread.start()
        # QtCore.QTimer.singleShot(0, self._worker.start)

        self._running = True
        self.btnStart.setText("Stop")
        self.btnStart.setIcon(QtGui.QIcon(os.path.join(icon_path, "stop.svg")))

        self.lblStatus.setText("Kör...")

        self._emit_weights()

    def _stop(self):
        self.lblStatus.setText("Stoppar...")
        self.btnStart.setEnabled(False)

        rc = App.ActiveDocument.OBARayConfig
        rc.DisableDebounce = self._prev_disabledebounce

        if self._worker:
            self.requestStop.emit()

            # säker fallback
            QtCore.QTimer.singleShot(500, self._force_cleanup)

    def _force_cleanup(self):
        print("⚠️ Force cleanup triggered")

        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)

        self._thread = None
        self._worker = None
        self._eval_service = None

        self._running = False
        self.btnStart.setText("Start")
        self.btnStart.setIcon(QtGui.QIcon(os.path.join(icon_path, "run.svg")))
        self.btnStart.setEnabled(True)
        self.lblStatus.setText("Avbruten")

    def _on_finished(self):
        self._thread = None
        self._worker = None
        self._eval_service = None

        self._running = False
        self.btnStart.setText("Start")
        self.btnStart.setEnabled(True)
        self.lblStatus.setText("Klar")

    def closeEvent(self, event: QtGui.QCloseEvent):
        """
        Called when the dock widget is closed.
        Ensures worker thread is properly stopped.
        """
        if self._running:
            print("🧹 OptimizeDialogDock closing – stopping worker")

            # 1) begär stopp
            try:
                self.requestStop.emit()
            except Exception:
                pass

            # 2) försök stänga tråden snyggt
            if self._thread and self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(1000)  # max 1 s

            self._thread = None
            self._worker = None
            self._eval_service = None
            self._running = False

        rc = App.ActiveDocument.OBARayConfig
        rc.DisableDebounce = self._prev_disabledebounce
        # ✅ låt Qt fortsätta stänga widgeten
        super().closeEvent(event)

    # -------------------------------------------------------

    def _on_plane(self, p):
        if self._running:
            self.planeChanged.emit(p)

    def _on_eq(self):
        mode = "2D" if self.comboEqMode.currentIndex() == 0 else "3D"
        if self._running:
            self.equalDistanceModeChanged.emit(mode)

    def _on_progress(self, info):
        if "score" in info:
            self.lblStatus.setText(f"Score: {info['score']:.4f}")

    def _read_bounds(self, doc, param_names):
        ss = doc.getObject(SPREADSHEET_NAME)
        info = read_param_bounds(ss) if ss else []
        m = {name: lohi for name, _, lohi, *_ in info}
        return {p: m.get(p, (0.0, 1.0)) for p in param_names}


# -------------------------------------------------------


def ShowOptimizeDialog():
    mw = Gui.getMainWindow()

    old = mw.findChild(QtWidgets.QDockWidget, DOCK_OBJECT_NAME)
    if old:
        mw.removeDockWidget(old)
        old.deleteLater()

    doc = App.ActiveDocument
    ss = doc.getObject(SPREADSHEET_NAME) if doc else None
    params_info = read_param_bounds(ss) if ss else None

    dock = OptimizeDialogDock(mw, params_info)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.show()
