# oba_ray_collector.py

import FreeCAD as App
import FreeCADGui as Gui
import Part
import traceback
from PySide import QtCore, QtWidgets
import time
from logger import get_logger

from .oba_ray_scene import collect_scene
from .oba_ray_trace import trace_emitter, trace_beam
from .oba_ray_collector_view import visualize_rays
from .oba_ray_core import OBARay, OBARayManager


class OBARayCollector:
    """FeaturePython-proxy for the Ray Collector."""

    def __init__(self, obj):
        obj.Proxy = self
        self.Object = obj

        # --- IN-COMPUTE FLAG ---
        self._in_compute = False

        self.rays = []  # referensen som innehåller alla rays
        self._setup_timer()

        self._scene_state = {}  # Används för scene visulaiseringen
        # self.disable_all_beam_previews()

        # Properties
        if not hasattr(obj, "TraceMode"):
            obj.addProperty(
                "App::PropertyEnumeration",
                "TraceMode",
                "TraceSettings",
                "Raytracing Backend Method",
            )
            obj.TraceMode = ["OCC", "Mesh"]
            obj.TraceMode = "Mesh"

        if not hasattr(obj, "DisableDebounce"):
            obj.addProperty(
                "App::PropertyBool",
                "DisableDebounce",
                "TraceSettings",
                "Disable debounce (always force raytrace)",
            ).DisableDebounce = False

        if not hasattr(obj, "MeshTolerance"):
            obj.addProperty(
                "App::PropertyFloat",
                "MeshTolerance",
                "MeshSettings",
                "Mesh tessellation tolerance [mm] (less = finer mesh)",
            ).MeshTolerance = 50.00

        if not hasattr(obj, "MeshRayMultiplier"):
            obj.addProperty(
                "App::PropertyInteger",
                "MeshRayMultiplier",
                "MeshSettings",
                "Multiplier for ray count when using Mesh mode",
            ).MeshRayMultiplier = 5

        if not hasattr(obj, "DrawMeshTriangles"):
            obj.addProperty(
                "App::PropertyBool",
                "DrawMeshTriangles",
                "Visualization_Mesh",
                "Draw mesh triangles in 3D view (debug)",
            ).DrawMeshTriangles = False

        if not hasattr(obj, "DrawVertexNormals"):
            obj.addProperty(
                "App::PropertyBool",
                "DrawVertexNormals",
                "Visualization_Mesh",
                "Draw vertex normals in 3D view (debug)",
            ).DrawVertexNormals = True

        if not hasattr(obj, "VertexNormalLength"):
            obj.addProperty(
                "App::PropertyFloat",
                "VertexNormalLength",
                "Visualization_Mesh",
                "Längd på debug-visade vertex-normaler",
            ).VertexNormalLength = 2.0

        if not hasattr(obj, "RaysToObject"):
            obj.addProperty(
                "App::PropertyBool",
                "RaysToObject",
                "Visualization",
                "Generate a geometry object from rays",
            ).RaysToObject = False

        if not hasattr(obj, "SceneIsolation"):
            obj.addProperty(
                "App::PropertyBool",
                "SceneIsolation",
                "Visualization",
                "Isolera optiska objekt: gör allt annat transparent",
            ).SceneIsolation = False

        if not hasattr(obj, "RayBounceMin"):
            obj.addProperty(
                "App::PropertyInteger",
                "RayBounceMin",
                "Visualization",
                "Minsta bounce-index som visas (0 = första strålen)",
            ).RayBounceMin = 0

        if not hasattr(obj, "RayBounceMax"):
            obj.addProperty(
                "App::PropertyInteger",
                "RayBounceMax",
                "Visualization",
                "Största bounce-index som visas (-1 = obegränsat)",
            ).RayBounceMax = -1

        if not hasattr(obj, "ColorByBounce"):
            obj.addProperty("App::PropertyBool", "ColorByBounce", "Visualization", "Färgsätt rays baserat på bounce_count").ColorByBounce

        if not hasattr(obj, "RayLineWidth"):
            obj.addProperty("App::PropertyFloat", "RayLineWidth", "Visualization", "Tjocklek på ray-linjer i Coin-visualiseringen").RayLineWidth = 2.0

    # ----------------------------------------------------------

    # ----------------------------------------------------------

    def _setup_timer(self):
        self._debounce = QtCore.QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._run_raytrace)

    # ----------------------------------------------------------

    def trigger_recompute(self, force=False):
        """
        Called by Emitters, Mirrors, Lenses, Absorbers.
        - force=True → bypass debounce
        - Object.DisableDebounce=True → bypass debounce
        """

        if not hasattr(self, "Object"):
            return  # objektet är inte färdigrestaurerat ännu, kan ske vid reopen

        if getattr(self.Object, "RunMode", "AUTO") == "MANUAL":
            return

        # Bypass via argument eller property
        if force or getattr(self.Object, "DisableDebounce", False):
            self._run_raytrace(force=True)
            return

        if not hasattr(self, "_in_compute"):
            self._in_compute

        # 🌟 BLOCK IF TRACE ALREADY RUNNING
        if self._in_compute:
            return
        # Stoppa tracen om objektet är dolt (Visibility=False)
        # if not self.Object.Active:
        #     return

        # one debouncer to rule them all
        self._debounce.start(300)

    # ----------------------------------------------------------

    def _run_raytrace(self, force=False):
        """Debouncer just fired → perform the tracing."""

        if not hasattr(self, "_in_compute"):
            self._in_compute

        if self._in_compute and not force:
            return

        self._in_compute = True
        try:
            App.Console.PrintLog("🔆 RayCollector: starting tracing...\n")
            self.Object.touch()

            if self.Object.Document:
                self.Object.Document.recompute()
        finally:
            self._in_compute = False

    # ----------------------------------------------------------

    def execute(self, obj):
        if not obj.ViewObject.Visibility:
            return

        log = get_logger()
        log.start("TOTAL", "RayCollector Execute()")

        self._in_compute = True
        trace_mode = obj.TraceMode
        ray_multiplier = obj.MeshRayMultiplier if trace_mode == "Mesh" else 1

        try:
            # 1. Samla scenen
            log.start("SCENE", "Collecting scene")
            beams, emitters, ray_targets = collect_scene(obj.Document)
            log.end("SCENE")

            # 2. Initiera motorn
            log.start("BVH", f"Building BVH / Intersect engine ({trace_mode})")
            if trace_mode == "OCC":
                engine = ray_targets
            elif trace_mode == "Mesh":
                from .oba_intersect_mesh import build_mesh_engine

                engine = build_mesh_engine(ray_targets, obj.MeshTolerance)

                if obj.DrawMeshTriangles:
                    debug_draw_triangles("Mesh", ray_targets, engine, show_triangles=True, show_vertex_normals=obj.DrawVertexNormals, normal_length=obj.VertexNormalLength)
            log.end("BVH")

            # 3. TRACE
            rm = OBARayManager()

            # --- Rensning ---
            rm.clear(mode="final")  # Ta bort gamla skarpa strålar
            rm.clear(mode="preview")  # Ta bort beam-previews så de inte stör vyn
            # 🔥 FULL reset av ray state (men inte Coin root)
            rm.clear(mode=None)

            # --- Emitters ---
            log.start("TRACE_EMITTERS", "Tracing emitters")
            for emitter in emitters:
                trace_emitter(emitter, engine, emitter.MaxBounce, emitter.MaxRayLength, trace_mode, ray_multiplier=ray_multiplier, mode="final")
            log.end("TRACE_EMITTERS")

            # --- Beams ---
            log.start("TRACE_BEAMS", "Tracing beams")
            for beam in beams:
                trace_beam(beam, engine, beam.MaxBounce, beam.MaxRayLength, trace_mode, ray_multiplier=ray_multiplier, mode="final")
            log.end("TRACE_BEAMS")

            # 4. VISUALISERA
            log.start("VIS", "Visualizing rays")
            rm.visualize(bounce_min=obj.RayBounceMin, bounce_max=obj.RayBounceMax, line_width=obj.RayLineWidth, color_by_bounce=obj.ColorByBounce, mode="final")
            log.end("VIS")

        except Exception as e:
            import traceback

            App.Console.PrintError(f"Raytrace failed: {e}\n{traceback.format_exc()}\n")
        finally:
            self._in_compute = False
            log.end("TOTAL")
            log.flush()
            log.clear()

    # ----------------------------------------------------------
    # ----------------------------------------------------------

    def onChanged(self, obj, prop):
        # 🛑 Blockera under compute/recompute
        if getattr(self, "_in_compute", False):
            return

        # ✅ GUARD: runtime-fält kan saknas vid restore
        if not hasattr(self, "_scene_state"):
            self._scene_state = {}

        # --------------------------------------------------
        # Scene isolation
        # --------------------------------------------------
        if prop == "SceneIsolation":
            if not obj.Document:
                return

            set_scene_isolation(
                obj.Document,
                obj.SceneIsolation,
                self._scene_state,
            )

        # --------------------------------------------------
        # Debug mesh triangles OFF → rensa debug-geometri
        # --------------------------------------------------
        elif prop == "DrawMeshTriangles":
            if not obj.DrawMeshTriangles:
                if obj.Document:
                    clear_debug_objects(obj.Document)

        elif prop == "RaysToObject":
            if obj.RaysToObject:
                # Skapa rayline-objektet
                OBARayManager().create_fc_line_object(obj.Document)
            else:
                # Ta bort objektet
                OBARayManager().remove_fc_line_object(obj.Document)

    # --------------------------------------------------
    # (framtida hooks här)
    # --------------------------------------------------
    # if prop == "RunPreview":
    #     ...
    # if prop == "RunPreview" and vobj.Object.RunPreview:
    #     vobj.Object.Proxy.run_beam_preview(vobj.Object)
    #     vobj.Object.RunPreview = False  # reset

    def _trigger_initial_trace(self):
        # Guard: dokumentet måste finnas
        if not self.Object or not self.Object.Document:
            return

        # Guard: objektet måste vara synligt
        if App.GuiUp and self.Object.ViewObject and not self.Object.ViewObject.Visibility:
            return

        App.Console.PrintLog("🔁 Initial ray trace after reopen\n")
        self.trigger_recompute(force=True)

    def onDocumentRestored(self, obj):
        """Called by FreeCAD when restoring document from file."""
        obj.Proxy = self
        self.Object = obj

        # ✅ Återställ alla interna runtime-fält
        self._in_compute = False
        self._scene_state = {}
        self.rays = []

        # Timer måste återskapas manuellt
        self._setup_timer()

        App.Console.PrintLog("✅ OBARayCollector restored\n")

        # 🔥 VIKTIGT: trigga initial tracing EFTER restore
        QtCore.QTimer.singleShot(0, self._trigger_initial_trace)

    # -------- FIX: Stoppa FreeCAD från att spara proxy som JSON ----------
    def __getstate__(self):
        return None

    def __setstate__(self, state):
        pass

    def __repr__(self):
        return "OBARayCollector()"

    def __str__(self):
        return "OBARayCollector"

    # ----------------------------------------------------------
    # ----------- Utils bör flyttas till en egen fil -----------
    # ----------------------------------------------------------


