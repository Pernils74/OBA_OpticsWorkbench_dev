# oba_beam.py
import os
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore
import Part

BASE_PATH = os.path.dirname(__file__)


# ============================================================
#  O B J E K T  –  B E A M
# ============================================================


from .oba_base import OBAElementProxy, OBABaseDialog, OBAViewProviderBase


class OBABeam(OBAElementProxy):
    """
    FeaturePython proxy för Beam (emitter)
    """

    def __init__(self, obj):
        super().__init__(obj)

        self._ensure_prop(obj, "App::PropertyBool", "Lambertian", "Beam", False)
        self._ensure_prop(obj, "App::PropertyFloat", "SpreadAngle", "Beam", 20.0)
        self._ensure_prop(obj, "App::PropertyInteger", "MaxRays", "Beam", 10)
        self._ensure_prop(obj, "App::PropertyInteger", "MaxBounce", "Beam", 10)
        self._ensure_prop(obj, "App::PropertyFloat", "MaxRayLength", "Beam", 1000.0)

        self._ensure_prop(obj, "App::PropertyFloat", "Power", "Beam", 100.0)
        self._ensure_prop(obj, "App::PropertyFloat", "Wavelength", "Beam", 585.0)
        self._ensure_prop(obj, "App::PropertyFloat", "PreviewLength", "Beam", 3.0)
        self._ensure_prop(obj, "App::PropertyFloat", "RayLineWidth", "Beam", 2.5)

        self._ensure_prop(obj, "App::PropertyFloat", "PreviewRayLength", "Beam", 2.0)

        if not hasattr(obj, "OpticalType"):
            obj.addProperty("App::PropertyString", "OpticalType", "Base")
        obj.OpticalType = "Beam"

    # hjälpfunktion (kan ligga i base)
    def _ensure_prop(self, obj, ptype, name, group, default):
        if hasattr(obj, name):
            return
        obj.addProperty(ptype, name, group)
        setattr(obj, name, default)

    # ℹ️ Måste finnas för att kunna reopen utan felmedellande
    def onDocumentRestored(self, obj):
        # 1. Återställ App-proxyn
        obj.Proxy = self
        self.Object = obj
        App.Console.PrintMessage(f"Restoring {obj.Label}\n")

        # 2. Återställ ViewProvidern
        if App.GuiUp and obj.ViewObject:
            # Om proxyn saknas helt, skapa en ny
            if not hasattr(obj.ViewObject, "Proxy") or obj.ViewObject.Proxy is None:
                # Skapa ny ViewProvider
                vp = BeamViewProvider(obj.ViewObject)
                # VIKTIGT: Eftersom __init__ kördes nu, sattes dialog_class korrekt
            else:
                # Om proxyn fanns kvar men var "död", kör dess restore
                obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)
                # SÄKERSTÄLL att dialog_class finns (eftersom den inte sparas i filen)
                obj.ViewObject.Proxy.dialog_class = BeamDialog

            obj.ViewObject.update()


# ============================================================
#  V I E W  P R O V I D E R
# ============================================================


class BeamViewProvider(OBAViewProviderBase):
    # ICON = "oba_beam.svg"

    def __init__(self, vobj):
        super().__init__(vobj)
        self.dialog_class = BeamDialog


# ============================================================
#  D I A L O G
# ============================================================


class BeamDialog(OBABaseDialog):
    ALLOW_SURFACE_SELECTION = False  # Beam har inga binders

    def __init__(self, obj):
        super().__init__(obj, title="Beam Settings")

        # -------------------------------------------------
        # Direction
        # -------------------------------------------------
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Direction:"))

        self.dx = QtWidgets.QDoubleSpinBox()
        self.dy = QtWidgets.QDoubleSpinBox()
        self.dz = QtWidgets.QDoubleSpinBox()

        for w in (self.dx, self.dy, self.dz):
            w.setRange(-1e6, 1e6)
            row.addWidget(w)

        d = obj.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        self.dx.setValue(d.x)
        self.dy.setValue(d.y)
        self.dz.setValue(d.z)

        self.dx.valueChanged.connect(self._set_dir)
        self.dy.valueChanged.connect(self._set_dir)
        self.dz.valueChanged.connect(self._set_dir)

        self.custom_layout.addLayout(row)

        # -------------------------------------------------
        # Beam parameters
        # -------------------------------------------------
        self._add_check("Lambertian", "Lambertian")
        self._add_spin("Spread angle", "SpreadAngle", 0, 180)
        self._add_int("Max rays", "MaxRays", 1, 10_000_000)
        self._add_int("Max bounce", "MaxBounce", 0, 10_000)
        self._add_spin("Max ray length", "MaxRayLength", 0.1, 1e9)
        self._add_spin("Power (W)", "Power", 0.0, 1e9)
        self._add_spin("Wavelength (nm)", "Wavelength", 350, 780)
        self._add_spin("Ray line width", "RayLineWidth", 0.5, 10)
        self._add_spin("Preview ray length", "PreviewRayLength", 0.1, 1e9)

    def _add_spin(self, label, prop, mn, mx):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        w = QtWidgets.QDoubleSpinBox()
        w.setRange(mn, mx)
        w.setValue(getattr(self.obj, prop))
        w.valueChanged.connect(lambda v: setattr(self.obj, prop, v))
        row.addWidget(w)
        self.custom_layout.addLayout(row)

    def _add_int(self, label, prop, mn, mx):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        w = QtWidgets.QSpinBox()
        w.setRange(mn, mx)
        w.setValue(getattr(self.obj, prop))
        w.valueChanged.connect(lambda v: setattr(self.obj, prop, v))
        row.addWidget(w)
        self.custom_layout.addLayout(row)

    def _add_check(self, label, prop):
        row = QtWidgets.QHBoxLayout()

        w = QtWidgets.QCheckBox(label)
        w.setChecked(getattr(self.obj, prop))
        w.stateChanged.connect(lambda v, p=prop: setattr(self.obj, p, bool(v)))

        row.addWidget(w)
        self.custom_layout.addLayout(row)

    def _set_dir(self):
        v = App.Vector(self.dx.value(), self.dy.value(), self.dz.value())
        if v.Length == 0:
            return
        v.normalize()
        p = self.obj.Placement
        self.obj.Placement = App.Placement(p.Base, App.Rotation(App.Vector(0, 0, 1), v))


# ============================================================
#  S K A P A  B E A M
# ============================================================


def OBA_CreateBeam():
    doc = App.ActiveDocument or App.newDocument()
    beam = doc.addObject("Part::FeaturePython", "Beam")
    OBABeam(beam)
    if App.GuiUp:
        BeamViewProvider(beam.ViewObject)
    doc.recompute()
    BeamDialog(beam).show()
