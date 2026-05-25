# target_weights_widget.py


# Ger payload :

# {
#   "entries": [
#     {
#       "metric": "density",
#       "active": true,
#       ...
#     },
#     {
#       "metric": "roundness",
#       "active": false,
#       ...
#     }
#   ]
# }


from PySide import QtCore, QtWidgets
import FreeCAD as App


class MetricEntry:
    def __init__(self, metric, plane="XY", raw=50, targets=None):
        self.metric = metric
        self.plane = plane
        self.raw = raw
        self.targets = targets or []

    def to_dict(self, total):
        return {
            "metric": self.metric,
            "raw": self.raw,
            "normalized": self.raw / total if total > 0 else 0.0,
            "targets": self.targets,
            "plane": self.plane,
        }


class MetricConfigModel:

    def __init__(self):
        self.entries = []

    def clear(self):
        self.entries = []

    def add(self, entry):
        self.entries.append(entry)

    def remove(self, entry):
        self.entries.remove(entry)

    def normalize(self):
        total = sum(e.raw for e in self.entries)
        if total <= 0:
            total = 1e-6

        return [e.to_dict(total) for e in self.entries]

    def to_payload(self):
        return {"entries": self.normalize()}


# ==========================================================
# ROW
# ==========================================================

AXIS_METRICS = {"axis_alignment"}

# Lågt nummer = Körs först. Högt nummer = Körs sist.
# METRIC_PRIORITY = {"density": 10, "roundness": 20, "equal_distance": 30, "equal_ray_hits_count": 40, "axis_alignment": 50}  # Dörrvakten (körs alltid först)  # Tunga beräkningar/scanners körs sist
# Definiera dina tröskelvärden (thresholds) här, t.ex. baserat på din baseline-skala (1.0)

METRICS = {
    "power_threshold": {
        "priority": 1,
        "threshold": 0.3,  # prunar om 30% är förlorad
    },
    "power": {
        "priority": 10,
    },
    "density": {
        "priority": 20,
    },
    "roundness": {
        "priority": 20,
    },
    "equal_distance": {
        "priority": 30,
    },
    "equal_ray_hits_count": {
        "priority": 30,
    },
    "axis_alignment": {
        "priority": 30,
    },
}


class MetricRowWidget(QtWidgets.QWidget):

    changed = QtCore.Signal()
    removed = QtCore.Signal(object)

    def __init__(self, metrics, metric="density", parent=None):
        super().__init__(parent)

        # ---------------- state ----------------
        self.targets = self._get_default_target()

        layout = QtWidgets.QHBoxLayout(self)

        self.cmb = QtWidgets.QComboBox()
        self.cmb.addItems(metrics)
        self.cmb.setCurrentText(metric)

        self.btnTargets = QtWidgets.QPushButton()

        self.cmbPlane = QtWidgets.QComboBox()
        self.cmbPlane.addItems(["XY", "XZ", "YZ", "3D"])

        self.cmbAxis = QtWidgets.QComboBox()
        self.cmbAxis.addItems(["X", "Y", "Z"])

        self.sld = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld.setRange(0, 100)
        self.sld.setValue(50)

        self.lbl = QtWidgets.QLabel()

        self.chkActive = QtWidgets.QCheckBox()
        self.chkActive.setChecked(True)
        self.chkActive.setToolTip("Enable / disable metric")

        layout.addWidget(self.chkActive)
        layout.addWidget(self.cmb)
        layout.addWidget(self.btnTargets)
        layout.addWidget(self.cmbPlane)

        layout.addWidget(self.cmbAxis)

        layout.addWidget(self.sld, 1)
        layout.addWidget(self.lbl)

        self._update_targets_button()
        self._update_label()

        # ---------------- signals ----------------
        # self.cmb.currentIndexChanged.connect(self.changed)
        self.cmb.currentIndexChanged.connect(self._update_axis_visibility)

        self.cmbPlane.currentIndexChanged.connect(self.changed)
        self.sld.valueChanged.connect(self._on_slider)

        self.btnTargets.clicked.connect(self._edit_targets)

        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setAutoFillBackground(True)
        self._selected = False

        self._update_axis_visibility()

    # -------------------------------------------------

    def clear_selection(self):
        for r in self.rows:
            r._selected = False
            r.setStyleSheet("")

    def mousePressEvent(self, event):
        parent = self.parent()
        if hasattr(parent, "clear_selection"):
            parent.clear_selection()

        self._selected = True
        self.setStyleSheet("background-color:#dfe6e9;")
        self.setFocus()

        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            self.removed.emit(self)
        else:
            super().keyPressEvent(event)

    def enterEvent(self, event):
        if not self._selected:
            self.setStyleSheet("background-color:#f5f6fa;")

    def leaveEvent(self, event):
        if not self._selected:
            self.setStyleSheet("")

    def _on_slider(self):
        self._update_label()
        self.changed.emit()

    def _update_label(self):
        self.lbl.setText(f"{self.sld.value()/100:.2f}")

    def set_values(self, raw, normalized):
        self.lbl.setText(f"{raw:.2f} → {normalized:.2f}")

    # -------------------------------------------------
    # TARGETS
    # -------------------------------------------------
    def _get_default_target(self):
        doc = App.ActiveDocument
        if not doc:
            return []

        mirrors = [obj.Label for obj in doc.Objects if getattr(obj, "OpticalType", None) == "Mirror"]

        if mirrors:
            return [mirrors[0]]

        # fallback
        optical = [obj.Label for obj in doc.Objects if hasattr(obj, "OpticalType")]
        return optical[:1]

    def _update_targets_button(self):
        if not self.targets:
            text = "—"
        else:
            text = "; ".join(self.targets)
            if len(text) > 25:
                text = text[:25] + "..."

        self.btnTargets.setText(text)
        self.btnTargets.setToolTip("; ".join(self.targets))

    def _edit_targets(self):
        doc = App.ActiveDocument
        if not doc:
            return

        available = [obj.Label for obj in doc.Objects if hasattr(obj, "OpticalType")]

        dlg = EditTargetsDialog(
            self,
            self.cmb.currentText(),
            available,
            self.targets,
        )

        if dlg.exec_():
            selected = dlg.selected_targets()

            if not selected:
                selected = self._get_default_target()

            self.targets = selected
            self._update_targets_button()

            self.changed.emit()

    def get_targets(self):
        if not self.targets:
            return self._get_default_target()
        return self.targets

    # -------------------------------------------------
    def get_payload_part(self, total):
        axis = self.cmbAxis.currentText()
        return {
            "metric": self.cmb.currentText(),
            "active": self.chkActive.isChecked(),
            "raw": self.sld.value(),
            "normalized": self.sld.value() / total,
            "targets": self.get_targets(),
            "plane": self.cmbPlane.currentText(),
            "axis": axis if axis else None,
        }

    def _update_axis_visibility(self):
        metric = self.cmb.currentText()
        self.cmbAxis.setVisible(metric in AXIS_METRICS)

        # if metric == "keep_position_in":
        #     self.cmbAxis.show()
        # else:
        #     self.cmbAxis.hide()


