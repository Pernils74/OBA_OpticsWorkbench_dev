# -*- coding: utf-8 -*-
import os
import numpy as np
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

import matplotlib

matplotlib.use("Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D

from .scan_db import HitsDB


DOCK_OBJECT_NAME = "BeamAbsorberHeatmapDock"


class BeamAbsorberHeatmapDock(QtWidgets.QDockWidget):

    # =====================================================================
    # INIT
    # =====================================================================
    def __init__(self, parent=None):
        super().__init__("Absorber‑Heatmap‑Viewer", parent)
        self.setObjectName(DOCK_OBJECT_NAME)

        self.db = HitsDB()
        self._last_mtime = None
        self._last_row_count = None

        self._build_ui()
        self._populate_doc_list()
        self._update_plot(force=True)

        # Auto-refresh timer
        self._watch = QtCore.QTimer(self)
        self._watch.setSingleShot(False)
        self._watch.timeout.connect(self._maybe_refresh)
        self._rearm_timer()

    # =====================================================================
    # UI
    # =====================================================================
    def _build_ui(self):
        central = QtWidgets.QWidget(self)
        self.setWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)

        form = QtWidgets.QFormLayout()

        # Dokument + Plan (på samma rad)
        self.comboDoc = QtWidgets.QComboBox()
        self.comboPlane = QtWidgets.QComboBox()
        self.comboPlane.addItems(["XY", "XZ", "YZ"])
        self.comboPlane.setMinimumContentsLength(4)  # tvinga minst 4 tecken bredd

        # Checkbox för radial
        self.chkRadial = QtWidgets.QCheckBox("Visa radial profil")
        self.chkRadial.setChecked(False)

        # Auto-refresh
        hrow = QtWidgets.QHBoxLayout()
        self.chkAuto = QtWidgets.QCheckBox("Auto-refresh")
        self.chkAuto.setChecked(True)
        self.spinInterval = QtWidgets.QSpinBox()
        self.spinInterval.setRange(100, 5000)
        self.spinInterval.setValue(500)
        hrow.addWidget(self.chkAuto)
        hrow.addWidget(QtWidgets.QLabel("Intervall (ms):"))
        hrow.addWidget(self.spinInterval)
        hrow.addStretch(1)

        # --- Dokument-rad: [ComboDoc] [Refresh] [Ta bort] [Plan:] [ComboPlane] ---
        doc_row = QtWidgets.QHBoxLayout()
        doc_row.addWidget(self.comboDoc)

        # NEW: REFRESH-KNAPP
        self.btnRefreshDoc = QtWidgets.QPushButton("↻")
        self.btnRefreshDoc.setToolTip("Uppdatera dokumentlistan")
        self.btnRefreshDoc.setFixedWidth(32)
        doc_row.addWidget(self.btnRefreshDoc)

        # Ta bort-knappen
        self.btnDeleteDoc = QtWidgets.QPushButton("Ta bort")
        self.btnDeleteDoc.setToolTip("Ta bort valt dokument från databasen")
        doc_row.addWidget(self.btnDeleteDoc)

        # Liten spacer mellan knappar och planvalet
        # doc_row.addSpacing(12)

        # Lägg plan-etikett + combobox på samma rad
        doc_row.addWidget(QtWidgets.QLabel("Plan:"))
        doc_row.addWidget(self.comboPlane)

        # Stretch i slutet
        doc_row.addStretch(1)

        # Lägg hela raden under "Dokument:"
        form.addRow("Dokument:", self._wrap(doc_row))

        # Radial och auto-refresh som tidigare
        form.addRow(self.chkRadial)
        form.addRow(hrow)
        layout.addLayout(form)

        # --- 2 plotfönster ---
        plotArea = QtWidgets.QHBoxLayout()

        self.fig3d = Figure(figsize=(5, 5))
        self.canvas3d = FigureCanvas(self.fig3d)
        plotArea.addWidget(self.canvas3d)

        self.figProf = Figure(figsize=(5, 5))
        self.canvasProf = FigureCanvas(self.figProf)
        plotArea.addWidget(self.canvasProf)

        layout.addLayout(plotArea)

        # SIGNALER
        self.comboDoc.currentIndexChanged.connect(self._doc_changed)

        self.comboPlane.currentIndexChanged.connect(lambda _: self._update_plot(force=True))
        self.chkRadial.toggled.connect(lambda _: self._update_plot(force=True))
        self.chkAuto.toggled.connect(self._rearm_timer)
        self.spinInterval.valueChanged.connect(self._rearm_timer)
        self.btnDeleteDoc.clicked.connect(self._on_delete_document_clicked)

        # NEW: REFRESH-KNAPP SIGNAL
        self.btnRefreshDoc.clicked.connect(self._on_refresh_doc_list)

    def _wrap(self, layout: QtWidgets.QLayout) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        w.setLayout(layout)
        return w

    def _on_refresh_doc_list(self):
        """Manuell uppdatering av dokumentlistan."""
        current = self.comboDoc.currentText()
        self._populate_doc_list()
        # Försök bevara valt dokument om det finns kvar
        idx = self.comboDoc.findText(current)
        if idx >= 0:
            self.comboDoc.setCurrentIndex(idx)
        # Uppdatera vyer
        self._doc_changed()

    def _on_delete_document_clicked(self):
        doc = self.comboDoc.currentText()
        if not doc or "<" in doc:
            QtWidgets.QMessageBox.information(self, "Ta bort dokument", "Inget giltigt dokument valt.")
            return

        # Fråga användaren först
        ok = QtWidgets.QMessageBox.question(self, "Ta bort dokument", ("Vill du ta bort alla datapunkter för:\n\n" f"  {doc}\n\n" "Detta går inte att ångra."), QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
        if ok != QtWidgets.QMessageBox.Yes:
            return

        try:
            removed = self.db.delete_document(doc)
            # Uppdatera listan & rensa figurer
            self._populate_doc_list()
            self._clear_plots()

            # Flytta fokus till första element om finns
            if self.comboDoc.count() > 0:
                self.comboDoc.setCurrentIndex(0)

            QtWidgets.QMessageBox.information(self, "Ta bort dokument", f"Raderade {removed} rader för dokumentet:\n{doc}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Fel", f"Kunde inte ta bort dokumentet:\n{e}")

    # =====================================================================
    # DOCUMENT LIST
    # =====================================================================
    def _populate_doc_list(self):
        docs = self.db.list_documents()
        self.comboDoc.clear()
        if docs:
            for d in docs:
                self.comboDoc.addItem(d)
        else:
            self.comboDoc.addItem("<tom databas>")

    def _doc_changed(self):
        self._last_mtime = None
        self._last_row_count = None
        self._update_plot(force=True)

    # =====================================================================
    # AUTO REFRESH
    # =====================================================================
    def _rearm_timer(self, *_):
        self._watch.stop()
        if self.chkAuto.isChecked():
            self._watch.start(self.spinInterval.value())

    def _maybe_refresh(self):
        doc = self.comboDoc.currentText()
        if "<" in doc:
            return

        path = self.db.path

        try:
            mtime = os.path.getmtime(path)
        except:
            mtime = None

        try:
            rowc = self.db.count_rows(doc)
        except:
            rowc = None

        changed = (mtime != self._last_mtime) or (rowc != self._last_row_count)

        if changed:
            self._last_mtime = mtime
            self._last_row_count = rowc
            self._update_plot(force=True)

    # =====================================================================
    # MAIN UPDATE
    # =====================================================================
    def _update_plot(self, force=False):
        doc = self.comboDoc.currentText()
        plane = self.comboPlane.currentText()

        if "<" in doc:
            self._clear_plots()
            return

        X, Y, Z, H = self.db.read_grid(doc)
        if not X:
            self._clear_plots()
            return

        X = np.asarray(X)
        Y = np.asarray(Y)
        Z = np.asarray(Z)
        H = np.asarray(H)

        # Välj plane-koordinater
        if plane == "XY":
            px, py = X, Y
        elif plane == "XZ":
            px, py = X, Z
        else:  # YZ
            px, py = Y, Z

        # RITA 3D SURFACE (vänster)
        self._plot_surface(px, py, H, plane)

        # RITA PROFILER (höger)
        self._plot_profiles(px, py, X, Y, Z, H, plane)

    def find_outlier_points(X, Y, Z, H, k=2.5, neigh_radius=0.1):
        """
        X, Y, Z, H från DB.
        k = threshold (# of std deviations)
        neigh_radius = max-dist för neighbor-points.
        """
        X = np.asarray(X)
        Y = np.asarray(Y)
        Z = np.asarray(Z)
        H = np.asarray(H)

        outliers = []

        for i in range(len(H)):
            x0, y0, z0, h0 = X[i], Y[i], Z[i], H[i]

            # Distans till närliggande punkter (lokal neighborhood)
            d = np.sqrt((X - x0) ** 2 + (Y - y0) ** 2 + (Z - z0) ** 2)
            mask = (d > 0) & (d < neigh_radius)

            if not np.any(mask):
                continue

            neighbors = H[mask]

            mu = np.mean(neighbors)
            sigma = np.std(neighbors)

            if sigma < 1e-12:
                continue

            # DEVIATION
            if abs(h0 - mu) > k * sigma:
                outliers.append((x0, y0, z0, h0, mu, sigma))

            # MISS: h0 är 0 men grannar har signal
            elif h0 == 0 and np.mean(neighbors) > 0:
                outliers.append((x0, y0, z0, h0, mu, sigma))

        return outliers

    # =====================================================================
    # 3D SURFACE
    # =====================================================================
    def _plot_surface(self, X, Y, H, plane):
        self.fig3d.clear()
        ax = self.fig3d.add_subplot(111, projection="3d")

        # Grid för interpolering
        Xi = np.linspace(X.min(), X.max(), 80)
        Yi = np.linspace(Y.min(), Y.max(), 80)
        Xi, Yi = np.meshgrid(Xi, Yi)

        # IDW-interpolering
        Hi = self._idw_interpolate(X, Y, H, Xi, Yi)

        surf = ax.plot_surface(Xi, Yi, Hi, cmap="viridis", linewidth=0)
        ax.set_title(f"3D Surface ({plane})")
        ax.set_xlabel(plane[0])
        ax.set_ylabel(plane[1])
        ax.set_zlabel("Hits")

        self.canvas3d.draw()

    def _idw_interpolate(self, X, Y, H, Xi, Yi, eps=1e-6):
        Hi = np.zeros_like(Xi)
        for i in range(Xi.shape[0]):
            for j in range(Xi.shape[1]):
                dx = X - Xi[i, j]
                dy = Y - Yi[i, j]
                d = np.sqrt(dx * dx + dy * dy)
                w = 1.0 / (d + eps)
                Hi[i, j] = np.sum(w * H) / np.sum(w)
        return Hi

    # =====================================================================
    # PROFILE PLOTTER
    # =====================================================================
    def _plot_profiles(self, px, py, X, Y, Z, H, plane):
        self.figProf.clear()
        ax = self.figProf.add_subplot(111)

        # ----------------------------------------------------
        # X- & Y-profil i valt plan
        # ----------------------------------------------------
        # X-profil = y≈median
        y0 = np.median(py)
        mask_x = np.abs(py - y0) < (0.02 * (py.max() - py.min() + 1e-12))
        Xp = px[mask_x]
        Hp = H[mask_x]
        if len(Xp) > 2:
            idx = np.argsort(Xp)
            ax.plot(Xp[idx], Hp[idx], "-", label=f"{plane[0]}‑profil")

        # Y-profil = x≈median
        x0 = np.median(px)
        mask_y = np.abs(px - x0) < (0.02 * (px.max() - px.min() + 1e-12))
        Yp = py[mask_y]
        Hp2 = H[mask_y]
        if len(Yp) > 2:
            idx2 = np.argsort(Yp)
            ax.plot(Yp[idx2], Hp2[idx2], "--", label=f"{plane[1]}‑profil")

        # ----------------------------------------------------
        # TREDJE AXELN PROFIL
        # ----------------------------------------------------
        # XY → Z‑profil
        # XZ → Y‑profil
        # YZ → X‑profil

        if plane == "XY":
            third = Z
            mask = (np.abs(X) < 1e-6) & (np.abs(Y) < 1e-6)

        elif plane == "XZ":
            third = Y
            mask = (np.abs(X) < 1e-6) & (np.abs(Z) < 1e-6)

        else:  # YZ
            third = X
            mask = (np.abs(Y) < 1e-6) & (np.abs(Z) < 1e-6)

        t = third[mask]
        h3 = H[mask]
        if len(t) > 2:
            idx3 = np.argsort(t)
            ax.plot(t[idx3], h3[idx3], ".-", label="3:e axel‑profil")

        # ----------------------------------------------------
        # RADIAL PROFIL
        # ----------------------------------------------------
        if self.chkRadial.isChecked():
            R = np.sqrt(px**2 + py**2)
            idxR = np.argsort(R)
            ax.plot(R[idxR], H[idxR], ":", label="Radial profil")

        # ----------------------------------------------------
        ax.set_title(f"Profiler ({plane})")
        ax.set_xlabel("Position")
        ax.set_ylabel("Hits")
        ax.legend(loc="upper right")
        ax.grid(True)

        self.canvasProf.draw()

    # =====================================================================
    def _clear_plots(self):
        self.fig3d.clear()
        self.figProf.clear()
        self.canvas3d.draw()
        self.canvasProf.draw()


# ======================================================================
# COMMAND
# ======================================================================
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
