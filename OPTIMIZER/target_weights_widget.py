from PySide import QtCore, QtWidgets
import FreeCAD as App

# ==========================================================
# METRICS CONFIG
# ==========================================================

METRICS = {
    "threshold_power": {
        "type": "threshold",
        "priority": 1,
        "widget": ["percent"],
    },
    "threshold_cluster_count": {
        "type": "threshold",
        "priority": 2,
        "widget": ["value", "percent"],  # ["range"]
    },
    "cluster_axis_alignment": {
        "type": "score",
        "priority": 30,
        "widget": ["axis"],
    },
    "cluster_count": {"type": "score", "priority": 15},
    "power": {"type": "score", "priority": 10},
    "density": {"type": "score", "priority": 20},
    "roundness": {"type": "score", "priority": 20},
    "equal_distance": {"type": "score", "priority": 30},
    "equal_ray_hits_count": {"type": "score", "priority": 30},
}

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

    # --------------------------------------------------
    # DYNAMIC UI
    # --------------------------------------------------

    def _rebuild_dynamic_ui(self):
        layout = self.layout()

        # ✅ reset dynamic data (KRITISK)
        for attr in ["percentWidget", "valueWidget", "rangeWidget", "axisWidget"]:
            if hasattr(self, attr):
                delattr(self, attr)

        for w in self.dynamic_widgets:
            layout.removeWidget(w)
            w.deleteLater()
        self.dynamic_widgets = []

        metric = self.cmb.currentText()
        cfg = METRICS.get(metric, {})
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

    # --------------------------------------------------
    # PAYLOAD
    # --------------------------------------------------

    def get_payload_part(self):
        metric = self.cmb.currentText()
        cfg = METRICS.get(metric, {})

        data = {
            "base_metric": metric,
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

        dlg = EditTargetsDialog(self, self.cmb.currentText(), available, self.targets)

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

        for m in self.available_metrics():
            self.add_row(m)

    def available_metrics(self):
        return sorted(METRICS.keys(), key=lambda k: METRICS[k]["priority"])

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

    def get_payload(self):
        entries = []

        for r in self.rows:
            if r.chkActive.isChecked():
                entries.append(r.get_payload_part())

        entries = sorted(entries, key=lambda e: METRICS.get(e["base_metric"], {}).get("priority", 999))

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

        layout.addWidget(QtWidgets.QLabel("≥"))
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
