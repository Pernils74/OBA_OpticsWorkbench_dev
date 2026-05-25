# -*- coding: utf-8 -*-
# oba_bounce_range_controller.py

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore, QtGui

from .oba_ray_core import OBARayManager


# ============================================================
# RANGE SLIDER (PURE PySide)
# ============================================================


class OBARangeSlider(QtWidgets.QWidget):
    """
    Dubbel slider (min/max) med magnet-funktion.
    Ingen extern dependency, ren PySide.
    """

    valueChanged = QtCore.Signal(int, int)
    HANDLE_RADIUS = 6

    def __init__(self, minimum=0, maximum=100, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(24)

        self._min = minimum
        self._max = maximum
        self._low = minimum
        self._high = maximum

        self._dragging = None  # "low" / "high"
        self.magnet_enabled = False

        self._last_low = self._low
        self._last_high = self._high

    # ----------------------------
    # API
    # ----------------------------

    def setRange(self, minimum, maximum):
        self._min = minimum
        self._max = maximum
        self._low = max(minimum, self._low)
        self._high = min(maximum, self._high)
        self.update()

    def setValue(self, low, high):
        self._low = max(self._min, min(low, self._max))
        self._high = max(self._low, min(high, self._max))
        self._emit()
        self.update()

    def value(self):
        return self._low, self._high

    # ----------------------------
    # Paint
    # ----------------------------

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        cy = h // 2

        def x_for(v):
            return int((v - self._min) / max(1, (self._max - self._min)) * (w - 2 * self.HANDLE_RADIUS)) + self.HANDLE_RADIUS

        x_low = x_for(self._low)
        x_high = x_for(self._high)

        # Track
        p.setPen(QtGui.QPen(QtGui.QColor("#888"), 2))
        p.drawLine(self.HANDLE_RADIUS, cy, w - self.HANDLE_RADIUS, cy)

        # Active range
        p.setPen(QtGui.QPen(QtGui.QColor("#2a82da"), 4))
        p.drawLine(x_low, cy, x_high, cy)

        # Handles
        p.setPen(QtGui.QPen(QtGui.QColor("#333"), 1))
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawEllipse(QtCore.QPoint(x_low, cy), self.HANDLE_RADIUS, self.HANDLE_RADIUS)
        p.drawEllipse(QtCore.QPoint(x_high, cy), self.HANDLE_RADIUS, self.HANDLE_RADIUS)

    # ----------------------------
    # Mouse handling
    # ----------------------------

    def mousePressEvent(self, ev):
        pos = ev.pos().x()
        low_x = self._value_to_x(self._low)
        high_x = self._value_to_x(self._high)
        self._dragging = "low" if abs(pos - low_x) < abs(pos - high_x) else "high"

    def mouseMoveEvent(self, ev):
        if not self._dragging:
            return

        val = self._x_to_value(ev.pos().x())

        if self.magnet_enabled:
            self._handle_magnet(val)
        else:
            if self._dragging == "low":
                self._low = min(val, self._high)
            else:
                self._high = max(val, self._low)

        self._emit()
        self.update()

    def mouseReleaseEvent(self, ev):
        self._dragging = None
        self._last_low = self._low
        self._last_high = self._high

    # ----------------------------
    # Helpers
    # ----------------------------

    def _emit(self):
        self.valueChanged.emit(self._low, self._high)

    def _value_to_x(self, val):
        w = self.width()
        return int((val - self._min) / max(1, (self._max - self._min)) * (w - 2 * self.HANDLE_RADIUS)) + self.HANDLE_RADIUS

    def _x_to_value(self, x):
        w = self.width()
        r = (x - self.HANDLE_RADIUS) / max(1, (w - 2 * self.HANDLE_RADIUS))
        return int(self._min + r * (self._max - self._min))

    def _handle_magnet(self, new_val):
        if self._dragging == "low":
            delta = new_val - self._last_low
        else:
            delta = new_val - self._last_high

        new_low = self._last_low + delta
        new_high = self._last_high + delta

        if new_low < self._min or new_high > self._max:
            return

        self._low = new_low
        self._high = new_high


# ============================================================
# DIALOG
# ============================================================


class OBARayBounceRangeDialog(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setWindowTitle("Ray · Bounce Range")
        self.setMinimumWidth(460)

        self._ray_config, max_bounce = self._get_config_and_max_bounce()
        if not self._ray_config:
            QtWidgets.QMessageBox.warning(
                self,
                "No Ray Data",
                "No OBARayConfig or rays found in the document.",
            )
            self.close()
            return

        self._ensure_properties(self._ray_config)

        layout = QtWidgets.QVBoxLayout(self)

        # Label
        self.lbl = QtWidgets.QLabel()
        layout.addWidget(self.lbl)

        # Slider
        self.slider = OBARangeSlider(0, max_bounce)
        layout.addWidget(self.slider)

        # Checkboxes
        self.chk_magnet = QtWidgets.QCheckBox("Magnet (lock range)")
        self.chk_color = QtWidgets.QCheckBox("Color by bounce")
        self.chk_scene = QtWidgets.QCheckBox("Scene isolation")

        layout.addWidget(self.chk_magnet)
        layout.addWidget(self.chk_color)
        layout.addWidget(self.chk_scene)

        # Init values
        rc = self._ray_config
        low = rc.RayBounceMin
        high = max_bounce if rc.RayBounceMax == -1 else rc.RayBounceMax

        self.slider.setValue(low, high)
        self.chk_color.setChecked(rc.ColorByBounce)
        self.chk_scene.setChecked(rc.SceneIsolation)

        self.slider.valueChanged.connect(self._apply)
        self.chk_color.toggled.connect(self._apply)
        self.chk_scene.toggled.connect(self._apply)
        self.chk_magnet.toggled.connect(self._on_magnet)

        self._update_label(low, high)

    # ----------------------------
    # Apply
    # ----------------------------

    def _apply(self, *args):
        low, high = self.slider.value()
        self._update_label(low, high)

        rc = self._ray_config
        rc.RayBounceMin = low
        rc.RayBounceMax = high
        rc.ColorByBounce = self.chk_color.isChecked()
        rc.SceneIsolation = self.chk_scene.isChecked()

        rm = OBARayManager()
        rm.visualize(
            bounce_min=low,
            bounce_max=high,
            line_width=rc.RayLineWidth,
            color_by_bounce=rc.ColorByBounce,
            mode="final",
        )

    def _on_magnet(self, state):
        self.slider.magnet_enabled = state

    def _update_label(self, low, high):
        self.lbl.setText(f"Bounce range: {low} – {high}")

    # ----------------------------
    # Helpers
    # ----------------------------

    def _ensure_properties(self, obj):
        if not hasattr(obj, "ColorByBounce"):
            obj.addProperty(
                "App::PropertyBool",
                "ColorByBounce",
                "Visualization",
                "Color rays by bounce count",
            ).ColorByBounce = True

        if not hasattr(obj, "SceneIsolation"):
            obj.addProperty(
                "App::PropertyBool",
                "SceneIsolation",
                "Visualization",
                "Isolate optical objects",
            ).SceneIsolation = False

        if not hasattr(obj, "RayLineWidth"):
            obj.addProperty(
                "App::PropertyFloat",
                "RayLineWidth",
                "Visualization",
                "Ray line width",
            ).RayLineWidth = 2.0

    def _get_config_and_max_bounce(self):
        doc = App.ActiveDocument
        if not doc:
            return None, 0

        rc = doc.getObject("OBARayConfig")
        if not rc:
            return None, 0

        rm = OBARayManager()
        max_bounce = max(
            (r.bounce_count for r in rm.get_all_rays() if r.mode == "final"),
            default=0,
        )
        return rc, max_bounce


# ============================================================
# PUBLIC API
# ============================================================


def OBA_ShowRayBounceRange():
    """
    Öppna dialog för att styra bounce-range-visualisering.
    """
    dlg = OBARayBounceRangeDialog()
    dlg.show()
    Gui._oba_bounce_range = dlg
    return dlg
