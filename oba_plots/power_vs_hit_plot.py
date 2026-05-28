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

    LABELS = {
        None: "",
        "power_in": "Power In",
        "power_out": "Power Out",
        "absorbed_power": "Absorbed Power",
        "ray_count": "Ray Count",
        "ray_length_seg": "Segment Length",
        "ray_length_total": "Total Length",
        "loss_per_meter": "Loss per meter",
    }

    def __init__(self):
        super().__init__(Gui.getMainWindow())

        self.setWindowTitle("Power / Rays vs Hit")
        self.resize(1150, 720)

        self._init_ui()

        # ✅ NU finns comboboxarna
        self.cmbY1.setCurrentIndex(1)  # Power In
        self.cmbY2.setCurrentIndex(0)  # None

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

        # -------- LEFT AXIS --------
        top.addWidget(QtWidgets.QLabel("Y1:"))
        self.cmbY1 = QtWidgets.QComboBox()
        self._fill_quantity_combo(self.cmbY1)
        self.cmbY1.setCurrentIndex(0)
        top.addWidget(self.cmbY1)

        self.chkNorm1 = QtWidgets.QCheckBox("Y1 %")
        top.addWidget(self.chkNorm1)

        # -------- RIGHT AXIS --------
        top.addWidget(QtWidgets.QLabel("Y2:"))
        self.cmbY2 = QtWidgets.QComboBox()
        self._fill_quantity_combo(self.cmbY2)
        self.cmbY2.setCurrentIndex(1)
        top.addWidget(self.cmbY2)

        self.chkNorm2 = QtWidgets.QCheckBox("Y2 %")
        top.addWidget(self.chkNorm2)

        # -------- OPTIONS --------
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
        self.cmbY1.currentIndexChanged.connect(self.reload_plot)
        self.cmbY2.currentIndexChanged.connect(self.reload_plot)
        self.chkNorm1.stateChanged.connect(self.reload_plot)
        self.chkNorm2.stateChanged.connect(self.reload_plot)

    # -------------------------------------------------
    def _fill_quantity_combo(self, cmb):
        cmb.addItem("None", None)  # ✅ NY
        cmb.addItem("Power In", "power_in")
        cmb.addItem("Power Out", "power_out")
        cmb.addItem("Absorbed Power", "absorbed_power")
        cmb.addItem("Ray Count", "ray_count")

        cmb.addItem("Ray Length (segment)", "ray_length")
        cmb.addItem("Ray Length (cumulative)", "ray_length_total")

        cmb.addItem("Loss per meter", "loss_per_meter")

    # -------------------------------------------------
    def on_rays_updated(self):
        QtCore.QTimer.singleShot(0, self.reload_plot)

    # -------------------------------------------------
    def reload_plot(self):
        import numpy as np

        length_samples = defaultdict(list)

        hits, _ = collect_ray_hits_and_stats(mode="final")

        if self.filterPanel.emitter_list.count() == 0:
            self.filterPanel.set_mode("final")

        filter_spec = self.filterPanel.get_filter_spec()

        q1 = self.cmbY1.currentData()
        q2 = self.cmbY2.currentData()

        # -------------------------------------------------
        # Collect per bounce
        # -------------------------------------------------
        data1 = defaultdict(float)
        data2 = defaultdict(float) if q2 is not None else None

        count_per_bounce = defaultdict(int)

        for h in hits:
            if h["emitter_id"] not in filter_spec["emitters"]:
                continue
            if h["object"] not in filter_spec["objects"]:
                continue

            b = h["bounce"]

            seg = h.get("segment_distance", 0.0)
            length_samples[b].append(seg)

            count_per_bounce[b] += 1

            def get_val(q):
                if q is None:
                    return 0.0

                elif q == "ray_count":
                    return 1.0

                elif q == "ray_length_seg":
                    return seg

                elif q == "ray_length_total":
                    return h.get("total_distance", 0.0)

                elif q == "loss_per_meter":
                    absorbed = h.get("absorbed_power", 0.0)
                    return absorbed / seg if seg > 1e-12 else 0.0

                else:
                    return h.get(q, 0.0)

            data1[b] += get_val(q1)

            if data2 is not None:
                data2[b] += get_val(q2)

        # -------------------------------------------------
        # FINALIZE DATA (✅ här sker all logik)
        # -------------------------------------------------
        def finalize_data(q, data):
            result = {}

            for b in data:
                samples = length_samples[b]
                n = count_per_bounce[b]

                if q == "ray_length_seg":
                    # ✅ spridning (mycket mer informativ)
                    result[b] = np.std(samples)

                elif q == "ray_length_total":
                    result[b] = data[b] / n if n > 0 else 0.0

                elif q == "loss_per_meter":
                    result[b] = data[b] / n if n > 0 else 0.0

                else:
                    result[b] = data[b]

            return result

        data1 = finalize_data(q1, data1)

        if data2 is not None:
            data2 = finalize_data(q2, data2)

        if not data1:
            self.fig.clear()
            self.canvas.draw_idle()
            self.lblStatus.setText("No data")
            return

        bounces = sorted(data1.keys())

        y1 = [data1[b] for b in bounces]
        y2 = [data2[b] for b in bounces] if data2 is not None else None

        # -------------------------------------------------
        # NORMALIZATION
        # -------------------------------------------------
        def normalize(vals):
            if not vals:
                return vals
            base = vals[0]
            if abs(base) < 1e-12:
                return [0.0] * len(vals)
            return [100.0 * v / base for v in vals]

        if self.chkNorm1.isChecked():
            y1 = normalize(y1)

        if self.chkNorm2.isChecked() and y2 is not None:
            y2 = normalize(y2)

        # -------------------------------------------------
        # PLOT
        # -------------------------------------------------
        self.fig.clear()
        ax1 = self.fig.add_subplot(111)

        ax1.plot(
            bounces,
            y1,
            marker="o",
            linewidth=2.0,
            color="tab:blue",
            label=self.LABELS.get(q1, str(q1)),
        )

        ax1.set_xlabel("Bounce Index")
        ax1.set_ylabel(self.LABELS.get(q1, str(q1)) + (" (%)" if self.chkNorm1.isChecked() else ""))

        ax1.grid(True)

        if q2 is not None and y2 is not None:
            ax2 = ax1.twinx()

            ax2.plot(
                bounces,
                y2,
                linestyle="--",
                marker="s",
                linewidth=2.0,
                color="tab:red",
                label=self.LABELS.get(q2, str(q2)),
            )

            ax2.set_ylabel(self.LABELS.get(q2, str(q2)) + (" (%)" if self.chkNorm2.isChecked() else ""))

            ax2.legend(loc="upper right")
            self.chkNorm2.setEnabled(True)
        else:
            self.chkNorm2.setEnabled(False)

        ax1.legend(loc="upper left")

        self.canvas.draw_idle()

        # -------------------------------------------------
        # STATUS
        # -------------------------------------------------
        total_hits = sum(count_per_bounce.values())

        self.lblStatus.setText(f"Bounces: {len(bounces)} | Hits: {total_hits}")

    def closeEvent(self, event):
        OBARayManager().remove_listener(self.on_rays_updated)
        super().closeEvent(event)


# -------------------------------------------------
def ShowPowerVsHitPlotDialog():
    dlg = PowerVsHitPlotDialog()
    dlg.show()
    Gui._power_vs_hit_plot = dlg
    return dlg
