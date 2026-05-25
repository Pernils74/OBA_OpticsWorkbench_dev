# oba_ray_config.py

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from .oba_base import (
    OBAElementProxy,
    OBAViewProviderBase,
    OBABaseDialog,
)

# ============================================================
#  O B J E K T  –  R A Y  C O N F I G
# ============================================================


class OBARayConfig(OBAElementProxy):
    """
    FeaturePython CONFIG object for the ray engine.

    - Innehåller ENDAST inställningar
    - INGEN tracing-logik
    - Exakt EN instans per dokument
    """

    # RayConfig ska INTE trigga tracing via onChanged
    TRACE_IGNORE_PROPERTIES = {"Proxy", "Label"}

    def __init__(self, obj):
        super().__init__(obj)

        # -------- Core tracing --------

        if not hasattr(obj, "TraceMode"):
            obj.addProperty(
                "App::PropertyEnumeration",
                "TraceMode",
                "TraceSettings",
                "Raytracing Backend Method",
            )
            obj.TraceMode = ["OCC", "Mesh"]
            obj.TraceMode = "Mesh"

        if not hasattr(obj, "RunMode"):
            obj.addProperty("App::PropertyEnumeration", "RunMode", "TraceSettings", "How tracing is triggered")
            obj.RunMode = ["AUTO", "MANUAL"]
            obj.RunMode = "AUTO"

        if not hasattr(obj, "OpticalType"):
            obj.addProperty("App::PropertyString", "OpticalType", "Base", "Type of optical element")
        obj.OpticalType = "RayConfig"  # används för icon

        # self._ensure_enum(
        #     obj,
        #     "TraceMode",
        #     "TraceSettings",
        #     ["OCC", "Mesh"],
        #     default="Mesh",
        # )

        self._ensure_bool(
            obj,
            "DisableDebounce",
            "TraceSettings",
            default=False,
        )

        self._ensure_bool(
            obj,
            "ShowLog",
            "TraceSettings",
            default=False,
        )

        # -------- Mesh --------
        self._ensure_float(
            obj,
            "MeshTolerance",
            "MeshSettings",
            default=50.0,
        )

        self._ensure_int(
            obj,
            "MeshRayMultiplier",
            "MeshSettings",
            default=5,
        )

        # -------- Visualization --------
        self._ensure_bool(obj, "SceneIsolation", "Visualization", False)
        self._ensure_bool(obj, "ColorByBounce", "Visualization", False)
        self._ensure_float(obj, "RayLineWidth", "Visualization", 2.0)
        self._ensure_int(obj, "RayBounceMin", "Visualization", 0)
        self._ensure_int(obj, "RayBounceMax", "Visualization", -1)

        # -------- Mesh debug --------
        self._ensure_bool(obj, "DrawMeshTriangles", "Visualization_Mesh", False)
        self._ensure_bool(obj, "DrawVertexNormals", "Visualization_Mesh", True)
        self._ensure_float(obj, "VertexNormalLength", "Visualization_Mesh", 2.0)

    # --------------------------------------------------
    # Helpers (idempotent – MÅSTE vara detta i FreeCAD)
    # --------------------------------------------------

    def _ensure_bool(self, obj, name, group, default):
        if hasattr(obj, name):
            return
        obj.addProperty("App::PropertyBool", name, group)
        setattr(obj, name, default)

    def _ensure_float(self, obj, name, group, default):
        if hasattr(obj, name):
            return
        obj.addProperty("App::PropertyFloat", name, group)
        setattr(obj, name, default)

    def _ensure_int(self, obj, name, group, default):
        if hasattr(obj, name):
            return
        obj.addProperty("App::PropertyInteger", name, group)
        setattr(obj, name, default)

    # def _ensure_enum(self, obj, name, group, values, default):
    #     if hasattr(obj, name):
    #         return
    #     obj.addProperty("App::PropertyEnumeration", name, group)
    #     setattr(obj, name, values)
    #     setattr(obj, name, default)

    # --------------------------------------------------
    # Restore (minimal – base tar hand om det mesta)
    # --------------------------------------------------
    # ℹ️ Måste finnas för att kunna reopen utan felmedellande
    def onDocumentRestored(self, obj):
        # 1. Återställ App-proxyn
        obj.Proxy = self
        self.Object = obj
        App.Console.PrintMessage(f"Restoring {obj.Label}\n")

        # ✅ Säkerställ properties (idempotent)
        # self._ensure_bool(obj, "SceneIsolation", "Visualization", False)
        # self._ensure_bool(obj, "ColorByBounce", "Visualization", True)
        # self._ensure_float(obj, "RayLineWidth", "Visualization", 2.0)
        # self._ensure_int(obj, "RayBounceMin", "Visualization", 0)
        # self._ensure_int(obj, "RayBounceMax", "Visualization", -1)

        # 2. Återställ ViewProvidern
        if App.GuiUp and obj.ViewObject:
            # Om proxyn saknas helt, skapa en ny
            if not hasattr(obj.ViewObject, "Proxy") or obj.ViewObject.Proxy is None:
                # Skapa ny ViewProvider
                vp = RayConfigViewProvider(obj.ViewObject)
                # VIKTIGT: Eftersom __init__ kördes nu, sattes dialog_class korrekt
            else:
                # Om proxyn fanns kvar men var "död", kör dess restore
                obj.ViewObject.Proxy.onDocumentRestored(obj.ViewObject)
                # SÄKERSTÄLL att dialog_class finns (eftersom den inte sparas i filen)
                obj.ViewObject.Proxy.dialog_class = RayConfigDialog

            obj.ViewObject.update()


