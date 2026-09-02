# -*- coding: utf-8 -*-
# heatmap_viewer.py

import os
import numpy as np
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
from PySide.QtWidgets import QSizePolicy

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from .scan_db import HitsDB, get_doc_db_path

from oba_objects.oba_base import _trigger_ray_engine
from oba_rayengine.oba_ray_analyser import collect_ray_hits_and_stats

from .batch_runner import (
    apply_step_offset,
    restore_all_step_states,
    store_hits,
    find_batch_object,
    find_step_by_id,
    run_steps_for_batch,
)

DOCK_OBJECT_NAME = "BeamAbsorberHeatmapDock"


# ==========================================================
class BeamAbsorberHeatmapDock(QtWidgets.QDockWidget):
    # ==========================================================
    def __init__(self, parent=None):
        super().__init__("Heatmap Viewer", parent)
        self.setObjectName(DOCK_OBJECT_NAME)

        self.db = HitsDB(get_doc_db_path())
        self._last_mtime = None

        self._origin_offset = None
        self._commit_requested = False  # sätta via knappen "Comitt and Close"

        self.emitter_checks = {}
        self._current_moved_objects = ""

        self._moved_objects = []

        self._click_busy = False
        self._cancel = False

        self._build_ui()

        self._refresh_db()
        self._populate_steps()
        self._populate_targets()

        self.canvas2d.mpl_connect("button_press_event", self._on_2d_click)

        QtCore.QTimer.singleShot(0, self._target_changed)

        self._watch = QtCore.QTimer(self)
        self._watch.timeout.connect(self._maybe_refresh)
        self._watch.start(500)

    # ==========================================================
    # UI
    # ==========================================================
    def _build_ui(self):
        central = QtWidgets.QWidget(self)
        self.setWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        form = QtWidgets.QFormLayout()

        # DB
        db_row = QtWidgets.QHBoxLayout()
        self.lblDB = QtWidgets.QLabel("")

        self.btnDBRefresh = QtWidgets.QPushButton("↻")
        self.btnRun = QtWidgets.QPushButton("Run step")
        self.btnStop = QtWidgets.QPushButton("Stop")
        self.btnDelete = QtWidgets.QPushButton("Delete Step")
        self.btnCommitClose = QtWidgets.QPushButton("Commit & Close")

        db_row.addWidget(QtWidgets.QLabel("DB:"))
        db_row.addWidget(self.lblDB, 1)

        db_row.addWidget(self.btnDBRefresh)
        db_row.addSpacing(20)
        db_row.addWidget(self.btnRun)
        db_row.addWidget(self.btnStop)
        db_row.addWidget(self.btnDelete)

        db_row.addWidget(self.btnCommitClose)

        form.addRow(db_row)

        # Progress
        # --------------------------------------------------
        self.prog = QtWidgets.QProgressBar()
        self.lbl = QtWidgets.QLabel("")
        layout.addWidget(self.prog)
        layout.addWidget(self.lbl)

        self.comboStep = QtWidgets.QComboBox()
        form.addRow("Step:", self.comboStep)

        self.comboTarget = QtWidgets.QComboBox()
        form.addRow("Target:", self.comboTarget)

        self.comboValue = QtWidgets.QComboBox()
        self.comboValue.addItems(["Hits", "Power In", "Power Out"])
        form.addRow("Value:", self.comboValue)

        # Emitters
        self.emitterBox = QtWidgets.QGroupBox("Emitters")
        self.emitterLayout = QtWidgets.QVBoxLayout(self.emitterBox)
        form.addRow(self.emitterBox)

        # Options
        self.comboPlane = QtWidgets.QComboBox()
        self.comboPlane.addItems(["XY", "XZ", "YZ"])

        self.chkSmooth = QtWidgets.QCheckBox("Smooth")
        self.chkSmooth.setChecked(True)
        self.spinSmooth = QtWidgets.QSpinBox()
        self.spinSmooth.setRange(1, 10)
        self.spinSmooth.setValue(2)

        self.chkPercent = QtWidgets.QCheckBox("Show %")

        self.chkPlane2D = QtWidgets.QCheckBox("2D plane view")

        self.btnGotoMax = QtWidgets.QPushButton("Go to Max")

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Plane"))
        row.addWidget(self.comboPlane)
        row.addSpacing(15)
        row.addWidget(self.chkSmooth)
        row.addWidget(self.spinSmooth)
        row.addSpacing(15)
        row.addWidget(self.chkPercent)

        row.addSpacing(15)
        row.addWidget(self.chkPlane2D)
        row.addSpacing(15)
        row.addWidget(self.btnGotoMax)
        row.addStretch()

        self.lblMoved = QtWidgets.QLabel("Moved: -")
        form.addRow("Moving:", self.lblMoved)
        self.lblMoved.setText(self._current_moved_objects)

        form.addRow(row)
        layout.addLayout(form)

        # PLOTS
        plotRow = QtWidgets.QHBoxLayout()

        self.fig3d = Figure()
        self.canvas3d = FigureCanvas(self.fig3d)
        self.canvas3d.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.fig2d = Figure()
        self.canvas2d = FigureCanvas(self.fig2d)
        self.canvas2d.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        plotRow.addWidget(self.canvas3d)
        plotRow.addWidget(self.canvas2d)

        layout.addLayout(plotRow, 1)

        # signals
        self.btnGotoMax.clicked.connect(self._goto_maximum)

        self.comboStep.currentIndexChanged.connect(self._update_plot)
        self.comboTarget.currentIndexChanged.connect(self._target_changed)
        self.comboValue.currentIndexChanged.connect(self._update_plot)
        self.comboPlane.currentIndexChanged.connect(self._update_plot)
        self.chkSmooth.toggled.connect(self._update_plot)
        self.spinSmooth.valueChanged.connect(self._update_plot)
        self.chkPercent.toggled.connect(self._update_plot)
        self.chkPlane2D.toggled.connect(self._update_plot)

        self.btnRun.clicked.connect(self._run_single)
        self.btnStop.clicked.connect(self._stop_run)
        self.btnDelete.clicked.connect(self._delete_step)

        self.btnCommitClose.clicked.connect(self._commit_and_close)

    # ==========================================================
    # DB
    # ==========================================================
    def _refresh_db(self):
        path = get_doc_db_path()
        if self.db.path != path:
            self.db.close()
            self.db = HitsDB(path)
        self.lblDB.setText(os.path.basename(path))
        self.lblDB.setToolTip(path)

    def _delete_step(self):
        step_id = self.comboStep.currentText()
        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete step",
            f"Delete all scan data for:\n\n{step_id} ?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )

        if reply != QtWidgets.QMessageBox.Yes:
            return
        self.db.clear_step(step_id)
        self._populate_steps()
        self._update_plot()

    # ==========================================================
    def _populate_steps(self):
        self.comboStep.clear()
        self.comboStep.addItems(self.db.list_steps() or ["<none>"])

    def _populate_targets(self):
        self.comboTarget.clear()
        for name in self.db.list_target_objects():
            obj = App.ActiveDocument.getObject(name)
            if obj:
                self.comboTarget.addItem(obj.Label, name)

    def _populate_emitters(self):
        while self.emitterLayout.count():
            w = self.emitterLayout.takeAt(0).widget()
            if w:
                w.deleteLater()

        target = self.comboTarget.currentData()
        if not target:
            return

        self.emitter_checks = {}
        for em in self.db.list_emitters(target):
            chk = QtWidgets.QCheckBox(em)
            chk.setChecked(True)
            chk.toggled.connect(self._update_plot)
            self.emitterLayout.addWidget(chk)
            self.emitter_checks[em] = chk

    # ==========================================================

    def _run_single(self):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self._cancel = False

        try:
            doc = App.ActiveDocument
            batch = find_batch_object(doc)
            if not batch:
                QtWidgets.QMessageBox.warning(self, "Run", "No BatchGroup found")
                return

            step_id = self.comboStep.currentText()
            step_obj = find_step_by_id(doc, step_id)
            if not step_obj:
                return

            desired_offset = App.Vector(step_obj.StepOffset.x, step_obj.StepOffset.y, step_obj.StepOffset.z)

            self.prog.setValue(0)
            self.lbl.setText("Running...")

            run_steps_for_batch(batch, self.prog, self.lbl, pump_events_func=QtWidgets.QApplication.processEvents, stop_flag_func=lambda: self._cancel, only_step_id=step_id)

            if self._cancel:
                self.lbl.setText("Stopped")
                return

            # BatchRunner restores after tracing. Re-apply the heatmap position.
            step_obj.StepOffset = desired_offset
            moved_objects = apply_step_offset(step_obj)

            self._set_moved_objects(moved_objects)
            doc.recompute()

            try:
                self._last_mtime = os.path.getmtime(self.db.path)
            except OSError:
                self._last_mtime = None

            self._update_plot()
            self.lbl.setText("Done")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _stop_run(self):
        self._cancel = True

    def _commit_and_close(self):
        step_obj = find_step_by_id(App.ActiveDocument, self.comboStep.currentText())
        self._commit_requested = True

        self.close()

    def _target_changed(self):
        self._populate_emitters()
        self._update_plot()

    def _maybe_refresh(self):
        try:
            mtime = os.path.getmtime(self.db.path)
        except OSError:
            return

        if mtime != self._last_mtime:
            self._last_mtime = mtime
            self._update_plot()

    def _get_selected_emitters(self):
        return [name for name, checkbox in self.emitter_checks.items() if checkbox.isChecked()]

    def _set_moved_objects(self, moved_objects):
        self._moved_objects = list(moved_objects or [])
        self._current_moved_objects = ";".join(sorted(obj.Name for obj in self._moved_objects))
        self.lblMoved.setText(self._current_moved_objects or "Moved: -")

    # ==========================================================
    # CORE
    # ==========================================================

    def _update_plot(self):
        result = self._compute_field()
        if result is None:
            self._clear()
            return

        Xi, Yi, Vi = result
        self._plot_3d(Xi, Yi, Vi)

        if self.chkPlane2D.isChecked():
            self._plot_2d_plane(Xi, Yi, Vi)
        else:
            self._plot_2d_profile(Xi, Yi, Vi)

    def _compute_field(self):
        hit_target = self.comboTarget.currentData()
        step_id = self.comboStep.currentText()

        if not hit_target or step_id == "<none>":
            return None

        emitters = self._get_selected_emitters()
        if not emitters:
            return None

        X = Y = Z = V = None
        value_mode = self.comboValue.currentText()

        for emitter in emitters:
            data = self.db.read_grid(hit_target, emitter, step_id)
            if not data:
                continue

            WX, WY, WZ, _Xi, _Yi, _Zi, hits, power_in, power_out, move_object, _moved_objects = data

            if not WX or not move_object:
                continue

            if value_mode == "Hits":
                values = np.asarray(hits, dtype=float)
            elif value_mode == "Power In":
                values = np.asarray(power_in, dtype=float)
            else:
                values = np.asarray(power_out, dtype=float)

            selected_name = move_object[0]
            selected_object = App.ActiveDocument.getObject(selected_name)
            if selected_object is None:
                continue

            mask = np.asarray(move_object) == selected_name
            wx = np.asarray(WX)[mask]
            wy = np.asarray(WY)[mask]
            wz = np.asarray(WZ)[mask]
            values = values[mask]

            if V is None:
                X = selected_object.Placement.Base.x - wx
                Y = selected_object.Placement.Base.y - wy
                Z = selected_object.Placement.Base.z - wz
                V = values.copy()
            else:
                V += values

        if V is None or X is None:
            return None

        plane = self.comboPlane.currentText()
        if plane == "XY":
            px, py = X, Y
        elif plane == "XZ":
            px, py = X, Z
        else:
            px, py = Y, Z

        Xi, Yi = np.meshgrid(
            np.linspace(px.min(), px.max(), 60),
            np.linspace(py.min(), py.max(), 60),
        )

        Vi = np.zeros_like(Xi)
        for i in range(Xi.shape[0]):
            for j in range(Xi.shape[1]):
                distances = np.hypot(px - Xi[i, j], py - Yi[i, j])
                weights = 1.0 / (distances + 1e-6)
                Vi[i, j] = np.average(V, weights=weights)

        if self.chkSmooth.isChecked():
            Vi = self._median(Vi, 2 * self.spinSmooth.value() + 1)

        if self.chkPercent.isChecked():
            maximum = np.max(Vi)
            if maximum > 0:
                Vi = Vi / maximum * 100

        return Xi, Yi, Vi

    def _trace_and_store(self, step_obj, dx, dy, dz):
        _trigger_ray_engine(reason="batch_trace", source=None, force=True)

        hits, _stats = collect_ray_hits_and_stats(mode="final")

        store_hits(self.db, step_obj.Id, hits, dx, dy, dz, self._moved_objects)

        self.db.commit()

    def _plot_3d(self, Xi, Yi, Vi):
        self.fig3d.clear()
        ax = self.fig3d.add_subplot(111, projection="3d")

        # =========================
        # MAIN SURFACE
        # =========================
        ax.plot_surface(Xi, Yi, Vi, cmap="viridis", alpha=0.9)

        # bounds
        xmin, xmax = Xi.min(), Xi.max()
        ymin, ymax = Yi.min(), Yi.max()
        zmin, zmax = Vi.min(), Vi.max()

        mid_x_idx = Vi.shape[0] // 2
        mid_y_idx = Vi.shape[1] // 2

        # mid_x = (xmin + xmax) * 0.5
        # mid_y = (ymin + ymax) * 0.5

        step_obj = find_step_by_id(App.ActiveDocument, self.comboStep.currentText())
        mid_x = step_obj.StepOffset.x
        mid_y = step_obj.StepOffset.y

        # =========================
        # GHOST PLANES (TRUE PLANES)
        # =========================

        # --- X plane (vertical slice)
        Yp, Zp = np.meshgrid(np.linspace(ymin, ymax, 30), np.linspace(zmin, zmax, 30))
        Xp = np.full_like(Yp, mid_x)

        ax.plot_surface(Xp, Yp, Zp, color="white", alpha=0.15, edgecolor="none")

        # --- Y plane (vertical slice)
        Xp, Zp = np.meshgrid(
            np.linspace(xmin, xmax, 30),
            np.linspace(zmin, zmax, 30),
        )
        Yp = np.full_like(Xp, mid_y)

        ax.plot_surface(Xp, Yp, Zp, color="cyan", alpha=0.15, edgecolor="none")

        # =========================
        # PROFILE LINES (on surface)
        # =========================

        # X profile
        X_line_X = Xi[mid_x_idx, :]
        X_line_Y = Yi[mid_x_idx, :]
        X_line_Z = Vi[mid_x_idx, :]

        ax.plot(X_line_X, X_line_Y, X_line_Z, color="white", linewidth=2)

        # Y profile
        Y_line_X = Xi[:, mid_y_idx]
        Y_line_Y = Yi[:, mid_y_idx]
        Y_line_Z = Vi[:, mid_y_idx]

        ax.plot(Y_line_X, Y_line_Y, Y_line_Z, color="cyan", linewidth=2)

        # =========================
        # COSMETICS
        # =========================
        # ax.set_title("3D Heatmap + Profile Planes")

        self.canvas3d.draw_idle()

    def _plot_2d_profile(self, Xi, Yi, Vi):

        self.fig2d.clear()
        ax = self.fig2d.add_subplot(111)

        mid_x = Vi.shape[0] // 2
        mid_y = Vi.shape[1] // 2

        ax.plot(Xi[mid_x], Vi[mid_x], label="X profile")
        ax.plot(Yi[:, mid_y], Vi[:, mid_y], "--", label="Y profile")

        step_obj = find_step_by_id(App.ActiveDocument, self.comboStep.currentText())

        # spar ner orginal vid första visningen
        if step_obj and not self._origin_offset:
            self._origin_offset = App.Vector(step_obj.StepOffset)

        if step_obj:
            if self.comboPlane.currentText() == "XY":
                current_x = self._origin_offset.x - step_obj.StepOffset.x
                current_y = self._origin_offset.y - step_obj.StepOffset.y

            elif self.comboPlane.currentText() == "XZ":
                current_x = self._origin_offset.x - step_obj.StepOffset.x
                current_y = self._origin_offset.z - step_obj.StepOffset.z

            else:
                current_x = self._origin_offset.y - step_obj.StepOffset.y
                current_y = self._origin_offset.z - step_obj.StepOffset.z

            # ax.scatter(self._current_heatmap_x, self._current_heatmap_y, s=120, color="red", edgecolors="black", label="Start")

            ax.scatter(current_x, current_y, s=120, color="red", edgecolors="black", label="Start")
        if hasattr(self, "_max_x"):
            ax.scatter(self._max_x, self._max_y, s=250, marker="*", color="yellow", edgecolors="black", label="Max")

        ax.legend()
        ax.grid(True)

        self.canvas2d.draw_idle()

    def _plot_2d_plane(self, Xi, Yi, Vi):
        self.fig2d.clear()
        ax = self.fig2d.add_subplot(111)

        # heatmap
        c = ax.pcolormesh(Xi, Yi, Vi, cmap="viridis", shading="auto")

        self.fig2d.colorbar(c, ax=ax)

        ax.set_title("2D Plane (clickable)")
        ax.set_aspect("equal")

        # spara data för klick
        self._plane_Xi = Xi
        self._plane_Yi = Yi
        self._plane_Vi = Vi

        # connect klick
        # self.canvas2d.mpl_connect("button_press_event", self._on_2d_click)

        self.canvas2d.draw_idle()

    def _on_2d_click(self, event):
        if self._click_busy:
            return
        if event.inaxes is None or not self.chkPlane2D.isChecked():
            return
        if event.xdata is None or event.ydata is None:
            return

        self._click_busy = True
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self.setEnabled(False)

        try:
            step_obj, dx, dy, dz = self._apply_heatmap_position(event.xdata, event.ydata)
            self._trace_and_store(step_obj, dx, dy, dz)
            self._update_plot()
        finally:
            self.setEnabled(True)
            QtWidgets.QApplication.restoreOverrideCursor()
            self._click_busy = False

    def _apply_heatmap_position(self, x, y):

        # self._current_heatmap_x = x
        # self._current_heatmap_y = y

        plane = self.comboPlane.currentText()

        if plane == "XY":
            dx, dy, dz = x, y, 0.0
        elif plane == "XZ":
            dx, dy, dz = x, 0.0, y
        else:
            dx, dy, dz = 0.0, x, y

        step_obj = find_step_by_id(
            App.ActiveDocument,
            self.comboStep.currentText(),
        )

        default_offset = step_obj.StepOffset

        dx = default_offset.x - dx
        dy = default_offset.y - dy
        dz = default_offset.z - dz

        step_obj.StepOffset = App.Vector(dx, dy, dz)
        moved_objects = apply_step_offset(step_obj)
        self._set_moved_objects(moved_objects)

        return step_obj, dx, dy, dz

    def _goto_maximum(self):

        result = self._compute_field()
        if result is None:
            return
        Xi, Yi, Vi = result
        idx = np.unravel_index(np.argmax(Vi), Vi.shape)
        x = float(Xi[idx])
        y = float(Yi[idx])

        self._max_x = x
        self._max_y = y

        print(f"[MAX] X={x:.3f} " f"Y={y:.3f} " f"V={float(Vi[idx]):.3f}")

        step_obj, dx, dy, dz = self._apply_heatmap_position(x, y)
        self._trace_and_store(step_obj, dx, dy, dz)
        self._update_plot()

    # ==========================================================
    def _median(self, data, k):
        pad = k // 2
        p = np.pad(data, pad, mode="edge")
        out = np.zeros_like(data)
        for i in range(data.shape[0]):
            for j in range(data.shape[1]):
                out[i, j] = np.median(p[i : i + k, j : j + k])
        return out

    def _clear(self):
        self.fig3d.clear()
        self.fig2d.clear()
        self.canvas3d.draw_idle()
        self.canvas2d.draw_idle()

    def closeEvent(self, event):
        try:
            # BatchRunner owns the snapshots and the restore operation.
            if not self._commit_requested:
                restore_all_step_states(App.ActiveDocument, recompute=True)

        except Exception as e:
            App.Console.PrintError(f"Restore failed: {e}\n")

        # self.db.close()
        super().closeEvent(event)


# ==========================================================
def ShowHeatmapViewer():
    mw = Gui.getMainWindow()
    old = mw.findChild(QtWidgets.QDockWidget, DOCK_OBJECT_NAME)
    if old:
        mw.removeDockWidget(old)
        old.deleteLater()

    dock = BeamAbsorberHeatmapDock(mw)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.setFloating(True)  # viktigt
    dock.show()
    return dock
