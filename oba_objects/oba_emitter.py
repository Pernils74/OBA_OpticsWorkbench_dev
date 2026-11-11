# oba_emitter.py

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets
from .oba_base import OBABaseDialog, OBAElementProxy, OBAViewProviderBase  # , runRaytracer
from .oba_lens_materials import get_material_list

# ============================================================
#  O B J E K T -   E M I T T E R
# ============================================================

OPTICAL_PROPERTIES = [
    {
        "name": "StartMedium",
        "type": "App::PropertyEnumeration",
        "group": "Optics",
        "default": get_material_list(),
    },
    {
        "name": "Lambertian",
        "type": "App::PropertyBool",
        "group": "Emitter",
        "default": True,
        "doc": "Apply cosine weighting to emitted ray power",
    },
    {
        "name": "SpreadAngle",
        "type": "App::PropertyFloat",
        "group": "Emitter",
        "default": 80.0,
    },
    {
        "name": "EmissionMode",
        "type": "App::PropertyEnumeration",
        "group": "Emitter",
        "default": ["Cone (position)", "Cone (radial)", "Cone (lambert)", "Focus"],
    },
    {
        "name": "FocusDistance",
        "type": "App::PropertyFloat",
        "group": "Emitter",
        "default": 100.0,
        "doc": "Distance to focus point along surface normal",
    },
    {
        "name": "Power",
        "type": "App::PropertyFloat",
        "group": "Emitter",
        "default": 100.0,
        "doc": "Total emitted power (W)",
    },
    {
        "name": "Wavelength",
        "type": "App::PropertyFloat",
        "group": "Emitter",
        "default": 585.0,
    },
    {
        "name": "MaxRays",
        "type": "App::PropertyInteger",
        "group": "Emitter",
        "default": 50,
    },
    {
        "name": "MaxBounce",
        "type": "App::PropertyInteger",
        "group": "Emitter",
        "default": 100,
    },
    {
        "name": "MaxRayLength",
        "type": "App::PropertyFloat",
        "group": "Emitter",
        "default": 5000.0,
    },
    {
        "name": "FlipNormal",
        "type": "App::PropertyBool",
        "group": "NormalSettings",
        "default": False,
        "doc": "Invert surface normal for optical computation",
    },
    {
        "name": "PreviewRayLength",
        "type": "App::PropertyFloat",
        "group": "Emitter",
        "default": 2.0,
    },
]


def ensure_initialized(obj):
    if "OpticalType" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "OpticalType", "Base")
    obj.OpticalType = "Emitter"


