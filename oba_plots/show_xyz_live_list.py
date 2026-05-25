# -*- coding: utf-8 -*-
# show_xyz_live_list.py

import csv
from PySide import QtCore, QtWidgets
import FreeCADGui as Gui

from oba_rayengine.oba_ray_analyser import collect_ray_hits_and_stats
from .filter_panel import ClusterHitFilterPanel


class DocXYZLiveDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())

        self.setWindowTitle("XYZ + Hits + Power (Live, Final, DEBUG)")
        self.setModal(True)
        self.setMinimumSize(1250, 700)

        self._build_ui()
        self._wire()

        # alltid final
        self.filterPanel.set_mode("final")
        self._reload()

    # ------------------------------------------------------------
    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        # ---------- TOP BAR ----------
        top = QtWidgets.QHBoxLayout()
        self.btnReload = QtWidgets.QPushButton("Reload")
        top.addWidget(self.btnReload)
        top.addStretch(1)

        self.chkShowFilter = QtWidgets.QCheckBox("Show Filter")
        self.chkShowFilter.setChecked(True)
        top.addWidget(self.chkShowFilter)
        root.addLayout(top)

        # ---------- TABLE ----------

        headers = [
            "X",
            "Y",
            "Z",
            "Hits",
            "Emitter",
            "Paths",
            "Faces",
            "Path Count",
            "Min Bounce",
            "Max Bounce",
            "Mean Bounce",
            "Absorbed Σ",  # ✅
            "Power In Σ",  # ✅
            "Power Out Σ",  # ✅
        ]

        self.tbl = QtWidgets.QTableWidget()
        self.tbl.setColumnCount(len(headers))
        self.tbl.setHorizontalHeaderLabels(headers)
        self.tbl.setSortingEnabled(True)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        # ---------- FILTER ----------
        self.filterPanel = ClusterHitFilterPanel(self)
        self.filterPanel.setMaximumHeight(220)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        splitter.addWidget(self.tbl)
        splitter.addWidget(self.filterPanel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        root.addWidget(splitter, 1)

        # ---------- STATUS ----------
        self.lblStatus = QtWidgets.QLabel("")
        self.lblStatus.setStyleSheet("color: gray;")
        root.addWidget(self.lblStatus)

        # ---------- BUTTONS ----------
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)

        self.btnCopy = QtWidgets.QPushButton("Kopiera")
        self.btnCSV = QtWidgets.QPushButton("Exportera CSV")
        self.btnClose = QtWidgets.QPushButton("Stäng")

        btns.addWidget(self.btnCopy)
        btns.addWidget(self.btnCSV)
        btns.addWidget(self.btnClose)

        root.addLayout(btns)

    # ------------------------------------------------------------
    def _wire(self):
        self.btnReload.clicked.connect(self._reload)
        self.filterPanel.filter_changed.connect(self._reload)
        self.chkShowFilter.toggled.connect(self.filterPanel.setVisible)

        self.btnCopy.clicked.connect(self._copy_clipboard)
        self.btnCSV.clicked.connect(self._export_csv)
        self.btnClose.clicked.connect(self.accept)

    # ------------------------------------------------------------
    def _reload(self):
        hits, _stats = collect_ray_hits_and_stats(mode="final")

        filter_spec = self.filterPanel.get_filter_spec()
        allowed_emitters = set(filter_spec["emitters"])
        allowed_objects = set(filter_spec["objects"])

        accum = {}

        for h in hits:
            emitter = h["emitter_id"]
            obj = h["object"]

            if emitter not in allowed_emitters:
                continue
            if obj not in allowed_objects:
                continue

            pt = h["point"]
            key = (obj, tuple(pt))  # ✅ tuple för säker dict-key

            if key not in accum:
                accum[key] = {
                    "x": pt[0],
                    "y": pt[1],
                    "z": pt[2],
                    "hits": 0,
                    "emitters": set(),
                    "faces": set(),
                    "paths": set(),
                    "bounces": [],
                    # ✅ energi
                    "power_in": 0.0,
                    "power_out": 0.0,
                    "absorbed": 0.0,
                }

            a = accum[key]
            a["hits"] += 1
            a["emitters"].add(emitter)
            a["faces"].add(h["last_hit_label"])
            a["paths"].add(tuple(h["path_signature"]))
            a["bounces"].append(h["bounce"])

            # ✅ korrekt energibokföring
            a["power_in"] += h.get("power_in", 0.0) or 0.0
            a["power_out"] += h.get("power_out", 0.0) or 0.0
            a["absorbed"] += h.get("absorbed_power", 0.0) or 0.0

        # ---------- Fill table ----------
        self.tbl.setSortingEnabled(False)
        self.tbl.setRowCount(len(accum))

        for row, a in enumerate(accum.values()):
            self.tbl.setItem(row, 0, self._num(a["x"]))
            self.tbl.setItem(row, 1, self._num(a["y"]))
            self.tbl.setItem(row, 2, self._num(a["z"]))
            self.tbl.setItem(row, 3, self._num(a["hits"]))

            self.tbl.setItem(row, 4, QtWidgets.QTableWidgetItem(", ".join(sorted(a["emitters"]))))
            self.tbl.setItem(row, 5, QtWidgets.QTableWidgetItem(str(len(a["paths"]))))
            self.tbl.setItem(row, 6, QtWidgets.QTableWidgetItem(", ".join(sorted(map(str, a["faces"])))))

            bs = a["bounces"]
            self.tbl.setItem(row, 7, self._num(len(a["paths"])))
            self.tbl.setItem(row, 8, self._num(min(bs)))
            self.tbl.setItem(row, 9, self._num(max(bs)))
            self.tbl.setItem(row, 10, self._num(sum(bs) / len(bs)))

            # ✅ NU MENINGSFULLA energikolumner
            self.tbl.setItem(row, 11, self._num(a["absorbed"]))
            self.tbl.setItem(row, 12, self._num(a["power_in"]))
            self.tbl.setItem(row, 13, self._num(a["power_out"]))

        self.tbl.setSortingEnabled(True)

        self.lblStatus.setText(f"Punkter: {len(accum)} | " f"Hits: {sum(a['hits'] for a in accum.values())}")

    # ------------------------------------------------------------
    def _num(self, v):
        it = QtWidgets.QTableWidgetItem()
        it.setData(QtCore.Qt.EditRole, v)
        it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
        return it

    # ------------------------------------------------------------
    def _copy_clipboard(self):
        rows, cols = self.tbl.rowCount(), self.tbl.columnCount()
        lines = ["\t".join(self.tbl.horizontalHeaderItem(c).text() for c in range(cols))]

        for r in range(rows):
            lines.append("\t".join(self.tbl.item(r, c).text() if self.tbl.item(r, c) else "" for c in range(cols)))

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


def OBA_ShowXYZLiveList(parent=None):
    dlg = DocXYZLiveDialog(parent or Gui.getMainWindow())
    dlg.show()
    Gui._xyz_live_list_dialog = dlg
    return dlg
