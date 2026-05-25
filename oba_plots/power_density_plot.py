# -*- coding: utf-8 -*-
# power_density_plot.py

import os
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore, QtGui

import matplotlib

matplotlib.rcParams["font.family"] = "DejaVu Sans"

import numpy as np
from scipy.ndimage import gaussian_filter

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5 import NavigationToolbar2QT as NavigationToolbar
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

from oba_rayengine.oba_ray_core import OBARayManager
from oba_rayengine.oba_ray_analyser import collect_ray_hits_and_stats
from .show_xyz_live_list import OBA_ShowXYZLiveList
from .filter_panel import ClusterHitFilterPanel

ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "icons")


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


def compute_power_density(hits, filter_spec, plane, bins, quantity):
    xs, ys, ws = [], [], []

    for h in hits:
        if h["emitter_id"] not in filter_spec["emitters"]:
            continue
        if h["object"] not in filter_spec["objects"]:
            continue

        if quantity == "net_power":
            val = (h.get("power_out") or 0.0) - (h.get("power_in") or 0.0)
        else:
            val = h.get(quantity)

        # val = h.get(quantity)
        if val is None:
            continue

        x, y = project_point(h["point"], plane)
        xs.append(x)
        ys.append(y)
        ws.append(val)

    if not xs:
        return None, None, None

    return np.histogram2d(xs, ys, bins=bins, weights=ws)


