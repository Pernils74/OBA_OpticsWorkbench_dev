# -*- coding: utf-8 -*-
# showXYZList.py

"""
DocXYZDialog – visar XYZ + Hits + PowerIn / PowerOut från HitsDB
"""

import sys
import csv

try:
    from PySide import QtCore, QtWidgets
except Exception:
    from PySide import QtCore, QtWidgets

try:
    import FreeCADGui as Gui
except Exception:
    Gui = None

try:
    from .scan_db import HitsDB
except Exception:
    from scan_db import HitsDB


class DocXYZDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("XYZ + Hits + Power")
        self.setModal(True)
        self.setMinimumSize(1000, 600)

        self.db = HitsDB()

        self._build_ui()
        self._wire()
        self._populate_steps()

    # ------------------------------------------------------------
    # UI
    # ------------------------------------------------------------
    def _build_ui(self):
        vbox = QtWidgets.QVBoxLayout(self)

        row = QtWidgets.QHBoxLayout()

        row.addWidget(QtWidgets.QLabel("Step:"))
        self.cbStep = QtWidgets.QComboBox()
        row.addWidget(self.cbStep, 2)

        row.addWidget(QtWidgets.QLabel("Target:"))
        self.cbTarget = QtWidgets.QComboBox()
        row.addWidget(self.cbTarget, 2)

        row.addWidget(QtWidgets.QLabel("Emitter:"))
        self.cbEmitter = QtWidgets.QComboBox()
        row.addWidget(self.cbEmitter, 1)

        vbox.addLayout(row)

        self.tbl = QtWidgets.QTableWidget()
        self.tbl.setColumnCount(8)
        self.tbl.setHorizontalHeaderLabels(["X", "Y", "Z", "Hits", "Power In", "Power Out", "Loss", "Moved Objects"])
        self.tbl.setSortingEnabled(True)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        vbox.addWidget(self.tbl, 1)

        self.lblStatus = QtWidgets.QLabel("")
        self.lblStatus.setStyleSheet("color: gray;")
        vbox.addWidget(self.lblStatus)

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        self.btnCopy = QtWidgets.QPushButton("Kopiera")
        self.btnCSV = QtWidgets.QPushButton("Exportera CSV")
        self.btnClose = QtWidgets.QPushButton("Stäng")

        btns.addWidget(self.btnCopy)
        btns.addWidget(self.btnCSV)
        btns.addWidget(self.btnClose)

        vbox.addLayout(btns)

    # ------------------------------------------------------------
    def _wire(self):
        self.cbStep.currentIndexChanged.connect(self._populate_targets)
        self.cbTarget.currentIndexChanged.connect(self._populate_emitters)
        self.cbEmitter.currentIndexChanged.connect(self._load_grid)

        self.btnCopy.clicked.connect(self._copy_clipboard)
        self.btnCSV.clicked.connect(self._export_csv)
        self.btnClose.clicked.connect(self.accept)

        self.tbl.cellClicked.connect(self._on_row_clicked)
        self.tbl.cellDoubleClicked.connect(self._zoom_to_object)

    def _zoom_to_object(self, row, col):
        item = self.tbl.item(row, 7)
        if not item:
            return

        names = item.data(QtCore.Qt.UserRole)
        if not names:
            return

        import FreeCAD as App
        import FreeCADGui as Gui

        doc = App.ActiveDocument

        for name in names.split(";"):
            obj = doc.getObject(name)
            if obj:
                Gui.Selection.addSelection(obj)
                Gui.ActiveDocument.ActiveView.fitAll()

    def _on_row_clicked(self, row, col):
        item = self.tbl.item(row, 7)
        if not item:
            return

        names = item.data(QtCore.Qt.UserRole)
        if not names:
            return

        import FreeCADGui as Gui
        import FreeCAD as App

        doc = App.ActiveDocument
        if not doc:
            return

        Gui.Selection.clearSelection()

        for name in names.split(";"):
            obj = doc.getObject(name.strip())
            if obj:
                Gui.Selection.addSelection(obj)

    # ------------------------------------------------------------
    # DATA FLOW
    # ------------------------------------------------------------
    def _populate_steps(self):
        self.cbStep.blockSignals(True)
        self.cbStep.clear()
        self.cbStep.addItems(self.db.list_steps())
        self.cbStep.blockSignals(False)

        self._populate_targets()

    def _populate_targets(self):
        self.cbTarget.blockSignals(True)
        self.cbTarget.clear()

        # targets = self.db.list_target_objects()
        # self.cbTarget.addItems(targets)

        targets = self.db.list_target_objects()

        self._target_map = {}  # label → name

        self.cbTarget.clear()

        for name in targets:
            label = self._get_label(name)
            self._target_map[label] = name
            self.cbTarget.addItem(label)

        self.cbTarget.blockSignals(False)
        self._populate_emitters()

    def _populate_emitters(self):

        label = self.cbTarget.currentText()
        target = self._target_map.get(label, label)

        self.cbEmitter.blockSignals(True)
        self.cbEmitter.clear()

        self._emitter_map = {}  # label → name
        self.cbEmitter.clear()
        if target:
            for name in self.db.list_emitters(target):
                label = self._get_label(name)
                self._emitter_map[label] = name
                self.cbEmitter.addItem(label)

        self.cbEmitter.blockSignals(False)
        self._load_grid()

    # ------------------------------------------------------------
    def _load_grid(self):
        step = self.cbStep.currentText()

        label = self.cbTarget.currentText()
        target = self._target_map.get(label, label)

        em_label = self.cbEmitter.currentText()
        emitter = self._emitter_map.get(em_label, em_label)

        if not (step and target and emitter):
            self.tbl.setRowCount(0)
            self._update_status(0, 0, 0.0, 0.0)
            return

        X, Y, Z, H, PIN, POUT, MOVED = self.db.read_grid(target, emitter, step)

        self.tbl.setSortingEnabled(False)
        self.tbl.setRowCount(len(X))

        sum_hits = 0
        sum_p_in = 0.0
        sum_p_out = 0.0

        for i in range(len(X)):
            x, y, z = X[i], Y[i], Z[i]
            h = H[i]
            pin = PIN[i]
            pout = POUT[i]
            moved = MOVED[i]

            self.tbl.setItem(i, 0, self._num_item(x))
            self.tbl.setItem(i, 1, self._num_item(y))
            self.tbl.setItem(i, 2, self._num_item(z))
            self.tbl.setItem(i, 3, self._num_item(h))
            self.tbl.setItem(i, 4, self._num_item(pin))
            self.tbl.setItem(i, 5, self._num_item(pout))

            loss = (pin or 0.0) - (pout or 0.0)
            self.tbl.setItem(i, 6, self._num_item(loss))

            # self.tbl.setItem(i, 7, self._text_item((moved or "").replace(";", ", ")))

            labels = []
            names = []

            for name in (moved or "").split(";"):
                name = name.strip()
                if name:
                    names.append(name)

                    lbl = self._get_label(name)

                    if lbl == name:
                        labels.append(name)
                    else:
                        labels.append(f"{lbl} ({name})")

            item = QtWidgets.QTableWidgetItem(", ".join(labels))
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)

            # ✅ spara original names (kan användas senare)
            item.setData(QtCore.Qt.UserRole, ";".join(names))

            self.tbl.setItem(i, 7, item)

            sum_hits += h or 0
            sum_p_in += pin or 0.0
            sum_p_out += pout or 0.0

        self.tbl.setSortingEnabled(True)
        self._update_status(len(X), sum_hits, sum_p_in, sum_p_out)

    def _get_label(self, name):
        try:
            import FreeCAD as App

            doc = App.ActiveDocument
            if not doc or not name:
                return name
            obj = doc.getObject(name.strip())
            if obj:
                return obj.Label
            # 🔍 DEBUG fallback
            # App.Console.PrintWarning(f"Object not found for name: {name}\n")
        except Exception:
            pass
        return name

    # ------------------------------------------------------------
    def _text_item(self, txt):
        it = QtWidgets.QTableWidgetItem(str(txt))
        it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
        return it

    def _num_item(self, v):
        it = QtWidgets.QTableWidgetItem()
        it.setData(QtCore.Qt.EditRole, v)
        it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
        return it

    def _update_status(self, n, hits, p_in, p_out):
        text = f"Punkter: {n} | Hits: {hits} | Σ Pin: {p_in:.6g} | Σ Pout: {p_out:.6g}"
        self.lblStatus.setText(text)

    # ------------------------------------------------------------
    def _copy_clipboard(self):
        rows = self.tbl.rowCount()
        cols = self.tbl.columnCount()

        lines = []
        headers = [self.tbl.horizontalHeaderItem(c).text() for c in range(cols)]
        lines.append("\t".join(headers))

        for r in range(rows):
            vals = [self.tbl.item(r, c).text() if self.tbl.item(r, c) else "" for c in range(cols)]
            lines.append("\t".join(vals))

        QtWidgets.QApplication.clipboard().setText("\n".join(lines))

    def _export_csv(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Exportera CSV", "", "CSV (*.csv)")
        if not path:
            return

        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")

            w.writerow([self.tbl.horizontalHeaderItem(c).text() for c in range(self.tbl.columnCount())])

            for r in range(self.tbl.rowCount()):
                w.writerow([self.tbl.item(r, c).text() if self.tbl.item(r, c) else "" for c in range(self.tbl.columnCount())])


def OBA_ShowScanXYZList(parent=None):
    if parent is None and Gui:
        parent = Gui.getMainWindow()

    # Stäng tidigare instans om den finns
    if hasattr(Gui, "_xyz_scan_list_dialog"):
        try:
            Gui._xyz_scan_list_dialog.close()
        except Exception:
            pass
    dlg = DocXYZDialog(parent)
    dlg.show()

    # ✅ UNIKT NAMN
    Gui._xyz_scan_list_dialog = dlg
    return dlg


# def OBA_ShowScanXYZList(parent=None):
#     if parent is None and Gui:
#         parent = Gui.getMainWindow()

#     dlg = DocXYZDialog(parent)
#     dlg.exec_()   # ✅ modal
#     return dlg
