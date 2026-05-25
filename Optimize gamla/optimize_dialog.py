# -*- coding: utf-8 -*-
# optimize_dialog.py — VERSION där Plan + Equal-distance-läge ligger på samma rad

import os
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets, QtGui

from .optimize_worker import OptimizationWorker
from .optimize_evaluator import EvaluationService
from .optimize_state import OptimizationState
from .spreadsheet_utils import read_param_bounds

# from __sparas__.oba_rayhits.sa_plot_dialog import ShowRayhitsPlot
from oba_plots.power_density_plot import ShowPowerDensityPlotDialog


from .optimize_config import (
    SPREADSHEET_NAME,
    SOURCE_SHEET_NAME,
    RESULT_SHEET_NAME,
)

DOCK_OBJECT_NAME = "OptimizeDialogDock"


class OptimizeDialogDock(QtWidgets.QDockWidget):

    # UI → Worker
    weightsChanged = QtCore.Signal(float, float, float)
    planeChanged = QtCore.Signal(str)
    equalDistanceModeChanged = QtCore.Signal(str)

    # pause/resume
    pauseRequested = QtCore.Signal()
    resumeRequested = QtCore.Signal()

    # control
    applyBest = QtCore.Signal(dict)
    requestStop = QtCore.Signal()
    requestShutdown = QtCore.Signal()

    def __init__(self, parent=None, params_info=None):
        super().__init__("Optimering", parent)
        self.setObjectName(DOCK_OBJECT_NAME)

        # slider debounce
        self._slider_timer = QtCore.QTimer(self)
        self._slider_timer.setSingleShot(True)
        self._slider_timer.timeout.connect(self._emit_weights_after_slider)
        self._slider_active = False
        self._pending_weights = (0.33, 0.33, 0.33)

        self.state = OptimizationState()
        self._thread = None
        self._worker = None
        self._running = False

        self._eval_service = EvaluationService(self)

        self._build_ui(params_info)
        self._connect_ui()

    # -------------------------------------------------------
    # BUILD UI
    # -------------------------------------------------------
    def _build_ui(self, params_info):
        central = QtWidgets.QWidget(self)
        self.setWidget(central)

        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self._build_status(root)
        self._build_header_with_eqdist(root)  # <-- NY
        self._build_param_list(root, params_info)
        self._build_sliders(root)
        self._build_sheet_section(root)
        self._build_buttons(root)

    # -------------------------------------------------------
    def _build_status(self, root):
        self.lblStatus = QtWidgets.QLabel("")
        self.lblWeights = QtWidgets.QLabel("")
        root.addWidget(self.lblStatus)
        root.addWidget(self.lblWeights)

    # -------------------------------------------------------
    # NEW HEADER: Plan + Equal-distance on same row
    # -------------------------------------------------------
    def _build_header_with_eqdist(self, root):

        row = QtWidgets.QHBoxLayout()

        # --- PLAN (left) ---
        lblPlane = QtWidgets.QLabel("Plan:")
        self.comboPlane = QtWidgets.QComboBox()
        self.comboPlane.addItems(["XY", "XZ", "YZ"])
        self.comboPlane.setCurrentText(self.state.plane)

        planLay = QtWidgets.QHBoxLayout()
        planLay.addWidget(lblPlane)
        planLay.addWidget(self.comboPlane)

        # --- EQUAL DISTANCE (right) ---
        lblEq = QtWidgets.QLabel("Equal-distance:")
        self.comboEqMode = QtWidgets.QComboBox()
        self.comboEqMode.addItems(["2D (valt plan)", "3D (riktigt avstånd)"])
        self.comboEqMode.setCurrentIndex(1)

        eqLay = QtWidgets.QHBoxLayout()
        eqLay.addWidget(lblEq)
        eqLay.addWidget(self.comboEqMode)

        # --- LAYOUT ---
        row.addLayout(planLay)
        row.addStretch()
        row.addLayout(eqLay)

        root.addLayout(row)

    # -------------------------------------------------------
    def _build_param_list(self, root, params_info):
        self.listParams = QtWidgets.QListWidget()
        self.listParams.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        root.addWidget(self.listParams, 1)

        if params_info:
            for name, *_ in params_info:
                self.listParams.addItem(name)

    # -------------------------------------------------------
    def _build_sliders(self, root):
        grp = QtWidgets.QGroupBox("Målvikter")
        v = QtWidgets.QVBoxLayout(grp)
        grid = QtWidgets.QGridLayout()

        def make_row(label, row):
            lbl = QtWidgets.QLabel(label)
            sld = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            sld.setRange(0, 100)
            sld.setValue(50)
            val = QtWidgets.QLabel("0.33")
            val.setAlignment(QtCore.Qt.AlignRight)
            grid.addWidget(lbl, row, 0)
            grid.addWidget(sld, row, 1)
            grid.addWidget(val, row, 2)
            return sld, val

        self.sldDensity, self.lblDensityWeight = make_row("Densitet:", 0)
        self.sldRoundness, self.lblRoundnessWeight = make_row("Rundhet / Isotropi:", 1)
        self.sldEqualDist, self.lblEqualDistWeight = make_row("Lika klusteravstånd:", 2)

        # connect
        for s in (self.sldDensity, self.sldRoundness, self.sldEqualDist):
            s.valueChanged.connect(self._update_three_weights)
            s.sliderPressed.connect(self._on_any_slider_pressed)
            s.sliderReleased.connect(self._on_any_slider_released)

        v.addLayout(grid)
        root.addWidget(grp)
        self._update_three_weights()

    # -------------------------------------------------------
    def _build_sheet_section(self, root):
        row = QtWidgets.QHBoxLayout()
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("Använda kalkylblad:"))

        self.lblSheets = QtWidgets.QLabel()
        self.lblSheets.setStyleSheet("color:#1a73e8; font-size:13px;")
        left.addWidget(self.lblSheets)

        row.addLayout(left)
        row.addStretch()
        root.addLayout(row)
        self._update_sheet_status()

    # -------------------------------------------------------
    def _build_buttons(self, root):
        row = QtWidgets.QHBoxLayout()

        self.btnRayhitsPlot = self._make_button("Kluster Plot", "rayhits_plot.svg")
        self.btnOptunaPlot = self._make_button("Optuna-plot", "optuna_plot.svg")
        self.btnNewStart = QtWidgets.QPushButton("Starta en ny")
        self.btnStart = QtWidgets.QPushButton("Starta")
        self.btnClose = QtWidgets.QPushButton("Stäng")

        row.addStretch()
        row.addWidget(self.btnRayhitsPlot)
        row.addWidget(self.btnOptunaPlot)
        row.addWidget(self.btnNewStart)
        row.addWidget(self.btnStart)
        row.addWidget(self.btnClose)

        root.addLayout(row)

    def _make_button(self, text, icon):
        btn = QtWidgets.QPushButton(text)
        p = os.path.join(os.path.dirname(__file__), "..", "icons", icon)
        btn.setIcon(QtGui.QIcon(p))
        return btn

    # -------------------------------------------------------
    # CONNECT
    # -------------------------------------------------------
    def _connect_ui(self):
        self.comboPlane.currentTextChanged.connect(self._on_plane_changed)
        self.comboEqMode.currentIndexChanged.connect(self._on_eq_mode_changed)

        self.btnRayhitsPlot.clicked.connect(ShowPowerDensityPlotDialog)
        self.btnOptunaPlot.clicked.connect(self._open_optuna_plot_window)

        self.btnNewStart.clicked.connect(self._start_new_clicked)
        self.btnStart.clicked.connect(self._toggle_start)
        self.btnClose.clicked.connect(self.close)

    def _on_eq_mode_changed(self):
        mode = "2D" if self.comboEqMode.currentIndex() == 0 else "3D"
        if self._running and self._worker:
            self.equalDistanceModeChanged.emit(mode)

    # -------------------------------------------------------
    # SLIDER HANDLING
    # -------------------------------------------------------
    def _on_any_slider_pressed(self):
        self._slider_active = True
        try:
            self._slider_timer.stop()
        except:
            pass
        if self._running and self._worker:
            self.pauseRequested.emit()

    def _on_any_slider_released(self):
        self._slider_active = False
        try:
            self._slider_timer.stop()
        except:
            pass
        if self._running and self._worker:
            wD, wR, wE = self._pending_weights
            self.weightsChanged.emit(wD, wR, wE)
            self.resumeRequested.emit()

    def _update_three_weights(self):
        d = self.sldDensity.value()
        r = self.sldRoundness.value()
        e = self.sldEqualDist.value()
        S = max(1e-6, d + r + e)
        wD, wR, wE = d / S, r / S, e / S
        self._pending_weights = (wD, wR, wE)

        self.lblDensityWeight.setText(f"{wD:.2f}")
        self.lblRoundnessWeight.setText(f"{wR:.2f}")
        self.lblEqualDistWeight.setText(f"{wE:.2f}")
        self.lblWeights.setText(f"Densitet: {wD:.2f} | Rundhet: {wR:.2f} | Klusteravst.: {wE:.2f}")

        if self._running and self._worker and not self._slider_active:
            self._slider_timer.start(150)

    def _emit_weights_after_slider(self):
        if self._slider_active:
            return
        if not self._running or not self._worker:
            return
        wD, wR, wE = self._pending_weights
        self.weightsChanged.emit(wD, wR, wE)

    # -------------------------------------------------------
    # PLANE
    # -------------------------------------------------------
    def _on_plane_changed(self, plane):
        if self._running and self._worker:
            self.planeChanged.emit(plane)
        self.lblStatus.setText(f"Plan valt: {plane}")

    # -------------------------------------------------------
    # WORKER MANAGEMENT
    # -------------------------------------------------------
    def _start_new_clicked(self):
        self._shutdown_worker(True)
        self._running = False
        with self.state.lock:
            self.state.required_clusters = None
            self.state.hitscores = {}
            self.state.global_score = None
            self.state.history.clear()
        self._start_worker(True)
        self.lblStatus.setText("Startar ny körning…")

    def _toggle_start(self):
        if not self._running:
            self._start_worker(False)
        else:
            self._stop_worker()

    def _start_worker(self, fresh=False):
        self._shutdown_worker(True)

        doc = App.ActiveDocument
        if not doc:
            QtWidgets.QMessageBox.warning(self, "Optimering", "Ingen aktiv modell.")
            return

        param_names = self._selected_param_names()
        if not param_names:
            QtWidgets.QMessageBox.warning(self, "Optimering", "Välj minst en parameter.")
            return

        self.state.active_params = list(param_names)
        bounds = self._read_bounds(doc, param_names)
        self.state.plane = self.comboPlane.currentText()

        self._thread = QtCore.QThread(self)
        self._worker = OptimizationWorker(self.state, param_names, bounds)
        self._worker.fresh = fresh
        self._worker.moveToThread(self._thread)

        self._connect_worker_signals()

        self._thread.started.connect(self._worker.start)
        self._thread.start()

        self._running = True
        self.btnStart.setText("Stoppa")

        self.planeChanged.emit(self.state.plane)
        self._on_eq_mode_changed()

    def _stop_worker(self):
        if self._worker:
            self.requestStop.emit()
            self.lblStatus.setText("Stoppar…")

    def _shutdown_worker(self, block=False):
        try:
            if self._worker:
                self.requestShutdown.emit()
        except:
            pass
        try:
            if self._thread:
                self._thread.quit()
                if block:
                    self._thread.wait(2000)
        except:
            pass
        self._worker = None
        self._thread = None

    def _connect_worker_signals(self):
        self.requestStop.connect(self._worker.stop)
        self.requestShutdown.connect(self._worker.shutdown)

        self._worker.requestEvaluate.connect(self._eval_service.evaluate)
        self._eval_service.evaluationReady.connect(self._worker.on_evaluated)

        self.weightsChanged.connect(self._worker.update_weights)
        self.applyBest.connect(self._eval_service.applyBest)

        self.planeChanged.connect(self._worker.update_plane)
        self.equalDistanceModeChanged.connect(self._worker.update_equal_distance_mode)

        self.pauseRequested.connect(self._worker.pause)
        self.resumeRequested.connect(self._worker.resume)

        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)

    # -------------------------------------------------------
    # PROGRESS
    # -------------------------------------------------------
    def _on_progress(self, info):
        t = info.get("type")
        if t == "step":
            sc = info.get("score")
            if sc is not None:
                self.lblStatus.setText(f"Score: {sc:.4f}")
            else:
                self.lblStatus.setText(info.get("reason", ""))
        elif t == "probe":
            self.lblStatus.setText(f"Ursprungscluster: {info.get('required_total')}")
        elif t == "best_params":
            s = info.get("score")
            if s is not None:
                self.lblStatus.setText(f"Återställde bästa (score={s:.4f})")
            else:
                self.lblStatus.setText("Återställde bästa")

    def _on_finished(self):
        self._running = False
        self.btnStart.setText("Starta")
        self.lblStatus.setText("Klar")
        self._thread = None
        self._worker = None

    # -------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------
    def _selected_param_names(self):
        return [i.text() for i in self.listParams.selectedItems()]

    def _read_bounds(self, doc, param_names):
        ss = doc.getObject(SPREADSHEET_NAME)
        info = read_param_bounds(ss) if ss else []
        m = {name: lohi for name, _, lohi, *_ in info}
        return {p: m.get(p, (0.0, 1.0)) for p in param_names}

    def _update_sheet_status(self):
        doc = App.ActiveDocument
        if not doc:
            self.lblSheets.setText("Ingen aktiv modell")
            return

        def ok(n):
            return "✓" if doc.getObject(n) else "✗"

        self.lblSheets.setText(f"{SPREADSHEET_NAME}: {ok(SPREADSHEET_NAME)}\n" f"{SOURCE_SHEET_NAME}: {ok(SOURCE_SHEET_NAME)}\n" f"{RESULT_SHEET_NAME}: {ok(RESULT_SHEET_NAME)}")

    # -------------------------------------------------------
    def closeEvent(self, event):
        self._shutdown_worker(True)
        self._running = False
        event.accept()

    # -------------------------------------------------------
    def _open_optuna_plot_window(self):
        try:
            from .optuna_plotting import open_optuna_plot_window
            from .optimize_worker import db_path

            open_optuna_plot_window(db_uri=db_path, ma_window=3, show_global=True)
            self.lblStatus.setText("Optuna-plotfönster öppnades.")
        except Exception as e:
            App.Console.PrintError(f"[UI] Plot error: {e}\n")
            self.lblStatus.setText(f"Kunde inte öppna plot: {e}")


# -------------------------------------------------------
def ShowOptimizeDialog():
    mw = Gui.getMainWindow()
    old = mw.findChild(QtWidgets.QDockWidget, DOCK_OBJECT_NAME)
    if old:
        mw.removeDockWidget(old)
        old.deleteLater()

    doc = App.ActiveDocument
    ss = doc.getObject("Spreadsheet") if doc else None
    params_info = read_param_bounds(ss) if ss else None

    dock = OptimizeDialogDock(mw, params_info)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.show()
    return dock


def CloseOptimizeDialog():
    mw = Gui.getMainWindow()
    old = mw.findChild(QtWidgets.QDockWidget, DOCK_OBJECT_NAME)
    if old:
        mw.removeDockWidget(old)
        old.deleteLater()


def OptimizeDialogCmd():
    ShowOptimizeDialog()
