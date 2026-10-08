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


def compute_field(
    doc,
    db,
    target,
    step_id,
    plane="XY",
    value_mode="Power In",
    emitters=None,
    grid_size=60,
    rbf_function="linear",  # "thin_plate",  # "linear"
    rbf_smooth=0.0,
):
    import numpy as np
    import FreeCAD as App

    from scipy.interpolate import Rbf

    if target is None:
        return None

    if step_id in (None, "<none>"):
        return None

    if emitters is None:
        emitters = db.list_emitters(target)

    X = Y = Z = V = None
    for emitter in emitters:
        data = db.read_grid(target, emitter, step_id)
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
        selected_object = doc.getObject(selected_name)
        # selected_object = App.ActiveDocument.getObject(selected_name)

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

    if V is None:
        return None

    # ---------------------------------------
    # välj plan
    # ---------------------------------------

    if plane == "XY":
        px = X
        py = Y
    elif plane == "XZ":
        px = X
        py = Z
    elif plane == "YZ":
        px = Y
        py = Z
    else:
        raise ValueError(f"Unsupported plane: {plane}")
    # ---------------------------------------
    # skapa jämnt rutnät
    # ---------------------------------------
    Xi, Yi = np.meshgrid(
        np.linspace(px.min(), px.max(), grid_size),
        np.linspace(py.min(), py.max(), grid_size),
    )

    # ---------------------------------------
    # RBF interpolation
    # ---------------------------------------
    rbf = Rbf(px, py, V, function=rbf_function, smooth=rbf_smooth)

    rbf_at_samples = rbf(px, py)
    error = rbf_at_samples - V
    print("mean abs error =", np.mean(np.abs(error)))
    print("max abs error =", np.max(np.abs(error)))

    Vi = rbf(Xi, Yi)
    return {
        "Xi": Xi,
        "Yi": Yi,
        "Vi": Vi,
        "px": px,
        "py": py,
        "V": V,
    }


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

        self.spinRange = QtWidgets.QDoubleSpinBox()
        self.spinRange.setRange(0.01, 100.0)
        self.spinRange.setDecimals(2)
        self.spinRange.setSingleStep(0.05)
        self.spinRange.setValue(0.50)

        self.chkPercent = QtWidgets.QCheckBox(f"Show % of emitted rays/power")
        self.chkPlane2D = QtWidgets.QCheckBox("2D plane view")
        self.btnGotoMax = QtWidgets.QPushButton("Go to Max")

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Plane"))
        row.addWidget(self.comboPlane)
        row.addSpacing(15)
        row.addWidget(QtWidgets.QLabel("Range"))
        row.addWidget(self.spinRange)

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

        result = compute_field(
            doc=App.ActiveDocument,
            db=self.db,
            target=hit_target,
            step_id=step_id,
            plane=self.comboPlane.currentText(),
            value_mode=self.comboValue.currentText(),
            emitters=self._get_selected_emitters(),
            grid_size=60,
            rbf_smooth=0.0,
        )

        if result is None:
            self._clear()
            return
        # Xi = result["Xi"]
        # Yi = result["Yi"]
        # Vi = result["Vi"]
        # self._raw_px = result["px"]
        # self._raw_py = result["py"]
        # self._raw_v = result["V"]

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

        store_hits(self.db, step_obj.Id, hits, dx, dy, dz, self._moved_objects)

        self.db.commit()

    def _plot_3d(self, Xi, Yi, Vi, raw_px, raw_py, raw_v):

        self.fig3d.clear()
        ax = self.fig3d.add_subplot(111, projection="3d")
        ax.plot_surface(Xi, Yi, Vi, cmap="viridis", alpha=0.9)
        xmin, xmax = Xi.min(), Xi.max()
        ymin, ymax = Yi.min(), Yi.max()
        zmin, zmax = Vi.min(), Vi.max()

        step_obj = find_step_by_id(
            App.ActiveDocument,
            self.comboStep.currentText(),
        )

        if not step_obj or not self._origin_offset:
            self.canvas3d.draw_idle()
            return

        # --------------------------------------------------
        # current position i valt plan
        # --------------------------------------------------
        if self.comboPlane.currentText() == "XY":
            current_x = self._origin_offset.x - step_obj.StepOffset.x
            current_y = self._origin_offset.y - step_obj.StepOffset.y
        elif self.comboPlane.currentText() == "XZ":
            current_x = self._origin_offset.x - step_obj.StepOffset.x
            current_y = self._origin_offset.z - step_obj.StepOffset.z
        else:
            current_x = self._origin_offset.y - step_obj.StepOffset.y
            current_y = self._origin_offset.z - step_obj.StepOffset.z

        # --------------------------------------------------
        # närmaste cell till current position
        # --------------------------------------------------

        current_idx = np.unravel_index(np.argmin((Xi - current_x) ** 2 + (Yi - current_y) ** 2), Xi.shape)
        row = current_idx[0]
        col = current_idx[1]
        current_v = float(Vi[row, col])

        # --------------------------------------------------
        # ghost planes genom current
        # --------------------------------------------------
        Yp, Zp = np.meshgrid(np.linspace(ymin, ymax, 30), np.linspace(zmin, zmax, 30))

        Xp = np.full_like(Yp, current_x)
        ax.plot_surface(Xp, Yp, Zp, color="white", alpha=0.15, edgecolor="none")
        Xp, Zp = np.meshgrid(np.linspace(xmin, xmax, 30), np.linspace(zmin, zmax, 30))
        Yp = np.full_like(Xp, current_y)
        ax.plot_surface(Xp, Yp, Zp, color="cyan", alpha=0.15, edgecolor="none")

        # --------------------------------------------------
        # profiler genom current
        # --------------------------------------------------
        ax.plot(Xi[row, :], Yi[row, :], Vi[row, :], color="white", linewidth=2, label="X profile")
        ax.plot(Xi[:, col], Yi[:, col], Vi[:, col], color="cyan", linewidth=2, label="Y profile")
        # --------------------------------------------------
        # current punkt
        # --------------------------------------------------
        # ax.scatter(current_x, current_y, current_v, color="red", s=200, edgecolors="black", label="Current")
        # --------------------------------------------------
        # DB max
        # --------------------------------------------------
        raw_idx = np.argmax(raw_v)
        ax.scatter(raw_px[raw_idx], raw_py[raw_idx], raw_v[raw_idx], color="yellow", s=150, marker="*", label="DB Max")
        # --------------------------------------------------
        # RBF max
        # --------------------------------------------------
        interp_idx = np.unravel_index(np.argmax(Vi), Vi.shape)
        ax.scatter(Xi[interp_idx], Yi[interp_idx], Vi[interp_idx], color="black", s=150, marker="*", label="RBF Max")
        # --------------------------------------------------
        # råa mätpunkter
        # --------------------------------------------------
        ax.scatter(raw_px, raw_py, raw_v, color="red", s=40, depthshade=False, label="DB")
        ax.legend()
        self.canvas3d.draw_idle()

    def _plot_2d_profile(self, Xi, Yi, Vi, raw_px, raw_py, raw_v):
        self.fig2d.clear()
        ax = self.fig2d.add_subplot(111)
        # mid_x = Vi.shape[0] // 2
        # mid_y = Vi.shape[1] // 2
        # ax.plot(Xi[mid_x], Vi[mid_x], label="X profile")
        # ax.plot(Yi[:, mid_y], Vi[:, mid_y], "--", label="Y profile")

        step_obj = find_step_by_id(
            App.ActiveDocument,
            self.comboStep.currentText(),
        )

        if step_obj and not self._origin_offset:
            self._origin_offset = App.Vector(step_obj.StepOffset)

        if self.comboPlane.currentText() == "XY":
            current_x = self._origin_offset.x - step_obj.StepOffset.x
            current_y = self._origin_offset.y - step_obj.StepOffset.y

        elif self.comboPlane.currentText() == "XZ":
            current_x = self._origin_offset.x - step_obj.StepOffset.x
            current_y = self._origin_offset.z - step_obj.StepOffset.z

        else:
            current_x = self._origin_offset.y - step_obj.StepOffset.y
            current_y = self._origin_offset.z - step_obj.StepOffset.z

        current_idx = np.unravel_index(
            np.argmin((Xi - current_x) ** 2 + (Yi - current_y) ** 2),
            Xi.shape,
        )

        row = current_idx[0]
        col = current_idx[1]

        ax.plot(Xi[row], Vi[row], label="X profile")
        ax.plot(Yi[:, col], Vi[:, col], "--", label="Y profile")

        ax.scatter(0.0, 0.0, s=180, color="red", edgecolors="black", zorder=10, label="Current")

        # step_obj = find_step_by_id(
        #     App.ActiveDocument,
        #     self.comboStep.currentText(),
        # )
        # if step_obj and not self._origin_offset:
        #     self._origin_offset = App.Vector(step_obj.StepOffset)
        # if step_obj:
        #     if self.comboPlane.currentText() == "XY":
        #         current_x = self._origin_offset.x - step_obj.StepOffset.x
        #     elif self.comboPlane.currentText() == "XZ":
        #         current_x = self._origin_offset.x - step_obj.StepOffset.x
        #     else:
        #         current_x = self._origin_offset.y - step_obj.StepOffset.y
        #     # -----------------------------
        #     # Current position
        #     # -----------------------------
        #     # current_idx = np.unravel_index(np.argmin((Xi - current_x) ** 2 + (Yi - 0.0) ** 2), Xi.shape)
        #     # current_v = float(Vi[current_idx])
        #     # ax.scatter(current_x, current_v, s=180, color="red", edgecolors="black", zorder=10, label="Current")
        #     # ax.scatter(0.0, current_v, s=180, color="red", edgecolors="black", zorder=10, label="Current")
        #     ax.scatter(current_x, 0.0, s=180, color="red", edgecolors="black", zorder=10, label="Current")
        # ----------------------------------------
        # DB best (uppmätt)
        # ----------------------------------------
        raw_max_v = float(np.max(raw_v))
        ax.axhline(raw_max_v, color="orange", linestyle=":", linewidth=2, label="DB Best")
        # ----------------------------------------
        # RBF best (interpolerat)
        # ----------------------------------------
        interp_max_v = float(np.max(Vi))
        ax.axhline(interp_max_v, color="black", linestyle="--", linewidth=2, label="RBF Best")
        # ----------------------------------------
        # Emitted %
        # ----------------------------------------
        if self.chkPercent.isChecked():
            ax.axhline(100.0, color="green", linestyle="--", linewidth=2, label="100 % emitted")

        interp_idx = np.unravel_index(np.argmax(Vi), Vi.shape)
        interp_max_x = float(Xi[interp_idx])
        interp_max_v = float(Vi[interp_idx])
        # ax.scatter(interp_max_x, interp_max_v, s=250, marker="*", color="yellow", edgecolors="black", label="RBF Max Position")
        # ax.scatter(0.0, interp_max_v, s=250, marker="*", color="yellow", edgecolors="black", label="RBF Max Position")
        ax.scatter(interp_max_x, 0.0, s=250, marker="*", color="yellow", edgecolors="black", label="RBF Max Position")

        # if hasattr(self, "_max_x"):
        #     ax.axvline(self._max_x, color="lime", linestyle="--", label="Last GotoMax")
        # ax.text(
        #     0.01,
        #     0.99,
        #     f"Current={current_efficiency:.1f}%\n" f"DB Best={raw_max_v:.1f}%\n" f"RBF Best={interp_max_v:.1f}%",
        #     transform=ax.transAxes,
        #     va="top",
        # )

        plot_range = self.spinRange.value()
        ax.set_xlim(-plot_range, plot_range)
        ax.legend()
        ax.grid(True)

        self.canvas2d.draw_idle()

    def _plot_2d_profile_old(self, Xi, Yi, Vi, raw_px, raw_py, raw_v):

        self.fig2d.clear()
        ax = self.fig2d.add_subplot(111)

        mid_x = Vi.shape[0] // 2
        mid_y = Vi.shape[1] // 2

        ax.plot(Xi[mid_x] - current_x, Vi[mid_x], label="X profile")
        ax.plot(Yi[:, mid_y] - current_y, Vi[:, mid_y], "--", label="Y profile")

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
            ax.axvline(current_x, color="red", linestyle=":")

            best_efficiency = float(np.max(raw_v))
            ax.axhline(best_efficiency, color="orange", linestyle=":", linewidth=2, label="Scan best")

            # tol = 0.02
            # mask_x = np.abs(raw_py) < tol
            # mask_y = np.abs(raw_px) < tol

            # ax.scatter(raw_px[mask_x], raw_v[mask_x], s=40, color="white", edgecolors="black", label=label_a)
            # ax.scatter(raw_py[mask_y], raw_v[mask_y], s=40, color="cyan", edgecolors="black", label=label_b)

        if hasattr(self, "_max_x"):
            ax.scatter(self._max_x, self._max_y, s=250, marker="*", color="yellow", edgecolors="black", label="Max")

        if self.chkPercent.isChecked():
            current_idx = np.unravel_index(
                np.argmin((Xi - current_x) ** 2 + (Yi - current_y) ** 2),
                Xi.shape,
            )
            current_efficiency = float(Vi[current_idx])
            best_efficiency = float(np.max(Vi))
            gain = best_efficiency - current_efficiency
            ax.set_title(f"Current={current_efficiency:.1f}%   " f"Best={best_efficiency:.1f}%   " f"Diff=+{gain:.1f} pts")
            ax.axhline(100, color="green", linestyle="--", linewidth=2, label="100 % emitted")
        else:
            # ----------------------------------------
            # DB best (uppmätt)
            # ----------------------------------------
            raw_idx = np.argmax(raw_v)
            raw_max_v = float(raw_v[raw_idx])
            # ----------------------------------------
            # RBF best (interpolerat)
            # ----------------------------------------
            interp_idx = np.unravel_index(np.argmax(Vi), Vi.shape)
            interp_max_v = float(Vi[interp_idx])

            # ----------------------------------------
            # Current (verklig senaste trace)
            # ----------------------------------------
            hits, _stats = collect_ray_hits_and_stats(mode="final")
            value_mode = self.comboValue.currentText()
            hit_target = self.comboTarget.currentData()
            selected_emitters = set(self._get_selected_emitters())
            target_hits = [h for h in hits if h.get("object") == hit_target and h.get("emitter_id") in selected_emitters]
            if value_mode == "Hits":
                current_value = len(target_hits)
            elif value_mode == "Power In":
                current_value = sum(h.get("power_in", 0.0) for h in target_hits)
            else:  # Power Out
                current_value = sum(h.get("power_out", 0.0) for h in target_hits)
            gap_db = raw_max_v - current_value
            gap_rbf = interp_max_v - current_value
            ax.set_title(f"Current={current_value:.0f}   " f"DB Best={raw_max_v:.0f} (+{gap_db:.0f})   " f"RBF Best={interp_max_v:.0f} (+{gap_rbf:.0f})")

        plot_range = self.spinRange.value()
        ax.set_xlim(-plot_range, plot_range)

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
        Xi = result["Xi"]
        Yi = result["Yi"]
        Vi = result["Vi"]
        # Xi, Yi, Vi = result
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
