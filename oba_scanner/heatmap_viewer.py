# -*- coding: utf-8 -*-
# heatmap_viewer.py

import os
from unittest import result
import numpy as np
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
from PySide.QtWidgets import QSizePolicy

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


from .scan_db import HitsDB, get_doc_db_path

from oba_objects.oba_base import _trigger_ray_engine
from oba_rayengine.oba_ray_analyser import collect_ray_hits_and_stats, get_emitted_power


from .batch_runner import (
    apply_step_offset,
    restore_all_step_states,
    store_hits,
    find_batch_object,
    find_step_by_id,
    run_steps_for_batch,
)

DOCK_OBJECT_NAME = "BeamAbsorberHeatmapDock"

_PLANE_AXIS_INDICES = {
    "XY": (0, 1),
    "XZ": (0, 2),
    "YZ": (1, 2),
}


def _get_plane_axis_indices(plane):
    try:
        return _PLANE_AXIS_INDICES[plane]
    except KeyError as exc:
        raise ValueError(f"Unsupported plane: {plane}") from exc


def get_plane_axes(plane, x, y, z):
    coordinates = (x, y, z)
    axis1_index, axis2_index = _get_plane_axis_indices(plane)
    return coordinates[axis1_index], coordinates[axis2_index]


def get_plane_offset(step_offset, plane):
    return get_plane_axes(
        plane,
        step_offset.x,
        step_offset.y,
        step_offset.z,
    )


def apply_plane_delta(offset, plane, axis1_delta, axis2_delta):
    new_offset = App.Vector(offset)
    axis_indices = _get_plane_axis_indices(plane)
    axis_names = ("x", "y", "z")

    for axis_index, delta in zip(axis_indices, (axis1_delta, axis2_delta)):
        axis_name = axis_names[axis_index]
        setattr(new_offset, axis_name, getattr(new_offset, axis_name) - delta)

    return new_offset


# DB
#  └─ absoluta world coordinates

# compute_field
#  └─ RBF i absoluta koordinater

# Viewer
#  └─ räknar current-relativa deltan

# GotoMax
#  └─ jobbar med current ↔ RBF max


# Convert world coordinates into coordinates relative to
# the current object position and build an RBF field.


