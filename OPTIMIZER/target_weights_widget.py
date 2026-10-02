# target_weights_widget.py

from PySide import QtCore, QtWidgets, QtGui
import FreeCAD as App

from .spreadsheet_utils import read_param_bounds, get_param_info
from .optimize_config import SPREADSHEET_NAME

from oba_objects.oba_base import get_optical_icon_path

# ==========================================================
# METRICS CONFIG
# ==========================================================

METRICS = {
    "power": {
        "label": "⚡ power",
        "threshold": True,
        "widget": ["targets", "percent"],
        "direction": "maximize",
        "tooltip": ("Power score = infångad effekt / emitterad effekt.\n" "1.0 betyder att all emitterad effekt når målet.\n" "\n" "Threshold:\n" "Percent anger minsta tillåtna power score.\n" "Används endast när Threshold är aktiv."),
    },
    "hit_count": {
        "label": "🎯 hit_count",
        "threshold": True,
        "widget": ["targets", "percent"],
        "direction": "maximize",
        "tooltip": ("Hit score baseras på hur stor andel av emitterade " "rays som träffar målet.\n" "\n" "Threshold:\n" "Percent anger minsta tillåtna andel träffande rays.\n" "Används endast när Threshold är aktiv."),
    },
    "target_cluster_count": {
        "label": "⚡ target_cluster_count",
        "threshold": True,
        "widget": ["targets", "percent", "value"],
        "direction": "maximize",
        "tooltip": ("Försöker uppnå ett visst antal betydande kluster.\n" "Filter (%) anger hur stor andel av emitterade rays ett kluster " "måste ha för att räknas.\n" "Målvärde (≈) är önskat antal kluster."),
    },
    "density": {
        "label": "density",
        "threshold": False,
        "widget": ["targets", "plane", "bounce"],
        "direction": "maximize",
        "tooltip": (
            "Mäter hur koncentrerade träffarna är inom klustren.\n"
            "\n"
            "Hög density = träffarna ligger tätt samlade.\n"
            "Låg density = träffarna är mer utspridda.\n"
            "\n"
            "Resultatet beräknas som ett hit-viktat medelvärde.\n"
            "\n"
            "Bounce-filter:\n"
            "0 = använd alla bounce, summan som gör att stora cluster kommer dominera \n"
            "1 = endast bounce 1\n"
            "2 = endast bounce 2\n"
            "...\n"
        ),
        # "tooltip": "Medeldensitet för kluster (viktad med antal träffar).\nHög densitet = kompakt träffbild.",
    },
    "roundness": {
        "label": "roundness",
        "threshold": False,
        "widget": ["targets", "plane", "bounce"],
        "direction": "maximize",
        "tooltip": "Mäter hur cirkulära kluster är.\n1 = perfekt rund, 0 = utdragen.",
    },
    "equal_distance": {
        "label": "equal_distance",
        "threshold": False,
        "widget": ["targets", "plane"],
        "direction": "maximize",
        "tooltip": "Belönar små klusterradier.\nGer jämnt fördelade och kompakta träffzoner.",
    },
    "cluster_distribution": {
        "label": "📏 cluster_distribution",
        "widget": ["targets", "plane", "axis"],
        "threshold": False,
        "direction": "maximize",
        "tooltip": ("Mäter hur jämnt klustercentra är fördelade längs vald axel.\n" "Hög score ges när klustren sprids ut på ett balanserat sätt."),
    },
    "cluster_position_matching": {
        "label": "📐 cluster_position_matching",
        "widget": ["targets", "origin_axis"],
        "threshold": False,
        "direction": "maximize",
        "tooltip": (
            "Belönar kluster vars centrum har liknande position "
            "i vald koordinatdimension.\n"
            "\n"
            "X   → jämför X-koordinat\n"
            "Y   → jämför Y-koordinat\n"
            "Z   → jämför Z-koordinat\n"
            "XY  → jämför avstånd från origo i XY-plan\n"
            "XZ  → jämför avstånd från origo i XZ-plan\n"
            "YZ  → jämför avstånd från origo i YZ-plan\n"
            "XYZ → jämför avstånd från origo i 3D\n"
            "\n"
            "Hög score ges när klustren ligger på ungefär samma "
            "position, oavsett var denna position är."
        ),
    },
    "cluster_origin_centering": {
        "label": "🎯 cluster_origin_centering",
        "widget": ["targets", "plane", "origin_axis", "bounce"],
        "threshold": False,
        "direction": "maximize",
        "tooltip": (
            "Belönar kluster vars centrum ligger nära origo.\n"
            "\n"
            "X → avstånd till X = 0\n"
            "Y → avstånd till Y = 0\n"
            "Z → avstånd till Z = 0\n"
            "XY → √(X² + Y²)\n"
            "XZ → √(X² + Z²)\n"
            "YZ → √(Y² + Z²)\n"
            "XYZ → √(X² + Y² + Z²)\n"
            "\n"
            "Bounce-filter:\n"
            "0 = alla bounce\n"
            "1 = endast bounce 1\n"
            "2 = endast bounce 2\n"
            "...\n"
            "\n"
            "Hög score ges när klustercentra ligger nära origo "
            "för valda koordinataxlar."
        ),
        # "tooltip": ("Belönar kluster som ligger nära origo " "för valda koordinataxlar.\n" "X  → X=0\n" "XY → sqrt(X²+Y²)\n" "XYZ → sqrt(X²+Y²+Z²)\n"),
    },
    "target_face_centering": {
        "label": "🎯 target_face_centering",
        "widget": ["targets", "bounce"],
        "threshold": False,
        "direction": "maximize",
        "tooltip": (
            "Belönar kluster vars centroid ligger nära "
            "centrum av den träffade ytan.\n"
            "\n"
            "Avstånd mäts mellan:\n"
            "cluster centroid ↔ target center\n"
            "\n"
            "Target center beräknas som medianen av alla "
            "surface centers i klustret.\n"
            "\n"
            "Bounce:\n"
            "0 = alla bounce\n"
            "1 = endast bounce 1\n"
            "2 = endast bounce 2\n"
            "...\n"
            "\n"
            "Hög score = träffbilden ligger nära "
            "mitten av målytan."
        ),
    },
    "scanner": {
        "label": "🧪 Scanner",
        "threshold": False,
        "widget": ["targets", "step", "radius"],
        "direction": "maximize",
        "tooltip": (
            "Scanner körs över ett område kring nominellt läge.\n"
            "Score = genomsnittlig infångad effekt i förhållande till "
            "emitterad effekt inom vald toleransradie.\n"
            "Belönar robusta lösningar som bibehåller effekt trots "
            "positioneringsfel. Ger ofta även högre koncentration "
            "och densitet som en bieffekt."
        ),
    },
    "preserve_parameter": {
        "label": "🔒 Preserve parameter",
        "threshold": False,
        "widget": ["params", "preserve_percent"],
        "direction": "maximize",
        "tooltip": "Belönar lösningar där parametern " "ligger nära sitt startvärde.",
    },
}


