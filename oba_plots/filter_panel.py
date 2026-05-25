# -*- coding: utf-8 -*-
# power_density_filter_panel.py

from PySide import QtWidgets, QtCore
from oba_rayengine.oba_ray_core import OBARayManager


class ClusterHitFilterPanel(QtWidgets.QWidget):
    """
    Stabil, debounce-säker filterpanel för ray hits.
    """

    filter_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._mapping = {}
        self._mode = "final"

        # 🔥 skydd mot rekursion
        self._updating = False

        # 🔥 debounce timer
        self._debounce_timer = QtCore.QTimer()
        self._debounce_timer.setInterval(50)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self.filter_changed.emit)

        self._build_ui()

    # -------------------------------------------------
    # UI
    # -------------------------------------------------
    def _build_ui(self):
        layout = QtWidgets.QHBoxLayout(self)

        # Emitters
        emitterBox = QtWidgets.QVBoxLayout()
        emitterBox.addWidget(QtWidgets.QLabel("<b>Emitters</b>"))
        self.emitter_list = QtWidgets.QListWidget()
        emitterBox.addWidget(self.emitter_list)

        # Objects
        objectBox = QtWidgets.QVBoxLayout()
        objectBox.addWidget(QtWidgets.QLabel("<b>Objects</b>"))
        self.object_list = QtWidgets.QListWidget()
        objectBox.addWidget(self.object_list)

        layout.addLayout(emitterBox)
        layout.addLayout(objectBox)

        # Signals (SAFE)
        self.emitter_list.itemChanged.connect(self._on_emitter_changed)
        self.object_list.itemChanged.connect(self._on_object_changed)

    # -------------------------------------------------
    # Public API
    # -------------------------------------------------
    def set_mode(self, mode):
        mode = mode or "final"

        # 🔥 undvik onödig rebuild
        if mode == self._mode and self.emitter_list.count() > 0:
            return

        self._mode = mode
        self._populate()

    def get_filter_spec(self):
        # emitters = tuple(self.emitter_list.item(i).text() for i in range(self.emitter_list.count()) if self.emitter_list.item(i).checkState() == QtCore.Qt.Checked)
        # objects = tuple(self.object_list.item(i).text() for i in range(self.object_list.count()) if self.object_list.item(i).checkState() == QtCore.Qt.Checked)

        emitters = tuple(self.emitter_list.item(i).data(QtCore.Qt.UserRole) for i in range(self.emitter_list.count()) if self.emitter_list.item(i).checkState() == QtCore.Qt.Checked)
        objects = tuple(self.object_list.item(i).data(QtCore.Qt.UserRole) for i in range(self.object_list.count()) if self.object_list.item(i).checkState() == QtCore.Qt.Checked)

        return {
            "emitters": emitters,
            "objects": objects,
        }

    # -------------------------------------------------
    # Internals
    # -------------------------------------------------
    def _populate(self):
        self._updating = True

        self._mapping = OBARayManager().get_hit_mapping(mode=self._mode)

        emitters = sorted(self._mapping.keys())
        objects = sorted({o for objs in self._mapping.values() for o in objs})

        self.emitter_list.blockSignals(True)
        self.object_list.blockSignals(True)

        self.emitter_list.clear()
        self.object_list.clear()

        for e in emitters:
            self._add_item(self.emitter_list, e)

        for o in objects:
            self._add_item(self.object_list, o)

        self.emitter_list.blockSignals(False)
        self.object_list.blockSignals(False)

        self._update_object_states()

        self._updating = False

        # 🔥 trigga EN redraw efter populate
        self._debounce_timer.start()

    def _add_item(self, listw, name):
        import FreeCAD as App

        doc = App.ActiveDocument
        obj = doc.getObject(name)

        label = obj.Label if obj else name
        item = QtWidgets.QListWidgetItem(label)
        # ✅ lagra original Name
        item.setData(QtCore.Qt.UserRole, name)

        item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable)
        item.setCheckState(QtCore.Qt.Checked)

        listw.addItem(item)

    def _add_item_old(self, listw, text):
        item = QtWidgets.QListWidgetItem(text)
        item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable)
        item.setCheckState(QtCore.Qt.Checked)
        listw.addItem(item)

    # -------------------------------------------------
    # SIGNAL HANDLERS
    # -------------------------------------------------
    def _on_emitter_changed(self, _item):
        if self._updating:
            return

        self._update_object_states()
        self._debounce_timer.start()

    def _on_object_changed(self, _item):
        if self._updating:
            return

        self._debounce_timer.start()

    # -------------------------------------------------
    def _update_object_states(self):
        self._updating = True
        # selected_emitters = {self.emitter_list.item(i).text() for i in range(self.emitter_list.count()) if self.emitter_list.item(i).checkState() == QtCore.Qt.Checked}
        selected_emitters = {self.emitter_list.item(i).data(QtCore.Qt.UserRole) for i in range(self.emitter_list.count()) if self.emitter_list.item(i).checkState() == QtCore.Qt.Checked}

        valid_objects = set()
        for e in selected_emitters:
            valid_objects |= self._mapping.get(e, set())

        for i in range(self.object_list.count()):
            item = self.object_list.item(i)
            # obj = item.text()
            obj = item.data(QtCore.Qt.UserRole)

            if obj in valid_objects:
                item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable)
            else:
                item.setFlags(QtCore.Qt.NoItemFlags)

        self._updating = False
