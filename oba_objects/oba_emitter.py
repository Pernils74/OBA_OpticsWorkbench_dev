# oba_emitter.py

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets
from .oba_base import OBABaseDialog, OBAElementProxy, OBAViewProviderBase  # , runRaytracer


# ============================================================
#  O B J E K T -   E M I T T E R
# ============================================================


class OBAEmitter(OBAElementProxy):
    def __init__(self, obj, source_obj=None, sub_elements=None):
        super().__init__(obj)  # Viktigt: kör basens init för self.Object

        # Grund-properties (binders)
        if not hasattr(obj, "Binders"):
            obj.addProperty("App::PropertyLinkList", "Binders", "Optics")

        # Emitter-specifika properties
        if not hasattr(obj, "Lambertian"):
            obj.addProperty("App::PropertyBool", "Lambertian", "Emitter").Lambertian = True
        if not hasattr(obj, "SpreadAngle"):
            obj.addProperty("App::PropertyFloat", "SpreadAngle", "Emitter").SpreadAngle = 5.0

        if not hasattr(obj, "Power"):
            obj.addProperty("App::PropertyFloat", "Power", "Emitter", "Total emitted power (W)").Power = 100.0
        if not hasattr(obj, "Wavelength"):
            obj.addProperty("App::PropertyFloat", "Wavelength", "Emitter").Wavelength = 585.0

        if not hasattr(obj, "MaxRays"):
            obj.addProperty("App::PropertyInteger", "MaxRays", "Emitter").MaxRays = 100
        if not hasattr(obj, "MaxBounce"):
            obj.addProperty("App::PropertyInteger", "MaxBounce", "Emitter").MaxBounce = 10
        if not hasattr(obj, "MaxRayLength"):
            obj.addProperty("App::PropertyFloat", "MaxRayLength", "Emitter").MaxRayLength = 1000.0
        if not hasattr(obj, "FlipNormal"):
            obj.addProperty("App::PropertyBool", "FlipNormal", "NormalSettings", "Invert surface normal for optical computation").FlipNormal = False
        # if not hasattr(obj, "ShowSurfaceNormal"):
        #     obj.addProperty(
        #         "App::PropertyBool",
        #         "ShowSurfaceNormal",
        #         "NormalSettings",
        #         "Show surface normal preview",
        #     ).ShowSurfaceNormal = False

        if not hasattr(obj, "PreviewRayLength"):
            obj.addProperty("App::PropertyFloat", "PreviewRayLength", "Emitter").PreviewRayLength = 2.0
        if not hasattr(obj, "OpticalType"):
            obj.addProperty("App::PropertyString", "OpticalType", "Base").OpticalType = "Emitter"

        if source_obj:
            self.add_binders(obj, source_obj, sub_elements)

    # ℹ️ Måste finnas för att kunna reopen utan felmedellande
    def onDocumentRestored(self, obj):
        """Återställer både Proxy och ViewProvider vid laddning"""
        obj.Proxy = self
        self.Object = obj
        App.Console.PrintMessage(f"Restoring {obj.Label}\n")

        # 2. Återställ ViewProvidern
        if App.GuiUp and obj.ViewObject:
            # Om proxyn saknas helt, skapa en ny
            if not hasattr(obj.ViewObject, "Proxy") or obj.ViewObject.Proxy is None:
                # Skapa ny ViewProvider
                vp = EmitterViewProvider(obj.ViewObject)
                # VIKTIGT: Eftersom __init__ kördes nu, sattes dialog_class korrekt
            else:
                # Om proxyn fanns kvar men var "död", kör dess restore
                obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)
                # SÄKERSTÄLL att dialog_class finns (eftersom den inte sparas i filen)
                obj.ViewObject.Proxy.dialog_class = EmitterDialog

            obj.ViewObject.update()


# ============================================================
#  D I A L O G
# ============================================================


class EmitterDialog(OBABaseDialog):
    ALLOW_SURFACE_SELECTION = True  # ℹ️ För att visa face select listan
    ALLOW_NORMAL_FLIPPING = True

    def __init__(self, obj):
        super().__init__(obj, title="Emitter Settings")

        self._add_check("Lambertian", "Lambertian")

        self._add_check("Flip normal", "FlipNormal")

        # self._add_check("Show normal", "ShowSurfaceNormal")

        self._add_spin("Spread angle (deg)", "SpreadAngle", 0.0, 180.0)

        self._add_spin("Power (W)", "Power", 0.0, 1e9)

        self._add_spin("Wavelength (nm)", "Wavelength", 350, 780)

        self._add_int("Max rays", "MaxRays", 1, 1_000_000)

        self._add_int("Max bounce", "MaxBounce", 0, 10_000)

        self._add_spin("Max ray length", "MaxRayLength", 0.1, 1e9)

        self._add_spin("Preview ray length", "PreviewRayLength", 0.1, 1e9)

    # ----------------------------------------------------------
    #  U P P D A T E R I N G   A V   P R O P S
    # ----------------------------------------------------------

    def _add_spin(self, label, prop, mn, mx):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))

        w = QtWidgets.QDoubleSpinBox()
        w.setRange(mn, mx)
        w.setValue(getattr(self.obj, prop))
        w.valueChanged.connect(lambda v, p=prop: setattr(self.obj, p, v))

        row.addWidget(w)
        self.custom_layout.addLayout(row)

    def _add_int(self, label, prop, mn, mx):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))

        w = QtWidgets.QSpinBox()
        w.setRange(mn, mx)
        w.setValue(getattr(self.obj, prop))
        w.valueChanged.connect(lambda v, p=prop: setattr(self.obj, p, v))

        row.addWidget(w)
        self.custom_layout.addLayout(row)

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


class EmitterViewProvider(OBAViewProviderBase):
    # ICON = "oba_emitter.svg"

    def __init__(self, vobj):
        super().__init__(vobj)
        # Denna variabel sparas INTE i .FCStd, därför måste den sättas om vid restore
        self.dialog_class = EmitterDialog


# ============================================================
#  S K A P A   E M I T T E R
# ============================================================


def OBA_CreateEmitter(show_dialog=True):
    doc = App.ActiveDocument or App.newDocument()
    sel_ex = Gui.Selection.getSelectionEx()

    # Skapa objektet
    emitter_obj = doc.addObject("App::DocumentObjectGroupPython", "Emitter")

    # Proxy
    if sel_ex:
        OBAEmitter(emitter_obj, sel_ex[0].Object, sel_ex[0].SubElementNames)
    else:
        OBAEmitter(emitter_obj)

    # ViewProvider
    if App.GuiUp:
        EmitterViewProvider(emitter_obj.ViewObject)

    doc.recompute()

    # Visa dialogen direkt
    if show_dialog:
        EmitterDialog(emitter_obj).show()

    return emitter_obj


# ============================================================
#  K O M M A N D O
# ============================================================


# class _CmdEmitter:
#     def GetResources(self):
#         return {"MenuText": "Create Emitter"}

#     def Activated(self):
#         OBA_CreateEmitter()


# if "OBA_CreateEmitter" not in Gui.listCommands():
#     Gui.addCommand("OBA_CreateEmitter", _CmdEmitter())
