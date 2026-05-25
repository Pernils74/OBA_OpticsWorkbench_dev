import os
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets
from .oba_base import OBABaseDialog, OBAElementProxy, OBAViewProviderBase


BASE_PATH = os.path.dirname(__file__)

# ============================================================
#  O B J E K T –  G R A T I N G
# ============================================================


class OBAGrating(OBAElementProxy):

    def __init__(self, obj, source_obj=None, sub_elements=None):
        super().__init__(obj)

        # Grating-specifika egenskaper
        if not hasattr(obj, "LinesPerMM"):
            obj.addProperty(
                "App::PropertyFloat",
                "LinesPerMM",
                "Grating",
                "Number of grooves per millimeter (e.g. 300, 600, 1200)",
            ).LinesPerMM = 600.0

        if not hasattr(obj, "Orders"):
            obj.addProperty(
                "App::PropertyIntegerList",
                "Orders",
                "Grating",
                "Diffraction orders to simulate (e.g. 0, 1, -1)",
            ).Orders = [0, 1, -1]

        if not hasattr(obj, "SpectrumRays"):
            obj.addProperty(
                "App::PropertyInteger",
                "SpectrumRays",
                "Grating",
                "Number of rays used for spectral split per dispersive order",
            ).SpectrumRays = 5

        if not hasattr(obj, "Efficiency"):
            obj.addProperty(
                "App::PropertyFloat",
                "Efficiency",
                "Grating",
                "Simplified power loss per order (0.0 - 1.0)",
            ).Efficiency = 0.5

        if not hasattr(obj, "OpticalType"):
            obj.addProperty(
                "App::PropertyString",
                "OpticalType",
                "Base",
                "Type of optical element",
            ).OpticalType = "Grating"

        if not hasattr(obj, "FlipNormal"):
            obj.addProperty("App::PropertyBool", "FlipNormal", "NormalSettings", "Invert surface normal for optical computation").FlipNormal = False
        if not hasattr(obj, "ShowSurfaceNormal"):
            obj.addProperty(
                "App::PropertyBool",
                "ShowSurfaceNormal",
                "NormalSettings",
                "Show surface normal preview",
            ).ShowSurfaceNormal = False

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
                vp = GratingViewProvider(obj.ViewObject)
                # VIKTIGT: Eftersom __init__ kördes nu, sattes dialog_class korrekt
            else:
                # Om proxyn fanns kvar men var "död", kör dess restore
                obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)
                # SÄKERSTÄLL att dialog_class finns (eftersom den inte sparas i filen)
                obj.ViewObject.Proxy.dialog_class = GratingDialog

            obj.ViewObject.update()


# ============================================================
#  D I A L O G
# ============================================================


