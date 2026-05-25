# oba_ray_engine.py

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

from .oba_ray_scene import collect_scene
from .oba_ray_trace import trace_emitter, trace_beam
from .oba_ray_core import OBARayManager

from logger import get_logger


from PySide import QtCore


class OBAGuiDispatcher:
    def __init__(self):
        self._pending = {}
        self._timer = QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._flush)

    def schedule(self, obj, rays, kwargs):
        self._pending[obj] = (rays, kwargs)
        self._timer.start(0)

    def _flush(self):
        import FreeCADGui as Gui

        for obj, (rays, kwargs) in self._pending.items():
            try:
                vp = obj.ViewObject.Proxy
                vp.update_preview(rays=rays, **kwargs)
            except Exception:
                pass

        self._pending.clear()

        view = Gui.ActiveDocument.ActiveView
        if view:
            view.redraw()


# singleton
_gui_dispatcher = OBAGuiDispatcher()


class OBARayEngine:
    """
    Runtime ray engine.
    - Hanterar debounce
    - Kör tracing
    - Läser RayConfig (FeaturePython)
    """

    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._in_compute = False
        self._dirty = False
        self._scene_state = {}  # ✅ Scene isolation
        self._scene_isolated = False  # ✅ NY FLAGGA

        self._debounce = QtCore.QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._run)

    # --------------------------------------------------
    # Public API (kallas från dispatcher)
    # --------------------------------------------------

    def notify_event(self, reason="", source=None, force=False):
        doc = source.Document if source else App.ActiveDocument
        if not doc:
            return

        cfg = doc.getObject("OBARayConfig")

        # print("[OBARayEngine] notify_event", reason, "force=" + str(force))
        # ----------------------------
        # VIEW-POLICY (ALLTID)
        # ----------------------------
        if cfg:
            self._apply_scene_isolation(cfg)
        # ----------------------------
        # TRACE-POLICY
        # ----------------------------

        # ✅ NYCKELN (läggs TIDIGT)
        if cfg and getattr(cfg, "RunMode", "AUTO") == "MANUAL" and not force:
            return  # ⛔ stoppa ALL auto-trace

        # fallback (om ingen config)
        if not cfg:
            if force:
                self._run(force=True)
            else:
                self._debounce.start(300)
            return

        # 🔄 skydd mot recursion
        if self._in_compute:
            self._dirty = True
            return

        # ⚙️ normal execution
        if force or getattr(cfg, "DisableDebounce", False):
            self._run(force=True)
        else:
            self._debounce.start(300)

    # --------------------------------------------------
    # Core execution
    # --------------------------------------------------

    def _run(self, force=False):
        # print("[OBARayEngine] _run() called with force =", force)
        if self._in_compute and not force:
            return

        self._in_compute = True
        try:
            self._trace_scene()
        finally:
            self._in_compute = False

        if self._dirty:
            self._dirty = False
            self._run(force=True)

    def _trace_scene(self):
        doc = App.ActiveDocument
        if not doc:
            return

        cfg = doc.getObject("OBARayConfig")
        # --------------------------------------------------
        # 0. Bestäm TRACE-NIVÅ (preview vs final)
        # --------------------------------------------------
        if cfg:
            run_final = App.GuiUp and hasattr(cfg, "ViewObject") and cfg.ViewObject.Visibility
            trace_mode_backend = cfg.TraceMode
            mesh_tolerance = cfg.MeshTolerance
            ray_multiplier = cfg.MeshRayMultiplier
            bounce_min = cfg.RayBounceMin
            bounce_max = cfg.RayBounceMax
            line_width = cfg.RayLineWidth
            color_by_bounce = cfg.ColorByBounce
            show_log = getattr(cfg, "ShowLog", False)
        else:
            # 🔥 Ingen RayConfig → implicit preview
            run_final = False
            trace_mode_backend = "Mesh"  # rimligt default
            mesh_tolerance = 50.0
            ray_multiplier = 1
            bounce_min = None
            bounce_max = None
            line_width = 2.0
            color_by_bounce = False
            show_log = False

        run_mode = "final" if run_final else "preview"

        log = get_logger(show_log=show_log)

        log.start("TOTAL", "RayCollector Execute()")
        # --------------------------------------------------
        # 1. Samla scenen
        # --------------------------------------------------
        log.start("SCENE", "Collecting scene")
        beams, emitters, ray_targets = collect_scene(doc)
        log.end("SCENE")

        # --------------------------------------------------
        # 2. Backend
        # --------------------------------------------------

        log.start("BVH", f"Building BVH / Intersect engine ({trace_mode_backend})")
        if trace_mode_backend == "OCC":
            engine = ray_targets
            ray_multiplier = 1
        else:
            from .oba_intersect_mesh import build_mesh_engine

            engine = build_mesh_engine(ray_targets, mesh_tolerance)
            # ray_multiplier = cfg.MeshRayMultiplier

        log.end("BVH")

        # ✅ DEBUG: visa / dölj mesh
        self._handle_mesh_debug(cfg, ray_targets, engine)

        # --------------------------------------------------
        # 3. Rensa coin3d lager
        # --------------------------------------------------
        rm = OBARayManager(doc)
        rm.clear(mode="final")
        rm.clear(mode="preview")

        # --------------------------------------------------
        # 4. TRACE
        # --------------------------------------------------
        log.start("TRACE_EMITTERS", "Tracing emitters")
        for emitter in emitters:
            max_bounce = emitter.MaxBounce if run_mode == "final" else 1  # eller 1
            max_ray_length = emitter.MaxRayLength if run_mode == "final" else getattr(emitter, "PreviewRayLength", 2.0)

            trace_emitter(
                emitter,
                engine,
                max_bounce,
                max_ray_length,
                trace_mode=trace_mode_backend,
                ray_multiplier=ray_multiplier,
                mode=run_mode,
            )
        log.end("TRACE_EMITTERS")

        log.start("TRACE_BEAMS", "Tracing beams")
        for beam in beams:
            max_bounce = beam.MaxBounce if run_mode == "final" else 1
            max_ray_length = beam.MaxRayLength if run_mode == "final" else getattr(beam, "PreviewLength", 3.0)

            trace_beam(
                beam,
                engine,
                max_bounce,
                max_ray_length,
                trace_mode=trace_mode_backend,
                ray_multiplier=ray_multiplier,
                mode=run_mode,
            )
        log.end("TRACE_BEAMS")

        # --------------------------------------------------
        # 5. Visualisera
        # --------------------------------------------------
        log.start("VIS", "Visualizing rays")

        rm.visualize(
            bounce_min=bounce_min,
            bounce_max=bounce_max,
            line_width=line_width,
            color_by_bounce=color_by_bounce,
            mode=run_mode,
        )

        # --------------------------------------------------
        # 6. Visualisera surface normals (VIEW OVERLAY)
        # --------------------------------------------------
        self._visualize_surface_normals(ray_targets)

        # if cfg is None:
        #     # Preview mode: use global visualize like old way
        #     rm.visualize(
        #         bounce_min=bounce_min,
        #         bounce_max=bounce_max,
        #         line_width=line_width,
        #         color_by_bounce=color_by_bounce,
        #         mode=run_mode,
        #     )
        # else:
        #     # Final mode: use per-object dispatch
        #     render_data = rm.collect_render_data(
        #         bounce_min=bounce_min,
        #         bounce_max=bounce_max,
        #         mode=run_mode,
        #         cfg=cfg,
        #     )

        log.end("VIS")
        log.end("TOTAL")
        log.flush("ActiveRays: " + str(len(rm.get_all_rays())))
        log.clear()

        return
        render_data = rm.collect_render_data(
            bounce_min=bounce_min,
            bounce_max=bounce_max,
            mode=run_mode,
            cfg=cfg,
        )

        self._dispatch_render_data(
            render_data,
            mode=run_mode,
            line_width=line_width,
            color_by_bounce=color_by_bounce,
        )

        # Force redraw of the 3D view
        Gui.updateGui()

    #
    #  Ta bort denna (nedan)
    #

    def _dispatch_render_data(self, render_data, *, mode, line_width, color_by_bounce):
        if not render_data:
            return
        # print("\n[OBA] dispatch_render_data", len(render_data))

        for obj, rays in render_data.items():
            try:
                vp = obj.ViewObject.Proxy
            except Exception:
                continue
            if hasattr(vp, "update_preview"):
                _gui_dispatcher.schedule(
                    obj,
                    rays,
                    dict(
                        mode=mode,
                        line_width=line_width,
                        color_by_bounce=color_by_bounce,
                    ),
                )
                # vp.update_preview(
                #     rays=rays,
                #     mode=mode,
                #     line_width=line_width,
                #     color_by_bounce=color_by_bounce,
                # )

    # OBARealtimeObserver
    #    ↓
    # _trigger_ray_engine()        # dum dispatcher
    #    ↓
    # RayEngine.notify_event()
    #    ↓
    # RayEngine._run()
    #    ↓
    # _trace_scene()               # returnerar render_data
    #    ↓
    # _dispatch_render_data()      # kopplar till VP
    #    ↓
    # ViewProvider.update_preview()
    #    ↓
    # Coin3D uppdateras live (även under drag)

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    def _handle_mesh_debug(self, cfg, ray_targets, engine):
        """
        Hanterar debug-visualisering av mesh (trianglar / vertex-normaler).
        Detta är REN VIEW-LOGIK, inte tracing.
        """
        doc = App.ActiveDocument
        if not doc:
            return

        if not cfg:
            return

        if cfg.TraceMode != "Mesh":
            # Om vi byter bort från Mesh → rensa debug
            clear_debug_objects(doc)
            return

        if cfg.DrawMeshTriangles:
            debug_draw_triangles(
                trace_mode="Mesh",
                ray_targets=ray_targets,
                engine=engine,
                show_triangles=True,
                show_vertex_normals=cfg.DrawVertexNormals,
                normal_length=cfg.VertexNormalLength,
            )
        else:
            clear_debug_objects(doc)

    def _visualize_surface_normals(self, ray_targets):
        rm = OBARayManager(App.ActiveDocument)

        # rensa ENBART normal‑lagret
        rm.clear(mode="normal_preview")

        for target in ray_targets:
            obj = target.get("obj_ref")
            if not obj:
                continue

            # 🔑 aktivt val per objekt
            if not getattr(obj, "ShowSurfaceNormal", False):
                continue

            point = target.get("surface_center")
            normal = target.get("surface_normal")
            if not point or not normal:
                continue

            flip = getattr(obj, "FlipNormal", False)
            sign = -1 if flip else 1
            # sign = -1 if obj.FlipNormal else 1

            rm.draw_normal_arrow(
                origin=point,
                direction=normal * sign,
                head_length=3,
                head_radius=0.7,
                color=(1.0, 0.2, 0.2),
                mode="normal_preview",
            )

    def _apply_scene_isolation(self, cfg):
        """
        Ren VIEW-policy.
        Påverkar aldrig tracing.
        """
        if not cfg or not cfg.Document:
            return

        # ✅ VIKTIGT: propertyn kan saknas under restore
        if not hasattr(cfg, "SceneIsolation"):
            return

        set_scene_isolation(
            cfg.Document,
            cfg.SceneIsolation,
            self._scene_state,
            already_isolated=self._scene_isolated,
        )
        # uppdatera lägesflagga
        self._scene_isolated = cfg.SceneIsolation