# ============================================================
#  D I A L O G
# ============================================================


class RayConfigDialog(OBABaseDialog):
    ALLOW_SURFACE_SELECTION = False  # ℹ️ För att visa face select listan

    def __init__(self, obj):
        super().__init__(obj, title="Ray Engine Configuration")

        # -----------------------------
        # Trace / Engine
        # -----------------------------
        self._add_group("Trace Settings", self._build_trace_settings)

        # -----------------------------
        # Mesh
        # -----------------------------
        self._add_group("Mesh Settings", self._build_mesh_settings)

        # -----------------------------
        # Visualization
        # -----------------------------
        self._add_group("Visualization", self._build_visualization)

        # -----------------------------
        # Mesh Debug
        # -----------------------------
        self._add_group("Mesh Debug", self._build_mesh_debug)

        # -----------------------------
        # Export
        # -----------------------------
        self._add_export_buttons()
        self.custom_layout.addStretch()

    def _add_group(self, title, builder_fn):
        box = QtWidgets.QGroupBox(title)
        layout = QtWidgets.QVBoxLayout(box)
        builder_fn(layout)
        self.custom_layout.addWidget(box)

    def _build_trace_settings(self, layout):
        self._add_enum("Trace mode", "TraceMode", layout)
        self._add_enum("Run mode", "RunMode", layout)

        self._add_bool("Show log output", "ShowLog", layout)

        self._add_bool("Disable debounce", "DisableDebounce", layout)

    def _build_mesh_settings(self, layout):
        self._add_float("Mesh tolerance", "MeshTolerance", layout)
        self._add_int("Mesh ray multiplier", "MeshRayMultiplier", layout)

    def _build_visualization(self, layout):
        self._add_bool("Scene isolation", "SceneIsolation", layout)
        self._add_bool("Color by bounce", "ColorByBounce", layout)
        self._add_float("Ray line width", "RayLineWidth", layout)
        self._add_int("Bounce min", "RayBounceMin", layout)
        self._add_int("Bounce max", "RayBounceMax", layout)

    def _build_mesh_debug(self, layout):
        self._add_bool("Show mesh", "DrawMeshTriangles", layout)
        self._add_bool("Show vertex normals", "DrawVertexNormals", layout)
        self._add_float("Vertex normal length", "VertexNormalLength", layout)

        # class RayConfigDialog(OBABaseDialog):
        #     ALLOW_SURFACE_SELECTION = False  # ℹ️ För att visa face select listan

        #     def __init__(self, obj):
        #         super().__init__(obj, title="Ray Engine Configuration")

        #         self._add_enum("Trace mode", "TraceMode")
        #         self._add_bool("Disable debounce", "DisableDebounce")

        #         self._add_float("Mesh tolerance", "MeshTolerance")
        #         self._add_int("Mesh ray multiplier", "MeshRayMultiplier")

        #         self._add_bool("Scene isolation", "SceneIsolation")
        #         self._add_bool("Color by bounce", "ColorByBounce")
        #         self._add_float("Ray line width", "RayLineWidth")

        #         self._add_int("Bounce min", "RayBounceMin")
        #         self._add_int("Bounce max", "RayBounceMax")

        #         self._add_bool("Show mesh", "DrawMeshTriangles")
        #         self._add_bool("Show vertex normals", "DrawVertexNormals")
        #         self._add_float("Vertex line length", "VertexNormalLength")

        #         # -----------------------------
        #         # Export / Utilities
        #         # -----------------------------

    def _add_export_buttons(self):
        box = QtWidgets.QGroupBox("Export / Utilities")
        layout = QtWidgets.QVBoxLayout(box)

        btn_create = QtWidgets.QPushButton("Create ray paths object")
        btn_create.clicked.connect(self._create_ray_object)
        layout.addWidget(btn_create)

        btn_remove = QtWidgets.QPushButton("Remove ray paths object")
        btn_remove.clicked.connect(self._remove_ray_object)
        layout.addWidget(btn_remove)

        self.custom_layout.addWidget(box)

    # ---------- helpers ----------
    def _add_bool(self, label, prop, layout):
        row = QtWidgets.QHBoxLayout()

        chk = QtWidgets.QCheckBox(label)
        chk.setChecked(getattr(self.obj, prop))
        chk.toggled.connect(lambda v: setattr(self.obj, prop, v))

        row.addWidget(chk)
        layout.addLayout(row)

    def _add_float(self, label, prop, layout):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))

        w = QtWidgets.QDoubleSpinBox()
        w.setRange(0, 1e9)
        w.setValue(getattr(self.obj, prop))
        w.valueChanged.connect(lambda v: setattr(self.obj, prop, v))

        row.addWidget(w)
        layout.addLayout(row)

    def _add_int(self, label, prop, layout):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))

        w = QtWidgets.QSpinBox()
        w.setRange(-1, 10_000_000)
        w.setValue(getattr(self.obj, prop))
        w.valueChanged.connect(lambda v: setattr(self.obj, prop, v))

        row.addWidget(w)
        layout.addLayout(row)

    def _add_enum(self, label, prop, layout):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        w = QtWidgets.QComboBox()

        # ✅ Hämta de tillgängliga alternativen korrekt
        try:
            # getEnumerationsOfProperty returnerar listan med val (t.ex. ['OCC', 'Mesh'])
            values = self.obj.getEnumerationsOfProperty(prop)
        except Exception:
            values = []

        w.addItems(values)

        # ✅ Sätt nuvarande valt värde
        current = getattr(self.obj, prop)
        if current in values:
            w.setCurrentText(current)

        w.currentTextChanged.connect(lambda v: setattr(self.obj, prop, v))
        row.addWidget(w)
        layout.addLayout(row)

    def _create_ray_object(self):
        from oba_rayengine.oba_ray_core import OBARayManager

        doc = self.obj.Document
        if not doc:
            return

        rm = OBARayManager(doc)
        obj = rm.create_fc_line_object(doc)

        if obj:
            App.Console.PrintMessage(f"[OBA] Created ray geometry object: {obj.Name}\n")
        else:
            App.Console.PrintWarning("[OBA] No rays available to export.\n")

    def _remove_ray_object(self):
        from oba_rayengine.oba_ray_core import OBARayManager

        doc = self.obj.Document
        if not doc:
            return

        rm = OBARayManager(doc)
        rm.remove_fc_line_object(doc)

        App.Console.PrintMessage("[OBA] Removed ray geometry object.\n")