class GratingDialog(OBABaseDialog):
    ALLOW_SURFACE_SELECTION = True  # ℹ️ För att visa face select listan

    def __init__(self, obj):
        super().__init__(obj, title="Diffraction Grating Settings")

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

        # --- Lines per mm ---
        row_lines = QtWidgets.QHBoxLayout()
        label_lines = QtWidgets.QLabel("Lines per mm:")
        label_lines.setToolTip("Groove density. Higher values create a wider rainbow spread.")
        row_lines.addWidget(label_lines)

        self.spin_lines = QtWidgets.QDoubleSpinBox()
        self.spin_lines.setRange(1.0, 5000.0)
        self.spin_lines.setValue(self.obj.LinesPerMM)
        self.spin_lines.valueChanged.connect(self._update_lines)
        row_lines.addWidget(self.spin_lines)
        self.custom_layout.addLayout(row_lines)

        # --- Orders (m) ---
        row_orders = QtWidgets.QHBoxLayout()
        label_orders = QtWidgets.QLabel("Diffraction Orders (m):")
        label_orders.setToolTip(
            "m=0: The direct beam (no dispersion).\n" "m=1, m=-1: First-order rainbows (primary spectral split).\n" "m=2: Second-order (wider dispersion, usually lower intensity).\n" "Separate values with commas (e.g., -1, 0, 1)."
        )
        row_orders.addWidget(label_orders)

        self.txt_orders = QtWidgets.QLineEdit(", ".join(map(str, self.obj.Orders)))
        self.txt_orders.setPlaceholderText("e.g. -1, 0, 1")
        self.txt_orders.editingFinished.connect(self._update_orders)
        row_orders.addWidget(self.txt_orders)
        self.custom_layout.addLayout(row_orders)

        # --- Spectrum Rays (Resolution) ---
        row_spec = QtWidgets.QHBoxLayout()
        label_spec = QtWidgets.QLabel("Spectrum Rays:")
        label_spec.setToolTip("Number of spectral sample rays generated for each dispersive order (m != 0).\n" "Higher values increase rainbow resolution but take longer to calculate.")
        row_spec.addWidget(label_spec)

        self.spin_rays = QtWidgets.QSpinBox()
        self.spin_rays.setRange(1, 50)
        self.spin_rays.setValue(getattr(self.obj, "SpectrumRays", 5))
        self.spin_rays.valueChanged.connect(self._update_spectrum_rays)
        row_spec.addWidget(self.spin_rays)
        self.custom_layout.addLayout(row_spec)

        # --- Efficiency ---
        row_eff = QtWidgets.QHBoxLayout()
        label_eff = QtWidgets.QLabel("Efficiency (Power):")
        label_eff.setToolTip("Total energy transmitted through the grating (0.0 to 1.0).")
        row_eff.addWidget(label_eff)

        self.spin_eff = QtWidgets.QDoubleSpinBox()
        self.spin_eff.setRange(0.0, 1.0)
        self.spin_eff.setSingleStep(0.1)
        self.spin_eff.setValue(self.obj.Efficiency)
        self.spin_eff.valueChanged.connect(self._update_efficiency)
        row_eff.addWidget(self.spin_eff)
        self.custom_layout.addLayout(row_eff)

        self.custom_layout.addStretch(1)

    def _on_flip_changed(self, checked):
        self.obj.FlipNormal = checked

    def _on_show_normal_changed(self, checked):
        self.obj.ShowSurfaceNormal = checked

        # _trigger_ray_engine(
        #     reason="show_surface_normal_toggled",
        #     source=self.obj,
        # )

    def _update_lines(self, val):
        self.obj.LinesPerMM = val

    def _update_orders(self):
        try:
            text = self.txt_orders.text()
            # Parsa, ta bort dubbletter med set() och sortera för tydlighet
            unique_orders = sorted(list(set(int(x.strip()) for x in text.split(",") if x.strip())))
            if not unique_orders:
                # Om listan är tom, behåll nollte ordningen som fallback
                unique_orders = [0]
            self.obj.Orders = unique_orders
            # Uppdatera textfältet så det ser snyggt ut: " -1, 0, 1 "
            self.txt_orders.setText(", ".join(map(str, unique_orders)))
        except ValueError:
            App.Console.PrintError("Invalid order format. Please use integers separated by commas (e.g. -1, 0, 1).\n")
            # Återställ till det gamla värdet i fältet vid fel
            self.txt_orders.setText(", ".join(map(str, self.obj.Orders)))

    def _update_efficiency(self, val):
        self.obj.Efficiency = val

    def _update_spectrum_rays(self, val):
        self.obj.SpectrumRays = val


# ============================================================
#  V I E W   P R O V I D E R
# ============================================================


class GratingViewProvider(OBAViewProviderBase):
    # ICON = "oba_grating.svg"
    # DIALOG = GratingDialog

    def __init__(self, vobj):
        super().__init__(vobj)
        self.dialog_class = GratingDialog


# ============================================================
#  S K A P A   G R A T I N G
# ============================================================


def OBA_CreateGrating(show_dialog=True):
    doc = App.ActiveDocument or App.newDocument()
    sel_ex = Gui.Selection.getSelectionEx()

    grating_obj = doc.addObject("App::DocumentObjectGroupPython", "Grating")

    if sel_ex:
        OBAGrating(grating_obj, sel_ex[0].Object, sel_ex[0].SubElementNames)
    else:
        OBAGrating(grating_obj)

    if App.GuiUp:
        GratingViewProvider(grating_obj.ViewObject)

    doc.recompute()
    # Öppna dialogen direkt

    # 4. Visa dialogen direkt vid skapande
    if show_dialog:
        GratingDialog(grating_obj).show()
    return grating_obj


# ============================================================
#  K O M M A N D O
# ============================================================


# class _CmdGrating:
#     def GetResources(self):
#         return {"MenuText": "Create Grating", "ToolTip": "Create a diffraction grating from surface"}

#     def Activated(self):
#         OBA_CreateGrating()


# if "OBA_CreateGrating" not in Gui.listCommands():
#     Gui.addCommand("OBA_CreateGrating", _CmdGrating())
