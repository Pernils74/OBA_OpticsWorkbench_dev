import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from .oba_base import OBABaseDialog, OBAElementProxy, OBAViewProviderBase

# ============================================================
#  O B J E K T  –  M I R R O R   B U I L D E R
# ============================================================


class OBAMirrorBuilder(OBAElementProxy):

    def __init__(self, obj):
        super().__init__(obj)

        # ---------- GEOMETRY ----------
        if not hasattr(obj, "Diameter"):
            obj.addProperty("App::PropertyFloat", "Diameter", "Mirror").Diameter = 50.0

        if not hasattr(obj, "Thickness"):
            obj.addProperty("App::PropertyFloat", "Thickness", "Mirror").Thickness = 5.0

        if not hasattr(obj, "Radius"):
            obj.addProperty("App::PropertyFloat", "Radius", "Mirror").Radius = 200.0

        if not hasattr(obj, "UseCurvature"):
            obj.addProperty("App::PropertyBool", "UseCurvature", "Mirror").UseCurvature = True

        if not hasattr(obj, "DShape"):
            obj.addProperty("App::PropertyBool", "DShape", "Mirror").DShape = False

        # ---------- OPTICS ----------
        if not hasattr(obj, "Reflectivity"):
            obj.addProperty("App::PropertyFloat", "Reflectivity", "Optics").Reflectivity = 1.0

        if not hasattr(obj, "UseFresnel"):
            obj.addProperty("App::PropertyBool", "UseFresnel", "Optics").UseFresnel = False

        if not hasattr(obj, "IsOptical"):
            obj.addProperty("App::PropertyBool", "IsOptical", "Base").IsOptical = True

        if not hasattr(obj, "OpticalType"):
            obj.addProperty("App::PropertyString", "OpticalType", "Base")
            obj.OpticalType = "MirrorBuilder"

        # ---------- SHAPE ----------
        body = App.ActiveDocument.addObject("Part::Feature", "MirrorShape")
        obj.addObject(body)
        self.body = body

        self.Object = obj
        self._init_done = True

        self.build_shape()

    # --------------------------------------------------------
    def build_shape(self):
        import Part
        import math

        obj = self.Object

        if not hasattr(self, "body"):
            return

        D = obj.Diameter
        T = obj.Thickness
        R = abs(obj.Radius)

        cyl = Part.makeCylinder(D / 2.0, T)

        if obj.UseCurvature:

            sagitta = R - math.sqrt(R * R - (D / 2.0) ** 2)

            sphere = Part.makeSphere(R)

            # sfärcentrum bakom frontytan
            sphere.translate(App.Vector(0, 0, T + (R - sagitta)))

            # if obj.Radius > 0:
            #     # konkav
            #     shape = cyl.cut(sphere)
            # else:
            #     # konvex
            #     shape = cyl.fuse(sphere)

            shape = cyl.cut(sphere)

        else:
            shape = cyl

        # ✅ D-shape
        if obj.DShape:
            box = Part.makeBox(D, D, T * 2)
            box.translate(App.Vector(0, -D / 2.0, -T))
            shape = shape.common(box)

        pl = self.body.Placement
        self.body.Shape = shape
        self.body.Placement = pl

        if App.GuiUp:
            v = self.body.ViewObject
            v.Transparency = 0
            v.ShapeColor = (0.8, 0.8, 0.85)

        self._rebuild_binders()

    # --------------------------------------------------------
    def _rebuild_binders(self):
        obj = self.Object

        if not hasattr(self.body, "Shape") or not self.body.Shape:
            return

        self.clear_binders(obj)

        faces = [f"Face{i+1}" for i in range(len(self.body.Shape.Faces))]
        self.add_binders(obj, self.body, faces)

    # --------------------------------------------------------
    def onChanged(self, obj, prop):
        if not getattr(self, "_init_done", False):
            return

        if prop in ("Diameter", "Thickness", "Radius", "UseCurvature", "DShape"):
            self.build_shape()


# ============================================================
#  G U I
# ============================================================


class MirrorBuilderDialog(OBABaseDialog):

    def __init__(self, obj):
        super().__init__(obj, title="Mirror Builder")

        self._add_spin("Diameter", obj, "Diameter", 1.0)
        self._add_spin("Thickness", obj, "Thickness", 1.0)
        self._add_spin("Radius", obj, "Radius", 10.0)

        chk = QtWidgets.QCheckBox("Use Curvature")
        chk.setChecked(obj.UseCurvature)
        chk.toggled.connect(lambda v: setattr(obj, "UseCurvature", v))
        self.custom_layout.addWidget(chk)

        chk_d = QtWidgets.QCheckBox("D-Shape")
        chk_d.setChecked(obj.DShape)
        chk_d.toggled.connect(lambda v: setattr(obj, "DShape", v))
        self.custom_layout.addWidget(chk_d)

        chk_f = QtWidgets.QCheckBox("Use Fresnel")
        chk_f.setChecked(obj.UseFresnel)
        chk_f.toggled.connect(lambda v: setattr(obj, "UseFresnel", v))
        self.custom_layout.addWidget(chk_f)

    def _add_spin(self, label, obj, prop, step):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))

        spin = QtWidgets.QDoubleSpinBox()
        spin.setValue(getattr(obj, prop))
        spin.valueChanged.connect(lambda v: setattr(obj, prop, v))

        spin.setRange(0.001, 1e6)
        spin.setDecimals(4)
        spin.setSingleStep(step)

        row.addWidget(spin)
        self.custom_layout.addLayout(row)


# ============================================================
#  V I E W
# ============================================================


class MirrorBuilderViewProvider(OBAViewProviderBase):
    def __init__(self, vobj):
        super().__init__(vobj)
        self.dialog_class = MirrorBuilderDialog


# ============================================================
#  C R E A T E
# ============================================================


def OBA_CreateMirrorBuilder(show_dialog=True):

    doc = App.ActiveDocument or App.newDocument()

    obj = doc.addObject("App::DocumentObjectGroupPython", "Mirror")

    OBAMirrorBuilder(obj)

    if App.GuiUp:
        MirrorBuilderViewProvider(obj.ViewObject)

    doc.recompute()

    if show_dialog:
        MirrorBuilderDialog(obj).show()

    return obj
