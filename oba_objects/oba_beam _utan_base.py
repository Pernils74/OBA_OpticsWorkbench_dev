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


class OBABeam:
    """FeaturePython proxy för en punkt‑emitter."""

    def __init__(self, obj):
        obj.Proxy = self
        self.Object = obj
        obj.addProperty("App::PropertyBool", "Lambertian", "Beam").Lambertian = False
        obj.addProperty("App::PropertyFloat", "SpreadAngle", "Beam").SpreadAngle = 20.0
        obj.addProperty("App::PropertyInteger", "MaxRays", "Beam").MaxRays = 10
        obj.addProperty("App::PropertyInteger", "MaxBounce", "Beam").MaxBounce = 10
        obj.addProperty("App::PropertyFloat", "MaxRayLength", "Beam").MaxRayLength = 1000.0

        obj.addProperty("App::PropertyFloat", "Power", "Beam").Power = 100.0
        obj.addProperty("App::PropertyFloat", "Wavelength", "Beam").Wavelength = 585.0
        obj.addProperty("App::PropertyFloat", "PreviewLength", "Beam").PreviewLength = 3.0
        obj.addProperty("App::PropertyFloat", "RayLineWidth", "Beam").RayLineWidth = 0.5

        obj.addProperty("App::PropertyString", "OpticalType", "Base")
        obj.OpticalType = "Beam"

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self.Object = obj
        if App.GuiUp and obj.ViewObject:
            BeamViewProvider(obj.ViewObject)

    def execute(self, obj):
        # Kör inte preview om RayCollector finns
        if App.ActiveDocument.getObject("OBARayCollector"):
            return
        self.run_beam_preview(obj)

    def run_beam_preview(self, obj):
        from raytracer.oba_ray_collector import trace_beam
        from raytracer.oba_ray import OBARayManager

        rm = OBARayManager()

        # 🔥 rensa endast preview för denna beam
        rm.clear(emitter_id=obj.Name, mode="preview")

        trace_beam(beam=obj, engine=[], max_bounce=1, max_length=obj.PreviewLength, trace_mode="Mesh", mode="preview")

        rm.visualize(line_width=obj.RayLineWidth, mode="preview")

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class BeamRealtimeObserver:
    """
    Triggar ray tracing i realtid vid gizmo-drag (Placement-ändringar).
    Faller tillbaka till lokal preview om RayCollector saknas.
    """

    def __init__(self):
        self.enabled = True

    def slotChangedObject(self, obj, prop):
        if not self.enabled:
            return

        # ✅ Begränsa till sånt som faktiskt påverkar optiken
        # Lägg till de egenskaper som faktiskt kräver ny tracing
        if prop not in [
            "Placement",
            "Lambertian",
            "SpreadAngle",
            "MaxRays",
            "MaxBounce",
            "MaxRayLength",
            "Power",
            "Wavelength",
            "PreviewLength",
            "RayLineWidth",
        ]:
            return

        # Bara Beam
        if not hasattr(obj, "OpticalType") or obj.OpticalType != "Beam":
            return

        doc = obj.Document
        if not doc:
            return

        engine = doc.getObject("OBARayCollector")

        # --------------------------------------------------
        # Fall A: RayCollector finns → trigga tracing
        # --------------------------------------------------
        if engine:
            if getattr(engine.Proxy, "_in_compute", False):
                return
            engine.Proxy.trigger_recompute()
            return

        # --------------------------------------------------
        # Fall B: Ingen RayCollector → kör lokal preview
        # --------------------------------------------------
        # ✅ DELEGATION (inte egen preview-logik här)
        try:
            obj.Proxy.run_beam_preview(obj)
        except Exception:
            pass

    def slotDeletedObject(self, obj):
        if not self.enabled:
            return
        if not hasattr(obj, "OpticalType") or obj.OpticalType != "Beam":
            return
        doc = App.ActiveDocument
        if not doc:
            return
        # 1. Rensa preview‑rays för just denna beam
        try:
            from raytracer.oba_ray import OBARayManager

            OBARayManager().clear(emitter_id=obj.Name)
        except Exception:
            pass
        # 2. Trigga ray tracing (för övriga objekt)
        engine = doc.getObject("OBARayCollector")
        if not engine:
            return
        if getattr(engine.Proxy, "_in_compute", False):
            return
        App.Console.PrintMessage(f"[BeamObserver] {obj.Name} deleted → retracing\n")
        engine.Proxy.trigger_recompute()


# ============================================================
#  V I E W  P R O V I D E R  (ANVÄNDER INTE BASE)
# ============================================================


class BeamViewProvider:
    """ViewProvider för Beam: ikon, dubbelklick, drag, preview."""

    def __init__(self, vobj):
        vobj.Proxy = self
        self.Object = vobj.Object

        self._updating = False
        self._last_placement = None

    # ---------- Tree icon ----------
    def getIcon(self):
        obj = self.Object
        if hasattr(obj, "OpticalType"):
            icon = "oba_" + obj.OpticalType.lower() + ".svg"
            icon_path = os.path.join(BASE_PATH, "..", "icons", icon)
            if os.path.exists(icon_path):
                return icon_path
        return ""

    # ---------- Double click ----------
    def doubleClicked(self, vobj):
        dlg = BeamDialog(vobj.Object)
        dlg.show()
        return True

    def onDocumentRestored(self, vobj):
        vobj.Proxy = self
        self.Object = vobj.Object

    # ---------- Live behaviour ----------

    def onChanged(self, vobj, prop):
        if prop == "Placement":
            # commit-event efter drag
            engine = App.ActiveDocument.getObject("OBARayCollector")
            if engine and not getattr(engine.Proxy, "_in_compute", False):
                engine.Proxy.trigger_recompute()

    def __getstate__(self):
        """Hindra FreeCAD från att försöka serialisera proxyn"""
        return None

    def __setstate__(self, state):
        """Kallas när dokument laddas"""
        return None


# ============================================================
#  D I A L O G
# ============================================================


class BeamDialog(QtWidgets.QDialog):
    def __init__(self, obj, title="Beam settings", parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.obj = obj

        self.setWindowTitle(title)
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        self.layout = QtWidgets.QVBoxLayout(self)
        self.custom_layout = QtWidgets.QVBoxLayout()
        self.layout.addLayout(self.custom_layout)

        # Direction
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

        self._add_spin("Spread angle", "SpreadAngle", 0, 180)
        self._add_int("Max rays", "MaxRays", 1, 10_000_000)
        self._add_int("Max bounce", "MaxBounce", 0, 10000)
        self._add_spin("Max ray length", "MaxRayLength", 0.1, 1e9)

        self._add_spin("Power (W)", "Power", 0.0, 1e9)
        self._add_spin("Wavelength (nm)", "Wavelength", 350, 780)
        self._add_spin("RayLineWidth", "RayLineWidth", 0.5, 10)

        btn = QtWidgets.QPushButton("Klar")
        btn.clicked.connect(self.accept)
        self.layout.addWidget(btn)

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


# class _CmdBeam:
#     def GetResources(self):
#         return {"MenuText": "Create Beam"}

#     def Activated(self):
#         OBA_CreateBeam()


# ------------------------------------------------------------
# Registrera Beam realtime observer
# ------------------------------------------------------------

if hasattr(App, "_BeamRealtimeObserver"):
    App.removeDocumentObserver(App._BeamRealtimeObserver)

App._BeamRealtimeObserver = BeamRealtimeObserver()
App.addDocumentObserver(App._BeamRealtimeObserver)


# if "OBA_CreateBeam" not in Gui.listCommands():
#     Gui.addCommand("OBA_CreateBeam", _CmdBeam())