LABEL_TO_KEY = {cfg.get("label", k): k for k, cfg in METRICS.items()}


# ==========================================================
# ROW
# ==========================================================


class MetricRowWidget(QtWidgets.QWidget):

    changed = QtCore.Signal()
    removed = QtCore.Signal(object)

    debugRequested = QtCore.Signal(dict)

    def __init__(self, metrics, metric="density", parent=None):
        super().__init__(parent)

        # self.targets = self._get_default_target()

        self.dynamic_widgets = []

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        self.cmb = QtWidgets.QComboBox()
        self.cmb.addItems(metrics)
        self.cmb.setCurrentText(metric)

        # self.btnTargets = QtWidgets.QPushButton()

        self.chkActive = QtWidgets.QCheckBox()
        self.chkActive.setChecked(True)

        # self.lbl = QtWidgets.QLabel()
        # self.lbl.setText("ℹ️")

        self.btnInfo = QtWidgets.QToolButton()
        self.btnInfo.setText("ℹ️")

        # delete button
        self.btnDelete = QtWidgets.QPushButton("✕")
        self.btnDelete.setCursor(QtCore.Qt.PointingHandCursor)
        self.btnDelete.setStyleSheet("""
            QPushButton {
                border: none;
                padding: 2px;
                color: #c0392b;
                font-weight: bold;
                min-width: 0px;
                min-height: 0px;
            }
            QPushButton:hover {
                background-color: #f8d7da;
                border-radius: 3px;
            }
        """)
        self.btnDelete.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.btnDelete.adjustSize()

        # layout
        layout.addWidget(self.chkActive)
        layout.addWidget(self.cmb)
        # layout.addWidget(self.btnTargets)

        # anchor for dynamic widgets
        self.dynamic_anchor_index = layout.count()

        layout.addWidget(self.btnInfo)
        layout.addStretch()
        layout.addWidget(self.btnDelete)

        # self._update_targets_button()
        self._rebuild_dynamic_ui()

        # signals
        self.cmb.currentIndexChanged.connect(self._rebuild_dynamic_ui)
        # self.btnTargets.clicked.connect(self._edit_targets)
        self.btnDelete.clicked.connect(lambda: self.removed.emit(self))
        self.chkActive.toggled.connect(self._update_row_style)

        # self.btnInfo.clicked.connect(lambda: self.parent().parent().run_single_metric(self.get_payload_part()))
        self.btnInfo.clicked.connect(self._debug_metric)

        # self._label_to_key = {cfg.get("label", k): k for k, cfg in METRICS.items()}

    # --------------------------------------------------
    # DYNAMIC UI
    # --------------------------------------------------

    def _update_row_style(self):
        self.setStyleSheet("")
        # ❌ inaktiv → gråa ut
        if not self.chkActive.isChecked():
            self.setStyleSheet("color: #999; background-color: #f5f5f5;")
            return
        if hasattr(self, "thresholdWidget") and self.thresholdWidget.isChecked():
            self.setStyleSheet("background-color: #fff4e6;")

    def _rebuild_dynamic_ui(self):
        layout = self.layout()

        # ✅ reset dynamic data (KRITISK)
        for attr in [
            "targetWidget",
            "percentWidget",
            "valueWidget",
            "rangeWidget",
            "planeWidget",
            "axisWidget",
            "thresholdWidget",
            "stepWidget",
            "bounceWidget",
            "radiusWidget",
            "paramWidget",
            "preservePercentWidget",
        ]:
            if hasattr(self, attr):
                delattr(self, attr)

        for w in self.dynamic_widgets:
            layout.removeWidget(w)
            w.deleteLater()
        self.dynamic_widgets = []

        label = self.cmb.currentText()
        metric_key = LABEL_TO_KEY.get(label, label)
        cfg = METRICS.get(metric_key, {})

        # metric = self.cmb.currentText()
        # cfg = METRICS.get(metric, {})

        tooltip = cfg.get("tooltip", "")
        self.setToolTip(tooltip)
        self.cmb.setToolTip(tooltip)
        # self.lbl.setToolTip(tooltip)
        self.btnInfo.setToolTip(tooltip)

        widgets = cfg.get("widget", [])
        insert_index = self.dynamic_anchor_index

        if "targets" in widgets:
            w = TargetSelectorWidget()
            w.changed.connect(self.changed.emit)
            layout.insertWidget(insert_index, w)
            self.dynamic_widgets.append(w)
            self.targetWidget = w
            insert_index += 1

        if "plane" in widgets:
            w = PlaneWidget()
            layout.insertWidget(insert_index, w)
            self.dynamic_widgets.append(w)
            self.planeWidget = w
            insert_index += 1

        if "value" in widgets:
            w = ValueWidget()
            layout.insertWidget(insert_index, w)
            self.dynamic_widgets.append(w)
            self.valueWidget = w
            insert_index += 1

        if "percent" in widgets:
            w = PercentWidget()
            layout.insertWidget(insert_index, w)
            self.dynamic_widgets.append(w)
            self.percentWidget = w
            insert_index += 1

        if "range" in widgets:
            w = RangeWidget()
            layout.insertWidget(insert_index, w)
            self.dynamic_widgets.append(w)
            self.rangeWidget = w
            insert_index += 1

        if "axis" in widgets:
            w = AxisWidget()
            layout.insertWidget(insert_index, w)
            self.dynamic_widgets.append(w)
            self.axisWidget = w
            insert_index += 1

        if "origin_axis" in widgets:
            w = OriginAxisWidget()
            layout.insertWidget(insert_index, w)
            self.dynamic_widgets.append(w)
            self.axisWidget = w
            insert_index += 1

        if "bounce" in widgets:
            w = BounceWidget()
            layout.insertWidget(insert_index, w)
            self.dynamic_widgets.append(w)
            self.bounceWidget = w
            insert_index += 1

        if "radius" in widgets:
            w = RadiusWidget()
            layout.insertWidget(insert_index, w)
            self.dynamic_widgets.append(w)
            self.radiusWidget = w
            insert_index += 1

        if "step" in widgets:
            w = StepSelectWidget()
            layout.insertWidget(insert_index, w)
            self.dynamic_widgets.append(w)
            self.stepWidget = w
            insert_index += 1

        if "params" in widgets:
            w = ParameterSelectorWidget()
            layout.insertWidget(insert_index, w)
            self.dynamic_widgets.append(w)
            self.paramWidget = w
            insert_index += 1

        if "preserve_percent" in widgets:
            w = PreservePercentWidget()
            layout.insertWidget(insert_index, w)
            self.dynamic_widgets.append(w)
            self.preservePercentWidget = w

            insert_index += 1

        if cfg.get("threshold", False):
            w = ThresholdWidget()
            w.toggled.connect(self._update_row_style)
            layout.insertWidget(insert_index, w)
            self.dynamic_widgets.append(w)
            self.thresholdWidget = w
            insert_index += 1

        self._update_row_style()

    # --------------------------------------------------
    # PAYLOAD
    # --------------------------------------------------

    def _debug_metric(self):
        payload = self.get_payload_part()
        print(payload)
        self.debugRequested.emit(payload)

        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "run_single_metric"):
                parent.run_single_metric(payload)
                return
            parent = parent.parent()

    def get_payload_part(self):
        # metric = self.cmb.currentText()
        # # ✅ översätt tillbaka
        # metric_key = self.parent()._metric_display_map.get(metric, metric)

        label = self.cmb.currentText()
        metric_key = LABEL_TO_KEY.get(label, label)

        cfg = METRICS.get(metric_key, {})
        direction = cfg.get("direction", "maximize")

        data = {
            "base_metric": metric_key,  # metric
            "type": cfg.get("type"),
            "active": self.chkActive.isChecked(),
            # "targets": self.get_targets(),
            "direction": direction,
        }

        # ✅ ONLY include valid fields
        widgets = cfg.get("widget", [])

        if "targets" in widgets and hasattr(self, "targetWidget"):
            data["targets"] = self.targetWidget.get_targets()
        else:
            data["targets"] = []

        if "plane" in widgets and hasattr(self, "planeWidget"):
            data["plane"] = self.planeWidget.currentText()

        if "value" in widgets and hasattr(self, "valueWidget"):
            data["value"] = self.valueWidget.get_value()

        if "percent" in widgets and hasattr(self, "percentWidget"):
            data["percent"] = self.percentWidget.get_value()

        if "range" in widgets and hasattr(self, "rangeWidget"):
            min_v, max_v = self.rangeWidget.get_values()
            if min_v > max_v:
                min_v, max_v = max_v, min_v
            data["min"] = min_v
            data["max"] = max_v

        if (("axis" in widgets) or ("origin_axis" in widgets)) and hasattr(self, "axisWidget"):
            data["axis"] = self.axisWidget.currentText()

        if "bounce" in widgets and hasattr(self, "bounceWidget"):
            data["bounce"] = self.bounceWidget.get_value()
            # print("[PAYLOAD]", metric_key, "bounce=", data["bounce"])

        if "radius" in widgets and hasattr(self, "radiusWidget"):
            data["radius"] = self.radiusWidget.get_value()

        if "step" in widgets and hasattr(self, "stepWidget"):
            data["step_id"] = self.stepWidget.get_value()

        if "params" in widgets:
            data["parameters"] = self.paramWidget.get_parameters()

        # {
        #     "base_metric": "preserve_parameter",
        #     "parameters": [
        #         {
        #             "name": "MirrorAngle",
        #             "value": 37.0,
        #             "unit": "deg",
        #         },
        #         {
        #             "name": "LED_X",
        #             "value": 12.5,
        #             "unit": "mm",
        #         },
        #     ],
        #     "tolerance": 0.10,
        # }

        if "preserve_percent" in widgets:
            data["tolerance"] = self.preservePercentWidget.get_value()

        # print("[ROW PAYLOAD]", data)

        if hasattr(self, "thresholdWidget"):
            data["use_threshold"] = self.thresholdWidget.get_value()
        else:
            data["use_threshold"] = False

        return data

    # --------------------------------------------------
    # TARGETS
    # --------------------------------------------------

    # def _get_default_target(self):
    #     doc = App.ActiveDocument
    #     if not doc:
    #         return []

    #     mirrors = [o.Label for o in doc.Objects if getattr(o, "OpticalType", None) == "Mirror"]
    #     if mirrors:
    #         return [mirrors[0]]

    #     optical = [o.Label for o in doc.Objects if hasattr(o, "OpticalType")]
    #     return optical[:1]

    # def _update_targets_button(self):
    #     txt = "—" if not self.targets else "; ".join(self.targets)
    #     if len(txt) > 25:
    #         txt = txt[:25] + "..."
    #     self.btnTargets.setText(txt)
    #     self.btnTargets.setToolTip("; ".join(self.targets))

    # def _edit_targets(self):
    #     doc = App.ActiveDocument
    #     if not doc:
    #         return

    #     available = [o.Label for o in doc.Objects if hasattr(o, "OpticalType")]

    #     label = self.cmb.currentText()
    #     metric_key = LABEL_TO_KEY.get(label, label)

    #     dlg = EditTargetsDialog(self, metric_key, available, self.targets)

    #     if dlg.exec_():
    #         selected = dlg.selected_targets() or self._get_default_target()
    #         self.targets = selected
    #         self._update_targets_button()
    #         self.changed.emit()

    # def get_targets(self):
    #     return self.targets or self._get_default_target()


