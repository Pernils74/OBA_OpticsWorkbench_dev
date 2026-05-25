# oba_detector.py

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from .oba_base import OBABaseDialog, OBAElementProxy, OBAViewProviderBase

# ============================================================
#  O B J E K T  –  D E T E C T O R
# ============================================================


class OBADetector(OBAElementProxy):

    def __init__(self, obj, source_obj=None, sub_elements=None):
        super().__init__(obj)

        # --- Optical type ---

        if not hasattr(obj, "OpticalType"):
            obj.addProperty("App::PropertyString", "OpticalType", "Base", "Type of optical element")
        obj.OpticalType = "Detector"

        # --- Offset (detta är nyckeln) ---
        if not hasattr(obj, "Offset"):
            obj.addProperty("App::PropertyFloat", "Offset", "Detector", "Offset distance along normal").Offset = 0.004  # default

        # --- Optional: enable/disable ---
        if not hasattr(obj, "Enabled"):
            obj.addProperty("App::PropertyBool", "Enabled", "Detector", "Enable detection").Enabled = True

        if not hasattr(obj, "ShowSurfaceNormal"):
            obj.addProperty(
                "App::PropertyBool",
                "ShowSurfaceNormal",
                "NormalSettings",
                "Show surface normal preview",
            ).ShowSurfaceNormal = False

        if not hasattr(obj, "HitMode"):
            obj.addProperty("App::PropertyEnumeration", "HitMode", "Detector", "Detection direction")
            obj.HitMode = ["Front", "Back", "Both"]
            obj.HitMode = 0  # ✅ default = Both

        # if not hasattr(obj, "FlipNormal"):
        #     obj.addProperty("App::PropertyBool", "FlipNormal", "NormalSettings", "Invert surface normal for optical computation").FlipNormal = False

        # --- Bind geometry ---
        if source_obj:
            self.add_binders(obj, source_obj, sub_elements)

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self.Object = obj

        if App.GuiUp and obj.ViewObject:
            if not hasattr(obj.ViewObject, "Proxy") or obj.ViewObject.Proxy is None:
                DetectorViewProvider(obj.ViewObject)
            else:
                obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)
                obj.ViewObject.Proxy.dialog_class = DetectorDialog
            obj.ViewObject.update()

    def onChanged(self, obj, prop):
        super().onChanged(obj, prop)

        if prop == "Offset":
            self.update_offset()

    def update_offset(self):
        for b in self.Object.Binders:

            if not b.Support:
                continue

            src, sub = b.Support[0]

            shape = src.Shape

            if not sub:
                continue

            face = shape.getElement(sub[0])

            center = face.CenterOfMass
            u, v = face.Surface.parameter(center)
            normal = face.normalAt(u, v).normalize()

            offset_vec = normal * self.Object.Offset

            b.Placement.Base = offset_vec


# ============================================================
#  D I A L O G
# ============================================================


class DetectorDialog(OBABaseDialog):
    ALLOW_SURFACE_SELECTION = True

    def __init__(self, obj):
        super().__init__(obj, title="Detector Settings")

        # --- Offset ---
        row = QtWidgets.QHBoxLayout()
        self.spin_offset = QtWidgets.QDoubleSpinBox()
        self.spin_offset.setRange(0.0, 10.0)
        self.spin_offset.setDecimals(6)
        self.spin_offset.setSingleStep(0.001)
        self.spin_offset.setValue(self.obj.Offset)

        self.spin_offset.valueChanged.connect(self._update_offset)

        row.addWidget(QtWidgets.QLabel("Offset:"))
        row.addWidget(self.spin_offset)
        self.custom_layout.addLayout(row)

        self._add_check("Show normal", "ShowSurfaceNormal")
        # self._add_check("Flip normal", "FlipNormal")

        # --- Hit mode ---
        row = QtWidgets.QHBoxLayout()

        row.addWidget(QtWidgets.QLabel("Hit direction:"))

        self.cmb_hit = QtWidgets.QComboBox()
        self.cmb_hit.addItems(["Both", "Front", "Back"])
        self.cmb_hit.setCurrentText(getattr(self.obj, "HitMode", "Front"))

        self.cmb_hit.currentTextChanged.connect(self._update_hitmode)

        row.addWidget(self.cmb_hit)
        self.custom_layout.addLayout(row)

    def _update_offset(self, val):
        self.obj.Offset = val

    def _update_hitmode(self, val):
        self.obj.HitMode = val

    def _add_check(self, label, prop):
        row = QtWidgets.QHBoxLayout()

        w = QtWidgets.QCheckBox(label)
        w.setChecked(getattr(self.obj, prop))
        w.stateChanged.connect(lambda v, p=prop: setattr(self.obj, p, bool(v)))

        row.addWidget(w)
        self.custom_layout.addLayout(row)


# ============================================================
#  V I E W   P R O V I D E R
# ============================================================


class DetectorViewProvider(OBAViewProviderBase):

    def __init__(self, vobj):
        super().__init__(vobj)
        self.dialog_class = DetectorDialog


# ============================================================
#  F A C T O R Y
# ============================================================


def OBA_CreateDetector(show_dialog=True):
    doc = App.ActiveDocument or App.newDocument()
    sel_ex = Gui.Selection.getSelectionEx()

    detector_obj = doc.addObject("App::DocumentObjectGroupPython", "Detector")

    if sel_ex:
        OBADetector(detector_obj, sel_ex[0].Object, sel_ex[0].SubElementNames)
    else:
        OBADetector(detector_obj)

    if App.GuiUp:
        DetectorViewProvider(detector_obj.ViewObject)

    doc.recompute()

    if show_dialog:
        DetectorDialog(detector_obj).show()

    return detector_obj
