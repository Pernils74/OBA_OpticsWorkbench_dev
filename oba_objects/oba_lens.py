# oba_lense.py

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets
from .oba_base import OBABaseDialog, OBAElementProxy, OBAViewProviderBase
from .oba_lens_materials import MATERIAL_DATA, get_material_list

# ============================================================
#  O B J E K T –  L E N S E
# ============================================================


class OBALense(OBAElementProxy):

    def __init__(self, obj, source_obj=None, sub_elements=None):
        # Initiera bas-props (Binders etc) via super()
        super().__init__(obj)

        # Lins-specifik property

        if not hasattr(obj, "Material"):
            obj.addProperty("App::PropertyString", "Material", "Lense", "Lens material preset").Material = "Custom"

        if not hasattr(obj, "RefractiveIndex"):
            obj.addProperty("App::PropertyFloat", "RefractiveIndex", "Lense", "Brytningsindex").RefractiveIndex = 1.50

        if not hasattr(obj, "AbbeNumber"):
            obj.addProperty("App::PropertyFloat", "AbbeNumber (V_d)", "Lense", "Abbe number (chromatic dispersion)").AbbeNumber = 50.0

        if not hasattr(obj, "UseFresnel"):
            obj.addProperty("App::PropertyBool", "UseFresnel", "Lense", "Enable Fresnel reflection (ray splitting)").UseFresnel = False

        if not hasattr(obj, "FlipNormal"):
            obj.addProperty("App::PropertyBool", "FlipNormal", "NormalSettings", "Invert surface normal for optical computation").FlipNormal = False

        if not hasattr(obj, "ShowSurfaceNormal"):
            obj.addProperty(
                "App::PropertyBool",
                "ShowSurfaceNormal",
                "NormalSettings",
                "Show surface normal preview",
            ).ShowSurfaceNormal = False

        # OpticalType = Lense (styr ikon via basen)
        if not hasattr(obj, "OpticalType"):
            obj.addProperty("App::PropertyString", "OpticalType", "Base", "Type of optical element").OpticalType = "Lens"

        # Om den skapas från geometri i vyn
        if source_obj:
            self.add_binders(obj, source_obj, sub_elements)

    # ℹ️ Måste finnas för att kunna reopen utan felmedellande
    def onDocumentRestored(self, obj):
        """Återställer logik och GUI-koppling vid laddning"""
        obj.Proxy = self
        self.Object = obj
        App.Console.PrintMessage(f"Restoring {obj.Label}\n")

        # 2. Återställ ViewProvidern
        if App.GuiUp and obj.ViewObject:
            # Om proxyn saknas helt, skapa en ny
            if not hasattr(obj.ViewObject, "Proxy") or obj.ViewObject.Proxy is None:
                # Skapa ny ViewProvider
                vp = LenseViewProvider(obj.ViewObject)
                # VIKTIGT: Eftersom __init__ kördes nu, sattes dialog_class korrekt
            else:
                # Om proxyn fanns kvar men var "död", kör dess restore
                obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)
                # SÄKERSTÄLL att dialog_class finns (eftersom den inte sparas i filen)
                obj.ViewObject.Proxy.dialog_class = LenseDialog

            obj.ViewObject.update()


# ============================================================
#  D I A L O G
# ============================================================