import FreeCADGui as Gui
import FreeCAD as App

OPTICAL_TYPES = {"Mirror", "Absorber", "Lens"}


def set_scene_isolation(doc, enable, state_cache):
    """
    enable=True  -> isolera optiska objekt
    enable=False -> återställ tidigare ViewObject-state
    state_cache  -> dict lagrad på OBARayCollector.Proxy
    """

    if enable:
        state_cache.clear()

        for obj in doc.Objects:

            vo = obj.ViewObject if hasattr(obj, "ViewObject") else None
            if vo is None:
                continue

            # --- spara ursprungsläge ---

            state_cache[obj.Name] = {
                "Visibility": vo.Visibility,
                "Transparency": vo.Transparency if hasattr(vo, "Transparency") else None,
            }

            optical_type = getattr(obj, "OpticalType", None)

            # ✅ Optiska objekt: alltid synliga
            if optical_type in OPTICAL_TYPES:
                vo.Visibility = True
                vo.Transparency = 0
                continue

            # ✅ SubShapeBinder kopplad till optiskt objekt
            if obj.TypeId == "PartDesign::SubShapeBinder":
                try:
                    linked = obj.Support[0][0]
                    if getattr(linked, "OpticalType", None) in OPTICAL_TYPES:
                        vo.Visibility = True
                        vo.Transparency = 0
                        continue
                except Exception:
                    pass

            # ❌ Alla andra objekt → transparenta
            vo.Visibility = True
            if hasattr(vo, "Transparency"):
                vo.Transparency = 85

    else:
        # 🔁 Återställ
        for obj in doc.Objects:

            vo = obj.ViewObject if hasattr(obj, "ViewObject") else None
            if vo is None:
                continue

            st = state_cache.get(obj.Name)
            if not st:
                continue

            vo.Visibility = st["Visibility"]
            if st["Transparency"] is not None and hasattr(vo, "Transparency"):
                vo.Transparency = st["Transparency"]

        state_cache.clear()


