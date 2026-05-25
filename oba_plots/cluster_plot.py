# -*- coding: utf-8 -*-
# cluster_plot.py

import os
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore

import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5 import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D  # noqa
import numpy as np


from .cluster_core import *
from oba_rayengine.oba_ray_core import OBARayManager
from oba_rayengine.oba_ray_analyser import aggregate_path_statistics
from oba_rayengine.oba_ray_analyser import debug_print_surface_clusters, aggregate_interaction_clusters


from .show_xyz_live_list import OBA_ShowXYZLiveList
from .filter_panel import ClusterHitFilterPanel

ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "icons")


# -------------------------------------------------
class ClusterPlotDialog(QtWidgets.QDialog):

    def __init__(self):
        super().__init__(Gui.getMainWindow())

        self.setWindowTitle("Cluster Plot")
        self.resize(1100, 900)

        OBARayManager().add_listener(self.on_rays_updated)

        self._init_ui()
        self.reload_plot()

    # -------------------------------------------------
    def _init_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        # ================= TOP BAR =================
        top = QtWidgets.QHBoxLayout()
        root.addLayout(top)

        top.addWidget(QtWidgets.QLabel("Mode:"))
        self.cmbMode = QtWidgets.QComboBox()
        self.cmbMode.addItems(["final", "all"])
        top.addWidget(self.cmbMode)

        btnReload = QtWidgets.QPushButton("Reload")
        btnReload.clicked.connect(self.reload_plot)
        top.addWidget(btnReload)

        top.addSpacing(15)

        top.addWidget(QtWidgets.QLabel("Plane:"))
        self.cmbPlane = QtWidgets.QComboBox()
        self.cmbPlane.addItems(["XY", "XZ", "YZ"])
        top.addWidget(self.cmbPlane)

        self.chkFlip = QtWidgets.QCheckBox("Flip")
        top.addWidget(self.chkFlip)

        self.chkGrid = QtWidgets.QCheckBox("Grid")
        self.chkGrid.setChecked(True)
        top.addWidget(self.chkGrid)

        self.chkEqual = QtWidgets.QCheckBox("Equal")
        self.chkEqual.setChecked(False)
        top.addWidget(self.chkEqual)

        self.chkBlobs = QtWidgets.QCheckBox("Blobs")
        self.chkBlobs.setChecked(True)
        top.addWidget(self.chkBlobs)

        self.chkSmooth = QtWidgets.QCheckBox("Smooth")
        self.chkSmooth.setChecked(True)
        top.addWidget(self.chkSmooth)

        self.chkCentroids = QtWidgets.QCheckBox("Centroids")
        self.chkCentroids.setChecked(True)
        top.addWidget(self.chkCentroids)

        top.addStretch()

        # ---- Filter + 3D ----
        self.chkShowFilter = QtWidgets.QCheckBox("Show Filter")
        self.chkShowFilter.setChecked(True)
        top.addWidget(self.chkShowFilter)

        self.chk3D = QtWidgets.QCheckBox("3D")
        self.chk3D.setChecked(False)
        self.chk3D.toggled.connect(self._update_plot_layout)
        top.addWidget(self.chk3D)

        self.btnXYZ = QtWidgets.QPushButton("XYZ list")
        self.btnXYZ.clicked.connect(self._open_xyz_list)
        top.addWidget(self.btnXYZ)

        # ================= FIGURES =================
        self.fig2d = Figure()
        self.canvas2d = FigureCanvas(self.fig2d)
        self.toolbar = NavigationToolbar(self.canvas2d, self)

        self.fig3d = Figure()
        self.canvas3d = FigureCanvas(self.fig3d)
        self.canvas3d.setVisible(False)

        root.addWidget(self.toolbar)

        # ---- Horizontal splitter: 2D | 3D ----
        self.plotSplitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.plotSplitter.addWidget(self.canvas2d)
        self.plotSplitter.addWidget(self.canvas3d)
        self.plotSplitter.setStretchFactor(0, 1)
        self.plotSplitter.setStretchFactor(1, 1)

        # ================= FILTER PANEL =================
        self.filterPanel = ClusterHitFilterPanel(self)
        self.filterPanel.setMaximumHeight(220)
        self.filterPanel.filter_changed.connect(self.reload_plot)

        self.chkShowFilter.toggled.connect(self.filterPanel.setVisible)

        # ================= MAIN VERTICAL SPLITTER =================
        mainSplitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        mainSplitter.addWidget(self.plotSplitter)
        mainSplitter.addWidget(self.filterPanel)
        mainSplitter.setStretchFactor(0, 1)  # plot prioritet
        mainSplitter.setStretchFactor(1, 0)  # filter sekundär

        root.addWidget(mainSplitter)

        # ================= STATUS =================
        self.lblStatus = QtWidgets.QLabel("")
        root.addWidget(self.lblStatus)

        # ================= SIGNALS =================
        self.cmbPlane.currentIndexChanged.connect(self.reload_plot)
        self.cmbMode.currentIndexChanged.connect(self._on_mode_changed)

        for chk in (
            self.chkFlip,
            self.chkGrid,
            self.chkEqual,
            self.chkBlobs,
            self.chkSmooth,
            self.chkCentroids,
        ):
            chk.stateChanged.connect(self.reload_plot)

        # init filter panel
        self._on_mode_changed()

    # -------------------------------------------------
    def _on_mode_changed(self):
        mode = self.cmbMode.currentText()
        self.filterPanel.set_mode(None if mode == "all" else mode)
        self.reload_plot()

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
    # MAIN DRAW
    # -------------------------------------------------

    def reload_plot(self):
        mode = self.cmbMode.currentText()
        plane = self.cmbPlane.currentText()
        flip2d = self.chkFlip.isChecked()

        # -------------------------------------------------
        # 1) HIT-DATA (för punkter, blobs, 3D)
        # -------------------------------------------------
        # hits, _ = collect_ray_hits_and_stats(None if mode == "all" else "final")

        hits, _ = aggregate_path_statistics(mode="final")

        # -------------------------------------------------
        # 2) CLUSTERS (för centroids / footprint)
        # -------------------------------------------------
        clusters = aggregate_interaction_clusters(
            mode=None if mode == "all" else "final",
        )

        # debug_print_surface_clusters(
        #     plane=plane,
        #     mode="final",
        #     min_hits=3,
        # )

        filter_spec = self.filterPanel.get_filter_spec()

        # -------------------------------------------------
        # 2D PLOT
        # -------------------------------------------------
        self.fig2d.clear()
        ax = self.fig2d.add_subplot(111)

        emitters, objects, bounces = compute_domains_for_legend(hits, filter_spec)
        mixer = ColorMixer(bounces)
        marker_map = {e: "o" for e in emitters}

        # --- Raw hit points ---
        draw_points(
            ax,
            hits,
            filter_spec,
            plane,
            flip2d,
            mixer,
            marker_map,
        )

        # --- Density blobs ---
        if self.chkBlobs.isChecked():
            draw_blobs_2d(
                ax,
                hits,
                filter_spec,
                plane,
                flip2d,
                mixer,
                self.chkSmooth.isChecked(),
            )

        # --- Cluster centroids (YT-KLUSTER, inte path-stats) ---
        if self.chkCentroids.isChecked():
            draw_cluster_centroids(
                ax,
                clusters,
                filter_spec,
                plane,
                flip2d,
            )

        # --- Legends ---
        # build_legends(ax, emitters, bounces, marker_map, mixer, hits)
        # Emitters legend (vänster, samma som tidigare)
        build_emitter_legend(ax, emitters, marker_map)

        # Bounce × Face legend (höger, baserad på KLUSTER)
        build_bounce_flow_legend(ax, clusters, mixer)

        # --- Axes options ---
        if self.chkEqual.isChecked():
            ax.set_aspect("equal")
        if self.chkGrid.isChecked():
            ax.grid(True)

        self.canvas2d.draw_idle()

        # -------------------------------------------------
        # 3D PLOT (rå hits, oförändrat)
        # -------------------------------------------------
        if self.chk3D.isChecked():
            self._draw_3d_plot(hits, filter_spec)

        # -------------------------------------------------
        # STATUS
        # -------------------------------------------------
        self.lblStatus.setText(f"Hits: {len(hits)} | Emitters: {len(emitters)} | Objects: {len(objects)}")

    # -------------------------------------------------

    def _draw_3d_plot(self, hits, filter_spec):
        self.fig3d.clear()
        ax = self.fig3d.add_subplot(111, projection="3d")

        # -------------------------------------------------
        # Group hits by object (filtered)
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

        for i, (obj, obj_hits) in enumerate(sorted(hits_by_object.items())):
            xs, ys, zs = zip(*(h["point"] for h in obj_hits))

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
                label=obj,
                zorder=2,
            )

        # -------------------------------------------------
        # Reference plane (halvtransparent)
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
                # Z = np.zeros_like(X)
                z0 = np.median(all_zs)
                Z = np.full_like(X, z0)

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
                    alpha=0.25,
                    linewidth=0,
                    antialiased=True,
                    zorder=0,
                )

        # -------------------------------------------------
        # Axes & legend
        # -------------------------------------------------
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")
        ax.legend(title="Objects")

        self.canvas3d.draw_idle()

    # -------------------------------------------------
    def closeEvent(self, event):
        OBARayManager().remove_listener(self.on_rays_updated)
        super().closeEvent(event)


# -------------------------------------------------
def ShowClusterPlotDialog():
    dlg = ClusterPlotDialog()
    dlg.show()
    Gui._cluster_plot_dialog = dlg
    return dlg