# ==========================================================
# MAIN
# ==========================================================


class TargetWeightsWidget(QtWidgets.QGroupBox):

    configChanged = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__("Målvikter", parent)

        self.rows = []

        layout = QtWidgets.QVBoxLayout(self)
        self.container = QtWidgets.QVBoxLayout()
        layout.addLayout(self.container)

        self.lblSummary = QtWidgets.QLabel()
        layout.addWidget(self.lblSummary)

        self.btnAdd = QtWidgets.QPushButton("+ Add metric")
        layout.addWidget(self.btnAdd)
        self.btnAdd.clicked.connect(lambda: self.add_row())

        self._label_to_key = {cfg.get("label", k): k for k, cfg in METRICS.items()}

        for m in self.available_metrics():
            self.add_row(m)

    def available_metrics(self):
        keys = sorted(METRICS.keys(), key=self.metric_sort_key)
        return [METRICS[k].get("label", k) for k in keys]

    # def available_metrics_old(self):
    #     return sorted(METRICS.keys(), key=self.metric_sort_key)

    def add_row(self, metric="density"):
        row = MetricRowWidget(self.available_metrics(), metric, self)
        row.changed.connect(self._update)
        row.removed.connect(self.remove_row)

        parent = self.parent()
        if parent and hasattr(parent, "run_single_metric"):
            row.debugRequested.connect(parent.run_single_metric)

        self.rows.append(row)
        self.container.addWidget(row)

        self._update()
        return row

    def remove_row(self, row):
        # if row not in self.rows:
        #     return  # ✅ skydd mot dubbel-removal
        self.rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self._update()

    def _update(self):
        payload = self.get_payload()
        entries = []
        for e in payload["entries"]:
            plane = e.get("plane")
            if plane:
                entries.append(f"{e['base_metric']}[{plane}]")
            else:
                entries.append(e["base_metric"])
        self.lblSummary.setText(" | ".join(entries))
        self.configChanged.emit(payload)

    def metric_sort_key(self, metric):

        if isinstance(metric, dict):
            name = metric.get("base_metric")
        else:
            # ✅ FIX: konvertera label → key
            name = self._label_to_key.get(metric, metric)

        cfg = METRICS.get(name, {})

        is_threshold = cfg.get("threshold", False)
        is_scanner = name == "scanner"

        return (
            0 if is_threshold else 1,
            2 if is_scanner else 1,
            name,
        )

    def get_payload(self):
        entries = []
        for r in self.rows:
            entries.append(r.get_payload_part())
        entries.sort(key=self.metric_sort_key)
        return {"entries": entries}


