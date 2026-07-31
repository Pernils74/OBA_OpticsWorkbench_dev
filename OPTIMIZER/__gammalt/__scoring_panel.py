# scoring_panel.py
from PySide import QtWidgets, QtCore
from .__slider_row import SliderRow


class ScoringPanel(QtWidgets.QGroupBox):

    weightsChanged = QtCore.Signal(dict)

    def __init__(self, parent=None):
        super().__init__("Scoring", parent)

        self.metrics = [
            "density",
            "roundness",
            "equal_distance",
            "power",
            "cluster_count",
        ]

        layout = QtWidgets.QVBoxLayout(self)

        self.rowsLayout = QtWidgets.QVBoxLayout()
        layout.addLayout(self.rowsLayout)

        # --- Add button ---
        self.btnAdd = QtWidgets.QPushButton("+ Add metric")
        layout.addWidget(self.btnAdd)

        self.btnAdd.clicked.connect(self._add_row)

        self.rows = []

        # start med en
        self._add_row()

    def _add_row(self):
        row = SliderRow(self.metrics)

        row.removed.connect(self._remove_row)
        row.changed.connect(self._update_weights)

        self.rowsLayout.addWidget(row)
        self.rows.append(row)

        self._update_weights()

    def _remove_row(self, row):
        self.rows.remove(row)
        row.setParent(None)
        row.deleteLater()

        self._update_weights()

    def _update_weights(self):
        values = {}

        for row in self.rows:
            key, v = row.get_value()
            values[key] = values.get(key, 0) + v

        S = max(sum(values.values()), 1e-6)

        weights = {k: v / S for k, v in values.items()}

        self.weightsChanged.emit(weights)
