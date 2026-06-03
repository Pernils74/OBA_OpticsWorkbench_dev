# oba_absorber.py

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets
from .oba_base import OBABaseDialog, OBAElementProxy, OBAViewProviderBase  # , runRaytracer

# ============================================================
#  O B J E K T  –  A B S O R B E R
# ============================================================


OPTICAL_PROPERTIES = [
    {
        "name": "Absorption",
        "type": "App::PropertyFloat",
        "group": "Absorber",
        "default": 1.0,
        "doc": "Absorptionsgrad",
    }
]


class OBAAbsorber(OBAElementProxy):

    def __init__(self, obj, source_obj=None, sub_elements=None):
        # Initiera bas-props (Binders etc) via super()
        super().__init__(obj)

        # Absorber-specifik property
        for p in OPTICAL_PROPERTIES:
            if not hasattr(obj, p["name"]):
                obj.addProperty(p["type"], p["name"], p["group"], p.get("doc", ""))
                setattr(obj, p["name"], p["default"])

        # # Absorber-specifik property
        # if not hasattr(obj, "Absorption"):
        #     obj.addProperty("App::PropertyFloat", "Absorption", "Absorber", "Absorptionsgrad").Absorption = 1.00

        # OpticalType (styr ikon via basen)
        if not hasattr(obj, "OpticalType"):
            obj.addProperty("App::PropertyString", "OpticalType", "Base", "Type of optical element")
        obj.OpticalType = "Absorber"

        # Om den skapas från geometri i vyn
        if source_obj:
            self.add_binders(obj, source_obj, sub_elements)

    def onDocumentRestored(self, obj):
        """Återställer logik utan att skapa serialiseringsproblem"""
        obj.Proxy = self
        self.Object = obj
        App.Console.PrintMessage(f"Restoring {obj.Label}\n")

        # 2. Återställ ViewProvidern
        if App.GuiUp and obj.ViewObject:
            # Om proxyn saknas helt, skapa en ny
            if not hasattr(obj.ViewObject, "Proxy") or obj.ViewObject.Proxy is None:
                # Skapa ny ViewProvider
                vp = AbsorberViewProvider(obj.ViewObject)
                # VIKTIGT: Eftersom __init__ kördes nu, sattes dialog_class korrekt
            else:
                # Om proxyn fanns kvar men var "död", kör dess restore
                obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)
                # SÄKERSTÄLL att dialog_class finns (eftersom den inte sparas i filen)
                obj.ViewObject.Proxy.dialog_class = AbsorberDialog

            obj.ViewObject.update()


# ============================================================
#  D I A L O G
# ============================================================


class AbsorberDialog(OBABaseDialog):
    ALLOW_SURFACE_SELECTION = True  # ℹ️ För att visa face select listan

    def __init__(self, obj):
        super().__init__(obj, title="AbsorberSettings")

        # ------------ Absorptionsgrad ------------
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Absorption:"))

        self.spin_abs = QtWidgets.QDoubleSpinBox()
        self.spin_abs.setRange(0.00, 1.00)
        self.spin_abs.setSingleStep(0.05)
        self.spin_abs.setValue(self.obj.Absorption)
        self.spin_abs.valueChanged.connect(self._update_absorption)

        row.addWidget(self.spin_abs)
        self.custom_layout.addLayout(row)

    def _update_absorption(self, val):
        self.obj.Absorption = val

    # ----------------------------------------------------------


# ============================================================
#  V I E W   P R O V I D E R
# ============================================================


class AbsorberViewProvider(OBAViewProviderBase):
    # ICON = "oba_absorber.svg"

    def __init__(self, vobj):
        super().__init__(vobj)
        # Länken till dialog-klassen måste sättas om vid varje laddning
        self.dialog_class = AbsorberDialog


# ============================================================
#  S K A P A   A B S O R B E R
# ============================================================


def OBA_CreateAbsorber(show_dialog=True):
    doc = App.ActiveDocument or App.newDocument()
    sel_ex = Gui.Selection.getSelectionEx()

    # Skapa objekt
    absorber_obj = doc.addObject("App::DocumentObjectGroupPython", "Absorber")

    # Proxy
    if sel_ex:
        OBAAbsorber(absorber_obj, sel_ex[0].Object, sel_ex[0].SubElementNames)
    else:
        OBAAbsorber(absorber_obj)

    # ViewProvider
    if App.GuiUp:
        AbsorberViewProvider(absorber_obj.ViewObject)

    doc.recompute()

    # Visa dialog direkt
    if show_dialog:
        AbsorberDialog(absorber_obj).show()

    # AbsorberDialog(absorber_obj).show()

    return absorber_obj


# ============================================================
#  K O M M A N D O
# ============================================================


# class _CmdAbsorber:
#     def GetResources(self):
#         return {"MenuText": "Create Absorber"}

#     def Activated(self):
#         OBA_CreateAbsorber()


# if "OBA_CreateAbsorber" not in Gui.listCommands():
#     Gui.addCommand("OBA_CreateAbsorber", _CmdAbsorber())
