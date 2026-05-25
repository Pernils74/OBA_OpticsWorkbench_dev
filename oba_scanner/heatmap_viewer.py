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
from mpl_toolkits.mplot3d import proj3d, Axes3D


from .batch_runner import resolve_move_target, snapshot_placement, clear_placement_expressions, apply_direct_offset, restore_placement, run_trace, store_hits
from .scan_db import HitsDB

DOCK_OBJECT_NAME = "BeamAbsorberHeatmapDock"


class BeamAbsorberHeatmapDock(QtWidgets.QDockWidget):

    # ==========================================================
    # INIT
    # ==========================================================
    def __init__(self, parent=None):
        super().__init__("Heatmap Viewer", parent)
        self.setObjectName(DOCK_OBJECT_NAME)

        self.db = HitsDB()
        self._last_mtime = None

        self._placement_snapshot = {}  # för att kunna klicka i 3d graf och sedan återställa originalplacering
        self._expr_snapshot = {}
        self._snapshotted_objects = []
        self._current_moved_objects = ""

        self._build_ui()
        self._populate_doc_list()
        self._populate_targets()
        self._populate_emitters()
        self._update_plot()

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

        self.comboDoc = QtWidgets.QComboBox()
        self.comboTarget = QtWidgets.QComboBox()

        self.comboPlane = QtWidgets.QComboBox()
        self.comboPlane.addItems(["XY", "XZ", "YZ"])

        self.comboValue = QtWidgets.QComboBox()
        self.comboValue.addItem("Hits", "hits")
        self.comboValue.addItem("Power In", "power_in")
        self.comboValue.addItem("Power Out", "power_out")

        row_doc = QtWidgets.QHBoxLayout()
        self.btnReload = QtWidgets.QPushButton("Reload")
        self.btnDeleteDoc = QtWidgets.QPushButton("Delete")

        row_doc.addWidget(self.comboDoc)
        row_doc.addWidget(self.btnReload)
        row_doc.addWidget(self.btnDeleteDoc)

        form.addRow("Document:", self._wrap(row_doc))
        form.addRow("Target object:", self.comboTarget)
        form.addRow("Value:", self.comboValue)

        # Emitters
        self.emitterBox = QtWidgets.QGroupBox("Emitters")
        self.emitterLayout = QtWidgets.QVBoxLayout(self.emitterBox)
        form.addRow(self.emitterBox)

        # Options
        self.chkSmooth = QtWidgets.QCheckBox("Smooth")
        self.spinSmooth = QtWidgets.QSpinBox()
        self.spinSmooth.setRange(1, 10)
        self.spinSmooth.setValue(2)

        self.chkPickable = QtWidgets.QCheckBox("Clickable surface")
        self.chkPickable.setChecked(True)

        self.chkPercent = QtWidgets.QCheckBox("Show %")

        row_opt = QtWidgets.QHBoxLayout()
        row_opt.addWidget(QtWidgets.QLabel("Plane:"))
        row_opt.addWidget(self.comboPlane)
        row_opt.addSpacing(10)
        row_opt.addWidget(self.chkPickable)

        row_opt.addSpacing(20)
        row_opt.addWidget(self.chkSmooth)
        row_opt.addWidget(QtWidgets.QLabel("Strength:"))
        row_opt.addWidget(self.spinSmooth)

        row_opt.addWidget(self.chkPercent)

        form.addRow(row_opt)
        layout.addLayout(form)

        # Plots
        plotArea = QtWidgets.QHBoxLayout()

        self.fig3d = Figure(figsize=(5, 5))
        self.canvas3d = FigureCanvas(self.fig3d)
        self.canvas3d.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.canvas3d.mpl_connect("pick_event", self._on_surface_pick)

        self.figProf = Figure(figsize=(5, 5))
        self.canvasProf = FigureCanvas(self.figProf)
        self.canvasProf.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        plotArea.addWidget(self.canvas3d)
        plotArea.addWidget(self.canvasProf)
        layout.addLayout(plotArea, 1)

        # Signals
        self.comboDoc.currentIndexChanged.connect(self._doc_changed)
        self.comboTarget.currentIndexChanged.connect(self._target_changed)

        self.btnReload.clicked.connect(self._reload_structure)

        self.comboPlane.currentIndexChanged.connect(self._update_plot)
        self.comboValue.currentIndexChanged.connect(self._update_plot)

        self.chkSmooth.toggled.connect(self._update_plot)
        self.spinSmooth.valueChanged.connect(self._update_plot)
        self.chkPercent.toggled.connect(self._update_plot)
        self.chkPickable.toggled.connect(self._update_plot)

        self.btnDeleteDoc.clicked.connect(self._on_delete_document_clicked)

    def _wrap(self, layout):
        w = QtWidgets.QWidget()
        w.setLayout(layout)
        return w

    def _reload_structure(self):
        self._last_mtime = None  # reset watcher
        self._populate_doc_list()
        self._populate_targets()
        self._populate_emitters()
        self._update_plot()

    # ==========================================================
    # DATA
    # ==========================================================
    def _populate_doc_list(self):
        current = self.comboDoc.currentText()
        docs = self.db.list_documents()

        self.comboDoc.blockSignals(True)
        self.comboDoc.clear()
        self.comboDoc.addItems(docs if docs else ["<none>"])
        if current:
            i = self.comboDoc.findText(current)
            if i >= 0:
                self.comboDoc.setCurrentIndex(i)
        self.comboDoc.blockSignals(False)

    def _populate_targets(self):
        self.comboTarget.clear()
        doc = self.comboDoc.currentText()
        if "<" in doc:
            return
        self.comboTarget.addItems(self.db.list_target_objects(doc))

    def _populate_emitters(self):
        while self.emitterLayout.count():
            w = self.emitterLayout.takeAt(0).widget()
            if w:
                w.deleteLater()

        doc = self.comboDoc.currentText()
        target = self.comboTarget.currentText()
        if not doc or not target or "<" in doc:
            return

        self.emitter_checks = {}
        for em in self.db.list_emitters(doc, target):
            chk = QtWidgets.QCheckBox(em)
            chk.setChecked(em == "__ALL__")
            chk.toggled.connect(self._update_plot)
            self.emitterLayout.addWidget(chk)
            self.emitter_checks[em] = chk

    # ==========================================================
    # CORE
    # ==========================================================
    def _doc_changed(self):
        self._last_mtime = None
        self._populate_targets()
        self._populate_emitters()
        self._update_plot()
        self._snapshot_objects()

    def _target_changed(self):
        self._populate_emitters()
        self._update_plot()

    def _maybe_refresh(self):
        try:
            mtime = os.path.getmtime(self.db.path)
        except Exception:
            return
        if mtime != self._last_mtime:
            self._last_mtime = mtime
            self._update_plot()

    def _get_selected_emitters(self):
        if "__ALL__" in self.emitter_checks and self.emitter_checks["__ALL__"].isChecked():
            return ["__ALL__"]
        return [e for e, chk in self.emitter_checks.items() if chk.isChecked()]

    def _update_plot(self):
        doc = self.comboDoc.currentText()
        target = self.comboTarget.currentText()
        if "<" in doc or not target:
            self._clear_plots()
            return

        emitters = self._get_selected_emitters()
        if not emitters:
            self._clear_plots()
            return
        # Samlingsarrayer
        X = Y = Z = V = None

        value_key = self.comboValue.currentText()
        # value_key är: "Hits", "Power In", "Power Out"
        for em in emitters:
            # NYTT schema
            Xi, Yi, Zi, Hi, Pin, Pout, Moved_objects = self.db.read_grid(doc, target, em)
            if not Xi:
                continue
            # Välj korrekt observabel
            if value_key == "Hits":
                val = np.asarray(Hi, dtype=float)
            elif value_key == "Power In":
                val = np.asarray(Pin, dtype=float)
            elif value_key == "Power Out":
                val = np.asarray(Pout, dtype=float)
            else:
                continue

            self._current_moved_objects = ""  # reset för varje emitter, så att det alltid är korrekt för den emitter som visas i grafen
            if V is None:
                X = np.asarray(Xi)
                Y = np.asarray(Yi)
                Z = np.asarray(Zi)
                V = val.copy()

                if Moved_objects:
                    self._current_moved_objects = Moved_objects[0]

                self._current_doc_name = doc
            else:
                V += val

        if V is None:
            self._clear_plots()
            return

        # Projektion
        plane = self.comboPlane.currentText()
        if plane == "XY":
            px, py = X, Y
        elif plane == "XZ":
            px, py = X, Z
        else:  # YZ
            px, py = Y, Z

        # Grid / interpolation
        Xi, Yi, Vi = self._build_grid(px, py, V)

        # Procentläge
        if self.chkPercent.isChecked():
            Vi, _ = self._to_percent(Vi)
        # Plot
        self._plot_surface(Xi, Yi, Vi, plane)
        self._plot_profiles(Xi, Yi, Vi)

    # ==========================================================
    # GRID / FILTERS
    # ==========================================================
    def _build_grid(self, X, Y, V, res=80):
        xi = np.linspace(X.min(), X.max(), res)
        yi = np.linspace(Y.min(), Y.max(), res)
        Xi, Yi = np.meshgrid(xi, yi)

        Vi = np.zeros_like(Xi)
        for i in range(res):
            for j in range(res):
                d = np.sqrt((X - Xi[i, j]) ** 2 + (Y - Yi[i, j]) ** 2)
                w = 1.0 / (d + 1e-6)
                Vi[i, j] = np.sum(w * V) / np.sum(w)

        # if self.chkSmooth.isChecked():
        #     Vi = self._median(Vi, 3)

        if self.chkSmooth.isChecked():
            strength = self.spinSmooth.value()
            k = max(1, 2 * strength + 1)
            Vi = self._median(Vi, k)

        return Xi, Yi, Vi

    def _median(self, data, k=3):
        pad = k // 2
        p = np.pad(data, pad, mode="edge")
        out = np.zeros_like(data)
        for i in range(data.shape[0]):
            for j in range(data.shape[1]):
                out[i, j] = np.median(p[i : i + k, j : j + k])
        return out

    def _to_percent(self, data):
        m = np.max(data)
        if not np.isfinite(m) or m <= 0:
            return np.zeros_like(data), 0
        return data / m * 100.0, m

    # ==========================================================
    # PLOTS
    # ==========================================================

    def _plot_surface(self, Xi, Yi, Vi, plane):
        self.current_Xi = Xi
        self.current_Yi = Yi
        self.current_Vi = Vi
        self.fig3d.clear()
        ax = self.fig3d.add_subplot(111, projection="3d")
        # Alltid rita snygg yta först
        # ax.plot_surface(Xi, Yi, Vi, cmap="viridis", alpha=0.5)
        # ✅ Bara om checkbox är aktiv → overlay scatter
        if self.chkPickable.isChecked():
            ax.plot_surface(Xi, Yi, Vi, cmap="viridis", alpha=0.5)
            # LITE glesare → snyggare + snabbare
            # step = 3  # kan tweakas
            step = max(1, int(len(Xi) / 40))
            xs = Xi[::step, ::step].flatten()
            ys = Yi[::step, ::step].flatten()
            zs = Vi[::step, ::step].flatten()
            self._scatter = ax.scatter(xs, ys, zs, c=zs, cmap="viridis", alpha=0.5, s=12, picker=True)
            self._scatter_data = (xs, ys, zs)
        else:
            ax.plot_surface(Xi, Yi, Vi, cmap="viridis")
            self._scatter = None
            self._scatter_data = None
        ax.set_title(f"{plane}")
        self.canvas3d.draw_idle()

    def _on_surface_pick(self, event):

        if not self.chkPickable.isChecked():
            return
        if self._scatter is None or event.artist != self._scatter:
            return
        ind = event.ind
        if ind is None or len(ind) == 0:
            return
        i = ind[0]
        X, Y, Z = self._scatter_data
        x_val = X[i]
        y_val = Y[i]
        z_val = Z[i]

        App.Console.PrintMessage("\n--- Klick ---\n")
        App.Console.PrintMessage(f"X: {x_val:.4f}\n")
        App.Console.PrintMessage(f"Y: {y_val:.4f}\n")
        App.Console.PrintMessage(f"Z: {z_val:.4f}\n")

        ax = event.artist.axes
        # ✅ robust remove
        if hasattr(self, "_current_click_point"):
            try:
                self._current_click_point.remove()
            except Exception:
                self._current_click_point.set_visible(False)

        z_offset = 0.1 * (np.max(self.current_Vi) - np.min(self.current_Vi))
        # punkt ovanför
        self._current_click_point = ax.scatter([x_val], [y_val], [z_val + z_offset], color="red", alpha=1.0, s=100, zorder=100)
        self.canvas3d.draw_idle()

        # ✅ säkerställ snapshot finns
        if not self._snapshotted_objects:
            self._snapshot_objects()

        plane = self.comboPlane.currentText()
        if plane == "XY":
            dx, dy, dz = x_val, y_val, 0.0
        elif plane == "XZ":
            dx, dy, dz = x_val, 0.0, y_val
        else:  # YZ
            dx, dy, dz = 0.0, x_val, y_val
        self._move_objects_to_offset(dx, dy, dz)

        # ----------------------------------
        # Kör trace + skriv till DB
        # ----------------------------------

        doc = App.ActiveDocument

        move_objects = {}
        placement_snaps = {}

        for obj in self._snapshotted_objects:
            move_objects[obj.Name] = obj
            placement_snaps[obj.Name] = self._placement_snapshot[obj.Name]

        moved_str = self._current_moved_objects or ""

        doc_name = self._current_doc_name
        moved_str = self._current_moved_objects

        hits = run_trace()
        store_hits(self.db, doc_name, hits, dx, dy, dz, moved_str)
        self.db.commit()  # spar direkt så det syns i grafen

        # trace_and_store(doc, self.db, move_objects, placement_snaps, dx, dy, dz, moved_str)

        self._update_profile_markers(x_val, y_val, z_val)

    def _plot_profiles(self, Xi, Yi, Vi):
        self.figProf.clear()
        ax = self.figProf.add_subplot(111)
        ax.plot(Xi[Vi.shape[0] // 2], Vi[Vi.shape[0] // 2], label="X profile")
        ax.plot(Yi[:, Vi.shape[1] // 2], Vi[:, Vi.shape[1] // 2], "--", label="Y profile")

        self._profile_X = Xi[Vi.shape[0] // 2]
        self._profile_Y = Yi[:, Vi.shape[1] // 2]

        self._profile_X_values = Vi[Vi.shape[0] // 2]
        self._profile_Y_values = Vi[:, Vi.shape[1] // 2]

        ax.legend()
        ax.grid(True)
        self.canvasProf.draw_idle()

    def _update_profile_markers(self, x_val, y_val, z_val):
        if not hasattr(self, "_profile_X"):
            return

        ax = self.figProf.axes[0]
        # ✅ ta bort gamla markers + linjer
        if hasattr(self, "_profile_markers"):
            for m in self._profile_markers:
                try:
                    m.remove()
                except:
                    pass

        if hasattr(self, "_profile_hline"):
            try:
                self._profile_hline.remove()
            except:
                pass

        # ✅ hitta index
        idx_x = np.argmin(np.abs(self._profile_X - x_val))
        idx_y = np.argmin(np.abs(self._profile_Y - y_val))

        val_x = self._profile_X_values[idx_x]
        val_y = self._profile_Y_values[idx_y]

        # ✅ punkter
        m1 = ax.scatter(self._profile_X[idx_x], val_x, color="red", s=60, zorder=10)
        m2 = ax.scatter(self._profile_Y[idx_y], val_y, color="blue", s=60, zorder=10)

        # ✅ NYTT: horisontell linje
        # z_val = (val_x + val_y) * 0.5  # eller direkt från klick om du vill
        col = "blue" if z_val > np.mean(self._profile_X_values) else "red"
        self._profile_hline = ax.axhline(y=z_val, color=col, linestyle="--", linewidth=1, alpha=0.7)
        ax.text(ax.get_xlim()[0], z_val, f"{z_val:.2f}", verticalalignment="bottom", fontsize=8, color="black")

        self._profile_markers = [m1, m2]

        self.canvasProf.draw_idle()

    # ==========================================================
    def _clear_plots(self):
        self.fig3d.clear()
        self.figProf.clear()
        self.canvas3d.draw_idle()
        self.canvasProf.draw_idle()

    def _on_delete_document_clicked(self):
        doc = self.comboDoc.currentText()
        if "<" in doc:
            return
        if QtWidgets.QMessageBox.question(self, "Delete", f"Delete {doc}?") == QtWidgets.QMessageBox.Yes:
            self.db.delete_document(doc)
            self._populate_doc_list()
            self._clear_plots()

    # ==========================================================
    # Click i 3d graf
    # ==========================================================

    def _snapshot_objects(self, objects=None):
        doc = App.ActiveDocument
        # ✅ fallback: hämta från current step
        if objects is None:
            if not hasattr(self, "_current_moved_objects") or not self._current_moved_objects:
                return
            names = self._current_moved_objects.split(";")
            objects = []
            for n in names:
                o = doc.getObject(n)
                if o:
                    objects.append(o)
        # ✅ reset snapshots
        self._placement_snapshot.clear()
        self._snapshotted_objects.clear()

        # ✅ snapshot
        for obj in objects:
            target = resolve_move_target(obj)
            if not target:
                continue
            if target.Name in self._placement_snapshot:
                continue
            snap = snapshot_placement(target)
            self._placement_snapshot[target.Name] = snap
            self._snapshotted_objects.append(target)

    def _restore_objects(self):
        doc = App.ActiveDocument

        for name, snap in self._placement_snapshot.items():
            obj = doc.getObject(name)
            if not obj:
                continue

            restore_placement(obj, snap)

        doc.recompute()

    def _move_objects_to_offset(self, dx, dy, dz):
        print("Snapshot contains:", [o.Name for o in self._snapshotted_objects])

        if not self._snapshotted_objects:
            print("No objects to move")
            return

        for obj in self._snapshotted_objects:
            snap = self._placement_snapshot.get(obj.Name)
            if not snap:
                continue

            clear_placement_expressions(obj)
            apply_direct_offset(obj, snap, dx, dy, dz)
            print(f"Moved {obj.Name} by dx={dx:.3f}, dy={dy:.3f}, dz={dz:.3f}")
        App.ActiveDocument.recompute()

    def closeEvent(self, event):
        self.db.commit()
        self._restore_objects()
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
    dock.show()
    return dock