# ==========================================================
# DYNAMIC WIDGETS
# ==========================================================


class TargetSelectorWidget(QtWidgets.QPushButton):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.targets = self._get_default_target()
        self.clicked.connect(self._edit_targets)
        self._update_text()

    def _get_default_target(self):
        doc = App.ActiveDocument
        if not doc:
            return []
        mirrors = [o.Label for o in doc.Objects if getattr(o, "OpticalType", None) == "Mirror"]
        if mirrors:
            return [mirrors[0]]
        optical = [o.Label for o in doc.Objects if hasattr(o, "OpticalType")]
        return optical[:1]

    def _update_text(self):
        txt = "—" if not self.targets else "; ".join(self.targets)
        if len(txt) > 25:
            txt = txt[:25] + "..."

        self.setText(txt)
        self.setToolTip("; ".join(self.targets))

    def _edit_targets(self):
        doc = App.ActiveDocument
        if not doc:
            return
        # available = [o.Label for o in doc.Objects if hasattr(o, "OpticalType")]
        available = [o for o in doc.Objects if hasattr(o, "OpticalType")]

        dlg = EditTargetsDialog(
            self,
            "targets",
            available,
            self.targets,
        )
        if dlg.exec_():
            self.targets = dlg.selected_targets() or self._get_default_target()
            self._update_text()
            self.changed.emit()

    def get_targets(self):
        return self.targets

    def set_targets(self, targets):
        self.targets = list(targets or [])
        self._update_text()