def compute_field(
    doc,
    db,
    target,
    step_obj,
    plane="XY",
    value_mode="Power In",
    emitters=None,
    grid_size=60,
    rbf_function="thin_plate",  # "linear",
    rbf_smooth=0.0,
):
    import numpy as np
    from scipy.interpolate import Rbf

    if target is None or step_obj is None:
        return None

    if emitters is None:
        emitters = db.list_emitters(target)

    X = Y = Z = V = None
    for emitter in emitters:
        data = db.read_grid(target, emitter, step_obj.Id)
        if not data:
            continue

        WX, WY, WZ, hits, power_in, power_out, move_object, _moved_objects = data
        if not WX or not move_object:
            continue

        if value_mode == "Hits":
            values = np.asarray(hits, dtype=float)
        elif value_mode == "Power In":
            values = np.asarray(power_in, dtype=float)
        else:
            values = np.asarray(power_out, dtype=float)

        selected_name = move_object[0]
        selected_object = doc.getObject(selected_name)

        if selected_object is None:
            continue

        mask = np.asarray(move_object) == selected_name
        wx = np.asarray(WX)[mask]
        wy = np.asarray(WY)[mask]
        wz = np.asarray(WZ)[mask]
        values = values[mask]

        if V is None:
            # Beräkna råa absoluta world-koordinater för mätpunkterna
            X = selected_object.Placement.Base.x - wx
            Y = selected_object.Placement.Base.y - wy
            Z = selected_object.Placement.Base.z - wz
            V = values.copy()
        else:
            V += values

    if V is None:
        return None

    # -------------------------------------------------------------
    # 1. HITTA NU-POSITIONEN (CURRENT ABSOLUT) FÖR VALT PLAN
    # -------------------------------------------------------------
    px_abs, py_abs = get_plane_axes(plane, X, Y, Z)
    current_abs_x, current_abs_y = get_plane_offset(step_obj.StepOffset, plane)

    # -------------------------------------------------------------
    # 2. SKAPA DELTA-KOORDINATER (Relativt till Current som blir 0.0)
    # -------------------------------------------------------------
    px_delta = px_abs - current_abs_x
    py_delta = py_abs - current_abs_y

    # fix för att inte det skall driva
    px_delta = px_abs
    py_delta = py_abs

    # Unika punkter för att säkra stabil RBF
    pts = np.round(np.column_stack([px_delta, py_delta]), 9)
    _, unique_idx = np.unique(pts, axis=0, return_index=True)
    px_delta = px_delta[unique_idx]
    py_delta = py_delta[unique_idx]
    V = V[unique_idx]

    # -------------------------------------------------------------
    # 3. RUTNÄT OCH INTERPOLATION (I DELTA-RYMD)
    # -------------------------------------------------------------
    Xi_delta, Yi_delta = np.meshgrid(
        np.linspace(px_delta.min(), px_delta.max(), grid_size),
        np.linspace(py_delta.min(), py_delta.max(), grid_size),
    )

    rbf = Rbf(px_delta, py_delta, V, function=rbf_function, smooth=rbf_smooth)
    Vi = rbf(Xi_delta, Yi_delta)

    axis_names = ("X", "Y", "Z")
    axis1_index, axis2_index = _get_plane_axis_indices(plane)

    return {
        "Xi": Xi_delta,  # 2D Grid med Delta-X (0.0 i centrum)
        "Yi": Yi_delta,  # 2D Grid med Delta-Y (0.0 i centrum)
        "Vi": Vi,  # Interpolerade intensiteter
        "px": px_delta,  # Insamlade mätpunkter (Delta-X)
        "py": py_delta,  # Insamlade mätpunkter (Delta-Y)
        "V": V,  # Råa mätvärden
        "axis1": axis_names[axis1_index],
        "axis2": axis_names[axis2_index],
        "current_abs": (current_abs_x, current_abs_y),  # Sparat för GoToMax
    }


