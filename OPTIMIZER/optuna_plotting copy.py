# -*- coding: utf-8 -*-
# optuna_plots.py — version med equal-distance (2D/3D) som ny metric

import math
import os
import sys
import numpy as np
import FreeCAD as App
import FreeCADGui as Gui
from vendor_optuna.optuna.testing import trials

# from .cad_refresh import recompute_doc, _restart_optics, _refresh_3d_view
from .spreadsheet_utils import apply_cad_params

FIG_NAME = "SlotScores"
WINDOW_OBJECT_NAME = "OptunaSlotScoresWindow"


from .optimize_worker import db_path


import optuna

# --- Qt ----
from PySide import QtCore, QtWidgets, QtGui

# --- Matplotlib ---
import matplotlib

matplotlib.use("Qt5Agg", force=True)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import matplotlib.pyplot as plt

# ============================================================================================
#  UTÖKAD METRIC‑HÄMTNING — inkluderar EQUAL DISTANCE (2D / 3D)
# ============================================================================================


def _extract_series_from_study(study, ma_window, show_global):
    """
    Returnerar:
        - canonical_slots
        - xs: trialnummer per slot
        - ys_slot: slot-score
        - ys_density
        - ys_round
        - ys_radius
        - ys_eqdist: NY! equal-distance per trial (2D eller 3D)
        - gx, gy: global score
        - trial_map
    """

    trials = [t for t in study.get_trials(deepcopy=False)]

    if not trials:
        return (None, None, None, None, None, None, None, None, None, None, {})  # y_eqdist, eqmod  # gx, gy  # trial_map

    # if not trials:
    #     return None, None, None, None, None, None, None, None, {}

    # hämta canonical order
    canonical_slots = None
    for t in trials:
        sl = t.user_attrs.get("canonical_slots")
        if isinstance(sl, (list, tuple)) and sl:
            canonical_slots = list(sl)
            break

    if not canonical_slots:
        # fallback: utgå från slot_scores-längd
        for t in trials:
            ss = t.user_attrs.get("slot_scores")
            if isinstance(ss, (list, tuple)) and ss:
                canonical_slots = [f"slot-{i}" for i in range(len(ss))]
                break

    if not canonical_slots:
        return (None, None, None, None, None, None, None, None, None, None, {})

        # return None, None, None, None, None, None, None, None, {}

    # tidsserier
    xs = {slot: [] for slot in canonical_slots}
    ys_slot = {slot: [] for slot in canonical_slots}
    ys_density = {slot: [] for slot in canonical_slots}
    ys_round = {slot: [] for slot in canonical_slots}
    ys_radius = {slot: [] for slot in canonical_slots}

    # NYTT: equal-distance är globalt, inte per slot
    gx = []
    gy = []
    y_eqdist = []  # <-- equal-distance serie
    eq_mode_list = []  # <-- label-stöd

    trial_map = {}

    for t in trials:
        trial_map[t.number] = t

        if t.state.name != "COMPLETE":
            continue

        slot_scores = t.user_attrs.get("slot_scores")
        cluster_metrics = t.user_attrs.get("cluster_metrics", {})
        gcomp = t.user_attrs.get("global_components", {})

        eqval = gcomp.get("equal_distance_global", None)
        eqmode = gcomp.get("equal_distance_mode", "3D")

        if isinstance(eqval, (float, int)):
            y_eqdist.append(float(eqval))
            eq_mode_list.append(eqmode)
        else:
            y_eqdist.append(np.nan)
            eq_mode_list.append("3D")

        # fyll slot-data
        for slot in canonical_slots:
            xs[slot].append(t.number)

            # slot-score
            if slot_scores and len(slot_scores) == len(canonical_slots):
                idx = canonical_slots.index(slot)
                try:
                    ys_slot[slot].append(float(slot_scores[idx]))
                except:
                    ys_slot[slot].append(np.nan)
            else:
                ys_slot[slot].append(np.nan)

            # per cluster metrics
            cm = cluster_metrics.get(slot, {})
            ys_density[slot].append(float(cm.get("density", np.nan)))
            ys_round[slot].append(float(cm.get("roundness", np.nan)))
            ys_radius[slot].append(float(cm.get("radius3d", np.nan)))

        # global score
        if show_global and t.value is not None:
            try:
                gx.append(t.number)
                gy.append(float(t.value))
            except:
                pass

    return (
        canonical_slots,
        xs,
        ys_slot,
        ys_density,
        ys_round,
        ys_radius,
        y_eqdist,  # <-- NY
        eq_mode_list,  # <-- NY (labels)
        gx,
        gy,
        trial_map,
    )