# ------------
# ------------


def _apply_shape_appearance(vo, rgb, transparency=0.0):
    if not vo:
        return

    r, g, b = rgb

    # Diffuse: full färg
    diffuse = (255 << 24) | (int(r * 255) << 16) | (int(g * 255) << 8) | int(b * 255)

    # Ambient: lite mörkare (precis som GUI)
    ambient = (255 << 24) | (int(r * 230) << 16) | (int(g * 230) << 8) | int(b * 230)

    mat = App.Material(
        DiffuseColor=diffuse,
        AmbientColor=ambient,
        SpecularColor=0x88FFFFFF,
        EmissiveColor=0x000000FF,
        Shininess=0.9,
        Transparency=transparency,
    )

    # 🔥 ALLTID nytt material
    vo.ShapeAppearance = ()  # clear först
    vo.ShapeAppearance = (mat,)
    vo.update()


def _set_transparency(vo, value):
    if not vo:
        return

    # ShapeBinder → transparens via material, ej här
    if vo.Object and vo.Object.TypeId == "PartDesign::ShapeBinder":
        return

    if hasattr(vo, "Transparency"):
        vo.Transparency = value


def set_color_from_optical_type(vo, optical_type):
    """
    OpticalType → visuell färg
    - ShapeBinder → ShapeAppearance (Material)
    - Vanliga objekt → ShapeColor / LineColor
    """
    if not vo or not optical_type:
        return

    rgb = COLOR_MAP.get(optical_type)
    if not rgb:
        return

    # ✅ ShapeBinder / SubShapeBinder
    if vo.Object and vo.Object.TypeId == "PartDesign::ShapeBinder":
        _apply_shape_appearance(vo, rgb, transparency=0.0)
        return

    # ✅ Vanliga objekt
    if hasattr(vo, "ShapeColor"):
        vo.ShapeColor = rgb
    if hasattr(vo, "LineColor"):
        vo.LineColor = rgb