class PlaneWidget(QtWidgets.QComboBox):
    def __init__(self):
        super().__init__()
        self.addItems(["XY", "XZ", "YZ", "3D"])


class ValueWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.spin = QtWidgets.QSpinBox()
        self.spin.setRange(0, 999)
        self.spin.setValue(5)

        layout.addWidget(QtWidgets.QLabel("≈"))
        layout.addWidget(self.spin)

    def get_value(self):
        return self.spin.value()


class PercentWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.spin_percent = QtWidgets.QSpinBox()
        self.spin_percent.setRange(0, 100)
        self.spin_percent.setValue(70)
        self.spin_percent.setToolTip("Minsta clusterstorlek (% av emitterade rays).\n" "Mindre kluster ignoreras vid beräkning.")

        layout.addWidget(QtWidgets.QLabel("Filter ≥"))
        layout.addWidget(self.spin_percent)
        layout.addWidget(QtWidgets.QLabel("%"))

    def get_value(self):
        return self.spin_percent.value() / 100.0  # ✅ normalisera


class RangeWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.min = QtWidgets.QSpinBox()
        self.max = QtWidgets.QSpinBox()

        layout.addWidget(self.min)
        layout.addWidget(QtWidgets.QLabel("–"))
        layout.addWidget(self.max)

    def get_values(self):
        return self.min.value(), self.max.value()


class BounceWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.spin = QtWidgets.QSpinBox()
        self.spin.setRange(0, 999)
        self.spin.setValue(1)
        # self.spin.setToolTip("Endast kluster från detta bounce-index används.\n" "0 = första träffen\n" "1 = andra träffen\n" "2 = tredje träffen\n" "osv.")
        layout.addWidget(QtWidgets.QLabel("Bounce"))
        layout.addWidget(self.spin)

    def get_value(self):
        return self.spin.value()


class RadiusWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.spin = QtWidgets.QDoubleSpinBox()
        self.spin.setDecimals(3)
        self.spin.setRange(0.001, 1000.0)
        self.spin.setValue(0.2)
        self.spin.setSuffix(" mm")

        layout.addWidget(QtWidgets.QLabel("R"))
        layout.addWidget(self.spin)

    def get_value(self):
        return self.spin.value()


class AxisWidget(QtWidgets.QComboBox):
    def __init__(self):
        super().__init__()
        self.addItems(["X", "Y", "Z"])


class OriginAxisWidget(QtWidgets.QComboBox):
    def __init__(self):
        super().__init__()

        self.addItems(
            [
                "X",
                "Y",
                "Z",
                "XY",
                "XZ",
                "YZ",
                "XYZ",
            ]
        )


class ThresholdWidget(QtWidgets.QCheckBox):
    def __init__(self):
        super().__init__("Threshold")
        self.setChecked(False)
        self.setToolTip("Aktivera threshold (pruning).\n" "Om värdet inte uppfyller kravet avbryts evaluation tidigt.")
        self.setStyleSheet("""
            QCheckBox {
                spacing: 4px;
            }
            QCheckBox:checked {
                color: orange;
                font-weight: bold;
            }
            """)

    def get_value(self):
        return self.isChecked()


