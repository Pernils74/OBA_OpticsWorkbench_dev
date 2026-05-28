# -*- coding: utf-8 -*-
# power_vs_hit_plot.py

import FreeCADGui as Gui
from PySide import QtWidgets, QtCore
import matplotlib

matplotlib.rcParams["font.family"] = "DejaVu Sans"

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5 import NavigationToolbar2QT as NavigationToolbar

from collections import defaultdict

from oba_rayengine.oba_ray_analyser import collect_ray_hits_and_stats
from oba_rayengine.oba_ray_core import OBARayManager
from .filter_panel import ClusterHitFilterPanel


# -------------------------------------------------
class PowerVsHitPlotDialog(QtWidgets.QDialog):
    """
    Power vs Hit/Bounce-plot
    Visar hur energi förändras längs strålgången.
    """

    def __init__(self):
        super().__init__(Gui.getMainWindow())

        self.setWindowTitle("Power vs Hit")
        self.resize(1100, 720)

        self._init_ui()

        OBARayManager().add_listener(self.on_rays_updated)
        self.reload_plot()

    # -------------------------------------------------
    def _init_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        # ---------- TOP BAR ----------
        top = QtWidgets.QHBoxLayout()
        root.addLayout(top)

        btnReload = QtWidgets.QPushButton("Reload")
        btnReload.clicked.connect(self.reload_plot)
        top.addWidget(btnReload)

        top.addWidget(QtWidgets.QLabel("Quantity:"))
        self.cmbQuantity = QtWidgets.QComboBox()
        self.cmbQuantity.addItem("Power In", userData="power_in")
        self.cmbQuantity.addItem("Power Out", userData="power_out")
        self.cmbQuantity.addItem("Absorbed Power", userData="absorbed_power")
        top.addWidget(self.cmbQuantity)

        self.chkNormalize = QtWidgets.QCheckBox("Normalize to %")
        top.addWidget(self.chkNormalize)

        self.chkShowRayCount = QtWidgets.QCheckBox("Show Ray Count")
        top.addWidget(self.chkShowRayCount)

        self.chkLogY = QtWidgets.QCheckBox("Log Y")
        top.addWidget(self.chkLogY)

        top.addStretch(1)

        self.chkShowFilter = QtWidgets.QCheckBox("Show Filter")
        self.chkShowFilter.setChecked(True)
        top.addWidget(self.chkShowFilter)

        # ---------- FIGURE ----------
        self.fig = Figure()
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)

        root.addWidget(self.toolbar)
        root.addWidget(self.canvas, 1)

        # ---------- FILTER ----------
        self.filterPanel = ClusterHitFilterPanel(self)
        self.filterPanel.setMaximumHeight(220)
        self.filterPanel.filter_changed.connect(self.reload_plot)
        self.chkShowFilter.toggled.connect(self.filterPanel.setVisible)

        root.addWidget(self.filterPanel)

        # ---------- STATUS ----------
        self.lblStatus = QtWidgets.QLabel("")
        self.lblStatus.setStyleSheet("color: gray;")
        root.addWidget(self.lblStatus)

        # ---------- SIGNALS ----------
        self.cmbQuantity.currentIndexChanged.connect(self.reload_plot)
        self.chkNormalize.stateChanged.connect(self.reload_plot)
        self.chkShowRayCount.stateChanged.connect(self.reload_plot)
        self.chkLogY.stateChanged.connect(self.reload_plot)

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

        # -------------------------------------------------
        # Samla data per bounce
        # -------------------------------------------------
        power_per_bounce = defaultdict(float)
        ray_count_per_bounce = defaultdict(int)

        for h in hits:
            if h["emitter_id"] not in filter_spec["emitters"]:
                continue
            if h["object"] not in filter_spec["objects"]:
                continue

            b = h["bounce"]
            val = h.get(quantity)
            if val is None:
                continue

            power_per_bounce[b] += val
            ray_count_per_bounce[b] += 1

        if not power_per_bounce:
            self.fig.clear()
            self.canvas.draw_idle()
            self.lblStatus.setText("No data")
            return

        bounces = sorted(power_per_bounce.keys())
        powers = [power_per_bounce[b] for b in bounces]
        ray_counts = [ray_count_per_bounce[b] for b in bounces]

        # -------------------------------------------------
        # Normalisering till %
        # -------------------------------------------------
        if self.chkNormalize.isChecked() and powers:
            base = powers[0]
            if abs(base) > 1e-12:
                powers = [100.0 * p / base for p in powers]
            else:
                powers = [0.0 for _ in powers]

        # -------------------------------------------------
        # Plot
        # -------------------------------------------------
        self.fig.clear()
        ax = self.fig.add_subplot(111)

        ax.plot(
            bounces,
            powers,
            marker="o",
            linewidth=2.0,
            color="tab:blue",
            label=quantity,
        )

        ax.set_xlabel("Hit / Bounce Index")
        ax.set_ylabel("Power (%)" if self.chkNormalize.isChecked() else "Power")

        ax.grid(True)

        if self.chkLogY.isChecked():
            ax.set_yscale("log")

        # -------------------------------------------------
        # Sekundär Y-axel: Ray Count
        # -------------------------------------------------
        if self.chkShowRayCount.isChecked():
            ax2 = ax.twinx()
            ax2.plot(
                bounces,
                ray_counts,
                linestyle="--",
                marker="s",
                color="tab:gray",
                alpha=0.85,
                label="Ray Count",
            )
            ax2.set_ylabel("Ray Count")

            ax2.legend(loc="upper right")

        ax.legend(loc="upper left")

        self.canvas.draw_idle()

        # -------------------------------------------------
        # Status
        # -------------------------------------------------
        total_hits = sum(ray_counts)
        total_power = sum(powers)

        self.lblStatus.setText(f"Bounces: {len(bounces)} | Hits: {total_hits} | Σ Power: {total_power:.6g}")

    # -------------------------------------------------
    def closeEvent(self, event):
        OBARayManager().remove_listener(self.on_rays_updated)
        super().closeEvent(event)


# -------------------------------------------------
def ShowPowerVsHitPlotDialog():
    dlg = PowerVsHitPlotDialog()
    dlg.show()
    Gui._power_vs_hit_plot = dlg
    return dlg
