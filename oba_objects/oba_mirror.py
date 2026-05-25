# oba_mirror.py

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets
from .oba_base import OBABaseDialog, OBAElementProxy, OBAViewProviderBase, _trigger_ray_engine


# ============================================================
#  O B J E K T  –  M I R R O R
# ============================================================


class OBAMirror(OBAElementProxy):

    def __init__(self, obj, source_obj=None, sub_elements=None):
        # Initiera bas-props (Binders etc)
        # obj.Proxy = self
        super().__init__(obj)  # Viktigt: kör basens init för self.Object

        if not hasattr(obj, "Binders"):
            obj.addProperty("App::PropertyLinkList", "Binders", "Optics")

        # Spegel-specifikt
        if not hasattr(obj, "Reflectivity"):
            obj.addProperty("App::PropertyFloat", "Reflectivity", "Mirror").Reflectivity = 0.95

        # ✨ NYTT FÄLT för semitransparent spegel
        if not hasattr(obj, "Transmissivity"):
            obj.addProperty("App::PropertyFloat", "Transmissivity", "Mirror").Transmissivity = 0.0

        if not hasattr(obj, "OpticalType"):
            obj.addProperty("App::PropertyString", "OpticalType", "Base", "Type of optical element")
        obj.OpticalType = "Mirror"  # eller vad din sub‑klass ska sätta

        if source_obj:
            self.add_binders(obj, source_obj, sub_elements)

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
                vp = MirrorViewProvider(obj.ViewObject)
                # VIKTIGT: Eftersom __init__ kördes nu, sattes dialog_class korrekt
            else:
                # Om proxyn fanns kvar men var "död", kör dess restore
                obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)
                # SÄKERSTÄLL att dialog_class finns (eftersom den inte sparas i filen)
                obj.ViewObject.Proxy.dialog_class = MirrorDialog

            obj.ViewObject.update()


# ============================================================
#  D I A L O G
# ============================================================


class MirrorDialog(OBABaseDialog):
    ALLOW_SURFACE_SELECTION = True  # ℹ️ För att visa face select listan

    def __init__(self, obj):
        super().__init__(obj, title="Mirror Settings")

        # Specifika Mirror-props
        row = QtWidgets.QHBoxLayout()
        self.spin_ref = QtWidgets.QDoubleSpinBox()
        self.spin_ref.setRange(0, 1)
        self.spin_ref.setSingleStep(0.1)
        self.spin_ref.setValue(self.obj.Reflectivity)
        self.spin_ref.valueChanged.connect(self._update_ref)

        row.addWidget(QtWidgets.QLabel("Reflectivity:"))
        row.addWidget(self.spin_ref)
        self.custom_layout.addLayout(row)

        # Transmissivity UI
        row2 = QtWidgets.QHBoxLayout()
        self.spin_trans = QtWidgets.QDoubleSpinBox()
        self.spin_trans.setRange(0, 1)
        self.spin_trans.setSingleStep(0.1)
        self.spin_trans.setValue(self.obj.Transmissivity)
        self.spin_trans.valueChanged.connect(self._update_trans)

        row2.addWidget(QtWidgets.QLabel("Transmissivity:"))
        row2.addWidget(self.spin_trans)
        self.custom_layout.addLayout(row2)

    def _update_trans(self, val):
        self.obj.Transmissivity = val
        # self.touch()

    def _update_ref(self, val):
        self.obj.Reflectivity = val


# ============================================================
#  V I E W   P R O V I D E R
# ============================================================


class MirrorViewProvider(OBAViewProviderBase):
    # ICON = "oba_mirror.svg"
    # DIALOG = MirrorDialog

    def __init__(self, vobj):
        super().__init__(vobj)
        # Berätta för basen vilken dialog som ska öppnas vid dubbelklick
        self.dialog_class = MirrorDialog


def OBA_CreateMirror(show_dialog=True):
    doc = App.ActiveDocument or App.newDocument()
    sel_ex = Gui.Selection.getSelectionEx()

    # 1. Skapa objektet
    mirror_obj = doc.addObject("App::DocumentObjectGroupPython", "Mirror")

    # 2. Koppla Proxy (Python-logik)
    if sel_ex:
        OBAMirror(mirror_obj, sel_ex[0].Object, sel_ex[0].SubElementNames)
    else:
        OBAMirror(mirror_obj)

    # 3. Koppla ViewProvider (GUI-logik/Dubbelklick)
    if App.GuiUp:
        MirrorViewProvider(mirror_obj.ViewObject)

    doc.recompute()

    # 4. Visa dialogen direkt vid skapande om inte show_dialog = False

    if show_dialog:
        MirrorDialog(mirror_obj).show()
    # MirrorDialog(mirror_obj).show()

    return mirror_obj


# ============================================================
#  K O M M A N D O
# ============================================================


# class _CmdMirror:
#     def GetResources(self):
#         return {"MenuText": "Create Mirror"}

#     def Activated(self):
#         OBA_CreateMirror()


# if "OBA_CreateMirror" not in Gui.listCommands():
#     Gui.addCommand("OBA_CreateMirror", _CmdMirror())
