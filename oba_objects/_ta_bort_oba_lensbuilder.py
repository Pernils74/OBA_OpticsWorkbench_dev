import FreeCAD as App
import FreeCADGui as Gui


from PySide import QtWidgets

from .oba_base import OBABaseDialog, OBAElementProxy, OBAViewProviderBase
from .oba_lens_materials import get_material_list, get_refractive_index, MATERIAL_DATA

# ============================================================
#  O B J E K T  –  L E N S   B U I L D E R  (OPTICAL)
# ============================================================


class OBALensBuilder(OBAElementProxy):

    def __init__(self, obj):
        super().__init__(obj)

        # ---------- GEOMETRY ----------
        if not hasattr(obj, "Diameter"):
            obj.addProperty("App::PropertyFloat", "Diameter", "Lens").Diameter = 50.0

        if not hasattr(obj, "Thickness"):
            obj.addProperty("App::PropertyFloat", "Thickness", "Lens").Thickness = 10.0

        if not hasattr(obj, "Focal"):
            obj.addProperty("App::PropertyFloat", "Focal", "Lens").Focal = 100.0

        # ---------- MATERIAL ----------
        if not hasattr(obj, "Material"):
            obj.addProperty("App::PropertyEnumeration", "Material", "Lens")
            obj.Material = get_material_list()

            # ✅ sätt default material
            if "N-BK7" in obj.Material:
                obj.Material = "N-BK7"

        if not hasattr(obj, "RefractiveIndex"):
            obj.addProperty("App::PropertyFloat", "RefractiveIndex", "Lens").RefractiveIndex = 1.5

        if not hasattr(obj, "AbbeNumber"):
            obj.addProperty("App::PropertyFloat", "AbbeNumber", "Lens").AbbeNumber = 50.0

        if not hasattr(obj, "Wavelength"):
            obj.addProperty("App::PropertyFloat", "Wavelength", "Lens").Wavelength = 550.0

        # ---------- OPTICAL FLAGS ----------
        if not hasattr(obj, "UseFresnel"):
            obj.addProperty("App::PropertyBool", "UseFresnel", "Optics").UseFresnel = False

        if not hasattr(obj, "FlipNormal"):
            obj.addProperty("App::PropertyBool", "FlipNormal", "Optics").FlipNormal = False

        # if not hasattr(obj, "ShowSurfaceNormal"):
        #     obj.addProperty("App::PropertyBool", "ShowSurfaceNormal", "Optics").ShowSurfaceNormal = False

        if not hasattr(obj, "IsOptical"):
            obj.addProperty("App::PropertyBool", "IsOptical", "Base").IsOptical = True

        if not hasattr(obj, "OpticalType"):
            obj.addProperty("App::PropertyString", "OpticalType", "Base")
            obj.OpticalType = "LensBuilder"

        # ---------- SHAPE CONTAINER ----------
        body = App.ActiveDocument.addObject("Part::Feature", "LensShape")
        obj.addObject(body)
        self.body = body

        self.Object = obj
        self._init_done = True

        self.build_shape()

    # --------------------------------------------------------

    def build_shape_fel(self):

        import Part
        import FreeCAD as App

        obj = self.Object

        if not hasattr(self, "body"):
            return

        D = obj.Diameter
        T = obj.Thickness
        f = obj.Focal

        n = get_refractive_index(
            obj.Material,
            wavelength_nm=obj.Wavelength,
            override_n=obj.RefractiveIndex if obj.Material == "Custom" else None,
        )

        if n <= 1.0:
            n = 1.0003

        R = max(f * (n - 1.0), D / 2.0 + 0.001)

        pl = self.body.Placement

        # =========================================================
        # 1. CYLINDER
        # =========================================================
        cyl = Part.makeCylinder(D / 2.0, T)

        # =========================================================
        # 2. SPHERE (placera så den skapar en topp-kupa)
        # =========================================================
        sphere = Part.makeSphere(R)

        # placera sfärens centrum så att den "ligger på toppen"
        sphere.translate(App.Vector(0, 0, T - R))

        # =========================================================
        # 3. SKAPA EN PLAN SOM KLIPPER BORT UNDERSIDAN AV SFÄREN
        # =========================================================
        box = Part.makeBox(D * 2, D * 2, R * 2)
        box.translate(App.Vector(-D, -D, T))  # skär vid z = T

        # behåll bara sfärens OVANFÖR T
        cap = sphere.cut(box)

        # =========================================================
        # 4. FUSERA CYLINDER + KUPA
        # =========================================================
        shape = cyl.fuse(cap)

        self.body.Shape = shape
        self.body.Placement = pl

        if App.GuiUp:
            self.body.ViewObject.Transparency = 70

        self._rebuild_binders()

    def build_shape(self):
        import Part
        import FreeCAD as App

        obj = self.Object
        if not hasattr(self, "body"):
            return

        D = obj.Diameter
        T = obj.Thickness
        f = obj.Focal

        # ✅ refractive index
        n = get_refractive_index(
            obj.Material,
            wavelength_nm=obj.Wavelength,
            override_n=obj.RefractiveIndex if obj.Material == "Custom" else None,
        )

        if n <= 1.0:
            n = 1.0003

        # ✅ radie
        R = max(f * (n - 1.0), D / 2.0 + 0.001)

        pl = self.body.Placement

        # =========================================================
        # 1. BAS – CYLINDER (full volym)
        # =========================================================
        cyl = Part.makeCylinder(D / 2.0, T)

        # =========================================================
        # 2. SFÄR – SKÄR UT KURVAN
        # =========================================================
        sphere = Part.makeSphere(R)

        # placera så att den trycker ner toppen
        sphere.translate(App.Vector(0, 0, T - R))

        # =========================================================
        # 3. SUBTRAHERA (DETTA ÄR NYCKELN)
        # =========================================================
        shape = cyl.common(sphere)  # ❌ gav halvkupa
        # shape = cyl.cut(sphere)    # ❌ men detta ger fel håll

        # ✅ korrekt:
        shape = cyl.common(sphere)  # och invertera logiken via placering

        # =========================================================
        self.body.Shape = shape
        self.body.Placement = pl

        if App.GuiUp:
            self.body.ViewObject.Transparency = 70

        self._rebuild_binders()

    # --------------------------------------------------------
    def _rebuild_binders(self):
        obj = self.Object

        if not hasattr(self.body, "Shape") or not self.body.Shape:
            return

        # rensa gamla
        self.clear_binders(obj)

        # skapa nya
        faces = [f"Face{i+1}" for i in range(len(self.body.Shape.Faces))]
        self.add_binders(obj, self.body, faces)

    # --------------------------------------------------------
    def onChanged(self, obj, prop):
        if not getattr(self, "_init_done", False):
            return

        if prop == "Material":
            self._apply_material(obj)

        if prop in (
            "Diameter",
            "Thickness",
            "Focal",
            "Material",
            "RefractiveIndex",
            "Wavelength",
        ):
            self.build_shape()

    def _apply_material(self, obj):
        name = obj.Material

        if name == "Custom":
            return

        n_d, v_d = MATERIAL_DATA.get(name, (1.5, 50.0))

        if n_d is not None:
            obj.RefractiveIndex = n_d

        if v_d is not None:
            obj.AbbeNumber = v_d

    # --------------------------------------------------------
    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self.Object = obj

        if App.GuiUp and obj.ViewObject:
            if not hasattr(obj.ViewObject, "Proxy") or obj.ViewObject.Proxy is None:
                LensBuilderViewProvider(obj.ViewObject)
            else:
                obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)
                obj.ViewObject.Proxy.dialog_class = LensBuilderDialog

            obj.ViewObject.update()