# ============================================================================================
#   OPTUNA PLOT WINDOW (uppdaterad med equal-distance plot)
# ============================================================================================


class OptunaPlotWindow(QtWidgets.QDialog):

    trialSelected = QtCore.Signal(int, object)

    def __init__(self, *, storage_uri: str, seq_id: int, parent=None):
        super().__init__(parent)

        self.seq_id = seq_id
        self.setObjectName(f"{WINDOW_OBJECT_NAME}_{self.seq_id}")
        self.setWindowTitle(f"{FIG_NAME} – Optuna [{self.seq_id}]")
        self.resize(1150, 760)

        self.storage = storage_uri
        self.current_study_name = None
        self.trial_map = {}
        self._sel_tnum = None
        self._sel_vline = None

        # UI layout
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # --------------------------------------
        # Översta raden
        # --------------------------------------
        top = QtWidgets.QHBoxLayout()

        top.addWidget(QtWidgets.QLabel("Study:"))
        self.cmbStudy = QtWidgets.QComboBox()
        self.cmbStudy.setMinimumWidth(420)
        top.addWidget(self.cmbStudy)

        top.addWidget(QtWidgets.QLabel("Index:"))
        self.spnIdx = QtWidgets.QSpinBox()
        self.spnIdx.setRange(0, 0)
        self.spnIdx.setEnabled(False)
        self.spnIdx.setMaximumWidth(70)
        top.addWidget(self.spnIdx)

        self.btnRefresh = QtWidgets.QPushButton("Uppdatera")
        top.addWidget(self.btnRefresh)

        self.btnDelete = QtWidgets.QPushButton("Ta bort vald")
        self.btnDelete.setStyleSheet("color:red; font-weight:bold;")
        top.addWidget(self.btnDelete)

        self.chkGlobal = QtWidgets.QCheckBox("Visa global score")
        top.addWidget(self.chkGlobal)

        top.addWidget(QtWidgets.QLabel("MA:"))
        self.spnMA = QtWidgets.QSpinBox()
        self.spnMA.setRange(1, 999)
        self.spnMA.setValue(1)
        self.spnMA.setMaximumWidth(70)
        top.addWidget(self.spnMA)

        top.addWidget(QtWidgets.QLabel("Trial:"))
        self.spnTrial = QtWidgets.QSpinBox()
        self.spnTrial.setRange(0, 0)
        self.spnTrial.setEnabled(False)
        self.spnTrial.setMaximumWidth(90)
        top.addWidget(self.spnTrial)

        self.btnRedraw = QtWidgets.QPushButton("Rita")
        top.addWidget(self.btnRedraw)

        # -----------------------------------------
        # Metrics checkboxes (NY: equal-distance)
        # -----------------------------------------
        self.chkSlot = QtWidgets.QCheckBox("Slot-score")
        self.chkSlot.setChecked(True)
        self.chkDensity = QtWidgets.QCheckBox("Density")
        self.chkRound = QtWidgets.QCheckBox("Roundness")
        self.chkRadius = QtWidgets.QCheckBox("Radius3D")
        self.chkEqDist = QtWidgets.QCheckBox("Equal-distance")  # <-- NY

        top.addWidget(self.chkSlot)
        top.addWidget(self.chkDensity)
        top.addWidget(self.chkRound)
        top.addWidget(self.chkRadius)
        top.addWidget(self.chkEqDist)

        top.addStretch(1)
        root.addLayout(top)

        # Info-bar
        infobar = QtWidgets.QHBoxLayout()
        self.lblClickInfo = QtWidgets.QLabel("Klicka i grafen för att välja trial…")
        infobar.addWidget(self.lblClickInfo)
        infobar.addStretch(1)
        root.addLayout(infobar)

        # -----------------------------------------
        # Matplotlib
        # -----------------------------------------
        self.fig = plt.Figure(figsize=(6, 4), tight_layout=True)
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.toolbar.setIconSize(QtCore.QSize(16, 16))

        root.addWidget(self.toolbar)
        root.addWidget(self.canvas, 1)

        self._ensure_crosshair()
        self._ensure_selection_line()

        # -----------------------------------------
        # SIGNALER
        # -----------------------------------------
        self.btnRefresh.clicked.connect(lambda: self._reload_studies(initial=True))
        self.btnDelete.clicked.connect(self._delete_selected)
        self.cmbStudy.currentIndexChanged.connect(self._study_changed)
        self.spnIdx.valueChanged.connect(self._index_changed)

        self.btnRedraw.clicked.connect(self._redraw)
        self.spnMA.valueChanged.connect(self._redraw)
        self.chkGlobal.stateChanged.connect(self._redraw)

        self.chkSlot.stateChanged.connect(self._redraw)
        self.chkDensity.stateChanged.connect(self._redraw)
        self.chkRound.stateChanged.connect(self._redraw)
        self.chkRadius.stateChanged.connect(self._redraw)
        self.chkEqDist.stateChanged.connect(self._redraw)  # <-- NY

        self.spnTrial.valueChanged.connect(self._trial_spin_changed)

        self.canvas.mpl_connect("button_press_event", self._canvas_click)
        self.canvas.mpl_connect("motion_notify_event", self._mouse_move)
        self.canvas.mpl_connect("axes_leave_event", self._axes_leave)

        self._reload_studies(initial=True)

    # ============================================================================================
    #       STUDY LOADING & CONTROL
    # ============================================================================================

    def closeEvent(self, evt):
        global _windows
        try:
            _windows = [w for w in _windows if w is not self]
        except:
            pass
        return super().closeEvent(evt)

    def _reload_studies(self, initial=False):

        try:
            summaries = optuna.study.get_all_study_summaries(storage=self.storage)
            names = [s.study_name for s in summaries]
        except:
            try:
                names = optuna.study.get_all_study_names(storage=self.storage)
            except:
                names = []

        self.cmbStudy.blockSignals(True)
        self.cmbStudy.clear()
        for n in names:
            self.cmbStudy.addItem(n)
        self.cmbStudy.blockSignals(False)

        self.spnIdx.blockSignals(True)
        if names:
            self.spnIdx.setEnabled(True)
            self.spnIdx.setRange(0, len(names) - 1)
            if initial or self.current_study_name not in names:
                self.spnIdx.setValue(0)
                self.current_study_name = names[0]
        else:
            self.spnIdx.setEnabled(False)
            self.spnIdx.setRange(0, 0)
            self.spnIdx.setValue(0)
            self.current_study_name = None
        self.spnIdx.blockSignals(False)

        if self.current_study_name:
            self._redraw()
        else:
            self._clear_axes("Inga studier funna.")

    def _delete_selected(self):
        name = self.current_study_name
        if not name:
            QtWidgets.QMessageBox.warning(self, "Ta bort", "Ingen study vald.")
            return

        if QtWidgets.QMessageBox.question(self, "Bekräfta", f"Ta bort study:\n{name}?", QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return

        try:
            optuna.delete_study(study_name=name, storage=self.storage)
            App.Console.PrintMessage(f"[Plot] Deleted study {name}\n")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Fel", str(e))
            return

        self._reload_studies(initial=True)
        self._clear_axes("Study borttagen.")

    def _study_changed(self, idx):
        self.current_study_name = self.cmbStudy.itemText(idx)
        self._sel_tnum = None
        self._redraw()
        self.spnIdx.blockSignals(True)
        self.spnIdx.setValue(idx)
        self.spnIdx.blockSignals(False)

    def _index_changed(self, idx):
        if idx < 0 or idx >= self.cmbStudy.count():
            return
        self.cmbStudy.blockSignals(True)
        self.cmbStudy.setCurrentIndex(idx)
        self.cmbStudy.blockSignals(False)
        self.current_study_name = self.cmbStudy.itemText(idx)
        self._redraw()

    # ============================================================================================
    #   PLOTTNING
    # ============================================================================================

    def _clear_axes(self, msg=""):
        self.ax.clear()
        if msg:
            self.ax.set_title(msg)
        self._ensure_crosshair()
        self.canvas.draw_idle()

    def _redraw(self):

        if not self.current_study_name:
            self._clear_axes("Ingen study vald.")
            return

        ma_window = int(self.spnMA.value())
        show_global = bool(self.chkGlobal.isChecked())

        # ladda studie
        try:
            study = optuna.load_study(study_name=self.current_study_name, storage=self.storage)
        except Exception as e:
            self._clear_axes(f"Kunde inte ladda study: {e}")
            return

        slot_keys, xs, ys_slot, ys_density, ys_round, ys_radius, y_eqdist, eqmod, gx, gy, trial_map = _extract_series_from_study(study, ma_window, show_global)  # <-- NY

        self.trial_map = trial_map
        self._update_trial_range()

        if not slot_keys:
            self._clear_axes("Inga data.")
            return

        # rensa
        self.ax.clear()

        COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]

        # map
        METRIC_MAP = {
            "slot_score": ys_slot,
            "density": ys_density,
            "roundness": ys_round,
            "radius3d": ys_radius,
        }

        STYLE_MAP = {
            "slot_score": "-",
            "density": "--",
            "roundness": ":",
            "radius3d": "-.",
        }

        # Rita slot- och cluster-metrics
        metrics_to_plot = []
        if self.chkSlot.isChecked():
            metrics_to_plot.append("slot_score")
        if self.chkDensity.isChecked():
            metrics_to_plot.append("density")
        if self.chkRound.isChecked():
            metrics_to_plot.append("roundness")
        if self.chkRadius.isChecked():
            metrics_to_plot.append("radius3d")

        for i, slot in enumerate(slot_keys):
            col = COLORS[i % len(COLORS)]
            xdata = xs[slot]

            for m in metrics_to_plot:
                ydata = METRIC_MAP[m][slot]
                style = STYLE_MAP[m]

                # MA
                if ma_window > 1:
                    y_ma = np.convolve(np.array(ydata, dtype=float), np.ones(ma_window) / ma_window, mode="valid")
                    x_ma = xdata[len(xdata) - len(y_ma) :]
                    self.ax.plot(x_ma, y_ma, linestyle=style, color=col, label=f"{slot} · {m} (MA)")
                else:
                    self.ax.plot(xdata, ydata, linestyle=style, color=col, label=f"{slot} · {m}")

        # ======================================================================================
        #  NY: rita EQUAL DISTANCE (global serie)
        # ======================================================================================
        if self.chkEqDist.isChecked() and len(y_eqdist) > 0:

            # färg magenta
            eq_color = "#CC00CC"

            # moving average
            if ma_window > 1:
                yarr = np.array(y_eqdist, dtype=float)
                y_ma = np.convolve(yarr, np.ones(ma_window) / ma_window, mode="valid")
                x_ma = list(trial_map.keys())[len(trial_map) - len(y_ma) :]
                self.ax.plot(x_ma, y_ma, color=eq_color, linewidth=2.0, linestyle="-", label="Equal-distance (MA)")
            else:
                # label visar typ
                # (notera: eqmod per trial kan variera, men i praktiken konstant per study)
                mode_hint = eqmod[-1] if eqmod else "3D"
                label = f"Equal-distance ({mode_hint})"
                self.ax.plot(list(trial_map.keys()), y_eqdist, color=eq_color, linewidth=1.8, linestyle="-", label=label)

        # ======================================================================================
        #  GLOBAL SCORE
        # ======================================================================================
        if show_global and gx:
            self.ax.plot(gx, gy, color="black", linewidth=1.5, alpha=0.85, label="global_score")

        # styling
        self.ax.grid(True, linestyle="--", alpha=0.35)
        self.ax.set_xlabel("Trialnummer")
        self.ax.set_ylabel("Score")
        self.ax.set_title("Cluster metrics per trial")
        self.ax.legend(loc="best", fontsize=9)

        self._ensure_crosshair()
        self._ensure_selection_line()
        self._update_selection_marker()

        self.canvas.draw_idle()

    # ============================================================================================
    #   TRIAL / MARKERS
    # ============================================================================================

    def _update_trial_range(self):
        nums = sorted(self.trial_map.keys())
        self.spnTrial.blockSignals(True)
        if nums:
            self.spnTrial.setEnabled(True)
            self.spnTrial.setRange(nums[0], nums[-1])
        else:
            self.spnTrial.setEnabled(False)
            self.spnTrial.setRange(0, 0)
        self.spnTrial.blockSignals(False)

    def _trial_spin_changed(self, val):
        if val not in self.trial_map:
            if not self.trial_map:
                return
            # snap to nearest
            nearest = min(self.trial_map.keys(), key=lambda n: abs(n - val))
            self.spnTrial.blockSignals(True)
            self.spnTrial.setValue(nearest)
            self.spnTrial.blockSignals(False)
            val = nearest

        self._sel_tnum = val
        self._update_selection_marker()
        self._apply_trial(val)

    def _ensure_crosshair(self):
        try:
            self._vline = self.ax.axvline(0, color="#888", linewidth=0.8, alpha=0.7, visible=False)
            self._hline = self.ax.axhline(0, color="#888", linewidth=0.8, alpha=0.7, visible=False)
        except:
            self._vline = None
            self._hline = None

    def _ensure_selection_line(self):
        try:
            self._sel_vline = self.ax.axvline(0, color="#d62728", linewidth=1.8, alpha=0.9, visible=False)
        except:
            self._sel_vline = None

    def _update_selection_marker(self):
        if self._sel_vline is None:
            return
        if self._sel_tnum is None:
            self._sel_vline.set_visible(False)
        else:
            self._sel_vline.set_xdata([self._sel_tnum, self._sel_tnum])
            self._sel_vline.set_visible(True)
        self.canvas.draw_idle()

    def _mouse_move(self, event):
        if not event or event.inaxes != self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        if self._vline is None:
            return

        self._vline.set_xdata([event.xdata, event.xdata])
        self._vline.set_visible(True)

        if self._hline:
            self._hline.set_ydata([event.ydata, event.ydata])
            self._hline.set_visible(True)

        self.canvas.draw_idle()

    def _axes_leave(self, event):
        if self._vline:
            self._vline.set_visible(False)
        if self._hline:
            self._hline.set_visible(False)
        self.canvas.draw_idle()

    def _canvas_click(self, event):
        if not event or event.inaxes != self.ax or event.xdata is None:
            return

        x = float(event.xdata)
        cand = int(round(x))
        if cand not in self.trial_map:
            nums = self.trial_map.keys()
            cand = min(nums, key=lambda n: abs(n - cand))

        self.spnTrial.blockSignals(True)
        self.spnTrial.setValue(cand)
        self.spnTrial.blockSignals(False)

        self._sel_tnum = cand
        self._update_selection_marker()

        self._apply_trial(cand)

    def _apply_trial(self, tnum):
        t = self.trial_map.get(tnum)
        if not t:
            return

        params = None
        cad_params = t.user_attrs.get("cad_params")
        if isinstance(cad_params, dict) and cad_params:
            params = cad_params
        else:
            params = dict(t.params) if t.params else {}

        try:
            apply_cad_params(params)
            doc = App.ActiveDocument
            if doc:
                doc.recompute()
            # _restart_optics()
            # _refresh_3d_view()
            self.lblClickInfo.setText(f"Trial {tnum} → CAD uppdaterad ({len(params)} parametrar).")
            App.Console.PrintMessage(f"[Plot] Trial={tnum} params applied.\n")
        except Exception as e:
            App.Console.PrintError(f"[Plot] CAD error: {e}\n")

        try:
            self.trialSelected.emit(tnum, params)
        except:
            pass


# ============================================================================================
#  MULTI-WINDOWS
# ============================================================================================

_windows = []
_counter = 0


def _next_id():
    global _counter
    _counter += 1
    return _counter


def open_optuna_plot_window(db_uri=db_path, ma_window=1, show_global=False):
    storage = db_uri or db_path
    seq = _next_id()
    w = OptunaPlotWindow(storage_uri=storage, seq_id=seq)
    _windows.append(w)
    w.show()
    w.raise_()
    w.activateWindow()
    w.spnMA.setValue(int(ma_window))
    w.chkGlobal.setChecked(bool(show_global))
    return w


def close_optuna_plot_window():
    for w in list(_windows):
        try:
            w.close()
        except:
            pass
