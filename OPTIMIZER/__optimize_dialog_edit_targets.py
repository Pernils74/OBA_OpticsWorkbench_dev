# optimize_dialog_edit_targets.py

from PySide import QtCore, QtWidgets, QtGui


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
            if tgt == "ALL":
                cb.stateChanged.connect(self._on_all_changed)
            else:
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

    def _on_all_changed(self, state):
        all_cb = self._checkboxes["ALL"]
        checked = all_cb.isChecked()

        for tgt, cb in self._checkboxes.items():
            if tgt != "ALL":
                cb.setEnabled(not checked)

                if checked:
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)

    # -------------------------

    def _on_item_changed(self, state):
        if state == QtCore.Qt.Checked:
            all_cb = self._checkboxes["ALL"]

            if all_cb.isChecked():
                all_cb.blockSignals(True)
                all_cb.setChecked(False)
                all_cb.blockSignals(False)

            # återaktivera alla (ifall ALL var aktiv nyss)
            for tgt, cb in self._checkboxes.items():
                if tgt != "ALL":
                    cb.setEnabled(True)
