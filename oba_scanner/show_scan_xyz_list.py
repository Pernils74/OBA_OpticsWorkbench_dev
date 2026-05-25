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
        self._populate_docs()

    # ------------------------------------------------------------
    # UI
    # ------------------------------------------------------------
    def _build_ui(self):
        vbox = QtWidgets.QVBoxLayout(self)

        # --- selectors ---
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Dokument:"))
        self.cbDoc = QtWidgets.QComboBox()
        row.addWidget(self.cbDoc, 2)

        row.addWidget(QtWidgets.QLabel("Objekt:"))
        self.cbTarget = QtWidgets.QComboBox()
        row.addWidget(self.cbTarget, 2)

        row.addWidget(QtWidgets.QLabel("Emitter:"))
        self.cbEmitter = QtWidgets.QComboBox()
        row.addWidget(self.cbEmitter, 1)

        vbox.addLayout(row)

        # --- table ---
        self.tbl = QtWidgets.QTableWidget()
        self.tbl.setColumnCount(8)  #  <--- obs denna måste matcha antal kolumner i read_grid()
        self.tbl.setHorizontalHeaderLabels(["X", "Y", "Z", "Hits", "Power In", "Power Out", "Loss", "Moved Objects"])
        self.tbl.setSortingEnabled(True)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        vbox.addWidget(self.tbl, 1)

        # --- status ---
        self.lblStatus = QtWidgets.QLabel("")
        self.lblStatus.setStyleSheet("color: gray;")
        vbox.addWidget(self.lblStatus)

        # --- buttons ---
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
    # Wiring
    # ------------------------------------------------------------
    def _wire(self):
        self.cbDoc.currentIndexChanged.connect(self._populate_targets)
        self.cbTarget.currentIndexChanged.connect(self._populate_emitters)
        self.cbEmitter.currentIndexChanged.connect(self._load_grid)
        self.btnCopy.clicked.connect(self._copy_clipboard)
        self.btnCSV.clicked.connect(self._export_csv)
        self.btnClose.clicked.connect(self.accept)

    # ------------------------------------------------------------
    # Data flow
    # ------------------------------------------------------------
    def _populate_docs(self):
        self.cbDoc.blockSignals(True)
        self.cbDoc.clear()
        self.cbDoc.addItems(self.db.list_documents())
        self.cbDoc.blockSignals(False)
        self._populate_targets()

    def _populate_targets(self):
        doc = self.cbDoc.currentText()
        self.cbTarget.blockSignals(True)
        self.cbTarget.clear()
        if doc:
            self.cbTarget.addItems(self.db.list_target_objects(doc))
        self.cbTarget.blockSignals(False)
        self._populate_emitters()

    def _populate_emitters(self):
        doc = self.cbDoc.currentText()
        tgt = self.cbTarget.currentText()
        self.cbEmitter.blockSignals(True)
        self.cbEmitter.clear()
        if doc and tgt:
            self.cbEmitter.addItems(self.db.list_emitters(doc, tgt))
        self.cbEmitter.blockSignals(False)
        self._load_grid()

    def _load_grid(self):
        doc = self.cbDoc.currentText()
        tgt = self.cbTarget.currentText()
        emi = self.cbEmitter.currentText()

        if not (doc and tgt and emi):
            self.tbl.setRowCount(0)
            self._update_status(0, 0, 0.0, 0.0)
            return

        # ⬇️ ANTAR: power_in och power_out returneras
        X, Y, Z, H, P_IN, P_OUT, MOVED = self.db.read_grid(doc, tgt, emi)

        self.tbl.setSortingEnabled(False)
        self.tbl.setRowCount(len(X))

        sum_hits = 0
        sum_p_in = 0.0
        sum_p_out = 0.0

        for i, (x, y, z, h, pin, pout, moved) in enumerate(zip(X, Y, Z, H, P_IN, P_OUT, MOVED)):
            self.tbl.setItem(i, 0, self._num_item(x))
            self.tbl.setItem(i, 1, self._num_item(y))
            self.tbl.setItem(i, 2, self._num_item(z))
            self.tbl.setItem(i, 3, self._num_item(h))
            self.tbl.setItem(i, 4, self._num_item(pin))
            self.tbl.setItem(i, 5, self._num_item(pout))
            loss = (pin or 0.0) - (pout or 0.0)
            self.tbl.setItem(i, 6, self._num_item(loss))

            self.tbl.setItem(i, 7, self._text_item(moved.replace(";", ", ")))

            sum_hits += h or 0
            sum_p_in += pin or 0.0
            sum_p_out += pout or 0.0

        self.tbl.setSortingEnabled(True)
        self._update_status(len(X), sum_hits, sum_p_in, sum_p_out)

    # ------------------------------------------------------------
    # Helpers
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
        text = (f"Punkter: {n:,} | Hits: {hits:,} | " f"Σ Power In: {p_in:.6g} | Σ Power Out: {p_out:.6g}").replace(",", " ")
        self.lblStatus.setText(text)

    # ------------------------------------------------------------
    # Actions
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
