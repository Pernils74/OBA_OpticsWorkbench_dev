# oba_ray_debug.py
# -*- coding: utf-8 -*-

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore

from .oba_ray_core import OBARayManager

# ============================================================
# HUVUDFUNKTION
# ============================================================


def OBA_ShowRayHistory():

    mgr = OBARayManager()
    rays = mgr.rays

    if not rays:
        QtWidgets.QMessageBox.information(
            None,
            "Ray Debug",
            "Inga rays hittades i OBARayManager().",
        )
        return

    dlg = RayHistoryDialog(rays)
    dlg.exec_()


# ============================================================
# DIALOG
# ============================================================


class RayHistoryDialog(QtWidgets.QDialog):

    def __init__(self, rays):
        super().__init__()

        self.setWindowTitle("Ray History Debug")
        self.resize(2200, 900)

        self.rays = rays
        self.all_bounces = self._collect_all_bounces()

        # ----------------------------------------------------
        # Name -> Label lookup
        # ----------------------------------------------------
        self.name_to_label = {}

        doc = App.ActiveDocument

        if doc:
            for obj in doc.Objects:
                self.name_to_label[obj.Name] = obj.Label

        layout = QtWidgets.QVBoxLayout(self)

        # ----------------------------------------------------
        # Top controls
        # ----------------------------------------------------

        top_row = QtWidgets.QHBoxLayout()

        self.cmb = QtWidgets.QComboBox()

        self.cmb.addItem("Alla studsar", -1)

        for bc in sorted(self.all_bounces):
            self.cmb.addItem(f"Bounce {bc}", bc)

        self.cmb.currentIndexChanged.connect(self.update_table)

        top_row.addWidget(QtWidgets.QLabel("Bounce:"))
        top_row.addWidget(self.cmb)

        self.btnCopy = QtWidgets.QPushButton("Copy Table")
        self.btnCopy.clicked.connect(self.copy_table_to_clipboard)

        top_row.addWidget(self.btnCopy)
        top_row.addStretch()

        layout.addLayout(top_row)

        # ----------------------------------------------------
        # TABLE
        # ----------------------------------------------------

        self.table = QtWidgets.QTableWidget()

        headers = [
            "Ray#",
            "Bounce#",
            "Ray ID",
            "Parent ID",
            "Path ID",
            "Emitter ID",
            "Object Name",
            "Object Label",
            "Optical Type",
            "Prev Label",
            "Last Label",
            "FaceID",
            "Hit (x,y,z)",
            "Incoming Dir",
            "Outgoing Dir",
            "Power In",
            "Power Out",
            "Absorbed Power",
        ]

        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

        self.table.setSortingEnabled(True)

        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)

        layout.addWidget(self.table)

        self.update_table()

    # --------------------------------------------------------

    def _collect_all_bounces(self):

        bounces = set()

        for ray in self.rays:
            for h in ray.history:

                if not isinstance(h, dict):
                    continue

                bounce = h.get("bounce_index")

                if bounce is not None:
                    bounces.add(bounce)

        return bounces

    # --------------------------------------------------------

    def copy_table_to_clipboard(self):

        rows = self.table.rowCount()
        cols = self.table.columnCount()

        lines = []

        # headers
        headers = []

        for c in range(cols):

            item = self.table.horizontalHeaderItem(c)

            headers.append(item.text() if item else "")

        lines.append("\t".join(headers))

        # rows
        for r in range(rows):

            values = []

            for c in range(cols):

                item = self.table.item(r, c)

                values.append(item.text() if item is not None else "")

            lines.append("\t".join(values))

        text = "\n".join(lines)

        QtWidgets.QApplication.clipboard().setText(text)

        QtWidgets.QMessageBox.information(
            self,
            "Ray History",
            f"{rows} rows copied to clipboard.",
        )

    # --------------------------------------------------------

    def update_table(self):

        bounce_filter = self.cmb.currentData()

        rows = []

        for ray_idx, ray in enumerate(self.rays):

            for h in ray.history:

                if not isinstance(h, dict):
                    continue

                if bounce_filter != -1 and h.get("bounce_index") != bounce_filter:
                    continue

                rows.append((ray_idx, h))

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))

        for row, (ray_idx, h) in enumerate(rows):

            def setcol(col, value):

                item = QtWidgets.QTableWidgetItem("" if value is None else str(value))

                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)

                self.table.setItem(row, col, item)

            # ------------------------------------------------
            # History data
            # ------------------------------------------------

            p = h.get("hit_point")
            inc = h.get("incoming_dir")
            out = h.get("outgoing_dir")

            obj_name = h.get("object_name")

            obj_label = h.get("object_label") or self.name_to_label.get(
                obj_name,
                obj_name,
            )

            prev_label = h.get("prev_hit_label")
            last_label = h.get("last_hit_label")

            extra = h.get("extra", {})

            power_in = extra.get("power_in")
            power_out = extra.get("power_out")
            absorbed = extra.get("absorbed_power")

            if absorbed is None and power_in is not None and power_out is not None:
                absorbed = power_in - power_out

            # ------------------------------------------------
            # Write row
            # ------------------------------------------------

            setcol(0, ray_idx)
            setcol(1, h.get("bounce_index"))

            setcol(2, h.get("ray_id"))
            setcol(3, h.get("parent_id"))
            setcol(4, h.get("path_id"))
            setcol(5, h.get("emitter_id"))

            setcol(6, obj_name)
            setcol(7, obj_label)

            setcol(8, h.get("optical_type"))

            setcol(9, prev_label)
            setcol(10, last_label)

            setcol(11, h.get("face_id"))

            setcol(12, f"({p[0]:.3f}, {p[1]:.3f}, {p[2]:.3f})" if p else "-")

            setcol(13, f"({inc[0]:.3f}, {inc[1]:.3f}, {inc[2]:.3f})" if inc else "-")

            setcol(14, f"({out[0]:.3f}, {out[1]:.3f}, {out[2]:.3f})" if out else "-")

            setcol(15, f"{power_in:.6g}" if power_in is not None else "-")

            setcol(16, f"{power_out:.6g}" if power_out is not None else "-")

            setcol(17, f"{absorbed:.6g}" if absorbed is not None else "-")

        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()


# ============================================================
# COMMAND
# ============================================================

# class _CmdShowRayHistory:
#
#     def GetResources(self):
#         return {
#             "MenuText": "Visa Ray Historik",
#             "ToolTip": "Visar full historik för alla OBARay objekt",
#             "Pixmap": "",
#         }
#
#     def Activated(self):
#         OBA_ShowRayHistory()
#
#
# if "OBA_ShowRayHistory" not in Gui.listCommands():
#     Gui.addCommand(
#         "OBA_ShowRayHistory",
#         _CmdShowRayHistory(),
#     )
