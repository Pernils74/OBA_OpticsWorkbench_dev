# oba_ray_debug.py
# -*- coding: utf-8 -*-
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore

from .oba_ray_core import OBARayManager


# ============================================================
#  HUVUDFUNKTION
# ============================================================


def OBA_ShowRayHistory():
    mgr = OBARayManager()
    rays = mgr.rays

    if not rays:
        QtWidgets.QMessageBox.information(None, "Ray Debug", "Inga rays hittades i OBARayManager().")
        return

    dlg = RayHistoryDialog(rays)
    dlg.exec_()


# ============================================================
#  DIALOG
# ============================================================


class RayHistoryDialog(QtWidgets.QDialog):
    def __init__(self, rays):
        super().__init__()
        self.setWindowTitle("Ray History Debug")
        self.resize(1100, 650)

        self.rays = rays
        self.all_bounces = self._collect_all_bounces()

        layout = QtWidgets.QVBoxLayout(self)

        # ---- Bounce-filter ----
        self.cmb = QtWidgets.QComboBox()
        self.cmb.addItem("Alla studsar", -1)
        for bc in sorted(self.all_bounces):
            self.cmb.addItem(f"Bounce {bc}", bc)
        self.cmb.currentIndexChanged.connect(self.update_table)
        layout.addWidget(self.cmb)

        # ---- Tabell ----
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels(
            [
                "Ray#",
                "Bounce#",
                "Object Name",
                "Optical Type",
                "FaceID",
                "Hit (x,y,z)",
                "Incoming Dir",
                "Outgoing Dir",
                "Power In",
                "Power Out",
                "Absorbed Power",
            ]
        )
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        layout.addWidget(self.table, 1)

        self.update_table()

    # --------------------------------------------------------

    def _collect_all_bounces(self):
        bounces = set()
        for r in self.rays:
            for h in r.history:
                if isinstance(h, dict):
                    bounces.add(h.get("bounce_index", 0))
        return bounces

    # --------------------------------------------------------

    def update_table(self):
        bc_filter = self.cmb.currentData()

        rows = []
        for ray_idx, ray in enumerate(self.rays):
            for h in ray.history:
                if not isinstance(h, dict):
                    continue
                if bc_filter != -1 and h.get("bounce_index") != bc_filter:
                    continue
                rows.append((ray_idx, h))

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))

        for row, (ray_id, h) in enumerate(rows):

            def setcol(col, value):
                item = QtWidgets.QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.table.setItem(row, col, item)

            p = h.get("hit_point")
            inc = h.get("incoming_dir")
            out = h.get("outgoing_dir")

            extra = h.get("extra", {})

            power_in = extra.get("power_in")
            power_out = extra.get("power_out")
            absorbed = extra.get("absorbed_power")

            # Fallback om absorbed inte loggats explicit
            if absorbed is None and power_in is not None and power_out is not None:
                absorbed = power_in - power_out

            setcol(0, ray_id)
            setcol(1, h.get("bounce_index"))
            setcol(2, h.get("object_name"))
            setcol(3, h.get("optical_type"))
            setcol(4, h.get("face_id"))

            setcol(
                5,
                f"({p[0]:.3f}, {p[1]:.3f}, {p[2]:.3f})" if p else "-",
            )
            setcol(
                6,
                f"({inc[0]:.3f}, {inc[1]:.3f}, {inc[2]:.3f})" if inc else "-",
            )
            setcol(
                7,
                f"({out[0]:.3f}, {out[1]:.3f}, {out[2]:.3f})" if out else "-",
            )

            setcol(8, f"{power_in:.6g}" if power_in is not None else "-")
            setcol(9, f"{power_out:.6g}" if power_out is not None else "-")
            setcol(10, f"{absorbed:.6g}" if absorbed is not None else "-")

        self.table.setSortingEnabled(True)


# ============================================================
#  COMMAND
# ============================================================


# class _CmdShowRayHistory:
#     def GetResources(self):
#         return {
#             "MenuText": "Visa Ray‑Historik",
#             "ToolTip": "Visar full historik för alla OBARay‑objekt",
#             "Pixmap": "",
#         }

#     def Activated(self):
#         OBA_ShowRayHistory()


# if "OBA_ShowRayHistory" not in Gui.listCommands():
#     Gui.addCommand("OBA_ShowRayHistory", _CmdShowRayHistory())
