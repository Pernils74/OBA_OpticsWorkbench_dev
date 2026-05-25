# -*- coding: utf-8 -*-
# power_density_plot.py

import FreeCADGui as Gui
from PySide import QtWidgets, QtCore

import numpy as np
from scipy.ndimage import gaussian_filter

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5 import NavigationToolbar2QT as NavigationToolbar

from raytracer.oba_ray import OBARayManager
from raytracer.oba_ray_analyser import collect_ray_hits_and_stats


# -------------------------------------------------
# Helpers
# -------------------------------------------------
def project_point(pt, plane):
    x, y, z = pt
    if plane == "XY":
        return x, y
    elif plane == "XZ":
        return x, z
    elif plane == "YZ":
        return y, z
    raise ValueError(plane)


def normalize_filter_spec(filter_spec, hits):
    spec = filter_spec or {}

    if not spec.get("emitters"):
        spec["emitters"] = tuple({h["emitter_id"] for h in hits})

    if not spec.get("objects"):
        spec["objects"] = tuple({h["object"] for h in hits})

    return spec


def compute_power_density(hits, filter_spec, plane, bins):
    xs, ys, ws = [], [], []

    for h in hits:
        if h["emitter_id"] not in filter_spec["emitters"]:
            continue
        if h["object"] not in filter_spec["objects"]:
            continue

        x, y = project_point(h["point"], plane)
        xs.append(x)
        ys.append(y)
        ws.append(h["power"])

    if not xs:
        return None, None, None

    H, xedges, yedges = np.histogram2d(xs, ys, bins=bins, weights=ws)
    return H, xedges, yedges


