from PySide import QtCore, QtWidgets
import FreeCAD as App

# ==========================================================
# METRICS CONFIG
# ==========================================================

METRICS = {
    "power": {
        "label": "⚡ power",
        "threshold": True,
        "widget": ["percent"],
        "tooltip": ("Maximerar inkommande effekt.\n" "Med threshold: kräver förbättring relativt baseline.\n" "Percent = min förbättringsgrad."),
    },
    "preserve_cluster_count": {
        "label": "⚡ preserve_cluster_count",
        "threshold": True,
        "widget": ["percent"],
        "tooltip": "Bibehåller antal kluster jämfört med baseline.\nStraffar för stora avvikelser.",
    },
    "target_cluster_count": {
        "label": "⚡ target_cluster_count",
        "threshold": True,
        "widget": ["percent", "value"],
        "tooltip": "Försöker nå ett specifikt antal kluster.\nPercent avgör vilka kluster som räknas.",
    },
    "density": {
        "label": "density",
        "threshold": False,
        "tooltip": "Medeldensitet för kluster (viktad med antal träffar).\nHög densitet = kompakt träffbild.",
    },
    "roundness": {
        "label": "roundness",
        "threshold": False,
        "tooltip": "Mäter hur cirkulära kluster är.\n1 = perfekt rund, 0 = utdragen.",
    },
    "equal_distance": {
        "label": "equal_distance",
        "threshold": False,
        "tooltip": "Belönar små klusterradier.\nGer jämnt fördelade och kompakta träffzoner.",
    },
    "equal_ray_hits_count": {
        "label": "equal_ray_hits_count",
        "threshold": False,
        "tooltip": ("Fördelar rays jämnt mellan kluster.\n" "Maximerar både total träffmängd och jämn fördelning."),
    },
    "scanner": {
        "label": "🧪 Scanner",
        "threshold": False,
        "widget": ["step", "percent"],
        "tooltip": "Kör valfri scanner-step och returnerar score.",
    },
}


LABEL_TO_KEY = {cfg.get("label", k): k for k, cfg in METRICS.items()}


# ==========================================================
# ROW
# ==========================================================


