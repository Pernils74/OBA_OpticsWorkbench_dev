# -*- coding: utf-8 -*-

# optimize_dialog.py

from logging import root
import os
import FreeCAD as App
import FreeCADGui as Gui
from OPTIMIZER.__slider_row import SliderRow
from PySide import QtCore, QtWidgets, QtGui

from .optimize_worker import OptimizationWorker
from .optimize_state import OptimizationState
from .spreadsheet_utils import read_param_bounds

from oba_plots.cluster_plot import ShowClusterPlotDialog

# from .optimize_dialog_edit_targets import EditTargetsDialog

from .optimize_config import SPREADSHEET_NAME
from .optuna_plotting import open_optuna_plot_window

from .evaluation_service import EvaluationService

# from .scoring_panel import ScoringPanel


from .target_weights_widget import TargetWeightsWidget

icon_path = os.path.join(os.path.dirname(__file__), "..", "icons")


DOCK_OBJECT_NAME = "OptimizeDialogDock"
_optimize_dock_instance = None


class OptimizeDialogDock(QtWidgets.QDockWidget):

    # weightsChanged = QtCore.Signal(float, float, float, float)
    weightsChanged = QtCore.Signal(object)

    pauseRequested = QtCore.Signal()
    resumeRequested = QtCore.Signal()

    requestStop = QtCore.Signal()

    def __init__(self, parent=None, params_info=None):
        super().__init__("Optimering", parent)
        self.setObjectName(DOCK_OBJECT_NAME)

        self.state = OptimizationState()

        self._prev_disabledebounce = None

        # threading
        self._thread = None
        self._worker = None
        self._running = False

        # slider debounce
        self._slider_timer = QtCore.QTimer(self)
        self._slider_timer.setSingleShot(True)
        self._slider_timer.timeout.connect(self._emit_weights)

        self._build_ui(params_info)

    # -------------------------------------------------------
    # UI
    # -------------------------------------------------------

    def _build_ui(self, params_info):
        central = QtWidgets.QWidget(self)
        self.setWidget(central)

        root = QtWidgets.QVBoxLayout(central)

        # --- status ---
        self.lblStatus = QtWidgets.QLabel("")
        self.lblWeights = QtWidgets.QLabel("")

        root.addWidget(self.lblStatus)
        root.addWidget(self.lblWeights)

        # --- parametrar ---
        self._build_param_list(root, params_info)

        # --- target weights ---
        self.targetWeights = TargetWeightsWidget(self)
        root.addWidget(self.targetWeights)

        # ✅ koppling direkt
        self.targetWeights.weightsChanged.connect(self._on_weights_changed)

        # --- buttons ---
        row = QtWidgets.QHBoxLayout()

        self.btnOptunaPlot = self._make_button("Optuna-plot", "optuna_plot.svg")
        self.btnClusterPlot = self._make_button("Cluster Plot", "plot_ray_cluster.svg")
        self.btnStart = self._make_button("Start", "run.svg")

        row.addWidget(self.btnOptunaPlot)
        row.addWidget(self.btnClusterPlot)
        row.addStretch()
        row.addWidget(self.btnStart)

        root.addLayout(row)

        # ✅ koppla signals direkt här istället för separat metod
        self.btnStart.clicked.connect(self._toggle)
        self.btnClusterPlot.clicked.connect(ShowClusterPlotDialog)
        self.btnOptunaPlot.clicked.connect(lambda: open_optuna_plot_window(ma_window=3, show_global=True))

    def _make_button(self, text, icon):
        btn = QtWidgets.QPushButton(text)
        p = os.path.join(icon_path, icon)
        btn.setIcon(QtGui.QIcon(p))
        return btn

    # -------------------------------------------------------
    # BUTTONS
    # -------------------------------------------------------

    def _build_param_list(self, root, params_info):
        self.listParams = QtWidgets.QListWidget()
        self.listParams.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)

        self.listParams.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.listParams.customContextMenuRequested.connect(self._on_param_context_menu)
        # QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+D"), self.listParams, activated=self.listParams.clearSelection)
        root.addWidget(self.listParams)

        if params_info:
            for name, *_ in params_info:
                self.listParams.addItem(name)
        # ✅ efter att items finns

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

    # -------------------------------------------------------
    # EMITTING WEIGHTS FROM SLIDERS
    # -------------------------------------------------------
    def _on_weights_changed(self, payload):
        # payload:
        #
        # {
        #     "entries":[
        #         {
        #             "metric":"density",
        #             "raw":50,
        #             "normalized":0.33,
        #             "targets":["Lens001"],
        #             "Plane" : "XY"
        #         }
        #     ]
        # }

        print("new weights is emitted")

        self._pending_weights = payload
        if self._running:
            self._slider_timer.start(120)

    def _emit_weights(self):
        if not self._running:
            return

        if not hasattr(self, "_pending_weights"):
            return

        self.weightsChanged.emit(self._pending_weights)

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

        self._pending_weights = self.targetWeights.get_payload()
        # self.weightsChanged.emit(self._pending_weights)
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


def ShowOptimizeDialog_old():
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