# -------------------------------------------------
# Dialog
# -------------------------------------------------
class PowerDensityPlotDialog(QtWidgets.QDialog):

    def __init__(self):
        super().__init__(Gui.getMainWindow())

        self.setWindowTitle("Plot Ray Power Density")
        self.resize(1100, 900)

        self._filter_spec = {}
        self._mapping = {}

        self._init_ui()

        OBARayManager().add_listener(self.on_rays_updated)
        self.reload_plot()

    # -------------------------------------------------
    def _init_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        # ---------------- Top controls ----------------
        top = QtWidgets.QHBoxLayout()
        root.addLayout(top)

        btnReload = QtWidgets.QPushButton("Reload")
        btnReload.clicked.connect(self.reload_plot)
        top.addWidget(btnReload)

        top.addWidget(QtWidgets.QLabel("Plane:"))
        self.cmbPlane = QtWidgets.QComboBox()
        self.cmbPlane.addItems(["XY", "XZ", "YZ"])
        top.addWidget(self.cmbPlane)

        top.addWidget(QtWidgets.QLabel("Bins:"))
        self.spnBins = QtWidgets.QSpinBox()
        self.spnBins.setRange(20, 500)
        self.spnBins.setValue(120)
        top.addWidget(self.spnBins)

        top.addWidget(QtWidgets.QLabel("σ:"))
        self.spnSigma = QtWidgets.QDoubleSpinBox()
        self.spnSigma.setRange(0.0, 20.0)
        self.spnSigma.setValue(3.0)
        top.addWidget(self.spnSigma)

        self.chkLog = QtWidgets.QCheckBox("Log")
        top.addWidget(self.chkLog)

        self.chkEqual = QtWidgets.QCheckBox("Equal")
        self.chkEqual.setChecked(True)
        top.addWidget(self.chkEqual)

        self.chkGrid = QtWidgets.QCheckBox("Grid")
        top.addWidget(self.chkGrid)

        top.addStretch(1)

        # 🔽 Visa filter checkbox
        self.chkShowFilter = QtWidgets.QCheckBox("Show Filter")
        self.chkShowFilter.setChecked(True)

        self.chkShowFilter.stateChanged.connect(self._toggle_filter_panel)
        top.addWidget(self.chkShowFilter)

        # ---------------- Plot ----------------
        self.fig = Figure()
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)

        root.addWidget(self.toolbar)
        root.addWidget(self.canvas)

        # ---------------- Filter panel ----------------
        self.filterPanel = QtWidgets.QWidget()
        filterLayout = QtWidgets.QHBoxLayout(self.filterPanel)

        # Emitters
        emitterBox = QtWidgets.QVBoxLayout()
        emitterBox.addWidget(QtWidgets.QLabel("<b>Emitters</b>"))
        self.emitter_list = QtWidgets.QListWidget()
        emitterBox.addWidget(self.emitter_list)

        # Objects
        objectBox = QtWidgets.QVBoxLayout()
        objectBox.addWidget(QtWidgets.QLabel("<b>Objects</b>"))
        self.object_list = QtWidgets.QListWidget()
        objectBox.addWidget(self.object_list)

        filterLayout.addLayout(emitterBox)
        filterLayout.addLayout(objectBox)

        root.addWidget(self.filterPanel)
        self.filterPanel.setVisible(self.chkShowFilter.isChecked())

        # ---------------- Status ----------------
        self.lblStatus = QtWidgets.QLabel("")
        root.addWidget(self.lblStatus)

        # Signals
        self.cmbPlane.currentIndexChanged.connect(self.reload_plot)
        self.spnBins.valueChanged.connect(self.reload_plot)
        self.spnSigma.valueChanged.connect(self.reload_plot)
        self.chkLog.stateChanged.connect(self.reload_plot)
        self.chkEqual.stateChanged.connect(self.reload_plot)
        self.chkGrid.stateChanged.connect(self.reload_plot)

    # -------------------------------------------------
    def _toggle_filter_panel(self):
        self.filterPanel.setVisible(self.chkShowFilter.isChecked())

    # -------------------------------------------------
    def _populate_filters(self, hits):
        self._mapping = OBARayManager().get_hit_mapping(mode="final")

        emitters = sorted(self._mapping.keys())
        objects = sorted({o for objs in self._mapping.values() for o in objs})

        self.emitter_list.blockSignals(True)
        self.object_list.blockSignals(True)

        self.emitter_list.clear()
        self.object_list.clear()

        for e in emitters:
            item = QtWidgets.QListWidgetItem(e)
            item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            self.emitter_list.addItem(item)

        for o in objects:
            item = QtWidgets.QListWidgetItem(o)
            item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            self.object_list.addItem(item)

        self.emitter_list.blockSignals(False)
        self.object_list.blockSignals(False)

        self.emitter_list.itemChanged.connect(self._update_object_states)
        self.object_list.itemChanged.connect(self.reload_plot)

    # -------------------------------------------------
    def _update_object_states(self):
        selected_emitters = {self.emitter_list.item(i).text() for i in range(self.emitter_list.count()) if self.emitter_list.item(i).checkState() == QtCore.Qt.Checked}

        # vilka objekt är giltiga?
        valid_objects = set()
        for e in selected_emitters:
            valid_objects |= self._mapping.get(e, set())

        for i in range(self.object_list.count()):
            item = self.object_list.item(i)
            obj = item.text()

            # 🔑 Viktig logik
            if obj in valid_objects:
                item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable)
            else:
                item.setFlags(QtCore.Qt.NoItemFlags)

        self.reload_plot()

    # -------------------------------------------------
    def _get_filter_spec(self):
        emitters = tuple(self.emitter_list.item(i).text() for i in range(self.emitter_list.count()) if self.emitter_list.item(i).checkState() == QtCore.Qt.Checked)

        objects = tuple(self.object_list.item(i).text() for i in range(self.object_list.count()) if self.object_list.item(i).checkState() == QtCore.Qt.Checked)

        return {"emitters": emitters, "objects": objects}

    # -------------------------------------------------
    def on_rays_updated(self):
        QtCore.QTimer.singleShot(0, self.reload_plot)

    # -------------------------------------------------
    def reload_plot(self):

        hits, _ = collect_ray_hits_and_stats(mode="final")

        self.fig.clear()
        ax = self.fig.add_subplot(111)

        if not hits:
            ax.text(0.5, 0.5, "No ray hits", ha="center", va="center", transform=ax.transAxes)
            self.canvas.draw_idle()
            return

        # init filter UI första gången
        if self.emitter_list.count() == 0:
            self._populate_filters(hits)

        filter_spec = normalize_filter_spec(self._get_filter_spec(), hits)

        H, xedges, yedges = compute_power_density(
            hits,
            filter_spec,
            self.cmbPlane.currentText(),
            self.spnBins.value(),
        )

        if H is None:
            ax.text(0.5, 0.5, "No data after filtering", ha="center", va="center", transform=ax.transAxes)
            self.canvas.draw_idle()
            return

        sigma = self.spnSigma.value()
        if sigma > 0:
            H = gaussian_filter(H, sigma=sigma)

        if self.chkLog.isChecked():
            H = np.log10(H + 1e-12)

        im = ax.imshow(
            H.T,
            origin="lower",
            extent=[xedges[0], xedges[-1], yedges[0], yedges[-1]],
            cmap="plasma",
            aspect="equal" if self.chkEqual.isChecked() else "auto",
        )

        self.fig.colorbar(im, ax=ax, label="Power density")

        if self.chkGrid.isChecked():
            ax.grid(True)

        total_power = sum(h["power"] for h in hits)
        self.lblStatus.setText(f"Hits: {len(hits)} | Total power: {total_power:.3f}")

        self.canvas.draw_idle()

    # -------------------------------------------------
    def closeEvent(self, event):
        OBARayManager().remove_listener(self.on_rays_updated)
        super().closeEvent(event)


# -------------------------------------------------
# FreeCAD Command
# -------------------------------------------------
def ShowPowerDensityPlotDialog():
    dlg = PowerDensityPlotDialog()
    dlg.show()
    Gui._power_density_plot = dlg
    return dlg