COLOR_MAP = {
    "Mirror": (0.25, 0.7, 1.0),
    "Lens": (0.3, 1.0, 0.5),
    "Grating": (0.9, 0.6, 0.2),
    "Absorber": (0.9, 0.1, 0.1),
    "Beam": (1.0, 1.0, 0.0),
    "RayConfig": (0.8, 0.8, 0.8),
}


def set_scene_isolation(doc, enable, state_cache, already_isolated=False):

    OPTICAL_TYPES = set(COLOR_MAP.keys())

    if enable and already_isolated:
        return

    # ==================================================
    # ENABLE
    # ==================================================
    if enable:
        state_cache.clear()

        # -----------------------------
        # PASS 1: spara state + gör ALLT transparent
        # -----------------------------
        for obj in doc.Objects:
            vo = getattr(obj, "ViewObject", None)
            if not vo:
                continue

            state_cache[obj.Name] = {
                "Visibility": vo.Visibility,
                "Transparency": vo.Transparency if hasattr(vo, "Transparency") else None,
                "ShapeColor": vo.ShapeColor if hasattr(vo, "ShapeColor") else None,
                "LineColor": vo.LineColor if hasattr(vo, "LineColor") else None,
                "ShapeAppearance": getattr(vo, "ShapeAppearance", None),
            }

            vo.Visibility = True
            _set_transparency(vo, 85)

        # -----------------------------
        # PASS 2: optiska huvudobjekt
        # -----------------------------
        for obj in doc.Objects:
            vo = getattr(obj, "ViewObject", None)
            if not vo:
                continue

            ot = getattr(obj, "OpticalType", None)
            if ot in OPTICAL_TYPES:
                _set_transparency(vo, 20)
                set_color_from_optical_type(vo, ot)

        # -----------------------------
        # PASS 3: ShapeBinders kopplade till optik
        # -----------------------------
        for obj in doc.Objects:
            if obj.TypeId != "PartDesign::ShapeBinder":
                continue

            vo = obj.ViewObject

            try:
                linked = obj.Support[0][0]
                ot = getattr(linked, "OpticalType", None)

                if ot in OPTICAL_TYPES:
                    vo.Visibility = True
                    set_color_from_optical_type(vo, ot)

            except Exception:
                pass

    # ==================================================
    # DISABLE (RESTORE)
    # ==================================================
    else:
        for obj in doc.Objects:
            vo = getattr(obj, "ViewObject", None)
            if not vo:
                continue

            st = state_cache.get(obj.Name)
            if not st:
                continue

            vo.Visibility = st["Visibility"]

            if st["Transparency"] is not None:
                _set_transparency(vo, st["Transparency"])

            if st["ShapeColor"] is not None and hasattr(vo, "ShapeColor"):
                vo.ShapeColor = st["ShapeColor"]

            if st["LineColor"] is not None and hasattr(vo, "LineColor"):
                vo.LineColor = st["LineColor"]

            if st.get("ShapeAppearance") is not None:
                vo.ShapeAppearance = st["ShapeAppearance"]

        state_cache.clear()


# --------------------------------------------
# --------------------------------------------
# --------------------------------------------
# --------------------------------------------
# --------------------------------------------
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
    # import FreeCAD as App
    import Part

    # import numpy as np

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
        # if trace_mode == "Mesh":
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
        # elif trace_mode == "OCC":
        #     return
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