class MetricRowWidget(QtWidgets.QWidget):

    changed = QtCore.Signal()
    removed = QtCore.Signal(object)

    def __init__(self, metrics, metric="density", parent=None):
        super().__init__(parent)

        self.targets = self._get_default_target()
        self.dynamic_widgets = []

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        self.cmb = QtWidgets.QComboBox()
        self.cmb.addItems(metrics)
        self.cmb.setCurrentText(metric)

        self.btnTargets = QtWidgets.QPushButton()

        self.cmbPlane = QtWidgets.QComboBox()
        self.cmbPlane.addItems(["XY", "XZ", "YZ", "3D"])

        self.chkActive = QtWidgets.QCheckBox()
        self.chkActive.setChecked(True)

        self.lbl = QtWidgets.QLabel()
        self.lbl.setText("ℹ️")

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
        layout.addWidget(self.btnTargets)
        layout.addWidget(self.cmbPlane)

        # anchor for dynamic widgets
        self.dynamic_anchor_index = layout.count()

        layout.addWidget(self.lbl, 1)
        layout.addWidget(self.btnDelete, 0)

        self._update_targets_button()
        self._rebuild_dynamic_ui()

        # signals
        self.cmb.currentIndexChanged.connect(self._rebuild_dynamic_ui)
        self.cmbPlane.currentIndexChanged.connect(self.changed)
        self.btnTargets.clicked.connect(self._edit_targets)
        self.btnDelete.clicked.connect(lambda: self.removed.emit(self))
        self.chkActive.toggled.connect(self._update_row_style)

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
        for attr in ["percentWidget", "valueWidget", "rangeWidget", "axisWidget", "thresholdWidget"]:
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
        self.lbl.setToolTip(tooltip)

        # is_scanner = metric == "scanner"
        # self.cmbPlane.setVisible(not is_scanner)
        # self.btnTargets.setVisible(not is_scanner)

        widgets = cfg.get("widget", [])

        insert_index = self.dynamic_anchor_index

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

        if "step" in widgets:
            w = StepSelectWidget()
            layout.insertWidget(insert_index, w)
            self.dynamic_widgets.append(w)
            self.stepWidget = w
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

    def get_payload_part(self):
        # metric = self.cmb.currentText()
        # # ✅ översätt tillbaka
        # metric_key = self.parent()._metric_display_map.get(metric, metric)

        label = self.cmb.currentText()
        metric_key = LABEL_TO_KEY.get(label, label)

        cfg = METRICS.get(metric_key, {})

        data = {
            "base_metric": metric_key,  # metric
            "type": cfg.get("type"),
            "active": self.chkActive.isChecked(),
            "targets": self.get_targets(),
            "plane": self.cmbPlane.currentText(),
        }

        # ✅ ONLY include valid fields
        widgets = cfg.get("widget", [])

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

        if "axis" in widgets and hasattr(self, "axisWidget"):
            data["axis"] = self.axisWidget.currentText()

        if "step" in widgets and hasattr(self, "stepWidget"):
            data["step_id"] = self.stepWidget.get_value()

        if hasattr(self, "thresholdWidget"):
            data["use_threshold"] = self.thresholdWidget.get_value()
        else:
            data["use_threshold"] = False

        return data

    # --------------------------------------------------
    # TARGETS
    # --------------------------------------------------

    def _get_default_target(self):
        doc = App.ActiveDocument
        if not doc:
            return []

        mirrors = [o.Label for o in doc.Objects if getattr(o, "OpticalType", None) == "Mirror"]
        if mirrors:
            return [mirrors[0]]

        optical = [o.Label for o in doc.Objects if hasattr(o, "OpticalType")]
        return optical[:1]

    def _update_targets_button(self):
        txt = "—" if not self.targets else "; ".join(self.targets)
        if len(txt) > 25:
            txt = txt[:25] + "..."
        self.btnTargets.setText(txt)
        self.btnTargets.setToolTip("; ".join(self.targets))

    def _edit_targets(self):
        doc = App.ActiveDocument
        if not doc:
            return

        available = [o.Label for o in doc.Objects if hasattr(o, "OpticalType")]

        label = self.cmb.currentText()
        metric_key = LABEL_TO_KEY.get(label, label)

        dlg = EditTargetsDialog(self, metric_key, available, self.targets)

        if dlg.exec_():
            selected = dlg.selected_targets() or self._get_default_target()
            self.targets = selected
            self._update_targets_button()
            self.changed.emit()

    def get_targets(self):
        return self.targets or self._get_default_target()


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

    def available_metrics_old(self):
        return sorted(METRICS.keys(), key=self.metric_sort_key)

    def add_row(self, metric="density"):
        row = MetricRowWidget(self.available_metrics(), metric)
        row.changed.connect(self._update)
        row.removed.connect(self.remove_row)

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
        txt = [f"{e['base_metric']}[{e['plane']}]" for e in payload["entries"]]
        self.lblSummary.setText(" | ".join(txt))
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
            if r.chkActive.isChecked():
                entries.append(r.get_payload_part())

        entries.sort(key=self.metric_sort_key)

        return {"entries": entries}


# ==========================================================
# DYNAMIC WIDGETS
# ==========================================================


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
        self.spin_percent.setToolTip("Minsta clusterstorlek (% av största cluster i baseline).\n" "Mindre cluster ignoreras vid beräkning.")

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


class AxisWidget(QtWidgets.QComboBox):
    def __init__(self):
        super().__init__()
        self.addItems(["X", "Y", "Z"])


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


# ==========================================================
# DIALOG
# ==========================================================


class EditTargetsDialog(QtWidgets.QDialog):

    def __init__(self, parent, metric_key, available_targets, selected_targets):
        super().__init__(parent)

        self.setWindowTitle(f"Select targets for {metric_key}")
        self.setModal(True)

        self._checkboxes = {}
        layout = QtWidgets.QVBoxLayout(self)

        for tgt in available_targets:
            cb = QtWidgets.QCheckBox(tgt)
            cb.setChecked(tgt in selected_targets)
            layout.addWidget(cb)
            self._checkboxes[tgt] = cb

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