# -------------------------------------------------
class PowerDensityPlotDialog(QtWidgets.QDialog):

    def __init__(self):
        super().__init__(Gui.getMainWindow())

        self.setWindowTitle("Ray Power Density Plot")
        self.resize(1150, 900)

        self._init_ui()

        OBARayManager().add_listener(self.on_rays_updated)
        self.reload_plot()

    # -------------------------------------------------
    def _init_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        # -------------------------------------------------
        # Top controls
        # -------------------------------------------------
        top = QtWidgets.QHBoxLayout()
        root.addLayout(top)

        btnReload = QtWidgets.QPushButton("Reload")
        btnReload.clicked.connect(self.reload_plot)
        top.addWidget(btnReload)

        top.addWidget(QtWidgets.QLabel("Plane:"))
        self.cmbPlane = QtWidgets.QComboBox()
        self.cmbPlane.addItems(["XY", "XZ", "YZ"])
        top.addWidget(self.cmbPlane)

        top.addWidget(QtWidgets.QLabel("Power:"))
        self.cmbQuantity = QtWidgets.QComboBox()
        self.cmbQuantity.addItem("Power In", userData="power_in")
        self.cmbQuantity.addItem("Power Out", userData="power_out")
        self.cmbQuantity.addItem("Absorbed Power", userData="absorbed_power")
        self.cmbQuantity.addItem("Net Power (Out − In)", userData="net_power")

        top.addWidget(self.cmbQuantity)

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

        self.chkFlip = QtWidgets.QCheckBox("Flip")
        top.addWidget(self.chkFlip)

        self.chkLog = QtWidgets.QCheckBox("Log")
        top.addWidget(self.chkLog)

        self.chkEqual = QtWidgets.QCheckBox("Equal")
        self.chkEqual.setChecked(False)
        top.addWidget(self.chkEqual)

        self.chkGrid = QtWidgets.QCheckBox("Grid")
        top.addWidget(self.chkGrid)

        top.addStretch(1)

        self.chkShowFilter = QtWidgets.QCheckBox("Show Filter")
        self.chkShowFilter.setChecked(True)
        top.addWidget(self.chkShowFilter)

        self.chk3D = QtWidgets.QCheckBox("3D")
        self.chk3D.setChecked(False)
        self.chk3D.toggled.connect(self._update_plot_layout)
        top.addWidget(self.chk3D)

        self.btn_xyz_list = QtWidgets.QPushButton("XYZ list")
        self.btn_xyz_list.setIcon(QtGui.QIcon(os.path.join(ICON_DIR, "xyz_list.svg")))
        top.addWidget(self.btn_xyz_list)

        # -------------------------------------------------
        # Matplotlib canvases
        # -------------------------------------------------
        self.fig2d = Figure()
        self.canvas2d = FigureCanvas(self.fig2d)
        self.toolbar = NavigationToolbar(self.canvas2d, self)

        self.fig3d = Figure()
        self.canvas3d = FigureCanvas(self.fig3d)
        self.canvas3d.setVisible(False)

        root.addWidget(self.toolbar)

        # -------------------------------------------------
        # Horizontal splitter: 2D | 3D
        # -------------------------------------------------
        self.plotSplitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.plotSplitter.addWidget(self.canvas2d)
        self.plotSplitter.addWidget(self.canvas3d)
        self.plotSplitter.setStretchFactor(0, 1)
        self.plotSplitter.setStretchFactor(1, 1)

        # -------------------------------------------------
        # Filter panel
        # -------------------------------------------------
        self.filterPanel = ClusterHitFilterPanel(self)
        self.filterPanel.filter_changed.connect(self.reload_plot)
        self.filterPanel.setMaximumHeight(220)
        self.chkShowFilter.toggled.connect(self.filterPanel.setVisible)

        # -------------------------------------------------
        # Vertical splitter: plots | filter
        # -------------------------------------------------
        mainSplitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        mainSplitter.addWidget(self.plotSplitter)
        mainSplitter.addWidget(self.filterPanel)
        mainSplitter.setStretchFactor(0, 1)
        mainSplitter.setStretchFactor(1, 0)

        root.addWidget(mainSplitter)

        # -------------------------------------------------
        # Status
        # -------------------------------------------------
        self.lblStatus = QtWidgets.QLabel("")
        root.addWidget(self.lblStatus)

        # -------------------------------------------------
        # Signals
        # -------------------------------------------------
        # ComboBox
        self.cmbPlane.currentIndexChanged.connect(self.reload_plot)
        self.cmbQuantity.currentIndexChanged.connect(self.reload_plot)

        # SpinBoxes
        self.spnBins.valueChanged.connect(self.reload_plot)
        self.spnSigma.valueChanged.connect(self.reload_plot)

        # CheckBoxes
        self.chkFlip.stateChanged.connect(self.reload_plot)
        self.chkLog.stateChanged.connect(self.reload_plot)
        self.chkEqual.stateChanged.connect(self.reload_plot)
        self.chkGrid.stateChanged.connect(self.reload_plot)

        self.btn_xyz_list.clicked.connect(self._open_xyz_list)

    # -------------------------------------------------
    def _update_plot_layout(self, enabled):
        self.canvas3d.setVisible(enabled)
        self.plotSplitter.setSizes([1, 1] if enabled else [1, 0])
        self.reload_plot()

    # -------------------------------------------------
    def _open_xyz_list(self):
        OBA_ShowXYZLiveList(parent=self)

    # -------------------------------------------------
    def on_rays_updated(self):
        QtCore.QTimer.singleShot(0, self.reload_plot)

    # -------------------------------------------------

    def reload_plot(self):
        hits, _ = collect_ray_hits_and_stats(mode="final")

        if self.filterPanel.emitter_list.count() == 0:
            self.filterPanel.set_mode("final")

        filter_spec = self.filterPanel.get_filter_spec()
        quantity = self.cmbQuantity.currentData()

        # ---------- 2D ----------
        self.fig2d.clear()
        ax2d = self.fig2d.add_subplot(111)

        H, xedges, yedges = compute_power_density(
            hits,
            filter_spec,
            self.cmbPlane.currentText(),
            self.spnBins.value(),
            quantity,
        )

        if H is not None:
            if self.spnSigma.value() > 0:
                H = gaussian_filter(H, sigma=self.spnSigma.value())
            if self.chkLog.isChecked():
                H = np.log10(H + 1e-12)

            H_plot = H.T
            x0, x1 = xedges[0], xedges[-1]
            y0, y1 = yedges[0], yedges[-1]

            # 🔥 flip axes
            if self.chkFlip.isChecked():
                H_plot = H_plot.T
                x0, x1, y0, y1 = y0, y1, x0, x1

            im = ax2d.imshow(
                H_plot,
                origin="lower",
                extent=[x0, x1, y0, y1],
                cmap="plasma",
                aspect="equal" if self.chkEqual.isChecked() else "auto",
            )

            # im = ax2d.imshow(
            #     H.T,
            #     origin="lower",
            #     extent=[xedges[0], xedges[-1], yedges[0], yedges[-1]],
            #     cmap="plasma",
            #     aspect="equal" if self.chkEqual.isChecked() else "auto",
            # )
            self.fig2d.colorbar(im, ax=ax2d)

        self.canvas2d.draw_idle()

        # ---------- 3D ----------
        if self.chk3D.isChecked():
            self._draw_3d_plot(hits, filter_spec)

        if quantity == "net_power":
            total_power = sum((h.get("power_out") or 0.0) - (h.get("power_in") or 0.0) for h in hits)
        else:
            total_power = sum(h.get(quantity) or 0.0 for h in hits)

        self.lblStatus.setText(f"Hits: {len(hits)} | Σ Power: {total_power:.6g}")

    # -------------------------------------------------

    def _draw_3d_plot(self, hits, filter_spec):
        self.fig3d.clear()
        ax = self.fig3d.add_subplot(111, projection="3d")

        # -------------------------------------------------
        # Group hits by object
        # -------------------------------------------------
        hits_by_object = {}

        for h in hits:
            if h["emitter_id"] not in filter_spec["emitters"]:
                continue
            if h["object"] not in filter_spec["objects"]:
                continue
            hits_by_object.setdefault(h["object"], []).append(h)

        if not hits_by_object:
            self.canvas3d.draw_idle()
            return

        # -------------------------------------------------
        # Plot points + samla ALLA punkter
        # -------------------------------------------------
        cmap = matplotlib.cm.get_cmap("tab10")
        all_xs, all_ys, all_zs = [], [], []

        for i, (obj_name, obj_hits) in enumerate(sorted(hits_by_object.items())):
            xs, ys, zs = [], [], []

            for h in obj_hits:
                x, y, z = h["point"]
                xs.append(x)
                ys.append(y)
                zs.append(z)

            all_xs.extend(xs)
            all_ys.extend(ys)
            all_zs.extend(zs)

            ax.scatter(
                xs,
                ys,
                zs,
                color=cmap(i % cmap.N),
                s=40,
                depthshade=True,
                label=obj_name,
                zorder=2,
            )

        # -------------------------------------------------
        # Reference plane (valt plan)
        # -------------------------------------------------
        if all_xs:
            plane = self.cmbPlane.currentText()
            n = 25

            xmin, xmax = min(all_xs), max(all_xs)
            ymin, ymax = min(all_ys), max(all_ys)
            zmin, zmax = min(all_zs), max(all_zs)

            if plane == "XY":
                X, Y = np.meshgrid(
                    np.linspace(xmin, xmax, n),
                    np.linspace(ymin, ymax, n),
                )
                Z = np.zeros_like(X)

            elif plane == "XZ":
                X, Z = np.meshgrid(
                    np.linspace(xmin, xmax, n),
                    np.linspace(zmin, zmax, n),
                )
                Y = np.zeros_like(X)

            elif plane == "YZ":
                Y, Z = np.meshgrid(
                    np.linspace(ymin, ymax, n),
                    np.linspace(zmin, zmax, n),
                )
                X = np.zeros_like(Y)
            else:
                X = Y = Z = None

            if X is not None:
                ax.plot_surface(
                    X,
                    Y,
                    Z,
                    color="gray",
                    alpha=0.25,  # ✅ halvtransparent
                    linewidth=0,
                    antialiased=True,
                    zorder=0,  # ✅ bakom punkterna
                )

        # -------------------------------------------------
        # Axes & legend
        # -------------------------------------------------
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")
        ax.legend(title="Object")

        self.canvas3d.draw_idle()

        print(f"3D plot: {sum(len(v) for v in hits_by_object.values())} points | " f"objects={tuple(hits_by_object.keys())}")

    def _draw_3d_plot_med_power(self, hits, filter_spec):
        print("3D raw points:")
        for h in hits:
            print(h["point"])

        self.fig3d.clear()
        ax = self.fig3d.add_subplot(111, projection="3d")

        xs, ys, zs, ps = [], [], [], []

        for h in hits:
            if h["emitter_id"] not in filter_spec["emitters"]:
                continue
            if h["object"] not in filter_spec["objects"]:
                continue

            x, y, z = h["point"]
            xs.append(x)
            ys.append(y)
            zs.append(z)
            ps.append(h.get("power_in", 0.0))

        if xs:
            sizes = [20 + 200 * p / max(ps) for p in ps]
            # sc = ax.scatter(xs, ys, zs, c=ps, s=sizes, cmap="plasma")
            sc = ax.scatter(xs, ys, zs, c=ps, cmap="plasma", s=4)
            self.fig3d.colorbar(sc, ax=ax, shrink=0.6)

        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")

        self.canvas3d.draw_idle()

        print(f"3D plot: {len(xs)} points | " f"emitters={filter_spec['emitters']} | " f"objects={filter_spec['objects']}")

    # -------------------------------------------------
    def closeEvent(self, event):
        OBARayManager().remove_listener(self.on_rays_updated)
        super().closeEvent(event)


# -------------------------------------------------
def ShowPowerDensityPlotDialog():
    dlg = PowerDensityPlotDialog()
    dlg.show()
    Gui._power_density_plot = dlg
    return dlg