# ============================================================
#  G U I
# ============================================================


class LensBuilderDialog(OBABaseDialog):

    ALLOW_SURFACE_SELECTION = False  # auto-bind används

    def __init__(self, obj):
        super().__init__(obj, title="Lens Builder")

        # self._add_check("Show normal", "ShowSurfaceNormal")

        # --- Diameter ---
        self._add_spin("Diameter", obj, "Diameter", 1.0)

        # --- Thickness ---
        self._add_spin("Thickness", obj, "Thickness", 1.0)

        # --- Focal ---
        self._add_spin("Focal length", obj, "Focal", 1.0)

        # --- Material ---
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Material:"))

        self.cmb = QtWidgets.QComboBox()
        self.cmb.addItems(get_material_list())
        self.cmb.setCurrentText(obj.Material)
        self.cmb.currentTextChanged.connect(self._update_material)

        row.addWidget(self.cmb)

        self.lbl_n = QtWidgets.QLabel()
        row.addWidget(self.lbl_n)

        self.custom_layout.addLayout(row)

        # --- Refractive Index ---
        self._add_spin("n (Custom)", obj, "RefractiveIndex", 0.05)

        # --- Abbe ---
        self._add_spin("Abbe", obj, "AbbeNumber", 1.0)

        # --- Fresnel ---
        chk = QtWidgets.QCheckBox("Use Fresnel")
        chk.setChecked(obj.UseFresnel)
        chk.toggled.connect(lambda v: setattr(obj, "UseFresnel", v))
        self.custom_layout.addWidget(chk)
        self._update_n()

    # --------------------------------------------------------
    def _add_spin(self, label, obj, prop, step):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))

        spin = QtWidgets.QDoubleSpinBox()
        spin.setValue(getattr(obj, prop))
        spin.valueChanged.connect(lambda v: setattr(obj, prop, v))

        # ✅ VIKTIGT: sätt range
        spin.setRange(0.001, 1e6)

        # ✅ precision (viktig för optik)
        spin.setDecimals(4)

        # ✅ snabbare step
        spin.setSingleStep(step)

        row.addWidget(spin)
        self.custom_layout.addLayout(row)

    def _add_check(self, label, prop):
        row = QtWidgets.QHBoxLayout()

        w = QtWidgets.QCheckBox(label)
        w.setChecked(getattr(self.obj, prop))
        w.stateChanged.connect(lambda v, p=prop: setattr(self.obj, p, bool(v)))

        row.addWidget(w)
        self.custom_layout.addLayout(row)

    # --------------------------------------------------------

    def _update_material(self, name):
        self.obj.Material = name
        self._update_n()

    def _update_material_old(self, name):
        self.obj.Material = name

        if name == "Custom":
            return  # ✅ låt user styra n själv

        n_d, v_d = MATERIAL_DATA.get(name, (1.5, 50.0))

        if n_d is not None:
            self.obj.RefractiveIndex = n_d

        if v_d is not None:
            self.obj.AbbeNumber = v_d

        self._update_n()

    # --------------------------------------------------------
    def _update_n(self):
        n = get_refractive_index(self.obj.Material, wavelength_nm=self.obj.Wavelength, override_n=self.obj.RefractiveIndex if self.obj.Material == "Custom" else None)
        self.lbl_n.setText(f"n = {n:.4f}")


# ============================================================
#  V I E W
# ============================================================


class LensBuilderViewProvider(OBAViewProviderBase):
    def __init__(self, vobj):
        super().__init__(vobj)
        self.dialog_class = LensBuilderDialog


# ============================================================
#  C R E A T E
# ============================================================


def OBA_CreateLensBuilder(show_dialog=True):

    doc = App.ActiveDocument or App.newDocument()

    obj = doc.addObject("App::DocumentObjectGroupPython", "Lens")

    OBALensBuilder(obj)

    if App.GuiUp:
        LensBuilderViewProvider(obj.ViewObject)

    doc.recompute()

    if show_dialog:
        LensBuilderDialog(obj).show()

    return obj
