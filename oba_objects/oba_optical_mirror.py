import FreeCAD as App
from PySide import QtWidgets

from .oba_base import (
    OBABaseDialog,
    OBAElementProxy,
    OBAViewProviderBase,
    _trigger_ray_engine,
)
from .oba_mirror import OPTICAL_PROPERTIES

# OPTICAL_PROPERTIES = [
#     {
#         "type": "App::PropertyFloat",
#         "name": "Reflectivity",
#         "group": "Mirror",
#         "default": 1.0,
#     },
#     {
#         "type": "App::PropertyFloat",
#         "name": "Transmissivity",
#         "group": "Mirror",
#         "default": 0.0,
#     },
# ]


def ensure_initialized(obj):
    if "OpticalType" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "OpticalType", "Base")
    obj.OpticalType = "Mirror"


class OBAMirror(OBAElementProxy):
    """Mirror optical behaviour attached to OpticalObject."""

    def __init__(self, obj, source_obj=None, sub_elements=None):
        super().__init__(obj)
        obj.Proxy = self
        self.Object = obj

        for p in OPTICAL_PROPERTIES:
            name = p["name"]
            if name not in obj.PropertiesList:
                obj.addProperty(p["type"], name, p["group"])
                setattr(obj, name, p["default"])

        if "OpticalType" not in obj.PropertiesList:
            obj.addProperty("App::PropertyString", "OpticalType", "Base")
        obj.OpticalType = "Mirror"

        if "Binders" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLinkList", "Binders", "Optics")

        if source_obj:
            self.add_binders(obj, source_obj, sub_elements)

    def onChanged(self, obj, prop):
        if prop in ("Reflectivity", "Transmissivity"):
            try:
                _trigger_ray_engine("Mirror property changed", obj)
            except Exception:
                pass

    def execute(self, obj):
        pass

    def onDocumentRestored(self, obj):
        self.Object = obj
        obj.Proxy = self
        if App.GuiUp and obj.ViewObject:
            vp = getattr(obj.ViewObject, "Proxy", None)
            if vp:
                vp.dialog_class = MirrorDialog
            else:
                MirrorViewProvider(obj.ViewObject)


class MirrorDialog(OBABaseDialog):
    ALLOW_SURFACE_SELECTION = True

    def __init__(self, obj):
        super().__init__(obj, title="Mirror Settings")
        self.obj = obj

        self._add_float_property("Reflectivity")
        self._add_float_property("Transmissivity")

    def _add_float_property(self, name):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(name))

        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(0.0, 1.0)
        spin.setSingleStep(0.05)
        spin.setDecimals(4)
        spin.setValue(float(getattr(self.obj, name)))
        spin.valueChanged.connect(lambda value, prop=name: setattr(self.obj, prop, value))

        row.addWidget(spin)
        self.custom_layout.addLayout(row)


class MirrorViewProvider(OBAViewProviderBase):
    def __init__(self, vobj):
        super().__init__(vobj)
        self.dialog_class = MirrorDialog

    def onDocumentRestored(self, vobj):
        self.Object = vobj.Object
        self.dialog_class = MirrorDialog