class OBAEmitter(OBAElementProxy):
    def __init__(self, obj, source_obj=None, sub_elements=None):
        super().__init__(obj)  # Viktigt: kör basens init för self.Object

        # Grund-properties (binders)
        if not hasattr(obj, "Binders"):
            obj.addProperty("App::PropertyLinkList", "Binders", "Optics")

        if not hasattr(obj, "StartMedium"):
            obj.addProperty("App::PropertyEnumeration", "StartMedium", "Optics")
            obj.StartMedium = get_material_list()
            if "Air" in obj.StartMedium:
                obj.StartMedium = "Air"

        # Emitter-specifika properties
        if not hasattr(obj, "Lambertian"):
            obj.addProperty("App::PropertyBool", "Lambertian", "Emitter").Lambertian = True
        if not hasattr(obj, "SpreadAngle"):
            obj.addProperty("App::PropertyFloat", "SpreadAngle", "Emitter").SpreadAngle = 5.0
        if not hasattr(obj, "EmissionMode"):
            obj.addProperty("App::PropertyEnumeration", "EmissionMode", "Emitter")
        current_emission_mode = getattr(obj, "EmissionMode", "Cone")
        emission_modes = ["Cone (position)", "Cone (radial)", "Cone (lambert)", "Focus"]
        obj.EmissionMode = emission_modes
        current_emission_mode = {
            "Cone": "Cone (position)",
            "Position Cone": "Cone (position)",
            "Radial Cone": "Cone (radial)",
            "Lambert Cone": "Cone (lambert)",
        }.get(current_emission_mode, current_emission_mode)
        if current_emission_mode in emission_modes:
            obj.EmissionMode = current_emission_mode

        if not hasattr(obj, "FocusDistance"):
            obj.addProperty("App::PropertyFloat", "FocusDistance", "Emitter", "Distance to focus point along surface normal").FocusDistance = 100.0

        if not hasattr(obj, "Power"):
            obj.addProperty("App::PropertyFloat", "Power", "Emitter", "Total emitted power (W)").Power = 100.0
        if not hasattr(obj, "Wavelength"):
            obj.addProperty("App::PropertyFloat", "Wavelength", "Emitter").Wavelength = 585.0

        if not hasattr(obj, "MaxRays"):
            obj.addProperty("App::PropertyInteger", "MaxRays", "Emitter").MaxRays = 50
        if not hasattr(obj, "MaxBounce"):
            obj.addProperty("App::PropertyInteger", "MaxBounce", "Emitter").MaxBounce = 100
        if not hasattr(obj, "MaxRayLength"):
            obj.addProperty("App::PropertyFloat", "MaxRayLength", "Emitter").MaxRayLength = 5000.0
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

    # def __init____old(self, obj):
    #     super().__init__(obj, title="Emitter Settings")
    #     self._add_material("Start medium", "StartMedium")
    #     self._add_enum("Emission mode", "EmissionMode")
    #     self._add_spin("Focus distance", "FocusDistance", -1e9, 1e9)
    #     self._add_check("Lambertian", "Lambertian")
    #     self._add_check("Flip normal", "FlipNormal")

    #     # self._add_check("Show normal", "ShowSurfaceNormal")

    #     self._add_spin("Spread angle (deg)", "SpreadAngle", 0.0, 180.0)
    #     self._add_spin("Power (W)", "Power", 0.0, 1e9)
    #     self._add_spin("Wavelength (nm)", "Wavelength", 350, 780)
    #     self._add_int("Max rays", "MaxRays", 1, 1_000_000)
    #     self._add_int("Max bounce", "MaxBounce", 0, 10_000)
    #     self._add_spin("Max ray length", "MaxRayLength", 0.1, 1e9)
    #     self._add_spin("Preview ray length", "PreviewRayLength", 0.1, 1e9)

    def __init__(self, obj):
        super().__init__(obj, title="Emitter Settings")

        # Gruppera efter funktionalitet
        self._add_group("Light Properties", self._build_light_properties)
        self._add_group("Emission Geometry", self._build_emission_geometry)
        self._add_group("Simulation Limits", self._build_simulation_limits)

        # self._add_group("Mesh Debug", self._build_mesh_debug)

        # -----------------------------
        # Export
        # -----------------------------
        # self._add_export_buttons()
        # self.custom_layout.addStretch()

    def _add_group(self, title, builder_fn):
        box = QtWidgets.QGroupBox(title)
        layout = QtWidgets.QVBoxLayout(box)
        builder_fn(layout)
        self.custom_layout.addWidget(box)

    # --- Nya grupperingsfunktioner ---

    def _build_light_properties(self, layout):
        """Färg, styrka och startmedium."""
        self._add_spin("Wavelength (nm)", "Wavelength", 350, 780, layout)
        self._add_spin("Power (W)", "Power", 0.0, 1e9, layout)
        self._add_material("Start medium", "StartMedium", layout)

    # def _build_emission_geometry_old(self, layout):
    #     """Strålgeometri, spridning och riktning."""
    #     self._add_enum("Emission mode", "EmissionMode", layout)
    #     self._add_check("Lambertian", "Lambertian", layout)
    #     self._add_spin("Spread angle (deg)", "SpreadAngle", 0.0, 180.0, layout)
    #     self._add_spin("Focus distance", "FocusDistance", -1e9, 1e9, layout)
    #     self._add_check("Flip normal", "FlipNormal", layout)

    #     self.emission_mode_combo.currentTextChanged.connect(self._update_emission_mode_ui)
    #     self._update_emission_mode_ui(self.obj.EmissionMode)
    #     # self._add_check("Show normal", "ShowSurfaceNormal", layout)

    def _build_emission_geometry(self, layout):
        """Strålgeometri, spridning och riktning."""
        self.emission_mode_combo = self._add_enum("Emission mode", "EmissionMode", layout)
        self.lambert_power_checkbox = self._add_check(
            "Lambert (power)",
            "Lambertian",
            layout,
            "Apply cosine weighting to ray power. Disable this when Cone (lambert) " "direction sampling alone should represent the Lambert distribution.",
        )
        self.spread_angle_widget = self._add_spin("Spread angle (deg)", "SpreadAngle", 0.0, 180.0, layout)
        self.focus_distance_widget = self._add_spin("Focus distance", "FocusDistance", -1e9, 1e9, layout)
        self._add_check("Flip normal", "FlipNormal", layout)
        self.emission_mode_combo.currentTextChanged.connect(self._update_emission_mode_ui)
        self._update_emission_mode_ui(self.obj.EmissionMode)
        # self._add_check("ShowNormal", "ShowSurfaceNormal", layout)

    def _build_simulation_limits(self, layout):
        """Prestanda och gränsvärden för simuleringsstrålar."""
        self._add_int("Max rays", "MaxRays", 1, 1_000_000, layout)
        self._add_int("Max bounce", "MaxBounce", 0, 10_000, layout)
        self._add_spin("Max ray length", "MaxRayLength", 0.1, 1e9, layout)
        self._add_spin("Preview ray length", "PreviewRayLength", 0.1, 1e9, layout)

    # ----------------------------------------------------------
    #  U P P D A T E R I N G   A V   P R O P S
    # ----------------------------------------------------------

    def _update_emission_mode_ui(self, mode):
        is_cone = mode in ("Cone", "Cone (position)", "Cone (radial)", "Cone (lambert)")
        is_focus = mode == "Focus"

        self.spread_angle_widget.setEnabled(is_cone)
        self.focus_distance_widget.setEnabled(is_focus)
        if mode == "Cone (lambert)":
            self.lambert_power_checkbox.setChecked(False)

    def _add_material(self, label, prop, layout):
        from .oba_lens_materials import get_material_list

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))

        cmb = QtWidgets.QComboBox()
        cmb.addItems(get_material_list())
        cmb.setCurrentText(getattr(self.obj, prop))
        cmb.currentTextChanged.connect(lambda v: setattr(self.obj, prop, v))

        row.addWidget(cmb)
        layout.addLayout(row)
        # self.custom_layout.addLayout(row)

    def _add_spin(self, label, prop, mn, mx, layout):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))

        # Skapa FreeCADs inbyggda sifferfält med uttrycksstöd (f(x)-knapp ingår)
        w = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")

        # Konfigurera gränser och enhet (FreeCAD hanterar internt rena tal eller t.ex. 'deg')
        w.setProperty("minimum", mn)
        w.setProperty("maximum", mx)

        # Om egenskapen är en vinkel (t.ex. Spread angle), ge den rätt enhet
        if "angle" in label.lower():
            w.setProperty("unit", "deg")

        # Hämta nuvarande värde från dokumentobjektet
        current_val = getattr(self.obj, prop)
        w.setProperty("rawValue", float(current_val))

        # Bind fältet direkt till FreeCADs interna Expression Engine
        # Detta sköter automatiskt uppdateringar till och från Spreadsheet!
        w.setProperty("binding", f"{self.obj.Name}.{prop}")

        # Koppla en signal för när användaren ändrar värdet manuellt i fältet
        w.valueChanged.connect(lambda v, p=prop: setattr(self.obj, p, v.Value))
        # w.valueChanged.connect(lambda v, p=prop: setattr(self.obj, p, v))

        row.addWidget(w)
        layout.addLayout(row)
        return w

    def _add_int(self, label, prop, mn, mx, layout):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))

        w = QtWidgets.QSpinBox()
        w.setRange(mn, mx)
        w.setValue(getattr(self.obj, prop))
        w.valueChanged.connect(lambda v, p=prop: setattr(self.obj, p, v))

        row.addWidget(w)
        layout.addLayout(row)
        # self.custom_layout.addLayout(row)

    def _add_check(self, label, prop, layout, tooltip=None):
        row = QtWidgets.QHBoxLayout()

        w = QtWidgets.QCheckBox(label)
        w.setChecked(getattr(self.obj, prop))
        if tooltip:
            w.setToolTip(tooltip)
        w.stateChanged.connect(lambda v, p=prop: setattr(self.obj, p, bool(v)))

        row.addWidget(w)
        layout.addLayout(row)
        return w
        # self.custom_layout.addLayout(row)

    def _add_enum(self, label, prop, layout):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        w = QtWidgets.QComboBox()
        values = self.obj.getEnumerationsOfProperty(prop)
        w.addItems(values)

        current = getattr(self.obj, prop)
        if current in values:
            w.setCurrentText(current)
        w.currentTextChanged.connect(lambda v: setattr(self.obj, prop, v))
        row.addWidget(w)
        layout.addLayout(row)
        return w


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