class StepSelectWidget(QtWidgets.QComboBox):
    def __init__(self):
        super().__init__()
        self.refresh()

    def refresh(self):
        self.clear()

        doc = App.ActiveDocument
        if not doc:
            return

        # hitta BatchGroup
        batch = None
        for obj in doc.Objects:
            if obj.TypeId == "App::DocumentObjectGroupPython" and hasattr(obj, "GroupId"):
                batch = obj
                break

        if not batch:
            return

        for step in batch.Group:
            if hasattr(step, "Id"):
                # visa Titel + ID
                label = f"{step.Title} ({step.Id})"
                self.addItem(label, step.Id)

    def get_value(self):
        return self.currentData()


class ParameterSelectorWidget(QtWidgets.QPushButton):

    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parameters = self._get_default_parameters()
        self.clicked.connect(self._edit_parameters)
        self._update_text()

    def _get_available_parameters(self):

        doc = App.ActiveDocument
        if not doc:
            return []
        ss = doc.getObject(SPREADSHEET_NAME)
        if not ss:
            return []
        info = read_param_bounds(ss)
        params = []

        for item in info:
            if item["type"] != "param":
                continue
            params.append({"name": item["name"], "value": item["value"], "unit": item["unit"] or ""})

        return params

    def _get_default_parameters(self):
        available = self._get_available_parameters()
        if not available:
            return []
        return [available[0]]

    def _update_text(self):
        if not self.parameters:
            txt = "—"
        elif len(self.parameters) == 1:
            p = self.parameters[0]
            txt = f"{p['name']} " f"({p['value']:g} {p['unit']})"
        elif len(self.parameters) <= 2:
            txt = "; ".join(f"{p['name']} ({p['value']:g})" for p in self.parameters)
        else:
            txt = f"{len(self.parameters)} params"

        self.setText(txt)
        self.setToolTip("\n".join(f"{p['name']} = {p['value']:g} {p['unit']}" for p in self.parameters))

    def _edit_parameters(self):
        available = self._get_available_parameters()
        dlg = EditParametersDialog(self, available, [p["name"] for p in self.parameters])
        # dlg = EditParametersDialog(self, [p["name"] for p in available], [p["name"] for p in self.parameters])

        if dlg.exec_():
            selected = set(dlg.selected_parameters())
            self.parameters = [p for p in available if p["name"] in selected]
            self._update_text()
            self.changed.emit()

    def get_parameters(self):
        return list(self.parameters)

    def set_parameters(self, parameters):
        self.parameters = list(parameters or [])
        self._update_text()