# ==========================================================
class BeamAbsorberHeatmapDock(QtWidgets.QDialog):  # QDockWidget
    # ==========================================================

    def __init__(self, parent=None):

        super().__init__(parent)

        # def __init__(self, parent=None):
        #     super().__init__("Heatmap Viewer", parent)
        self.setObjectName(DOCK_OBJECT_NAME)
        self.setWindowTitle("Heatmap Viewer")
        # self.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)

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

    # ==========================================================
    # UI
    # ==========================================================
    def _build_ui(self):
        # Skapa huvudlayouten direkt för fönstret (QDialog använder setLayout)
        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()

        # DB-raden
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

        # Progress och Statusmeddelanden
        # --------------------------------------------------
        self.prog = QtWidgets.QProgressBar()
        self.lbl = QtWidgets.QLabel("")
        layout.addLayout(form)  # Lägg till formuläret i huvudlayouten först
        layout.addWidget(self.prog)
        layout.addWidget(self.lbl)

        # Nytt formulärblock för parametrar och alternativ
        form_opts = QtWidgets.QFormLayout()

        self.comboStep = QtWidgets.QComboBox()
        form_opts.addRow("Step:", self.comboStep)

        self.comboTarget = QtWidgets.QComboBox()
        form_opts.addRow("Target:", self.comboTarget)

        self.comboValue = QtWidgets.QComboBox()
        self.comboValue.addItems(["Hits", "Power In", "Power Out"])
        form_opts.addRow("Value:", self.comboValue)

        # Emitters GroupBox
        self.emitterBox = QtWidgets.QGroupBox("Emitters")
        self.emitterLayout = QtWidgets.QVBoxLayout(self.emitterBox)
        form_opts.addRow(self.emitterBox)

        # Inställningar för plan, range och knappar
        self.comboPlane = QtWidgets.QComboBox()
        self.comboPlane.addItems(["XY", "XZ", "YZ"])

        self.spinRange = QtWidgets.QDoubleSpinBox()
        self.spinRange.setRange(0.01, 100.0)
        self.spinRange.setDecimals(2)
        self.spinRange.setSingleStep(0.05)
        self.spinRange.setValue(0.40)

        self.chkPercent = QtWidgets.QCheckBox("Show % of emitted rays/power")
        self.chkPlane2D = QtWidgets.QCheckBox("2D plane view")
        self.btnGotoMax = QtWidgets.QPushButton("Go to Max")

        row_opts = QtWidgets.QHBoxLayout()
        row_opts.addWidget(QtWidgets.QLabel("Plane"))
        row_opts.addWidget(self.comboPlane)
        row_opts.addSpacing(15)
        row_opts.addWidget(QtWidgets.QLabel("Range"))
        row_opts.addWidget(self.spinRange)
        row_opts.addSpacing(15)
        row_opts.addWidget(self.chkPercent)
        row_opts.addSpacing(15)
        row_opts.addWidget(self.chkPlane2D)
        row_opts.addSpacing(15)
        row_opts.addWidget(self.btnGotoMax)
        row_opts.addStretch()

        self.lblMoved = QtWidgets.QLabel("Moved: -")
        form_opts.addRow("Moving:", self.lblMoved)
        self.lblMoved.setText(self._current_moved_objects)

        form_opts.addRow(row_opts)
        layout.addLayout(form_opts)

        # PLOTS (Matplotlib fönster)
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

        # Sätt hela layouten till QDialog-fönstret
        self.setLayout(layout)

        # Koppla signaler
        self.btnGotoMax.clicked.connect(self._goto_maximum)
        self.spinRange.valueChanged.connect(self._update_plot)

        self.comboStep.currentIndexChanged.connect(self._update_plot)
        self.comboTarget.currentIndexChanged.connect(self._target_changed)
        self.comboValue.currentIndexChanged.connect(self._update_plot)
        self.comboPlane.currentIndexChanged.connect(self._update_plot)
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

    def refresh_from_external_change(self):
        self._refresh_db()
        self._update_plot()

    def _update_plot(self):
        result = self._compute_field()
        if result is None:
            self._clear()
            return

        Xi = result["Xi"]
        Yi = result["Yi"]
        Vi = result["Vi"]
        raw_px = result["px"]
        raw_py = result["py"]
        raw_v = result["V"]

        # Xi, Yi, Vi = result
        self._plot_3d(Xi, Yi, Vi, raw_px, raw_py, raw_v)

        if self.chkPlane2D.isChecked():
            self._plot_2d_plane(Xi, Yi, Vi)
        else:
            self._plot_2d_profile(Xi, Yi, Vi, raw_px, raw_py, raw_v)

    def _compute_field(self):
        hit_target = self.comboTarget.currentData()
        step_id = self.comboStep.currentText()
        step_obj = find_step_by_id(App.ActiveDocument, step_id)

        result = compute_field(
            doc=App.ActiveDocument,
            db=self.db,
            target=hit_target,
            step_obj=step_obj,
            plane=self.comboPlane.currentText(),
            value_mode=self.comboValue.currentText(),
            emitters=self._get_selected_emitters(),
            grid_size=60,
            rbf_smooth=0.0,
        )

        if result is None:
            self._clear()
            return

        Xi = result["Xi"]
        Yi = result["Yi"]
        Vi = result["Vi"]
        raw_v = np.asarray(result["V"], dtype=float).copy()

        if self.chkPercent.isChecked():

            emitted_power = 0.0
            emitted_rays = 0

            for emitter in self._get_selected_emitters():
                p, r = get_emitted_power(emitter)
                emitted_power += p
                emitted_rays += r

            value_mode = self.comboValue.currentText()

            if value_mode in ("Power In", "Power Out"):
                if emitted_power > 1e-12:
                    scale = 100.0 / emitted_power
                    Vi *= scale
                    raw_v *= scale

            elif value_mode == "Hits":
                if emitted_rays > 0:
                    scale = 100.0 / emitted_rays
                    Vi *= scale
                    raw_v *= scale

        # return Xi, Yi, Vi
        return {
            "Xi": Xi,
            "Yi": Yi,
            "Vi": Vi,
            "px": result["px"],
            "py": result["py"],
            "V": raw_v,
            # "emitters": emitters,
        }
        # return result["Xi"], result["Yi"], result["Vi"]

    def _trace_and_store(self, step_obj, dx, dy, dz):
        _trigger_ray_engine(reason="batch_trace", source=None, force=True)

        hits, _stats = collect_ray_hits_and_stats(mode="final")

        store_hits(self.db, step_obj.Id, hits, self._moved_objects)

        self.db.commit()

    def _plot_3d(self, Xi, Yi, Vi, raw_px, raw_py, raw_v):
        self.fig3d.clear()
        ax = self.fig3d.add_subplot(111, projection="3d")

        step_obj = find_step_by_id(App.ActiveDocument, self.comboStep.currentText())
        # if not step_obj or not self._origin_offset:
        #     ax.plot_surface(Xi, Yi, Vi, cmap="viridis", alpha=0.9)
        #     self.canvas3d.draw_idle()
        #     return

        if not step_obj:
            self.canvas3d.draw_idle()
            return

        # 1. Ytan plottas direkt med rena delta-koordinater från compute_field
        ax.plot_surface(Xi, Yi, Vi, cmap="viridis", alpha=0.8)

        # Hämta gränser för att dimensionera ghost-planen korrekt
        xmin, xmax = Xi.min(), Xi.max()
        ymin, ymax = Yi.min(), Yi.max()
        zmin, zmax = Vi.min(), Vi.max()

        # Nu-positionen (Current) motsvarar cellen närmast (0,0) i delta-griddet
        current_idx = np.unravel_index(np.argmin(Xi**2 + Yi**2), Xi.shape)
        row, col = current_idx[0], current_idx[1]

        # 2. Skapa och rita transparenta ghost planes genom aktuellt läge (0, 0)
        # Vertikalt plan längs Y-axeln skuren vid X = 0.0
        Yp, Zp = np.meshgrid(np.linspace(ymin, ymax, 30), np.linspace(zmin, zmax, 30))
        Xp = np.full_like(Yp, 0.0)
        ax.plot_surface(Xp, Yp, Zp, color="white", alpha=0.15, edgecolor="none", zorder=1)

        # Vertikalt plan längs X-axeln skuren vid Y = 0.0
        Xp, Zp = np.meshgrid(np.linspace(xmin, xmax, 30), np.linspace(zmin, zmax, 30))
        Yp = np.full_like(Xp, 0.0)
        ax.plot_surface(Xp, Yp, Zp, color="cyan", alpha=0.15, edgecolor="none", zorder=1)

        # 3. Profiler skurna genom nuvarande position (0,0) på ytan
        ax.plot(Xi[row, :], Yi[row, :], Vi[row, :], color="white", linewidth=2.5, label="X profile", zorder=4)
        ax.plot(Xi[:, col], Yi[:, col], Vi[:, col], color="cyan", linewidth=2.5, label="Y profile", zorder=4)

        # 4. Karaktäristiska punkter ( RBF Max och DB Max)
        raw_max_idx = np.argmax(raw_v)
        ax.scatter(raw_px[raw_max_idx], raw_py[raw_max_idx], raw_v[raw_max_idx], color="yellow", s=150, marker="*", edgecolors="black", label="DB Max", zorder=5)

        interp_idx = np.unravel_index(np.argmax(Vi), Vi.shape)
        ax.scatter(Xi[interp_idx], Yi[interp_idx], Vi[interp_idx], color="black", s=150, marker="*", edgecolors="white", label="RBF Max", zorder=5)

        # 5. Råa mätpunkter (px, py, V) tagna direkt från databasen via compute_field
        ax.scatter(raw_px, raw_py, raw_v, color="red", s=40, depthshade=False, edgecolors="black", alpha=0.8, label="DB Points", zorder=3)

        # Axelinställningar och visning
        ax.set_xlabel("Axis 1 Δ")
        ax.set_ylabel("Axis 2 Δ")
        ax.set_zlabel(self.comboValue.currentText())

        ax.legend()
        self.canvas3d.draw_idle()

    def _plot_3d_old(self, Xi, Yi, Vi, raw_px, raw_py, raw_v):
        self.fig3d.clear()
        ax = self.fig3d.add_subplot(111, projection="3d")

        step_obj = find_step_by_id(App.ActiveDocument, self.comboStep.currentText())
        if not step_obj or not self._origin_offset:
            ax.plot_surface(Xi, Yi, Vi, cmap="viridis", alpha=0.9)
            self.canvas3d.draw_idle()
            return

        # Ytan plottas direkt med rena delta-koordinater från compute_field
        ax.plot_surface(Xi, Yi, Vi, cmap="viridis", alpha=0.9)

        xmin, xmax = Xi.min(), Xi.max()
        ymin, ymax = Yi.min(), Yi.max()
        zmin, zmax = Vi.min(), Vi.max()

        # Nu-positionen motsvarar den cell som ligger närmast (0,0) i delta-griddet
        current_idx = np.unravel_index(np.argmin(Xi**2 + Yi**2), Xi.shape)
        row, col = current_idx[0], current_idx[1]

        # Ghost planes genom (0, 0)
        Yp, Zp = np.meshgrid(np.linspace(ymin, ymax, 30), np.linspace(zmin, zmax, 30))
        Xp = np.full_like(Yp, 0.0)
        ax.plot_surface(Xp, Yp, Zp, color="white", alpha=0.15, edgecolor="none")

        Xp, Zp = np.meshgrid(np.linspace(xmin, xmax, 30), np.linspace(zmin, zmax, 30))
        Yp = np.full_like(Xp, 0.0)
        ax.plot_surface(Xp, Yp, Zp, color="cyan", alpha=0.15, edgecolor="none")

        # Profiler skurna genom nuvarande position (0,0)
        ax.plot(Xi[row, :], Yi[row, :], Vi[row, :], color="white", linewidth=2, label="X profile")
        ax.plot(Xi[:, col], Yi[:, col], Vi[:, col], color="cyan", linewidth=2, label="Y profile")

        # Karaktäristiska punkter (allt ritas stabilt i delta-rymd)
        ax.scatter(0.0, 0.0, float(Vi[row, col]), color="red", s=200, edgecolors="black", label="Current (0,0)")

        raw_idx = np.argmax(raw_v)
        ax.scatter(raw_px[raw_idx], raw_py[raw_idx], raw_v[raw_idx], color="yellow", s=150, marker="*", label="DB Max")

        interp_idx = np.unravel_index(np.argmax(Vi), Vi.shape)
        ax.scatter(Xi[interp_idx], Yi[interp_idx], Vi[interp_idx], color="black", s=150, marker="*", label="RBF Max")

        # Råa historiska mätpunkter
        ax.scatter(raw_px, raw_py, raw_v, color="red", s=40, depthshade=False, label="DB Points")
        ax.legend(loc="upper right")
        ax.legend()
        self.canvas3d.draw_idle()

    def _plot_2d_profile(self, Xi, Yi, Vi, raw_px, raw_py, raw_v):
        self.fig2d.clear()
        ax = self.fig2d.add_subplot(111)

        step_obj = find_step_by_id(App.ActiveDocument, self.comboStep.currentText())
        if not step_obj:
            self.canvas2d.draw_idle()
            return

        # Index för nuvarande (0,0) och interpolerat RBF Max
        cur_idx = np.unravel_index(np.argmin(Xi**2 + Yi**2), Xi.shape)
        max_idx = np.unravel_index(np.argmax(Vi), Vi.shape)

        # 1D-profiler skurna genom nuvarande position (0,0)
        ax.plot(Xi[cur_idx[0]], Vi[cur_idx[0]], color="blue", linewidth=2, label="Current Axis 1 Profile")
        ax.plot(Yi[:, cur_idx[1]], Vi[:, cur_idx[1]], color="red", linewidth=2, label="Current Axis 2 Profile")

        # 1D-profiler skurna genom det beräknade optimala RBF Maxmet
        ax.plot(Xi[max_idx[0]], Vi[max_idx[0]], "--", color="lightblue", alpha=0.7, label="Best Axis 1 Profile")
        ax.plot(Yi[:, max_idx[1]], Vi[:, max_idx[1]], "--", color="orange", alpha=0.7, label="Best Axis 2 Profile")

        # Markera nollpunkten (komponentens nuvarande läge)
        ax.scatter(0.0, 0.0, s=180, color="red", edgecolors="black", zorder=10, label="Current")

        # Horisontella linjer för bästa uppmätta vs interpolerade värden
        raw_max_v = float(np.max(raw_v))
        ax.axhline(raw_max_v, color="orange", linestyle=":", linewidth=2, label="DB Best")

        interp_max_v = float(np.max(Vi))
        ax.axhline(interp_max_v, color="black", linestyle="--", linewidth=2, label="RBF Best")

        if self.chkPercent.isChecked():
            ax.axhline(100.0, color="green", linestyle="--", linewidth=2, label="100 % Emitted")

        # Markera hur långt bort (förskjutning) RBF-Max ligger i förhållande till 0.0
        rbf_max_x = float(Xi[max_idx])
        rbf_max_y = float(Yi[max_idx])
        ax.scatter(rbf_max_x, 0.0, s=250, marker="*", color="yellow", edgecolors="black", zorder=11, label="RBF Max Position")

        # Sätt en tydlig rubrik med exakt förflyttningsförslag
        ax.set_title(f"Suggested Move: Axis 1 Δ={rbf_max_x:.3f}  Axis 2 Δ={rbf_max_y:.3f}")

        plot_range = self.spinRange.value()
        ax.set_xlim(-plot_range, plot_range)
        ax.legend()
        ax.legend(loc="upper right")
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
            step_id = self.comboStep.currentText()
            step_obj = find_step_by_id(App.ActiveDocument, step_id)
            if step_obj:
                # Eftersom vyn visar rena deltan, är event.xdata och event.ydata
                # exakt det avstånd (det delta) som vi ska flytta oss från nuvarande position!
                delta_x = event.xdata
                delta_y = event.ydata

                # Beräkna ny offset, flytta objekten och hämta de modifierade komponenterna
                step_obj, new_offset = self._apply_heatmap_position(step_obj, delta_x, delta_y)

                # Kör raytrace och spara på den nya positionen
                self._trace_and_store(step_obj, new_offset.x, new_offset.y, new_offset.z)
                self._update_plot()
        finally:
            self.setEnabled(True)
            QtWidgets.QApplication.restoreOverrideCursor()
            self._click_busy = False

    def _apply_heatmap_position(self, step_obj, delta_x, delta_y):
        plane = self.comboPlane.currentText()
        new_offset = apply_plane_delta(
            step_obj.StepOffset,
            plane,
            delta_x,
            delta_y,
        )

        step_obj.StepOffset = new_offset

        moved_objects = apply_step_offset(step_obj)
        self._set_moved_objects(moved_objects)

        return step_obj, new_offset

    def _apply_heatmap_position_old(self, step_obj, delta_x, delta_y):
        plane = self.comboPlane.currentText()

        # Vi drar bort deltat eftersom förflyttningsriktningen i StepOffset
        # rör sig i motsatt riktning mot hur mätmatrisen förskjuts i compute_field.
        new_offset = apply_plane_delta(
            step_obj.StepOffset,
            plane,
            delta_x,
            delta_y,
        )

        # Uppdatera FreeCAD-komponentens faktiska läge i scenen
        step_obj.StepOffset = new_offset
        moved_objects = apply_step_offset(step_obj)
        self._set_moved_objects(moved_objects)

        return step_obj, new_offset

    def _goto_maximum(self):
        result = self._compute_field()
        if result is None:
            print("[GOTO MAX] No data available to compute maximum.")
            return

        Xi = result["Xi"]
        Yi = result["Yi"]
        Vi = result["Vi"]

        # Eftersom Xi och Yi i det nya koordinatsystemet redan är rena deltan (0.0 = där vi står nu),
        # så motsvarar koordinaten vid max_idx direkt sträckan (deltat) till toppen!
        idx = np.unravel_index(np.argmax(Vi), Vi.shape)
        delta_x = float(Xi[idx])
        delta_y = float(Yi[idx])

        step_id = self.comboStep.currentText()
        step_obj = find_step_by_id(App.ActiveDocument, step_id)
        if not step_obj:
            return

        print(f"[GOTO MAX] Delta-förflyttning till topp: ΔX={delta_x:.3f}, ΔY={delta_y:.3f}")

        # Använd samma strömlinjeformade metod som 2D-klicket för att flytta komponenten det beräknade deltat
        step_obj, new_offset = self._apply_heatmap_position(step_obj, delta_x, delta_y)

        # Kör en ny raytrace på den optimala punkten och lagra i DB
        self._trace_and_store(step_obj, new_offset.x, new_offset.y, new_offset.z)
        self._update_plot()

    def _goto_maximu_old(self):
        result = self._compute_field()
        if result is None:
            print("[GOTO MAX] No data available to compute maximum.")
            return

        Xi = result["Xi"]
        Yi = result["Yi"]
        Vi = result["Vi"]

        # 1. Hitta RBF max i absoluta world-koordinater på mät-ytan
        idx = np.unravel_index(np.argmax(Vi), Vi.shape)
        rbf_max_abs_x = float(Xi[idx])
        rbf_max_abs_y = float(Yi[idx])

        step_id = self.comboStep.currentText()
        step_obj = find_step_by_id(App.ActiveDocument, step_id)
        if not step_obj:
            return

        # 2. Ta reda på var komponenten står just NU i absoluta koordinater på ytan
        plane = self.comboPlane.currentText()
        origin_abs_x, origin_abs_y = get_plane_offset(self._origin_offset, plane)
        offset_x, offset_y = get_plane_offset(step_obj.StepOffset, plane)
        current_abs_x = origin_abs_x - offset_x
        current_abs_y = origin_abs_y - offset_y

        # 3. Räkna ut det sanna deltat (sträckan från NU till MAX)
        delta_x = rbf_max_abs_x - current_abs_x
        delta_y = rbf_max_abs_y - current_abs_y

        print(f"[GOTO MAX] Absolut mål: X={rbf_max_abs_x:.3f}, Y={rbf_max_abs_y:.3f}")
        print(f"[GOTO MAX] Flyttvektor beräknad: ΔX={delta_x:.3f}, ΔY={delta_y:.3f}")

        # 4. Justera den nuvarande StepOffset-vektorn i FreeCAD med den sanna målsträckan
        new_offset = apply_plane_delta(
            step_obj.StepOffset,
            plane,
            delta_x,
            delta_y,
        )

        # 5. Uppdatera objektet och flytta CAD-geometrin
        step_obj.StepOffset = new_offset
        moved_objects = apply_step_offset(step_obj)
        self._set_moved_objects(moved_objects)

        # 6. Kör en verifierande raytrace på den nya mittpunkten och lagra i DB
        self._trace_and_store(step_obj, new_offset.x, new_offset.y, new_offset.z)
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
    old = mw.findChild(QtWidgets.QDialog, DOCK_OBJECT_NAME)
    if old:
        old.close()
        old.deleteLater()
    win = BeamAbsorberHeatmapDock(mw)
    win.show()
    return win


def ShowHeatmapViewer_old():
    mw = Gui.getMainWindow()
    old = mw.findChild(QtWidgets.QDialog, DOCK_OBJECT_NAME)
    if old:
        mw.removeDockWidget(old)
        old.deleteLater()

    dock = BeamAbsorberHeatmapDock(mw)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.setFloating(True)  # viktigt
    dock.show()
    return dock
