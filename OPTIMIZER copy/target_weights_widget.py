# target_weights_widget.py

from PySide import QtCore, QtWidgets
import FreeCAD as App

# from .slider_row import SliderRow
# from .optimize_dialog_edit_targets import EditTargetsDialog


class TargetWeightsWidget(QtWidgets.QGroupBox):

    #
    # payload:
    #
    # {
    #     "entries":[
    #         {
    #             "metric":"density",
    #             "raw":50,
    #             "normalized":0.33,
    #             "targets":["Lens001"]
    #         }
    #     ]
    # }
    #
    weightsChanged = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__("Målvikter", parent)

        self.sliderRows = []
        self._build_ui()
        #
        # standardrader
        #
        for metric in (
            "cluster_count",
            "density",
            "roundness",
            "equal_distance",
        ):
            self.add_row(metric)

    # --------------------------------------------------
    # UI
    # --------------------------------------------------

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        self.sliderContainer = QtWidgets.QVBoxLayout()
        root.addLayout(self.sliderContainer)
        self.lblSummary = QtWidgets.QLabel("")
        root.addWidget(self.lblSummary)

        self.btnAdd = QtWidgets.QPushButton("+ Lägg till metric")
        self.btnAdd.clicked.connect(self._on_add_clicked)
        root.addWidget(self.btnAdd)

    # --------------------------------------------------
    # PUBLIC API
    # --------------------------------------------------

    def get_payload(self):
        return self._build_payload()

    def set_payload(self, payload):
        self.clear()
        for entry in payload.get("entries", []):
            row = self.add_row(entry["metric"])
            row.sld.setValue(entry.get("raw", 50))
            row.set_targets(entry.get("targets", ["ALL"]))
        self._recalculate()

    def clear(self):

        while self.sliderRows:
            self.remove_row(self.sliderRows[0])

    # --------------------------------------------------
    # ROW MANAGEMENT
    # --------------------------------------------------

    def available_metrics(self):

        return [
            "cluster_count",
            "density",
            "roundness",
            "equal_distance",
        ]

    def add_row(self, metric=None):
        row = SliderRow(
            self.available_metrics(),
            self,
        )

        if metric:
            idx = row.cmb.findText(metric)
            if idx >= 0:
                row.cmb.setCurrentIndex(idx)
        row.changed.connect(self._recalculate)
        row.removed.connect(self.remove_row)
        row.targetsRequested.connect(self._edit_targets)
        self.sliderRows.append(row)
        self.sliderContainer.addWidget(row)
        self._recalculate()
        return row

    def remove_row(self, row):

        if row not in self.sliderRows:
            return
        self.sliderRows.remove(row)
        self.sliderContainer.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._recalculate()

    # --------------------------------------------------
    # TARGETS
    # --------------------------------------------------

    def _edit_targets(self, row):
        doc = App.ActiveDocument
        if not doc:
            return
        available = ["ALL"]
        for obj in doc.Objects:
            if hasattr(obj, "OpticalType"):
                available.append(obj.Label)

        dlg = EditTargetsDialog(
            self,
            row.get_metric_key(),
            available,
            row.get_targets(),
        )

        if dlg.exec_():
            row.set_targets(dlg.selected_targets() or ["ALL"])
            self._recalculate()

    # --------------------------------------------------
    # EVENTS
    # --------------------------------------------------

    def _on_add_clicked(self):

        self.add_row()

    # --------------------------------------------------
    # WEIGHT CALC
    # --------------------------------------------------

    def _recalculate(self):

        payload = self._build_payload()

        #
        # uppdatera labels
        #
        for entry, row in zip(
            payload["entries"],
            self.sliderRows,
        ):

            row.set_values(
                entry["raw"] / 100.0,
                entry["normalized"],
            )

        #
        # summaryrad
        #
        txt = []

        for e in payload["entries"]:
            # txt.append(f"{e['metric']}:{e['normalized']:.2f}")
            txt.append(f"{e['metric']}[{e['plane']}]:{e['normalized']:.2f}")

        self.lblSummary.setText(" | ".join(txt))
        #
        # emit
        #
        self.weightsChanged.emit(payload)

    def _build_payload(self):
        rows = []
        total = 0
        for row in self.sliderRows:
            metric, raw = row.get_value()
            total += raw
            rows.append(
                {
                    "row": row,
                    "metric": metric,
                    "raw": raw,
                    "targets": row.get_targets(),
                    "plane": row.get_plane(),
                }
            )

        if total <= 0:
            total = 1e-6
        entries = []
        for item in rows:
            normalized = item["raw"] / total
            entries.append(
                {
                    "metric": item["metric"],
                    "raw": item["raw"],
                    "normalized": normalized,
                    "targets": item["targets"],
                    "plane": item["plane"],
                }
            )

        return {"entries": entries}


