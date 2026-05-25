# -*- coding: utf-8 -*-
# dialog_batch_edit.py

import json
import datetime
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore, QtGui


from .dialog_step_edit import StepEditDialog
from .batch_runner import run_steps_for_batch
from .heatmap_viewer import ShowHeatmapViewer
from .show_scan_xyz_list import OBA_ShowScanXYZList

ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "icons")
DOCK_NAME = "BatchGroupDock"


# --------------------------------------------------
# List widget with delete shortcut
# --------------------------------------------------
class StepListWidget(QtWidgets.QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._delete_callback = None

    def set_delete_callback(self, fn):
        self._delete_callback = fn

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Delete:
            if self._delete_callback:
                self._delete_callback()
        else:
            super().keyPressEvent(event)


# --------------------------------------------------
# Batch group object
# --------------------------------------------------
class BatchGroupProxy:
    def __init__(self, obj):
        obj.Proxy = self

        if not hasattr(obj, "GroupId"):
            obj.addProperty("App::PropertyString", "GroupId")
            obj.GroupId = datetime.datetime.now().strftime("BG_%Y%m%d_%H%M%S")

    def onDocumentRestored(self, obj):
        # 🔑 EXTREMT VIKTIGT
        obj.Proxy = self
        self.Object = obj

    def doubleClicked(self, vobj):
        ShowBatchGroupPanel(vobj.Object)
        return True

    # def __getstate__(self):
    #     # Vi sparar inga Python‑fält, bara Properties
    #     return None

    # def __setstate__(self, state):
    #     # Anropas vid reopen, innan onDocumentRestored
    #     return None


class BatchGroupViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def doubleClicked(self, vobj):
        return vobj.Object.Proxy.doubleClicked(vobj)

    # def onDocumentRestored(self, vobj):
    #     vobj.Proxy = self


def create_batchgroup(doc=None):
    doc = doc or App.ActiveDocument or App.newDocument()

    # 🔎 Leta efter befintlig BatchGroup
    for obj in doc.Objects:
        if obj.TypeId == "App::DocumentObjectGroupPython" and hasattr(obj, "GroupId"):
            # ✅ Återanvänd befintlig
            return obj

    # ➕ Skapa ny om ingen finns
    obj = doc.addObject("App::DocumentObjectGroupPython", "BatchGroup")
    BatchGroupProxy(obj)
    BatchGroupViewProvider(obj.ViewObject)

    return obj


# --------------------------------------------------
# Dock widget
# --------------------------------------------------
class BatchGroupDock(QtWidgets.QDockWidget):
    def __init__(self, parent, batch_obj):
        super().__init__(parent)
        self.setObjectName(DOCK_NAME)
        self.setWindowTitle("Batch Group – Steps")

        self.batch = batch_obj
        self._cancel = False

        main = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(main)

        # --------------------------------------------------
        # Step list
        # --------------------------------------------------
        self.list = StepListWidget()
        self.list.set_delete_callback(self._delete_selected_step)
        self.list.itemDoubleClicked.connect(self._open_step_dialog)
        lay.addWidget(self.list)

        # --------------------------------------------------
        # Buttons
        # --------------------------------------------------
        row = QtWidgets.QHBoxLayout()

        self.btn_add = QtWidgets.QPushButton("Add Step")
        self.btn_run = QtWidgets.QPushButton("Run")
        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_heatmap = QtWidgets.QPushButton("Heatmap")
        self.btn_xyz_list = QtWidgets.QPushButton("DB XYZ list")

        self.btn_add.setIcon(QtGui.QIcon(os.path.join(ICON_DIR, "add.svg")))
        self.btn_run.setIcon(QtGui.QIcon(os.path.join(ICON_DIR, "run.svg")))
        self.btn_stop.setIcon(QtGui.QIcon(os.path.join(ICON_DIR, "stop.svg")))
        self.btn_heatmap.setIcon(QtGui.QIcon(os.path.join(ICON_DIR, "heatmap.svg")))
        self.btn_xyz_list.setIcon(QtGui.QIcon(os.path.join(ICON_DIR, "xyz_scan_list")))

        row.addWidget(self.btn_heatmap)
        row.addWidget(self.btn_xyz_list)
        row.addStretch()
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_run)
        row.addWidget(self.btn_stop)
        lay.addLayout(row)

        # --------------------------------------------------
        # Progress
        # --------------------------------------------------
        self.prog = QtWidgets.QProgressBar()
        self.lbl = QtWidgets.QLabel("")
        lay.addWidget(self.prog)
        lay.addWidget(self.lbl)

        self.setWidget(main)

        # --------------------------------------------------
        # Signals
        # --------------------------------------------------
        self.btn_add.clicked.connect(self._add_step)
        self.btn_run.clicked.connect(self._run)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_heatmap.clicked.connect(self._open_heatmap)
        self.btn_xyz_list.clicked.connect(self._open_xyz_list)

        # QtCore.QTimer.singleShot(0, self.refresh_list)

        self.refresh_list()

    # --------------------------------------------------
    def refresh_list(self):
        self.list.clear()

        for s in self.batch.Group:
            if not s.TypeId.startswith("App::FeaturePython"):
                continue

            try:
                data = json.loads(s.DataJSON or "{}")

                json_str = json.dumps(data, separators=(",", ":"))
            except Exception:
                json_str = "<invalid json>"

            text = f"{s.Title} (ID: {s.Id}) | {json_str}"
            it = QtWidgets.QListWidgetItem(text)
            it.setData(QtCore.Qt.UserRole, s.Name)
            if not getattr(s, "Active", True):
                it.setForeground(QtGui.QBrush(QtGui.QColor("gray")))
            self.list.addItem(it)

    # --------------------------------------------------
    # Step handling
    # --------------------------------------------------
    def _add_step(self):
        step = create_step_object(self.batch)
        dlg = StepEditDialog(self)

        if dlg.exec_():
            values = dlg.values()

            data = {
                "plan": values[2],
                "move": values[3],
                "move1": values[4],
                "move2": values[5],
                "angle": values[6],
                "rf": values[7],
                "rt": values[8],
                "rs": values[9],
                "rotAxis": values[10],
                "rotAngle": values[11],
            }

            step.DataJSON = json.dumps(data, indent=2)
            step.Id = values[0]
            step.Active = values[1]
        else:
            # Cancel → ta bort steget
            self.batch.removeObject(step)
            step.Document.removeObject(step.Name)

        self.batch.Document.recompute()
        self.refresh_list()

    def _open_step_dialog(self, item):
        name = item.data(QtCore.Qt.UserRole)
        step = self.batch.Document.getObject(name)

        dlg = StepEditDialog(self)

        try:
            data = json.loads(step.DataJSON or "{}")
        except Exception:
            data = {}

        dlg.editID.setText(step.Id or "")
        dlg.chkActive.setChecked(step.Active)

        dlg.plan.setCurrentText(data.get("plan", "XY"))
        dlg.move.setCurrentText(data.get("move", "none"))
        dlg.move1.setCurrentText(data.get("move1", "none"))
        dlg.move2.setCurrentText(data.get("move2", "none"))
        dlg.angle.setValue(int(data.get("angle", 4)))
        dlg.rf.setValue(float(data.get("rf", 0)))
        dlg.rt.setValue(float(data.get("rt", 0.4)))
        dlg.rs.setValue(int(data.get("rs", 4)))
        dlg.rotAxis.setCurrentText(data.get("rotAxis", "X"))
        dlg.rotAngle.setValue(float(data.get("rotAngle", 0.0)))

        if dlg.exec_():
            values = dlg.values()
            step.DataJSON = json.dumps(
                {
                    "plan": values[2],
                    "move": values[3],
                    "move1": values[4],
                    "move2": values[5],
                    "angle": values[6],
                    "rf": values[7],
                    "rt": values[8],
                    "rs": values[9],
                    "rotAxis": values[10],
                    "rotAngle": values[11],
                },
                indent=2,
            )

            step.Id = values[0]
            step.Active = values[1]

        self.refresh_list()

    # --------------------------------------------------
    def _delete_selected_step(self):
        items = self.list.selectedItems()
        if not items:
            return

        doc = self.batch.Document
        doc.openTransaction("Delete Step")

        for item in items:
            name = item.data(QtCore.Qt.UserRole)
            obj = doc.getObject(name)
            if obj:
                self.batch.removeObject(obj)
                doc.removeObject(obj.Name)

        doc.commitTransaction()
        doc.recompute()
        self.refresh_list()

    # --------------------------------------------------
    def _run(self):
        self._cancel = False
        run_steps_for_batch(
            self.batch,
            self.prog,
            self.lbl,
            lambda: QtWidgets.QApplication.processEvents(),
            lambda: self._cancel,
        )

    def _stop(self):
        self._cancel = True

    # --------------------------------------------------
    def _open_xyz_list(self):
        try:
            # OBA_ShowScanXYZList(parent=self)
            OBA_ShowScanXYZList()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "XYZ list", str(e))

    def _open_heatmap(self):
        ShowHeatmapViewer()


# --------------------------------------------------
# Utilities
# --------------------------------------------------
def create_step_object(parent_group):
    doc = parent_group.Document
    step = doc.addObject("App::FeaturePython", "Step")

    step.addProperty("App::PropertyString", "Title")
    step.addProperty("App::PropertyString", "Id")
    step.addProperty("App::PropertyString", "DataJSON")
    step.addProperty("App::PropertyBool", "Active")

    step.Title = "Step"
    step.Id = datetime.datetime.now().strftime("ST_%Y%m%d_%H%M%S")
    step.Active = True

    step.DataJSON = json.dumps({}, indent=2)
    parent_group.addObject(step)
    return step


def ShowBatchGroupPanel(batch_obj):
    mw = Gui.getMainWindow()
    old = mw.findChild(QtWidgets.QDockWidget, DOCK_NAME)
    if old:
        mw.removeDockWidget(old)
        old.deleteLater()

    dock = BatchGroupDock(mw, batch_obj)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.show()
    return dock


def OBA_ShowBatchDialog():
    doc = App.ActiveDocument or App.newDocument()
    obj = create_batchgroup(doc)
    ShowBatchGroupPanel(obj)