class PreservePercentWidget(QtWidgets.QWidget):

    def __init__(self):
        super().__init__()

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.spin = QtWidgets.QSpinBox()
        self.spin.setRange(0, 100)
        self.spin.setValue(10)

        layout.addWidget(QtWidgets.QLabel("±"))
        layout.addWidget(self.spin)
        layout.addWidget(QtWidgets.QLabel("%"))

    def get_value(self):
        return self.spin.value() / 100.0


# ==========================================================
# DIALOGS
# ==========================================================


class EditParametersDialog(QtWidgets.QDialog):

    # def __init__(self, parent, available_parameters, selected_parameters):
    def __init__(self, parent, available_parameters, selected_parameters):
        super().__init__(parent)

        self.setWindowTitle("Select parameters")
        self.setModal(True)

        self._checkboxes = {}

        layout = QtWidgets.QVBoxLayout(self)
        # for name in available_parameters:
        #     cb = QtWidgets.QCheckBox(name)
        #     cb.setChecked(name in selected_parameters)
        #     layout.addWidget(cb)
        #     self._checkboxes[name] = cb

        for p in available_parameters:
            name = p["name"]
            value = p["value"]
            unit = p["unit"]
            # txt = f"{name} ({value:g} {unit})"
            txt = f"{name}   [{value:g} {unit}]"
            # txt = f"{name:<20}  {value:g} {unit}"
            cb = QtWidgets.QCheckBox(txt)
            cb.setFont(QtGui.QFont("Courier New"))  # Eller "Consolas", "Monospace" etc.

            cb.setChecked(name in selected_parameters)
            layout.addWidget(cb)
            self._checkboxes[name] = cb

        row = QtWidgets.QHBoxLayout()
        btnApply = QtWidgets.QPushButton("Apply")
        btnCancel = QtWidgets.QPushButton("Cancel")

        row.addStretch()
        row.addWidget(btnApply)
        row.addWidget(btnCancel)

        layout.addLayout(row)

        btnApply.clicked.connect(self.accept)
        btnCancel.clicked.connect(self.reject)

    def selected_parameters(self):
        return [name for name, cb in self._checkboxes.items() if cb.isChecked()]


class EditTargetsDialog(QtWidgets.QDialog):

    def __init__(self, parent, metric_key, available_targets, selected_targets):
        super().__init__(parent)

        self.setWindowTitle(f"Select targets for {metric_key}")
        self.setModal(True)

        self._checkboxes = {}
        layout = QtWidgets.QVBoxLayout(self)

        # for tgt in available_targets:
        #     cb = QtWidgets.QCheckBox(tgt)
        #     cb.setChecked(tgt in selected_targets)
        #     layout.addWidget(cb)
        #     self._checkboxes[tgt] = cb

        for obj in available_targets:
            label = obj.Label
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)

            icon_label = QtWidgets.QLabel()
            icon_path = get_optical_icon_path(obj)
            if icon_path:
                icon_label.setPixmap(QtGui.QIcon(icon_path).pixmap(16, 16))

            cb = QtWidgets.QCheckBox(label)
            cb.setChecked(label in selected_targets)

            row_layout.addWidget(icon_label)
            row_layout.addWidget(cb)
            row_layout.addStretch()

            layout.addWidget(row)
            self._checkboxes[label] = cb

        row = QtWidgets.QHBoxLayout()
        btnApply = QtWidgets.QPushButton("Apply")
        btnCancel = QtWidgets.QPushButton("Cancel")

        row.addStretch()
        row.addWidget(btnApply)
        row.addWidget(btnCancel)
        layout.addLayout(row)

        btnApply.clicked.connect(self.accept)
        btnCancel.clicked.connect(self.reject)

    def selected_targets(self):
        return [t for t, cb in self._checkboxes.items() if cb.isChecked()]
