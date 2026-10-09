# -*- coding: utf-8 -*-
# heatmap_viewer.py

import os
import math
import numpy as np
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
from PySide.QtWidgets import QSizePolicy

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from .scan_db import HitsDB, get_doc_db_path
from oba_objects.oba_base import _trigger_ray_engine
from oba_rayengine.oba_ray_analyser import collect_ray_hits_and_stats, get_emitted_power

from .batch_runner import (
    apply_step_offset,
    restore_all_step_states,
    store_hits,
    find_batch_object,
    find_step_by_id,
    run_steps_for_batch,
)

DOCK_OBJECT_NAME = "BeamAbsorberHeatmapDock"


def compute_field(
    doc,
    db,
    target,
    step_obj,
    plane="XY",
    value_mode="Power In",
    emitters=None,
    grid_size=60,
    rbf_function="linear",
    rbf_smooth=0.0,
    origin_offset=None,
):
    import numpy as np
    from scipy.interpolate import Rbf

    if target is None or step_obj is None:
        return None

    if emitters is None:
        emitters = db.list_emitters(target)

    X = Y = Z = V = None
    for emitter in emitters:
        data = db.read_grid(target, emitter, step_obj.Id)
        if not data:
            continue

        WX, WY, WZ, hits, power_in, power_out, move_object, _moved_objects = data
        if not WX or not move_object:
            continue

        if value_mode == "Hits":
            values = np.asarray(hits, dtype=float)
        elif value_mode == "Power In":
            values = np.asarray(power_in, dtype=float)
        else:
            values = np.asarray(power_out, dtype=float)

        selected_name = move_object[0]
        selected_object = doc.getObject(selected_name)

        if selected_object is None:
            continue

        mask = np.asarray(move_object) == selected_name
        wx = np.asarray(WX)[mask]
        wy = np.asarray(WY)[mask]
        wz = np.asarray(WZ)[mask]
        values = values[mask]

        if V is None:
            # Beräkna råa absoluta world-koordinater för mätpunkterna
            X = selected_object.Placement.Base.x - wx
            Y = selected_object.Placement.Base.y - wy
            Z = selected_object.Placement.Base.z - wz
            V = values.copy()
        else:
            V += values

    if V is None:
        return None

    # -------------------------------------------------------------
    # 1. HITTA NU-POSITIONEN (CURRENT ABSOLUT) FÖR VALT PLAN
    # -------------------------------------------------------------
    if origin_offset is None:
        origin_offset = App.Vector(step_obj.StepOffset)

    if plane == "XY":
        current_abs_x = origin_offset.x - step_obj.StepOffset.x
        current_abs_y = origin_offset.y - step_obj.StepOffset.y
        px_abs, py_abs = X, Y
    elif plane == "XZ":
        current_abs_x = origin_offset.x - step_obj.StepOffset.x
        current_abs_y = origin_offset.z - step_obj.StepOffset.z
        px_abs, py_abs = X, Z
    elif plane == "YZ":
        current_abs_x = origin_offset.y - step_obj.StepOffset.y
        current_abs_y = origin_offset.z - step_obj.StepOffset.z
        px_abs, py_abs = Y, Z
    else:
        raise ValueError(f"Unsupported plane: {plane}")

    # -------------------------------------------------------------
    # 2. SKAPA DELTA-KOORDINATER (Relativt till Current som blir 0.0)
    # -------------------------------------------------------------
    px_delta = px_abs - current_abs_x
    py_delta = py_abs - current_abs_y

    # Unika punkter för att säkra stabil RBF
    pts = np.round(np.column_stack([px_delta, py_delta]), 9)
    _, unique_idx = np.unique(pts, axis=0, return_index=True)
    px_delta = px_delta[unique_idx]
    py_delta = py_delta[unique_idx]
    V = V[unique_idx]

    # -------------------------------------------------------------
    # 3. RUTNÄT OCH INTERPOLATION (I DELTA-RYMD)
    # -------------------------------------------------------------
    Xi_delta, Yi_delta = np.meshgrid(
        np.linspace(px_delta.min(), px_delta.max(), grid_size),
        np.linspace(py_delta.min(), py_delta.max(), grid_size),
    )

    rbf = Rbf(px_delta, py_delta, V, function=rbf_function, smooth=rbf_smooth)
    Vi = rbf(Xi_delta, Yi_delta)

    return {
        "Xi": Xi_delta,  # 2D Grid med Delta-X (0.0 i centrum)
        "Yi": Yi_delta,  # 2D Grid med Delta-Y (0.0 i centrum)
        "Vi": Vi,  # Interpolerade intensiteter
        "px": px_delta,  # Insamlade mätpunkter (Delta-X)
        "py": py_delta,  # Insamlade mätpunkter (Delta-Y)
        "V": V,  # Råa mätvärden
        "current_abs": (current_abs_x, current_abs_y),  # Sparat för GoToMax
    }


