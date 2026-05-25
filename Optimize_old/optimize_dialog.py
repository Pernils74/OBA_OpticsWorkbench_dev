# -*- coding: utf-8 -*-


# ▼ Density       Targets: Mirror_001, Mirror_002   [====|---] 0.40   [Edit]
# ▼ Roundness     Targets: Mirror_*                 [=== |----] 0.30   [Edit]
# ▼ Equal dist    Targets: ALL                      [=== |----] 0.30


# Select targets for Density:

# ☑ Mirror_001
# ☑ Mirror_002
# ☐ Mirror_003
# --------------------------------
# [ Apply ]   [ Cancel ]


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
from oba_plots.cluster_plot import ShowClusterPlotDialog
from .optimize_dialog_edit_targets import EditTargetsDialog

from .optimize_config import (
    SPREADSHEET_NAME,
    SOURCE_SHEET_NAME,
    RESULT_SHEET_NAME,
)

DOCK_OBJECT_NAME = "OptimizeDialogDock"


class OptimizeDialogDock(QtWidgets.QDockWidget):

    # UI → Worker
    weightsChanged = QtCore.Signal(float, float, float, float)
    # semantik: cluster, density, roundness, equal_distance
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

        self.state = OptimizationState()

        # RayConfig debounce backup
        self._rayconfig_obj = None
        self._rayconfig_prev_disabled = None

        self.state.metric_targets = {
            "density": ["ALL"],
            "roundness": ["ALL"],
            "equal_distance": ["ALL"],
        }

        # slider debounce
        self._slider_timer = QtCore.QTimer(self)
        self._slider_timer.setSingleShot(True)
        self._slider_timer.timeout.connect(self._emit_weights_after_slider)
        self._slider_active = False
        self._pending_weights = (0.33, 0.33, 0.33)

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
        lblPlane = QtWidgets.QLabel("Optimerings Plan (global coords.):")
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

        self._metric_rows = {}

        def make_row(metric_key, label_text, row):
            lbl = QtWidgets.QLabel(label_text)

            # Target summary
            lblTargets = QtWidgets.QLabel("Targets: ALL")
            lblTargets.setStyleSheet("color:#666; font-size:11px;")

            # Slider
            sld = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            sld.setRange(0, 100)
            sld.setValue(50)

            val = QtWidgets.QLabel("0.33")
            val.setAlignment(QtCore.Qt.AlignRight)

            # Edit button
            btnEdit = QtWidgets.QPushButton("⋯")
            btnEdit.setFixedSize(20, 20)
            # btnEdit.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogDetailedView))
            # btnEdit.setText("⋯")
            btnEdit.setStyleSheet("padding: 0px;")

            btnEdit.clicked.connect(lambda _, k=metric_key: self._edit_targets(k))

            # Layout
            grid.addWidget(lbl, row, 0)
            grid.addWidget(lblTargets, row, 1)
            grid.addWidget(btnEdit, row, 2)
            grid.addWidget(sld, row, 3)
            grid.addWidget(val, row, 4)

            self._metric_rows[metric_key] = {
                "slider": sld,
                "label": val,
                "targets_label": lblTargets,
            }

            return sld, val

        # ---- 1) STRUKTURELL METRIC (WHITE CELL) ----
        self.sldClusterCount, self.lblClusterCountWeight = make_row(
            "cluster_count",
            "Studs‑stabilitet (antal kluster)",
            0,
        )
        self.sldClusterCount.setValue(100)
        self.sldClusterCount.setToolTip("Styr hur hårt optimeringen håller samma antal ljusstudsar.\n" "Hög vikt = strikt white‑cell‑struktur.\n" "Lägre vikt = tillåter ändring av studs‑antal.")

        # ---- 2) KVALITETSMETRICS ----
        self.sldDensity, self.lblDensityWeight = make_row("density", "Densitet", 1)
        self.sldRoundness, self.lblRoundnessWeight = make_row("roundness", "Rundhet / Isotropi", 2)
        self.sldEqualDist, self.lblEqualDistWeight = make_row("equal_distance", "Lika klusteravstånd", 3)

        grid.setColumnStretch(0, 0)  # Textlabel
        grid.setColumnStretch(1, 1)  # Targets (får växa lite)
        grid.setColumnStretch(2, 0)  # Edit-knapp (låst)
        grid.setColumnStretch(3, 3)  # Slider (ska få mest plats)
        grid.setColumnStretch(4, 0)  # Vikt-label

        for s in (self.sldClusterCount, self.sldDensity, self.sldRoundness, self.sldEqualDist):
            s.valueChanged.connect(self._update_weights)
            s.sliderPressed.connect(self._on_any_slider_pressed)
            s.sliderReleased.connect(self._on_any_slider_released)

        v.addLayout(grid)
        root.addWidget(grp)

        self._update_weights()
        self._update_target_labels()

    def _edit_targets(self, metric_key):
        doc = App.ActiveDocument
        if not doc:
            return

        # Samla tillgängliga targets från optiska objekt
        available = ["ALL"]
        for obj in doc.Objects:
            if hasattr(obj, "OpticalType") and obj.OpticalType not in ("RayConfig"):
                available.append(obj.Label)

        current = self.state.metric_targets.get(metric_key, ["ALL"])

        dlg = EditTargetsDialog(self, metric_key, available, current)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            selected = dlg.selected_targets()
            if not selected:
                selected = ["ALL"]

            self.state.metric_targets[metric_key] = selected
            self._update_target_labels()

            # Live update till worker
            if self._running and self._worker:
                self.pauseRequested.emit()
                self._worker.update_metric_targets(metric_key, selected)
                self.resumeRequested.emit()

    def _update_target_labels(self):
        for metric, row in self._metric_rows.items():
            targets = self.state.metric_targets.get(metric, ["ALL"])
            txt = ", ".join(targets[:3])
            if len(targets) > 3:
                txt += f" (+{len(targets)-3})"
            row["targets_label"].setText(f"Targets: {txt}")

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

        self.btnRayhitsPlot.clicked.connect(ShowClusterPlotDialog)
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
            wC, wD, wR, wE = self._pending_weights
            self.weightsChanged.emit(wC, wD, wR, wE)
            self.resumeRequested.emit()

    def _update_weights(self):
        d = self.sldDensity.value()
        r = self.sldRoundness.value()
        e = self.sldEqualDist.value()
        c = self.sldClusterCount.value()

        S = max(1e-6, d + r + e + c)
        wD, wR, wE, wC = d / S, r / S, e / S, c / S

        self._pending_weights = (wC, wD, wR, wE)

        self.lblDensityWeight.setText(f"{wD:.2f}")
        self.lblRoundnessWeight.setText(f"{wR:.2f}")
        self.lblEqualDistWeight.setText(f"{wE:.2f}")
        self.lblClusterCountWeight.setText(f"{wC:.2f}")

        self.lblWeights.setText(f"Studs‑stabilitet: {wC:.2f} | " f"Densitet: {wD:.2f} | " f"Rundhet: {wR:.2f} | " f"Avstånd: {wE:.2f}")

    def _update_three_weights_old(self):
        d = self.sldDensity.value()
        r = self.sldRoundness.value()
        e = self.sldEqualDist.value()
        c = self.sldClusterCount.value()
        S = max(1e-6, d + r + e + c)
        wD, wR, wE, wC = d / S, r / S, e / S, c / S
        self._pending_weights = (wC, wD, wR, wE)

        self.lblDensityWeight.setText(f"{wD:.2f}")
        self.lblRoundnessWeight.setText(f"{wR:.2f}")
        self.lblEqualDistWeight.setText(f"{wE:.2f}")
        self.lblClusterCountWeight.setText(f"{wC:.2f}")

        self.lblWeights.setText(f"Densitet: {wD:.2f} | " f"Rundhet: {wR:.2f} | " f"Avstånd: {wE:.2f} | " f"Studs‑stabilitet: {wC :.2f}")

        if self._running and self._worker and not self._slider_active:
            self._slider_timer.start(150)

    def _emit_weights_after_slider(self):
        if self._slider_active:
            return
        if not self._running or not self._worker:
            return
        wC, wD, wR, wE = self._pending_weights
        self.weightsChanged.emit(wC, wD, wR, wE)

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
            self.state.target_cluster_count = None
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

        if self.state.target_cluster_count is None:
            self.lblStatus.setText("Kör baseline…")

        self.state.active_params = list(param_names)
        bounds = self._read_bounds(doc, param_names)
        self.state.plane = self.comboPlane.currentText()

        self._thread = QtCore.QThread(self)
        self._worker = OptimizationWorker(self.state, param_names, bounds)
        self._worker.fresh = fresh
        self._worker.moveToThread(self._thread)

        self._connect_worker_signals()

        self._disable_rayconfig_debounce()  # För att inte debounce skall störa optimeirngen

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
            self._restore_rayconfig_debounce()

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
    # Rayconfig settings
    # -------------------------------------------------------

    def _disable_rayconfig_debounce(self):
        doc = App.ActiveDocument
        if not doc:
            return

        for obj in doc.Objects:
            if getattr(obj, "OpticalType", None) == "RayConfig":
                if hasattr(obj, "DisableDebounce"):
                    self._rayconfig_obj = obj
                    self._rayconfig_prev_disabled = obj.DisableDebounce
                    obj.DisableDebounce = True
                break

    def _restore_rayconfig_debounce(self):

        if self._rayconfig_obj and self._rayconfig_prev_disabled is not None:
            try:
                self._rayconfig_obj.DisableDebounce = self._rayconfig_prev_disabled
            except Exception as e:
                App.Console.PrintWarning(f"[OptimizeDialog] Kunde inte återställa RayConfig debounce: {e}\n")

        self._rayconfig_obj = None
        self._rayconfig_prev_disabled = None

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

        elif t == "baseline":
            # Körs exakt en gång efter initialkörningen
            n = info.get("cluster_count")
            if n is not None:
                self.lblStatus.setText(f"Baseline fastställd: {n} ljusstudsar")

        elif t == "best_params":
            s = info.get("score")
            if s is not None:
                self.lblStatus.setText(f"Återställde bästa (score = {s:.4f})")
            else:
                self.lblStatus.setText("Återställde bästa")

        elif t == "error":
            # Hårda fel (t.ex. inga giltiga kluster i baseline)
            self.lblStatus.setText(info.get("reason", "Okänt fel"))

    def _on_finished(self):
        self._restore_rayconfig_debounce()

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