# ==========================================================
# MAIN WIDGET
# ==========================================================


class TargetWeightsWidget(QtWidgets.QGroupBox):

    weightsChanged = QtCore.Signal(object)

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

        # defaults
        # for m in ["density", "roundness", "equal_distance"]:
        # self.add_row(m)
        for m in self.available_metrics():
            self.add_row(m)

    # -----------------------------
    def available_metrics(self):
        return sorted(METRICS.keys(), key=lambda k: METRICS[k]["priority"])
        # return [
        #     "density",
        #     "roundness",
        #     "equal_distance",
        #     "equal_ray_hits_count",
        #     "axis_alignment",
        # ]

    def add_row(self, metric="density"):
        row = MetricRowWidget(self.available_metrics(), metric)

        row.changed.connect(self._update)
        row.removed.connect(self.remove_row)

        self.rows.append(row)
        self.container.addWidget(row)

        self._update()

    def remove_row(self, row):
        self.rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self._update()

    # -----------------------------

    def _update(self):
        payload = self.get_payload()

        # ✅ uppdatera varje rad
        for entry, row in zip(payload["entries"], self.rows):
            row.set_values(
                entry["raw"] / 100.0,
                entry["normalized"],
            )
        # summary
        txt = [f"{e['metric']}[{e['plane']}]:{e['normalized']:.2f}" for e in payload["entries"]]

        self.lblSummary.setText(" | ".join(txt))

        self.weightsChanged.emit(payload)

    def get_payload_old(self):
        total = sum(r.sld.value() for r in self.rows)
        if total <= 0:
            total = 1e-6

        return {"entries": [r.get_payload_part(total) for r in self.rows]}

    def get_payload(self):
        active_entries = []
        for r in self.rows:
            if r.chkActive.isChecked():
                active_entries.append(r.get_payload_part(total=1))  # behåll din befintliga get_payload_part

        # 💡 AUTOMATISK HÅRDKODAD SORTERING:
        # Vi tittar på "metric"-strängen (t.ex. "density") och hämtar dess prioritet ur vår ordbok.
        # Om en metric saknas i ordboken får den prioritet 999 (körs sist).
        sorted_entries = sorted(active_entries, key=lambda e: METRICS.get(e["metric"], {}).get("priority", 999))

        return {"entries": sorted_entries}


# ==========================================================
# DIALOG
# ==========================================================


class EditTargetsDialog(QtWidgets.QDialog):

    def __init__(self, parent, metric_key, available_targets, selected_targets):
        super().__init__(parent)

        self.setWindowTitle(f"Select targets for {metric_key}")
        self.setModal(True)
        self.resize(260, 300)

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