# ==========================================================
class BeamAbsorberHeatmapDock(QtWidgets.QDockWidget):
    # ==========================================================
    def __init__(self, parent=None):
        super().__init__("Heatmap Viewer", parent)
        self.setObjectName(DOCK_OBJECT_NAME)

        self.db = HitsDB(get_doc_db_path())
        self._last_mtime = None
        self._origin_offset = None
        self._commit_requested = False

        self.emitter_checks = {}
        self._current_moved_objects = ""
        self._moved_objects = []
        self._click_busy = False
        self._cancel = False

        self._build_ui()
        self._refresh_db()
        self._populate_steps()
        self._populate_targets()

        self.canvas2d.mpl_connect("button_press_event", self._on_2d_click)
        QtCore.QTimer.singleShot(0, self._target_changed)

        self._watch = QtCore.QTimer(self)
        self._watch.timeout.connect(self._maybe_refresh)
        self._watch.start(500)

    def _build_ui(self):
        central = QtWidgets.QWidget(self)
        self.setWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        form = QtWidgets.QFormLayout()

        db_row = QtWidgets.QHBoxLayout()
        self.lblDB = QtWidgets.QLabel("")
        self.btnDBRefresh = QtWidgets.QPushButton("↻")
        self.btnRun = QtWidgets.QPushButton("Run step")
        self.btnStop = QtWidgets.QPushButton("Stop")
        self.btnDelete = QtWidgets.QPushButton("Delete Step")
        self.btnCommitClose = QtWidgets.QPushButton("Commit & Close")

        db_row.addWidget(QtWidgets.QLabel("DB:"))
        db_row.addWidget(self.lblDB, 1)
        db_row.addWidget(self.btnDBRefresh)
        db_row.addSpacing(20)
        db_row.addWidget(self.btnRun)
        db_row.addWidget(self.btnStop)
        db_row.addWidget(self.btnDelete)
        db_row.addWidget(self.btnCommitClose)
        form.addRow(db_row)

        self.prog = QtWidgets.QProgressBar()
        self.lbl = QtWidgets.QLabel("")
        layout.addWidget(self.prog)
        layout.addWidget(self.lbl)

        self.comboStep = QtWidgets.QComboBox()
        form.addRow("Step:", self.comboStep)

        self.comboTarget = QtWidgets.QComboBox()
        form.addRow("Target:", self.comboTarget)

        self.comboValue = QtWidgets.QComboBox()
        self.comboValue.addItems(["Hits", "Power In", "Power Out"])
        form.addRow("Value:", self.comboValue)

        self.emitterBox = QtWidgets.QGroupBox("Emitters")
        self.emitterLayout = QtWidgets.QVBoxLayout(self.emitterBox)
        form.addRow(self.emitterBox)

        self.comboPlane = QtWidgets.QComboBox()
        self.comboPlane.addItems(["XY", "XZ", "YZ"])

        self.spinRange = QtWidgets.QDoubleSpinBox()
        self.spinRange.setRange(0.01, 100.0)
        self.spinRange.setDecimals(2)
        self.spinRange.setSingleStep(0.05)
        self.spinRange.setValue(0.40)

        self.chkPercent = QtWidgets.QCheckBox("Show % of emitted rays/power")
        self.chkPlane2D = QtWidgets.QCheckBox("2D plane view")
        self.btnGotoMax = QtWidgets.QPushButton("Go to Max")

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Plane"))
        row.addWidget(self.comboPlane)
        row.addSpacing(15)
        row.addWidget(QtWidgets.QLabel("Range"))
        row.addWidget(self.spinRange)
        row.addSpacing(15)
        row.addWidget(self.chkPercent)
        row.addSpacing(15)
        row.addWidget(self.chkPlane2D)
        row.addSpacing(15)
        row.addWidget(self.btnGotoMax)
        row.addStretch()

        self.lblMoved = QtWidgets.QLabel("Moved: -")
        form.addRow("Moving:", self.lblMoved)

        form.addRow(row)
        layout.addLayout(form)

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

        self.btnGotoMax.clicked.connect(self._goto_maximum)
        self.spinRange.valueChanged.connect(self._update_plot)
        self.comboStep.currentIndexChanged.connect(self._update_plot)
        self.comboTarget.currentIndexChanged.connect(self._target_changed)
        self.comboValue.currentIndexChanged.connect(self._update_plot)
        self.comboPlane.currentIndexChanged.connect(self._update_plot)
        self.chkPercent.toggled.connect(self._update_plot)
        self.chkPlane2D.toggled.connect(self._update_plot)

        self.btnRun.clicked.connect(self._run_single)
        self.btnStop.clicked.connect(self._stop_run)
        self.btnDelete.clicked.connect(self._delete_step)
        self.btnCommitClose.clicked.connect(self._commit_and_close)

    def _refresh_db(self):
        path = get_doc_db_path()
        if self.db.path != path:
            self.db.close()
            self.db = HitsDB(path)
