# -*- coding: utf-8 -*-
import os
import numpy as np
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
from PySide.QtWidgets import QSizePolicy

import matplotlib

matplotlib.use("Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from .scan_db import HitsDB

DOCK_OBJECT_NAME = "BeamAbsorberHeatmapDock"


class BeamAbsorberHeatmapDock(QtWidgets.QDockWidget):

    def __init__(self, parent=None):
        super().__init__("Absorber-Heatmap-Viewer", parent)
        self.setObjectName(DOCK_OBJECT_NAME)

        self.db = HitsDB()
        self._last_mtime = None

        self._build_ui()
        self._populate_doc_list()
        self._update_plot()

        self._watch = QtCore.QTimer(self)
        self._watch.timeout.connect(self._maybe_refresh)
        self._watch.start(500)

    # ================= UI =================
    def _build_ui(self):
        central = QtWidgets.QWidget(self)
        self.setWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        form = QtWidgets.QFormLayout()

        self.comboDoc = QtWidgets.QComboBox()
        self.comboPlane = QtWidgets.QComboBox()
        self.comboPlane.addItems(["XY", "XZ", "YZ"])

        self.btnDeleteDoc = QtWidgets.QPushButton("Ta bort")

        self.chkSmooth = QtWidgets.QCheckBox("Utjämna (median+gauss)")
        self.spinSmooth = QtWidgets.QSpinBox()
        self.spinSmooth.setRange(1, 10)
        self.spinSmooth.setValue(2)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.comboDoc)
        row.addWidget(self.btnDeleteDoc)
        row.addWidget(QtWidgets.QLabel("Plan:"))
        row.addWidget(self.comboPlane)

        smooth_row = QtWidgets.QHBoxLayout()
        smooth_row.addWidget(self.chkSmooth)
        smooth_row.addWidget(QtWidgets.QLabel("Styrka:"))
        smooth_row.addWidget(self.spinSmooth)

        form.addRow("Dokument:", self._wrap(row))
        form.addRow(smooth_row)

        layout.addLayout(form)

        # Plot
        plotArea = QtWidgets.QHBoxLayout()

        # --- 3D plot ---
        self.fig3d = Figure(figsize=(5, 5))
        self.canvas3d = FigureCanvas(self.fig3d)
        self.canvas3d.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.canvas3d.updateGeometry()
        plotArea.addWidget(self.canvas3d)

        # --- Profile plot ---
        self.figProf = Figure(figsize=(5, 5))
        self.canvasProf = FigureCanvas(self.figProf)
        self.canvasProf.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.canvasProf.updateGeometry()
        plotArea.addWidget(self.canvasProf)

        # Make plots stretch properly
        plotArea.setStretch(0, 1)
        plotArea.setStretch(1, 1)

        layout.addLayout(plotArea, 1)

        # signals
        self.comboDoc.currentIndexChanged.connect(self._doc_changed)
        self.comboDoc.showPopup = self._wrap_doc_popup(self.comboDoc.showPopup)

        self.comboPlane.currentIndexChanged.connect(self._doc_changed)
        self.chkSmooth.toggled.connect(self._update_plot)
        self.spinSmooth.valueChanged.connect(self._update_plot)

        self.btnDeleteDoc.clicked.connect(self._on_delete_document_clicked)

    def _wrap(self, layout):
        w = QtWidgets.QWidget()
        w.setLayout(layout)
        return w

    def _wrap_doc_popup(self, original):
        def wrapper():
            self._populate_doc_list()
            original()

        return wrapper

    # ================= DATA =================
    def _populate_doc_list(self):
        current = self.comboDoc.currentText()
        docs = self.db.list_documents()

        self.comboDoc.blockSignals(True)
        self.comboDoc.clear()

        if docs:
            self.comboDoc.addItems(docs)
        else:
            self.comboDoc.addItem("<tom>")

        idx = self.comboDoc.findText(current)
        if idx >= 0:
            self.comboDoc.setCurrentIndex(idx)

        self.comboDoc.blockSignals(False)

    def _doc_changed(self):
        self._last_mtime = None
        self._update_plot()

    def _maybe_refresh(self):
        try:
            mtime = os.path.getmtime(self.db.path)
        except:
            return

        if mtime != self._last_mtime:
            self._last_mtime = mtime
            self._update_plot()

    # ================= CORE =================
    def _update_plot(self):
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

        if plane == "XY":
            px, py = X, Y
        elif plane == "XZ":
            px, py = X, Z
        else:
            px, py = Y, Z

        Xi, Yi, Hi = self._build_grid(px, py, H)

        self._plot_surface(Xi, Yi, Hi, plane)
        self._plot_profiles(Xi, Yi, Hi)

    # ================= GRID =================
    def _build_grid(self, X, Y, H, res=80):
        xi = np.linspace(X.min(), X.max(), res)
        yi = np.linspace(Y.min(), Y.max(), res)
        Xi, Yi = np.meshgrid(xi, yi)

        Hi = np.zeros_like(Xi)

        for i in range(res):
            for j in range(res):
                d = np.sqrt((X - Xi[i, j]) ** 2 + (Y - Yi[i, j]) ** 2)
                w = 1.0 / (d + 1e-6)
                Hi[i, j] = np.sum(w * H) / np.sum(w)

        if self.chkSmooth.isChecked():
            Hi = self._median_filter(Hi, 3)
            Hi = self._gaussian_edge(Hi, self.spinSmooth.value())

        return Xi, Yi, Hi

    # ================= FILTERS =================
    def _median_filter(self, data, k=3):
        pad = k // 2
        padded = np.pad(data, pad, mode="edge")
        out = np.zeros_like(data)

        for i in range(data.shape[0]):
            for j in range(data.shape[1]):
                window = padded[i : i + k, j : j + k]
                out[i, j] = np.median(window)

        return out

    def _gaussian_edge(self, data, sigma):
        size = int(2 * sigma + 1)
        x = np.linspace(-sigma, sigma, size)
        kernel = np.exp(-0.5 * (x / sigma) ** 2)
        kernel /= kernel.sum()

        pad = size // 2
        padded = np.pad(data, pad, mode="edge")

        out = np.copy(data)

        for i in range(data.shape[0]):
            for j in range(data.shape[1]):
                window = padded[i : i + size, j : j + size]
                out[i, j] = np.sum(window * np.outer(kernel, kernel))

        return out

    # ================= PLOTS =================
    def _plot_surface(self, Xi, Yi, Hi, plane):
        self.fig3d.clear()
        ax = self.fig3d.add_subplot(111, projection="3d")

        ax.plot_surface(Xi, Yi, Hi, cmap="viridis")
        ax.set_title(f"3D ({plane})")

        self.canvas3d.draw_idle()

    def _plot_profiles(self, Xi, Yi, Hi):
        self.figProf.clear()
        ax = self.figProf.add_subplot(111)

        mid_x = Hi.shape[0] // 2
        mid_y = Hi.shape[1] // 2

        ax.plot(Xi[mid_x, :], Hi[mid_x, :], label="X profil")
        ax.plot(Yi[:, mid_y], Hi[:, mid_y], "--", label="Y profil")

        ax.legend()
        ax.grid(True)

        self.canvasProf.draw_idle()

    # ================= UTIL =================
    def _clear_plots(self):
        self.fig3d.clear()
        self.figProf.clear()
        self.canvas3d.draw_idle()
        self.canvasProf.draw_idle()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.canvas3d.draw_idle()
        self.canvasProf.draw_idle()

    def _on_delete_document_clicked(self):
        doc = self.comboDoc.currentText()
        if "<" in doc:
            return

        ok = QtWidgets.QMessageBox.question(
            self,
            "Ta bort",
            f"Ta bort {doc}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )

        if ok == QtWidgets.QMessageBox.Yes:
            self.db.delete_document(doc)
            self._populate_doc_list()
            self._clear_plots()


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