class EditTargetsDialog(QtWidgets.QDialog):
    """
    Liten popup för att välja targets för en metric.
    """

    def __init__(self, parent, metric_key, available_targets, selected_targets):
        super().__init__(parent)
        self.setWindowTitle(f"Select targets for {metric_key.capitalize()}")
        self.setModal(True)
        self.resize(260, 300)

        self.metric_key = metric_key
        self._checkboxes = {}

        v = QtWidgets.QVBoxLayout(self)

        lbl = QtWidgets.QLabel("Select which optical objects\nshould be included:")
        v.addWidget(lbl)

        self.list = QtWidgets.QWidget()
        list_layout = QtWidgets.QVBoxLayout(self.list)

        # --- skapa checkboxar ---
        for tgt in available_targets:
            cb = QtWidgets.QCheckBox(tgt)
            cb.setChecked(tgt in selected_targets)
            list_layout.addWidget(cb)
            self._checkboxes[tgt] = cb

        # --- koppla signaler ---
        for tgt, cb in self._checkboxes.items():
            cb.stateChanged.connect(self._on_item_changed)

        v.addWidget(self.list, 1)

        # --- knappar ---
        row = QtWidgets.QHBoxLayout()
        btnApply = QtWidgets.QPushButton("Apply")
        btnCancel = QtWidgets.QPushButton("Cancel")
        row.addStretch()
        row.addWidget(btnApply)
        row.addWidget(btnCancel)
        v.addLayout(row)

        btnApply.clicked.connect(self.accept)
        btnCancel.clicked.connect(self.reject)

        # --- init-state fix ---
        if "ALL" in selected_targets:
            self._on_all_changed(QtCore.Qt.Checked)

    # -------------------------

    def selected_targets(self):
        return [t for t, cb in self._checkboxes.items() if cb.isChecked()]

    # -------------------------

    # -------------------------

    def _on_item_changed(self, state):
        pass


class SliderRow(QtWidgets.QWidget):

    removed = QtCore.Signal(object)
    changed = QtCore.Signal()
    targetsRequested = QtCore.Signal(object)  # 🔥 för target dialog

    def __init__(self, metrics, parent=None):
        super().__init__(parent)

        # ✅ egna targets per row

        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setAutoFillBackground(True)
        self._selected = False

        layout = QtWidgets.QHBoxLayout(self)

        # --- metric selector ---
        self.cmb = QtWidgets.QComboBox()
        self.cmb.addItems(metrics)

        # --- target button (precis som gamla UI) ---
        self.btnTargets = QtWidgets.QPushButton("")
        self.btnTargets.setMinimumWidth(100)

        # --- slider ---
        self.sld = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld.setRange(0, 100)
        self.sld.setValue(50)

        # --- value label ---
        self.lbl = QtWidgets.QLabel("0.50")

        # --- delete button ---
        # self.btnDelete = QtWidgets.QPushButton("X")
        # # Gör knappen så liten som möjligt baserat på texten "X"
        # self.btnDelete.setStyleSheet("min-width: 0px; padding: 2px 6px;")

        self.cmbPlane = QtWidgets.QComboBox()
        self.cmbPlane.addItems(["XY", "XZ", "YZ", "3D"])
        # self.cmbPlane.setFixedWidth(60)

        # --- layout ---
        layout.addWidget(self.cmb)
        layout.addWidget(self.btnTargets)
        layout.addWidget(self.sld, 1)
        # layout.addStretch(1)
        layout.addWidget(self.lbl)
        # layout.addWidget(self.btnDelete)
        layout.addWidget(self.cmbPlane)

        # --- signals ---
        self.sld.valueChanged.connect(self._on_slider_change)
        self.cmb.currentIndexChanged.connect(self._on_change)

        # self.btnDelete.clicked.connect(lambda: self.removed.emit(self))
        self.cmbPlane.currentIndexChanged.connect(self._on_change)

        # 🔥 klick öppnar target dialog via parent
        self.btnTargets.clicked.connect(lambda: self.targetsRequested.emit(self))

        self.set_targets(self._get_default_target())

    def _get_default_target(self):
        doc = App.ActiveDocument
        if not doc:
            return []
        for obj in doc.Objects:
            if getattr(obj, "OpticalType", None) == "Mirror":
                return [obj.Label]
        return []

    # -------------------------------------------------
    # EVENTS
    # -------------------------------------------------
    def _on_slider_change(self, val):
        self.lbl.setText(f"{val/100:.2f}")
        self._on_change()

    def _on_change(self):
        self.changed.emit()

    def get_metric_key(self):
        return self.cmb.currentText()

    def mousePressEvent(self, event):
        self._selected = True
        self.setStyleSheet("background-color: #dfe6e9;")
        self.setFocus()
        super().mousePressEvent(event)

    def focusOutEvent(self, event):
        self._selected = False
        self.setStyleSheet("")
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            self.removed.emit(self)
        else:
            super().keyPressEvent(event)

    # -------------------------------------------------
    # TARGET HANDLING (som gamla dialogen)
    # -------------------------------------------------
    def set_targets(self, targets):
        # ✅ fallback direkt här
        if not targets:
            targets = self._get_default_target()

        self.targets = targets

        # --- text ---
        if not self.targets:
            text = "—"  # inget valt
            tooltip = "No targets selected"
        else:
            text = "; ".join(self.targets)
            tooltip = text
            if len(text) > 25:
                text = text[:25] + "..."
        self.btnTargets.setText(text)
        self.btnTargets.setToolTip(tooltip)

        # --- highlight ---
        if self.targets:
            self.btnTargets.setStyleSheet("background-color:#ffeaa7")
        else:
            self.btnTargets.setStyleSheet("")

    def get_targets(self):
        return self.targets

    def get_plane(self):
        return self.cmbPlane.currentText()

    # -------------------------------------------------
    def get_value(self):
        return self.cmb.currentText(), self.sld.value()

    def set_values(self, raw, normalized):
        self.lbl.setText(f"{raw:.2f} → {normalized:.2f}")

    def get_plane(self):
        return self.cmbPlane.currentText()
