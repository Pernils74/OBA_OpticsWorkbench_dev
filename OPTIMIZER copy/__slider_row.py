# slider_row.py
from PySide import QtWidgets, QtCore


class SliderRow(QtWidgets.QWidget):

    removed = QtCore.Signal(object)
    changed = QtCore.Signal()
    targetsRequested = QtCore.Signal(object)  # 🔥 för target dialog

    def __init__(self, metrics, parent=None):
        super().__init__(parent)

        # ✅ egna targets per row
        self.targets = ["ALL"]

        layout = QtWidgets.QHBoxLayout(self)

        # --- metric selector ---
        self.cmb = QtWidgets.QComboBox()
        self.cmb.addItems(metrics)

        # --- target button (precis som gamla UI) ---
        self.btnTargets = QtWidgets.QPushButton("ALL")
        self.btnTargets.setMinimumWidth(100)

        # --- slider ---
        self.sld = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld.setRange(0, 100)
        self.sld.setValue(50)

        # --- value label ---
        self.lbl = QtWidgets.QLabel("0.50")

        # --- delete button ---
        self.btnDelete = QtWidgets.QPushButton("X")
        # Gör knappen så liten som möjligt baserat på texten "X"
        self.btnDelete.setStyleSheet("min-width: 0px; padding: 2px 6px;")

        # --- layout ---
        layout.addWidget(self.cmb)
        layout.addWidget(self.btnTargets)
        layout.addWidget(self.sld, 1)
        # layout.addStretch(1)
        layout.addWidget(self.lbl)
        layout.addWidget(self.btnDelete)

        # --- signals ---
        self.sld.valueChanged.connect(self._on_slider_change)
        self.cmb.currentIndexChanged.connect(self._on_change)

        self.btnDelete.clicked.connect(lambda: self.removed.emit(self))

        # 🔥 klick öppnar target dialog via parent
        self.btnTargets.clicked.connect(lambda: self.targetsRequested.emit(self))

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

    # -------------------------------------------------
    # TARGET HANDLING (som gamla dialogen)
    # -------------------------------------------------
    def set_targets(self, targets):
        self.targets = targets or ["ALL"]

        if self.targets == ["ALL"]:
            text = "ALL"
        else:
            text = "; ".join(self.targets)
            if len(text) > 25:
                text = text[:25] + "..."

        self.btnTargets.setText(text)
        self.btnTargets.setToolTip("; ".join(self.targets))

        # ✅ highlight om specifika targets
        if self.targets != ["ALL"]:
            self.btnTargets.setStyleSheet("background-color:#ffeaa7")
        else:
            self.btnTargets.setStyleSheet("")

    def get_targets(self):
        return self.targets

    # -------------------------------------------------
    def get_value(self):
        return self.cmb.currentText(), self.sld.value()

    def set_values(self, raw, normalized):
        self.lbl.setText(f"{raw:.2f} → {normalized:.2f}")