# ============================================================
#  V I E W  P R O V I D E R
# ============================================================


class RayConfigViewProvider(OBAViewProviderBase):
    # ICON = "oba_rayconfig.svg"

    def __init__(self, vobj):
        super().__init__(vobj)
        self.dialog_class = RayConfigDialog


# ============================================================
#  S K A P A  /  H Ä M T A  (S I N G L E T O N)
# ============================================================


def OBA_CreateRayConfig(doc=None, show_dialog=True):
    """
    Skapar (eller hämtar) RayConfig.
    Beter sig exakt som OBA_CreateMirror:
    - säker singleton
    - proxy + viewprovider
    - recompute
    - visa dialog
    """
    doc = doc or App.ActiveDocument or App.newDocument()
    from oba_objects.oba_base import _trigger_ray_engine

    # 0. Finns den redan? → använd den
    cfg = doc.getObject("OBARayConfig")
    if cfg:
        _trigger_ray_engine(reason="rayconfig_opened", source=cfg, force=True)

        # if show_dialog:
        #     RayConfigDialog(cfg).show()

        # RayConfigDialog(cfg).show()
        return cfg

    # 1. Skapa objektet
    cfg = doc.addObject("App::DocumentObjectGroupPython", "OBARayConfig")

    # 2. Koppla Proxy (Python-logik)
    OBARayConfig(cfg)

    # 3. Koppla ViewProvider (GUI-logik)
    if App.GuiUp:
        RayConfigViewProvider(cfg.ViewObject)

    # 4. Recompute
    doc.recompute()

    # 5. Visa dialogen direkt vid skapande
    if show_dialog:
        RayConfigDialog(cfg).show()

    return cfg
