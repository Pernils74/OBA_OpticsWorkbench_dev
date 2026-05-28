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
from mpl_toolkits.mplot3d import Axes3D

from .scan_db import HitsDB, get_doc_db_path


from .batch_runner import (
    resolve_move_target,
    snapshot_placement,
    clear_placement_expressions,
    apply_direct_offset,
    run_trace,
    store_hits,
    restore_placement,
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

        self.emitter_checks = {}
        self.profile_mode = "profile"  # Är för 2d profileplotten
        # senare: "hist", "scatter", "fft" etc
        self._placement_snapshot = {}
        self._snapshotted_objects = []
        self._current_moved_objects = ""
        self._click_busy = False

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
        db_row.addWidget(QtWidgets.QLabel("DB:"))
        db_row.addWidget(self.lblDB, 1)
        db_row.addWidget(self.btnDBRefresh)
        form.addRow(db_row)

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
        self.comboStep.currentIndexChanged.connect(self._update_plot)
        self.comboTarget.currentIndexChanged.connect(self._target_changed)
        self.comboValue.currentIndexChanged.connect(self._update_plot)
        self.comboPlane.currentIndexChanged.connect(self._update_plot)
        self.chkSmooth.toggled.connect(self._update_plot)
        self.spinSmooth.valueChanged.connect(self._update_plot)
        self.chkPercent.toggled.connect(self._update_plot)
        self.chkPlane2D.toggled.connect(self._update_plot)

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
    def _target_changed(self):
        self._populate_emitters()
        self._update_plot()

    def _maybe_refresh(self):
        try:
            if os.path.getmtime(self.db.path) != self._last_mtime:
                self._last_mtime = os.path.getmtime(self.db.path)
                self._update_plot()
        except:
            pass

    def _get_selected_emitters(self):
        return [e for e, c in self.emitter_checks.items() if c.isChecked()]

    # ==========================================================
    # CORE
    # ==========================================================

    def _snapshot_objects(self):
        doc = App.ActiveDocument

        self._placement_snapshot.clear()
        self._snapshotted_objects.clear()

        if not hasattr(self, "_current_moved_objects"):
            return

        if not self._current_moved_objects:
            return

        names = self._current_moved_objects.split(";")

        for name in names:
            obj = doc.getObject(name)
            obj = resolve_move_target(obj)

            if not obj:
                continue

            if obj.Name in self._placement_snapshot:
                continue

            snap = snapshot_placement(obj)

            self._placement_snapshot[obj.Name] = snap
            self._snapshotted_objects.append(obj)

    def _restore_objects(self):
        doc = App.ActiveDocument
        for name, snap in self._placement_snapshot.items():
            obj = doc.getObject(name)
            if obj:
                restore_placement(obj, snap)
        doc.recompute()

    def _update_plot_old(self):
        result = self._compute_field()

        if result is None:
            self._clear()
            return

        Xi, Yi, Vi = result

        # 3D alltid
        self._plot_3d(Xi, Yi, Vi)

        # 2D beroende på mode
        if self.profile_mode == "profile":
            self._plot_2d_profile(Xi, Yi, Vi)
        else:
            self._plot_2d_profile(Xi, Yi, Vi)  # fallback

    def _update_plot(self):
        result = self._compute_field()

        if result is None:
            self._clear()
            return

        Xi, Yi, Vi = result

        # reset snapshot när vi laddar ny data
        # self._snapshotted_objects = []
        # self._placement_snapshot = {}

        self._plot_3d(Xi, Yi, Vi)

        if self.chkPlane2D.isChecked():
            self._plot_2d_plane(Xi, Yi, Vi)
        else:
            self._plot_2d_profile(Xi, Yi, Vi)

    def _compute_field(self):
        target = self.comboTarget.currentData()
        step = self.comboStep.currentText()

        if not target or step == "<none>":
            return None

        emitters = self._get_selected_emitters()
        if not emitters:
            return None

        X = Y = Z = V = None

        for em in emitters:
            data = self.db.read_grid(target, em, step)
            if not data:
                continue

            Xi, Yi, Zi, Hi, Pin, Pout, moved = data

            if self.comboValue.currentText() == "Hits":
                val = np.asarray(Hi, float)
            elif self.comboValue.currentText() == "Power In":
                val = np.asarray(Pin, float)
            else:
                val = np.asarray(Pout, float)

            if V is None:
                X, Y, Z = map(np.asarray, (Xi, Yi, Zi))
                V = val.copy()
                # ✅ SÄTT vilka objekt som flyttas
                if moved:
                    self._current_moved_objects = moved[0]
                    self.lblMoved.setText(self._current_moved_objects)
            else:
                V += val

        if V is None:
            return None

        # projection
        plane = self.comboPlane.currentText()
        px, py = (X, Y) if plane == "XY" else (X, Z) if plane == "XZ" else (Y, Z)

        Xi, Yi = np.meshgrid(
            np.linspace(px.min(), px.max(), 60),
            np.linspace(py.min(), py.max(), 60),
        )

        Vi = np.zeros_like(Xi)

        for i in range(Xi.shape[0]):
            for j in range(Xi.shape[1]):
                d = np.sqrt((px - Xi[i, j]) ** 2 + (py - Yi[i, j]) ** 2)
                w = 1 / (d + 1e-6)
                Vi[i, j] = np.sum(w * V) / np.sum(w)

        # smooth
        if self.chkSmooth.isChecked():
            Vi = self._median(Vi, 2 * self.spinSmooth.value() + 1)

        # percent
        if self.chkPercent.isChecked():
            m = np.max(Vi)
            if m > 0:
                Vi = Vi / m * 100

        return Xi, Yi, Vi

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

        mid_x = (xmin + xmax) * 0.5
        mid_y = (ymin + ymax) * 0.5

        # =========================
        # GHOST PLANES (TRUE PLANES)
        # =========================

        # --- X plane (vertical slice)
        Yp, Zp = np.meshgrid(
            np.linspace(ymin, ymax, 30),
            np.linspace(zmin, zmax, 30),
        )
        Xp = np.full_like(Yp, mid_x)

        ax.plot_surface(
            Xp,
            Yp,
            Zp,
            color="white",
            alpha=0.15,
            edgecolor="none",
        )

        # --- Y plane (vertical slice)
        Xp, Zp = np.meshgrid(
            np.linspace(xmin, xmax, 30),
            np.linspace(zmin, zmax, 30),
        )
        Yp = np.full_like(Xp, mid_y)

        ax.plot_surface(
            Xp,
            Yp,
            Zp,
            color="cyan",
            alpha=0.15,
            edgecolor="none",
        )

        # =========================
        # PROFILE LINES (on surface)
        # =========================

        # X profile
        X_line_X = Xi[mid_x_idx, :]
        X_line_Y = Yi[mid_x_idx, :]
        X_line_Z = Vi[mid_x_idx, :]

        ax.plot(
            X_line_X,
            X_line_Y,
            X_line_Z,
            color="white",
            linewidth=2,
        )

        # Y profile
        Y_line_X = Xi[:, mid_y_idx]
        Y_line_Y = Yi[:, mid_y_idx]
        Y_line_Z = Vi[:, mid_y_idx]

        ax.plot(
            Y_line_X,
            Y_line_Y,
            Y_line_Z,
            color="cyan",
            linewidth=2,
        )

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
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self.setEnabled(False)
        # if self._click_busy:
        #     return

        if event.inaxes is None:
            return
        if not self.chkPlane2D.isChecked():
            return
        x = event.xdata
        y = event.ydata

        # print("CLICK")
        # print(event.xdata, event.ydata)

        if x is None or y is None:
            return
        self._click_busy = True  # 🔥 LOCK
        try:
            plane = self.comboPlane.currentText()
            if plane == "XY":
                dx, dy, dz = x, y, 0.0
            elif plane == "XZ":
                dx, dy, dz = x, 0.0, y
            else:
                dx, dy, dz = 0.0, x, y
            doc = App.ActiveDocument
            if not doc:
                return
            cfg = doc.getObject("OBARayConfig")
            old_mode = None
            try:
                if cfg:
                    old_mode = cfg.RunMode
                    cfg.RunMode = "MANUAL"
                if not self._snapshotted_objects:
                    self._snapshot_objects()
                # ✅ viktig
                self._restore_objects()
                for obj in self._snapshotted_objects:
                    snap = self._placement_snapshot[obj.Name]
                    clear_placement_expressions(obj)

                    step_id = self.comboStep.currentText()
                    step_obj = None
                    for s in App.ActiveDocument.Objects:
                        if getattr(s, "Id", "") == step_id:
                            step_obj = s
                            break

                    apply_direct_offset(obj, snap, dx, dy, dz)

                    if step_obj is not None:
                        step_obj.StepOffset = App.Vector(dx, dy, dz)

                    dx_eff = dx
                    dy_eff = dy
                    dz_eff = dz
                    print("stored:", dx_eff, dy_eff, dz_eff)
                    # print(self.db.count_rows())

                # print("after restore", obj.Placement.Base)

                doc.recompute()

                # print("after recompute", obj.Placement.Base)

                # before = obj.Placement.Base
                hits = run_trace()
                # after = obj.Placement.Base
                # print(before)
                # print(after)

                step = self.comboStep.currentText()
                moved = self._current_moved_objects if hasattr(self, "_current_moved_objects") else ""

                store_hits(self.db, step, hits, dx_eff, dy_eff, dz_eff, moved)
                self.db.commit()
            finally:
                if cfg and old_mode is not None:
                    cfg.RunMode = old_mode
            self._update_plot()
        finally:
            self.setEnabled(True)
            QtWidgets.QApplication.restoreOverrideCursor()
            # self._click_busy = False  # 🔓 UNLOCK

    def _on_2d_click_old(self, event):
        if event.inaxes is None:
            return
        if not self.chkPlane2D.isChecked():
            return
        x = event.xdata
        y = event.ydata
        if x is None or y is None:
            return
        # -----------------------------
        # konvertera till dx,dy,dz
        # -----------------------------
        plane = self.comboPlane.currentText()
        if plane == "XY":
            dx, dy, dz = x, y, 0.0
        elif plane == "XZ":
            dx, dy, dz = x, 0.0, y
        else:  # YZ
            dx, dy, dz = 0.0, x, y
        doc = App.ActiveDocument
        if not doc:
            return
        cfg = doc.getObject("OBARayConfig")
        old_mode = None
        try:
            # ✅ BLOCK AUTO TRACE
            if cfg:
                old_mode = cfg.RunMode
                cfg.RunMode = "MANUAL"
            # -----------------------------
            # snapshot (om inte gjort)
            # -----------------------------
            if not self._snapshotted_objects:
                self._snapshot_objects()
            # -----------------------------
            # flytta objekt
            # -----------------------------
            for obj in self._snapshotted_objects:
                snap = self._placement_snapshot[obj.Name]
                clear_placement_expressions(obj)

                apply_direct_offset(obj, snap, dx, dy, dz)
            doc.recompute()
            # -----------------------------
            # TRACE + STORE
            # -----------------------------
            hits = run_trace()

            step = self.comboStep.currentText()
            moved = self._current_moved_objects if hasattr(self, "_current_moved_objects") else ""

            store_hits(self.db, step, hits, dx, dy, dz, moved)
            self.db.commit()
        finally:
            # ✅ ALLTID ÅTERSTÄLL
            if cfg and old_mode is not None:
                cfg.RunMode = old_mode
        # -----------------------------
        # uppdatera graf
        # -----------------------------
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
            if self._snapshotted_objects:
                App.Console.PrintMessage("Restoring objects on close...\n")
                self._restore_objects()

        except Exception as e:
            App.Console.PrintError(f"Restore failed: {e}\n")
        self.db.close()
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
