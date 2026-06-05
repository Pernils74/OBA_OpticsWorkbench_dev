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
        "ray_length_seg_mean": "Segment Length (mean)",
        "ray_length_seg_std": "Segment Length (std dev)",
        "ray_length_total": "Total Path Length (mean)",
        "loss_per_meter": "Loss per meter",
        "linearity": "Linearity",
        "density_3d": "Density (3D)",
        "roundness_3d": "Roundness (3D)",
        "radius_rms": "Radius RMS",
        "focus_quality": "Focus Quality",
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

        self.chkShowLabels = QtWidgets.QCheckBox("Show Labels")
        self.chkShowLabels.setChecked(True)
        top.addWidget(self.chkShowLabels)

        self.chkShowLegend = QtWidgets.QCheckBox("Show Legend")
        self.chkShowLegend.setChecked(True)
        top.addWidget(self.chkShowLegend)

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
        self.chkShowLabels.stateChanged.connect(self.reload_plot)
        self.chkShowLegend.stateChanged.connect(self.reload_plot)

    # -------------------------------------------------
    def _fill_quantity_combo(self, cmb):
        cmb.addItem("None", None)  # ✅ NY
        cmb.addItem("Power In", "power_in")
        cmb.addItem("Power Out", "power_out")
        cmb.addItem("Absorbed Power", "absorbed_power")
        cmb.addItem("Ray Count", "ray_count")

        cmb.addItem("Segment Length Mean", "ray_length_seg_mean")
        cmb.addItem("Segment Length Std", "ray_length_seg_std")

        cmb.addItem("Ray Length (cumulative)", "ray_length_total")

        cmb.addItem("Loss per meter", "loss_per_meter")
        cmb.addItem("Linearity", "linearity")

        cmb.addItem("Density (3D)", "density_3d")
        cmb.addItem("Roundness (3D)", "roundness_3d")
        cmb.addItem("Radius RMS", "radius_rms")
        cmb.addItem("Focus Quality", "focus_quality")

    # -------------------------------------------------
    def add_labels(self, ax, x, y, color):
        if not self.chkShowLabels.isChecked():
            return
        if not y:
            return
        max_val = max(y)
        for xi, yi in zip(x, y):
            txt = f"{yi:.2f}"
            # ✅ markera max
            if yi == max_val:
                txt += " (max)"
            ax.annotate(txt, (xi, yi), textcoords="offset points", xytext=(0, 6), ha="center", fontsize=10, color=color)  # lite offset uppåt

    # -------------------------------------------------

    def on_rays_updated(self):
        QtCore.QTimer.singleShot(0, self.reload_plot)

        # -------------------------------------------------

    def reload_plot(self):
        import numpy as np

        length_samples = defaultdict(list)
        points_per_bounce = defaultdict(list)

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
            points_per_bounce[b].append(h["point"])

            count_per_bounce[b] += 1

            def get_val(q):
                if q is None:
                    return 0.0

                elif q == "ray_count":
                    return 1.0

                # elif q == "ray_length_seg":
                #     return seg

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
                pts = points_per_bounce[b]
                n = count_per_bounce[b]

                if not pts:
                    result[b] = 0.0
                    continue

                import numpy as np

                pts_arr = np.array(pts, dtype=float)
                centroid = pts_arr.mean(axis=0)

                diff = pts_arr - centroid
                radius_rms = float(np.sqrt(np.mean(np.sum(diff**2, axis=1))))

                cov = np.cov(pts_arr.T) if len(pts_arr) >= 3 else None

                def roundness(cov):
                    if cov is None:
                        return 0.0
                    vals = np.linalg.eigvals(cov)
                    lam_max = float(np.max(vals).real)
                    lam_min = float(np.min(vals).real)
                    return lam_min / lam_max if lam_max > 0 else 0.0

                if q == "density_3d":
                    # result[b] = len(pts) / (radius_rms**3 + 1e-9)
                    raw = len(pts) / (radius_rms**2 + 1e-9)
                    result[b] = 1.0 - np.exp(-0.01 * raw)

                elif q == "roundness_3d":
                    # result[b] = roundness(cov)
                    scale = min(1.0, n / 20.0)
                    result[b] = roundness(cov) * scale

                elif q == "radius_rms":
                    result[b] = radius_rms

                elif q == "linearity":
                    if cov is None:
                        result[b] = 0.0
                    else:
                        vals = np.sort(np.linalg.eigvals(cov).real)
                        result[b] = vals[-1] / (vals[0] + 1e-9)
                elif q == "focus_quality":
                    dens = len(pts) / (radius_rms**2 + 1e-9)
                    rnd = roundness(cov)
                    result[b] = dens * rnd

                elif q == "ray_length_seg_mean":
                    result[b] = np.mean(samples) if samples else 0.0

                elif q == "ray_length_seg_std":
                    result[b] = np.std(samples) if samples else 0.0

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
        def normalize(vals, ref=None):
            if not vals:
                return vals

            if ref is None:
                ref = vals[0]  # fallback (gamla beteendet)

            if abs(ref) < 1e-12:
                return [0.0] * len(vals)

            return [100.0 * v / ref for v in vals]

        if self.chkNorm1.isChecked():
            y1 = normalize(y1, max(y1))

        if self.chkNorm2.isChecked() and y2 is not None:
            y2 = normalize(y2, max(y2))

        # -------------------------------------------------
        # PLOT
        # -------------------------------------------------

        def legend_label(q, y, normalized):
            if not y:
                return self.LABELS.get(q, str(q))

            max_val = max(y)

            if normalized:
                return f"{self.LABELS.get(q, str(q))} (max={max_val:.1f}%)"
            else:
                return f"{self.LABELS.get(q, str(q))} (max={max_val:.3g})"

        def is_bar_quantity(q):
            if self.chkNorm1.isChecked() or self.chkNorm2.isChecked():
                return False
            return q in ("ray_length_seg_mean", "ray_length_seg_std", "ray_count")

        self.fig.clear()
        ax1 = self.fig.add_subplot(111)

        width = 0.4

        if is_bar_quantity(q1):
            ax1.bar(
                [b - width / 2 for b in bounces],
                y1,
                width=width,
                color="tab:blue",
                alpha=0.7,
                # label=self.LABELS.get(q1, str(q1)),
                label=legend_label(q1, y1, self.chkNorm1.isChecked()),
            )
            # ax1.bar(bounces, y1, alpha=0.7, color="tab:blue", label=self.LABELS.get(q1, str(q1)))
        else:
            ax1.plot(
                bounces,
                y1,
                marker="o",
                linewidth=2.0,
                color="tab:blue",
                # label=self.LABELS.get(q1, str(q1)),
                label=legend_label(q1, y1, self.chkNorm1.isChecked()),
            )

        # ax1.plot(
        #     bounces,
        #     y1,
        #     marker="o",
        #     linewidth=2.0,
        #     color="tab:blue",
        #     label=self.LABELS.get(q1, str(q1)),
        # )

        ax1.set_xlabel("Bounce Index")

        self.add_labels(ax1, bounces, y1, "blue")

        ax1.set_ylabel(self.LABELS.get(q1, str(q1)) + (" (%)" if self.chkNorm1.isChecked() else ""))

        ax1.grid(True)

        if q2 is not None and y2 is not None:
            ax2 = ax1.twinx()

            if is_bar_quantity(q2):
                ax2.bar(
                    [b + width / 2 for b in bounces],
                    y2,
                    width=width,
                    color="tab:red",
                    alpha=0.5,
                    # label=self.LABELS.get(q2, str(q2)),
                    label=legend_label(q2, y2, self.chkNorm2.isChecked()),
                )
                # ax2.bar(bounces, y2, alpha=0.7, color="tab:red", label=self.LABELS.get(q2, str(q2)))
            else:
                ax2.plot(
                    bounces,
                    y2,
                    linestyle="--",
                    marker="s",
                    linewidth=2.0,
                    color="tab:red",
                    # label=self.LABELS.get(q2, str(q2)),
                    label=legend_label(q2, y2, self.chkNorm2.isChecked()),
                )
            self.add_labels(ax2, bounces, y2, "red")

            # ax2.plot(
            #     bounces,
            #     y2,
            #     linestyle="--",
            #     marker="s",
            #     linewidth=2.0,
            #     color="tab:red",
            #     label=self.LABELS.get(q2, str(q2)),
            # )

            ax2.set_ylabel(self.LABELS.get(q2, str(q2)) + (" (%)" if self.chkNorm2.isChecked() else ""))

            if self.chkShowLegend.isChecked():
                ax2.legend(loc="upper right")

            self.chkNorm2.setEnabled(True)
        else:
            self.chkNorm2.setEnabled(False)

        if self.chkShowLegend.isChecked():
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