def clear_debug_objects(doc):
    """Tar bort allt i debuggruppen, om den finns."""
    grp = doc.getObject("DebugGeometry")
    if not grp:
        return

    for obj in list(grp.Group):
        try:
            doc.removeObject(obj.Name)
        except Exception:
            pass


def debug_draw_triangles(
    trace_mode,
    ray_targets,
    engine,
    name_prefix="DbgTri",
    show_triangles=True,
    show_vertex_normals=True,
    normal_length=2.0,
):
    import FreeCAD as App
    import Part
    import numpy as np

    doc = App.ActiveDocument
    if not doc:
        doc = App.newDocument("Debug")

    # -------------------------------------------------------
    # ✅ Se till att en Debug‑grupp finns
    # -------------------------------------------------------
    dbg_grp = doc.getObject("DebugGeometry")
    if not dbg_grp:
        dbg_grp = doc.addObject("App::DocumentObjectGroup", "DebugGeometry")

    # -------------------------------------------------------
    # ✅ Rensa tidigare debug‑geometri
    # -------------------------------------------------------
    clear_debug_objects(doc)

    # -------------------------------------------------------
    # ✅ Skapa trianglar per target
    # -------------------------------------------------------
    for target in ray_targets:

        obj_props = target["props"]
        obj_name = obj_props.get("Name", "Unknown")
        shapes = []

        # =====================================================
        # ✅ MESH MODE (ny Numpy-baserad pipeline)
        # =====================================================
        if trace_mode == "Mesh":

            tri_array = target.get("tri_array")
            norm_array = target.get("norm_array")

            if tri_array is None:
                print(f"[debug_draw_triangles] No tri_array for {obj_name}")
                continue

            # Iterera över trianglar
            for i in range(len(tri_array)):

                v0, v1, v2 = [App.Vector(*p) for p in tri_array[i]]

                # --- TRIANGLE ---
                if show_triangles:
                    try:
                        wire = Part.makePolygon([v0, v1, v2, v0])
                        shapes.append(Part.Face(wire))
                    except Exception:
                        pass

                # --- VERTEX NORMALS ---
                if show_vertex_normals:
                    for v, n in zip((v0, v1, v2), norm_array[i]):
                        n_vec = App.Vector(*n)
                        if n_vec.Length > 0:
                            n_vec.normalize()
                            shapes.append(Part.makeLine(v, v + n_vec * normal_length))

        # =====================================================
        # ✅ OCC MODE (oförändrat)
        # =====================================================
        elif trace_mode == "OCC":
            return

        # =====================================================
        # ✅ Skapa FreeCAD‑objekt för debug‑geometrin
        # =====================================================
        if not shapes:
            continue

        comp = Part.Compound(shapes)
        dbg_name = f"{name_prefix}_{obj_name}"

        fc_obj = doc.addObject("Part::Feature", dbg_name)
        fc_obj.Shape = comp

        # ✅ Lägg till debug‑flagga
        if not hasattr(fc_obj, "IsDebugObject"):
            fc_obj.addProperty("App::PropertyBool", "IsDebugObject", "Debug", "Intern flagga för att markera debugtrianglar")
        fc_obj.IsDebugObject = True

        # ✅ Flytta objektet in i debuggruppen
        dbg_grp.addObject(fc_obj)

        # ✅ Styla debug‑visning
        vo = fc_obj.ViewObject
        vo.DisplayMode = "Flat Lines"
        vo.ShapeColor = (1.0, 1.0, 0.0)
        vo.LineColor = (1.0, 0.3, 0.0)

    doc.recompute()
