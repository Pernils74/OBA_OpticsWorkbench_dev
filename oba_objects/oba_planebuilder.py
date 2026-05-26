import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from .oba_base import OBABaseDialog, OBAViewProviderBase


class OBAPlaneBuilder:

    def __init__(self, obj):
        obj.Proxy = self
        self.Object = obj

        # ✅ parametrar
        if not hasattr(obj, "Width"):
            obj.addProperty("App::PropertyFloat", "Width", "Plane").Width = 20.0

        if not hasattr(obj, "Height"):
            obj.addProperty("App::PropertyFloat", "Height", "Plane").Height = 20.0

        if not hasattr(obj, "FlipNormal"):
            obj.addProperty("App::PropertyBool", "FlipNormal", "Plane").FlipNormal = False

        if not hasattr(obj, "OpticalType"):
            obj.addProperty("App::PropertyString", "OpticalType", "Base")
        obj.OpticalType = "Planebuilder"

        # ✅ skapa shape-holder
        body = App.ActiveDocument.addObject("Part::Feature", "PlaneShape")
        obj.addObject(body)

        self.body = body

        self._init_done = True
        self.build_shape()

    # --------------------------------------------------------

    def build_shape(self):
        import Part

        obj = self.Object

        if not hasattr(self, "body"):
            return
        if not hasattr(obj, "Width"):
            return
        if not hasattr(obj, "Height"):
            return

        # ✅ BEHÅLL placement
        pl = self.body.Placement

        w = obj.Width
        h = obj.Height

        p1 = App.Vector(-w / 2, -h / 2, 0)
        p2 = App.Vector(w / 2, -h / 2, 0)
        p3 = App.Vector(w / 2, h / 2, 0)
        p4 = App.Vector(-w / 2, h / 2, 0)

        wire = Part.makePolygon([p1, p2, p3, p4, p1])
        face = Part.Face(wire)

        self.body.Shape = face

        # ✅ ÅTERSTÄLL placement
        self.body.Placement = pl
        # --------------------------------------------------------

    def onChanged(self, obj, prop):
        if not getattr(self, "_init_done", False):
            return

        if prop in ("Width", "Height"):
            self.build_shape()

    # --------------------------------------------------------

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self.Object = obj

        if App.GuiUp and obj.ViewObject:
            if not hasattr(obj.ViewObject, "Proxy") or obj.ViewObject.Proxy is None:
                PlaneBuilderViewProvider(obj.ViewObject)
            else:
                obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)
                obj.ViewObject.Proxy.dialog_class = PlaneBuilderDialog

            obj.ViewObject.update()


class PlaneBuilderDialog(OBABaseDialog):
    ALLOW_SURFACE_SELECTION = False

    def __init__(self, obj):
        super().__init__(obj, title="Plane Geometry")

        # Flip normal
        row0 = QtWidgets.QHBoxLayout()

        self.chk_flip = QtWidgets.QCheckBox()
        self.chk_flip.setChecked(obj.FlipNormal)
        self.chk_flip.toggled.connect(lambda v: setattr(obj, "FlipNormal", v))

        row0.addWidget(QtWidgets.QLabel("Flip Normal:"))
        row0.addWidget(self.chk_flip)

        self.custom_layout.addLayout(row0)

        # Width
        row1 = QtWidgets.QHBoxLayout()
        self.spin_w = QtWidgets.QDoubleSpinBox()
        self.spin_w.setRange(0.1, 10000)
        self.spin_w.setValue(obj.Width)
        self.spin_w.valueChanged.connect(lambda v: setattr(obj, "Width", v))

        row1.addWidget(QtWidgets.QLabel("Width:"))
        row1.addWidget(self.spin_w)
        self.custom_layout.addLayout(row1)

        # Height
        row2 = QtWidgets.QHBoxLayout()
        self.spin_h = QtWidgets.QDoubleSpinBox()
        self.spin_h.setRange(0.1, 10000)
        self.spin_h.setValue(obj.Height)
        self.spin_h.valueChanged.connect(lambda v: setattr(obj, "Height", v))

        row2.addWidget(QtWidgets.QLabel("Height:"))
        row2.addWidget(self.spin_h)
        self.custom_layout.addLayout(row2)


class PlaneBuilderViewProvider(OBAViewProviderBase):

    def __init__(self, vobj):
        super().__init__(vobj)
        self.dialog_class = PlaneBuilderDialog


def OBA_CreatePlaneBuilder(show_dialog=True):

    doc = App.ActiveDocument or App.newDocument()

    obj = doc.addObject("App::DocumentObjectGroupPython", "PlaneBuilder")

    OBAPlaneBuilder(obj)

    if App.GuiUp:
        PlaneBuilderViewProvider(obj.ViewObject)

    doc.recompute()

    if show_dialog:
        PlaneBuilderDialog(obj).show()

    return obj