class LenseDialog(OBABaseDialog):
    ALLOW_SURFACE_SELECTION = True  # ℹ️ För att visa face select listan

    def __init__(self, obj):
        super().__init__(obj, title="Lens Settings")

        #     # --- Flip normal (optisk) ---
        self.chk_flip = QtWidgets.QCheckBox("Flip surface normal")
        self.chk_flip.setChecked(getattr(obj, "FlipNormal", obj.FlipNormal))
        self.chk_flip.toggled.connect(self._on_flip_changed)
        self.layout.addWidget(self.chk_flip)

        # --- Show normal (visualisering) ---
        self.chk_show = QtWidgets.QCheckBox("Show surface normal")
        self.chk_show.setChecked(getattr(obj.ViewObject, "ShowNormal", obj.ShowSurfaceNormal))
        self.chk_show.toggled.connect(self._on_show_normal_changed)
        self.layout.addWidget(self.chk_show)

        # --- Material ---
        row_mat = QtWidgets.QHBoxLayout()
        row_mat.addWidget(QtWidgets.QLabel("Material:"))
        self.cmb_material = QtWidgets.QComboBox()
        self.cmb_material.addItems(get_material_list())

        current_mat = getattr(self.obj, "Material", "Custom")
        self.cmb_material.setCurrentText(current_mat)
        self.cmb_material.currentTextChanged.connect(self._update_material)
        row_mat.addWidget(self.cmb_material)
        self.custom_layout.addLayout(row_mat)

        # --- Refractive Index (n_d) ---
        row_index = QtWidgets.QHBoxLayout()
        row_index.addWidget(QtWidgets.QLabel("Refractive Index (n_d):"))
        self.spin_index = QtWidgets.QDoubleSpinBox()
        self.spin_index.setRange(1.0, 5.0)
        self.spin_index.setDecimals(4)
        self.spin_index.setValue(self.obj.RefractiveIndex)
        self.spin_index.valueChanged.connect(self._update_index)
        row_index.addWidget(self.spin_index)
        self.custom_layout.addLayout(row_index)

        # --- Abbe Number (För prisma/dispersion) ---
        row_abbe = QtWidgets.QHBoxLayout()
        row_abbe.addWidget(QtWidgets.QLabel("Abbe Number (V_d):"))
        self.spin_abbe = QtWidgets.QDoubleSpinBox()
        self.spin_abbe.setRange(0.0, 200.0)  # 0 = ingen dispersion
        self.spin_abbe.setValue(getattr(self.obj, "AbbeNumber", 50.0))
        self.spin_abbe.valueChanged.connect(self._update_abbe)
        row_abbe.addWidget(self.spin_abbe)
        self.custom_layout.addLayout(row_abbe)

        # --- Fresnel ---
        self.chk_fresnel = QtWidgets.QCheckBox("Enable Fresnel (Ray Splitting)")
        self.chk_fresnel.setChecked(getattr(self.obj, "UseFresnel", False))
        self.chk_fresnel.toggled.connect(self._update_fresnel)
        self.custom_layout.addWidget(self.chk_fresnel)

    def _on_flip_changed(self, checked):
        self.obj.FlipNormal = checked

    def _on_show_normal_changed(self, checked):
        self.obj.ShowSurfaceNormal = checked

    def _update_fresnel(self, val):
        self.obj.UseFresnel = val

    def _update_material(self, name):
        self.obj.Material = name
        n_d, v_d = MATERIAL_DATA.get(name, (1.5, 50.0))

        self.spin_index.blockSignals(True)
        self.spin_abbe.blockSignals(True)

        self.spin_index.setValue(n_d)
        self.spin_abbe.setValue(v_d)
        self.obj.RefractiveIndex = n_d
        self.obj.AbbeNumber = v_d

        self.spin_index.blockSignals(False)
        self.spin_abbe.blockSignals(False)

    def _update_index(self, val):
        self.obj.RefractiveIndex = val
        self._set_custom()

    def _update_abbe(self, val):
        self.obj.AbbeNumber = val
        self._set_custom()

    def _set_custom(self):
        self.obj.Material = "Custom"
        self.cmb_material.blockSignals(True)
        self.cmb_material.setCurrentText("Custom")
        self.cmb_material.blockSignals(False)


# ============================================================
#  V I E W   P R O V I D E R
# ============================================================


class LenseViewProvider(OBAViewProviderBase):
    # ICON = "oba_lens.svg"
    # DIALOG = LenseDialog

    def __init__(self, vobj):
        super().__init__(vobj)
        # Denna länk till klassen måste sättas explicit (sparas ej i filen)
        self.dialog_class = LenseDialog


# ============================================================
#  S K A P A   L E N S E
# ============================================================


def OBA_CreateLense():
    doc = App.ActiveDocument or App.newDocument()
    sel_ex = Gui.Selection.getSelectionEx()

    # Skapa objekt
    lense_obj = doc.addObject("App::DocumentObjectGroupPython", "Lense")

    # Proxy
    if sel_ex:
        OBALense(lense_obj, sel_ex[0].Object, sel_ex[0].SubElementNames)
    else:
        OBALense(lense_obj)

    # ViewProvider
    if App.GuiUp:
        LenseViewProvider(lense_obj.ViewObject)

    doc.recompute()

    # Visa dialogen direkt
    LenseDialog(lense_obj).show()


# ============================================================
#  K O M M A N D O
# ============================================================


# class _CmdLense:
#     def GetResources(self):
#         return {"MenuText": "Create Lense"}

#     def Activated(self):
#         OBA_CreateLense()


# if "OBA_CreateLense" not in Gui.listCommands():
#     Gui.addCommand("OBA_CreateLense", _CmdLense())
