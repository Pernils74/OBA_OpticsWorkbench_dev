# oba_ray.py
import FreeCAD as App
import uuid
from pivy import coin
import FreeCADGui as gui
import math


class OBARay:
    def __init__(self, start_point, direction, wavelength=550.0, power=1.0, emitter_id=None, bounce_count=0, mode="final", parent_id=None, medium_stack=None, path_id=None):
        self.id = uuid.uuid4()  # Unikt ID för varje strål-segment/gren
        self.parent_id = parent_id  # Koppling till ursprungsstrålen

        if path_id is None:
            self.path_id = self.id  # root-ray
        else:
            self.path_id = path_id

        self.points = [start_point]  # Lista med App.Vector
        self.direction = direction.normalize()

        self.wavelength = wavelength
        self.power = power  # lambert power
        self.emitter_id = emitter_id  # vilken source

        self.mode = mode  # 🔥 final = vanlig raytrace, preview = temporärt för beam visningen

        self.bounce_count = bounce_count

        self.last_facet = None  # Används i propogate frö att inte "fastna" i samma yta vid hit
        self.last_target_id = None  # “Vilken triangel/facet på vilket target träffades senast, så vi inte träffar exakt samma igen p.g.a. numerik.”

        self.last_hit_label = None  # label på senaste träffad yta. Sätts i add_segment
        self.prev_hit_label = None  # label på föregående träffad yta. Sätts i spawn_child

        self.history = []  # historik

        if medium_stack is None:
            self.medium_stack = [1.0]  # Startar i luft
        else:
            self.medium_stack = list(medium_stack)

        OBARayManager().add(self)

    def add_segment(self, end_point, interaction_type=None, hit_face_label=None):  # origin_face=None, origin_label=None):
        self.points.append(end_point)

        # Logga senaste träffade yta.
        if hit_face_label is not None:
            self.last_hit_label = hit_face_label

        if interaction_type:
            self.history.append(interaction_type)

    # -----------------------------
    # MEDIUM HELPERS
    # -----------------------------
    @property
    def current_n(self):
        return self.medium_stack[-1]

    def enter_medium(self, n):
        self.medium_stack.append(n)

    def exit_medium(self):
        if len(self.medium_stack) > 1:
            return self.medium_stack.pop()
        return self.medium_stack[-1]

    @property
    def last_point(self):
        return self.points[-1]

    def move_origin(self, new_point):
        """Uppdaterar den senaste punkten (används för offset/reflektion)"""
        self.points[-1] = new_point

    # -----------------------------
    # LOGGNING
    # -----------------------------

    def log_bounce(
        self,
        object_name,
        optical_type,
        last_hit_label,
        prev_hit_label,
        hit_point,
        normal,
        incoming_dir,
        outgoing_dir,
        extra=None,
    ):
        entry = {
            # Identitet
            "ray_id": str(self.id),
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "path_id": str(self.path_id),
            "bounce_index": self.bounce_count,
            # Optisk kontext
            "object_name": object_name,
            "optical_type": optical_type,  # Mirror /Lens / Absorber ...
            # Topologi
            "last_hit_label": last_hit_label,  # Vart ray har sist aggerat emot
            "prev_hit_label": prev_hit_label,  # "prev_face": str(prev_face) if prev_face else None,
            # Geometri
            "hit_point": (hit_point.x, hit_point.y, hit_point.z),
            "normal": (normal.x, normal.y, normal.z),
            "incoming_dir": ((incoming_dir.x, incoming_dir.y, incoming_dir.z) if incoming_dir else None),
            "outgoing_dir": ((outgoing_dir.x, outgoing_dir.y, outgoing_dir.z) if outgoing_dir else None),
        }

        if extra:
            entry["extra"] = extra

        self.history.append(entry)

    # -----------------------------
    # BRANCHING (NY!)
    # parent_id   vilken händelse skapade mig
    # path_id     vilken fysisk stråle tillhör jag?
    # -----------------------------
    def spawn_child(self, direction, power, offset, wavelength=None, extra=None):
        """
        Skapar en ny stråle som gren från denna.
        wavelength: Om None, ärvs förälderns våglängd (bra för speglar).
                   Om satt, används den nya (bra för prismor/gitter).
        """
        child_wavelength = wavelength if wavelength is not None else self.wavelength

        child = OBARay(
            start_point=self.last_point + offset,
            direction=direction,
            wavelength=child_wavelength,
            power=power,
            emitter_id=self.emitter_id,
            bounce_count=self.bounce_count,  # Behåll index för samma interaktion
            mode=self.mode,
            parent_id=self.id,  # vilken händelse skapade mig
            path_id=self.path_id,  # Ärver path_id så att alla i samma "gren" har samma path_id. vilken fysisk stråle tillhör jag?
            # 🔥 ✅ SKAPA EN KOPIA AV LISTAN (list() eller .copy())
            medium_stack=list(self.medium_stack),
        )

        child.last_facet = self.last_facet
        child.last_target_id = self.last_target_id

        child.prev_hit_label = self.last_hit_label  # ✅ Ärver ifrån parent

        if extra:
            # Istället för att bara appenda extra till history,
            # kan vi logga det som en "spawn"-händelse
            child.history.append({"type": "spawn_info", "data": extra})

        return child


# from .oba_ray import OBARayManager
# total = OBARayManager().total_hits_on(absorber)

# SceneGraph
#  └── RayManagerRoot
#       ├── PreviewLayer   👈 beam preview
#       └── FinalLayer     👈 raycollector


class OBARayManager:
    # _instance = None
    _instances = {}

    # def __new__(cls):
    #     if cls._instance is None:
    #         cls._instance = super().__new__(cls)
    #         cls._instance.clear()
    #         cls._instance._listeners = set()
    #     return cls._instance

    def __new__(cls, document=None):
        import FreeCAD as App

        if document is None:
            document = App.ActiveDocument

        if document is None:
            raise RuntimeError("No active document for OBARayManager")

        doc_id = id(document)

        if doc_id not in cls._instances:
            inst = super().__new__(cls)
            inst._init_for_document(document)
            cls._instances[doc_id] = inst

        return cls._instances[doc_id]

    def _init_for_document(self, document):
        self.document = document
        self.rays = []
        self._listeners = set()

        # Coin3D-noder är dokument-/view-specifika
        self._coin_root = None
        self._preview_node = None
        self._normal_preview_node = None
        self._final_node = None

    # -----------------------------
    # Observer API
    # -----------------------------
    def add_listener(self, fn):
        self._listeners.add(fn)

    def remove_listener(self, fn):
        self._listeners.discard(fn)

    def _notify(self):
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                pass

    # -----------------------------
    # Övrig API
    # -----------------------------

    def add(self, ray):
        self.rays.append(ray)

    def clear(self, emitter_id=None, mode=None):
        """
        Rensar ray-data och/eller Coin3D-visualisering.

        mode:
          - None              → rensa ALLT
          - "preview"         → rensa preview-rays
          - "final"           → rensa final-rays
          - "normal_preview"  → rensa endast normal-preview (UI)
        """
        # 1. Rensa Python ray-lista (endast ray-relaterade modes)
        if mode in (None, "preview", "final"):
            if emitter_id is None and mode is None:
                self.rays = []
            else:
                self.rays = [r for r in self.rays if not ((emitter_id is None or r.emitter_id == emitter_id) and (mode is None or r.mode == mode))]

        # 2. Rensa Coin3D-lager
        if not (hasattr(self, "_coin_root") and self._coin_root):
            return

        # 🔹 Preview rays
        if mode in (None, "preview"):
            if hasattr(self, "_preview_node"):
                self._preview_node.removeAllChildren()

        # 🔹 Final rays
        if mode in (None, "final"):
            if hasattr(self, "_final_node"):
                self._final_node.removeAllChildren()

        # 🔹 Normal preview
        if mode in (None, "normal_preview"):
            if hasattr(self, "_normal_preview_node"):
                self._normal_preview_node.removeAllChildren()

        # 3. Tvinga refresh
        self._coin_root.touch()

    def clear_all(self):
        """Rensar ALLT: rays + Coin3D-visualisering."""
        self.rays = []
        if hasattr(self, "_coin_root") and self._coin_root:
            # 1. Rensa barnen
            self._preview_node.removeAllChildren()
            self._final_node.removeAllChildren()
            self._normal_preview_node.removeAllChildren()

            # 2. Ta bort själva roten från scenegraph om möjligt
            import FreeCADGui as gui

            view = gui.activeDocument().activeView()
            if view:
                root = view.getSceneGraph()
                if root.findChild(self._coin_root) != -1:
                    root.removeChild(self._coin_root)

            # Nollställ referensen så att visualize() tvingas bygga om nästa gång
            self._coin_root = None
        # touchar all beams så att de återställs i preview läget
        import FreeCAD as App

        for obj in App.ActiveDocument.Objects:
            # Kolla om objektet är en Beam via din OpticalType-property
            if hasattr(obj, "OpticalType") and obj.OpticalType == "Beam":
                if hasattr(obj.Proxy, "run_beam_preview"):
                    # Anropa direkt för att slippa vänta på FreeCADs interna kö
                    obj.Proxy.run_beam_preview(obj)

    def get_children(self, ray_id):
        return [r for r in self.rays if r.parent_id == ray_id]

    def get_all_rays(self):
        """Returnerar alla strålar för visualisering/export."""
        return self.rays

    def count_hits_on_object(self, obj):
        if obj is None:
            return 0

        name = obj.Name
        count = 0

        for ray in self.rays:
            # En generator-expression inuti sum() är ofta snabbare i Python
            count += sum(1 for h in ray.history if isinstance(h, dict) and h.get("object_name") == name)

        return count

    def create_fc_line_object(self, doc, name="RayPaths"):
        """
        Skapar ett Part::Feature med alla ray-segment som linjer.
        Ett linje-segment = mellan två sample-punkter i ray.points.
        """
        import Part
        import FreeCAD as App

        # Ta bort gammalt objekt om det finns
        old = doc.getObject(name)
        if old:
            doc.removeObject(name)

        shapes = []

        for ray in self.rays:
            pts = ray.points
            for i in range(len(pts) - 1):
                p1 = pts[i]
                p2 = pts[i + 1]
                try:
                    shapes.append(Part.makeLine(p1, p2))
                except Exception:
                    pass

        if not shapes:
            App.Console.PrintWarning("[OBARayManager] No ray lines to create.\n")
            return None

        comp = Part.Compound(shapes)
        obj = doc.addObject("Part::Feature", name)
        obj.Shape = comp

        # Style
        vo = obj.ViewObject
        vo.LineColor = (1.0, 0.0, 0.0)
        vo.LineWidth = 2
        vo.DisplayMode = "Wireframe"

        return obj

    def remove_fc_line_object(self, doc, name="RayPaths"):
        old = doc.getObject(name)
        if old:
            doc.removeObject(name)

    def collect_render_data(self, bounce_min, bounce_max, mode, cfg=None):
        doc = self.document
        per_owner = {}
        for ray in self.rays:
            if ray.mode != mode:
                continue
            if bounce_min is not None and ray.bounce_count < bounce_min:
                continue
            if bounce_max is not None and ray.bounce_count > bounce_max:
                continue

            if cfg is not None:
                owner = cfg
            else:
                owner = doc.getObject(ray.emitter_id)
            if owner is None:
                continue

            per_owner.setdefault(owner, []).append(ray)

        return per_owner

    def _ensure_coin_layers(self):
        view = gui.activeDocument().activeView()
        root = view.getSceneGraph()

        if self._coin_root is None or self._coin_root.getRefCount() == 0:
            self._coin_root = coin.SoSeparator()
            root.addChild(self._coin_root)

        if not hasattr(self, "_preview_node") or self._preview_node is None:
            self._preview_node = coin.SoSeparator()
            self._coin_root.addChild(self._preview_node)

        if not hasattr(self, "_final_node") or self._final_node is None:
            self._final_node = coin.SoSeparator()
            self._coin_root.addChild(self._final_node)

        if not hasattr(self, "_normal_preview_node") or self._normal_preview_node is None:
            self._normal_preview_node = coin.SoSeparator()
            self._coin_root.addChild(self._normal_preview_node)

    def visualize(self, bounce_min=None, bounce_max=None, line_width=2.0, color_by_bounce=False, mode="final"):

        # print("ritar mode:", mode)

        # ============================================================
        # 1. ENSURE ROOT EXISTS
        # ============================================================
        self._ensure_coin_layers()

        # ============================================================
        # 2. SELECT TARGET NODE
        # ============================================================
        target_node = self._preview_node if mode == "preview" else self._final_node

        # ============================================================
        # 3. CLEAR
        # ============================================================
        target_node.removeAllChildren()

        # ============================================================
        # 4. DATA PREP
        # ============================================================
        if bounce_max == -1:
            bounce_max = None

        max_bounce_in_data = max((r.bounce_count for r in self.rays), default=0)

        # ============================================================
        # 5. STYLE
        # ============================================================
        draw_style = coin.SoDrawStyle()
        draw_style.lineWidth.setValue(line_width)
        target_node.addChild(draw_style)

        # ============================================================
        # 6. COLLECT ALL DATA (🔥 KEY OPTIMIZATION)
        # ============================================================
        all_coords = []
        num_vertices = []
        colors = []

        valid = 0

        for ray in self.rays:
            # if ray.power <= 0.0:
            #     continue

            if ray.mode != mode:
                continue

            if bounce_min is not None and ray.bounce_count < bounce_min:
                continue
            if bounce_max is not None and ray.bounce_count > bounce_max:
                continue

            pts = ray.points
            if len(pts) < 2:
                continue

            valid += 1

            # --- samla koordinater ---
            for p in pts:
                all_coords.append((p.x, p.y, p.z))

            num_vertices.append(len(pts))

            # --- färg ---
            if color_by_bounce:
                r, g, b = self._bounce_to_rgb(ray.bounce_count, bounce_min or 0, max_bounce_in_data)
            else:
                r, g, b = self._wavelength_to_rgb(ray.wavelength)

            colors.append((r, g, b))

        # print("VALID RAYS:", valid)

        if not all_coords:
            self._coin_root.touch()
            gui.updateGui()
            return

        # ============================================================
        # 7. BUILD SINGLE COIN GRAPH (🔥 HUGE SPEEDUP)
        # ============================================================
        root_sep = coin.SoSeparator()

        # --- Material ---
        mat = coin.SoMaterial()
        mat.diffuseColor.setValues(0, len(colors), colors)
        root_sep.addChild(mat)

        # --- Bind per ray ---
        binding = coin.SoMaterialBinding()
        binding.value = coin.SoMaterialBinding.PER_PART
        root_sep.addChild(binding)

        # --- Coordinates ---
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(all_coords), all_coords)
        root_sep.addChild(coords)

        # --- LineSet ---
        line = coin.SoLineSet()
        line.numVertices.setValues(0, len(num_vertices), num_vertices)
        root_sep.addChild(line)

        target_node.addChild(root_sep)

        # ============================================================
        # 8. REFRESH
        # ============================================================
        self._coin_root.touch()
        gui.updateGui()

        self._notify()  # ✅ Trigger för notify listeners

    def _rotation_from_y(self, direction: App.Vector):
        d = direction.normalize()
        y = App.Vector(0, 1, 0)

        axis = y.cross(d)
        if axis.Length < 1e-9:
            if y.dot(d) > 0:
                return coin.SbRotation()
            else:
                return coin.SbRotation(coin.SbVec3f(1, 0, 0), math.pi)

        axis.normalize()
        angle = math.acos(max(-1.0, min(1.0, y.dot(d))))
        return coin.SbRotation(coin.SbVec3f(axis.x, axis.y, axis.z), angle)

    def draw_normal_arrow(
        self,
        origin,
        direction,
        head_length=0.35,
        head_radius=0.12,
        color=(1, 0, 0),
        mode="normal_preview",
    ):

        self._ensure_coin_layers()

        if mode == "normal_preview":
            target = self._normal_preview_node
        else:
            raise ValueError("Unsupported arrow mode")

        target.removeAllChildren()

        if direction.Length == 0:
            return

        d = direction.normalize()

        sep = coin.SoSeparator()

        # Material
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*color)
        sep.addChild(mat)

        # ============================================================
        # Transform (Y → direction)
        # ============================================================
        tr = coin.SoTransform()
        tr.translation.setValue(origin.x, origin.y, origin.z)
        tr.rotation.setValue(self._rotation_from_y(d))
        sep.addChild(tr)

        # ============================================================
        # Cone (pilhuvud)
        # ============================================================
        head_tr = coin.SoTransform()

        # Placera så att konens bas ligger vid origin
        head_tr.translation.setValue(0, head_length * 0.05, 0)

        sep.addChild(head_tr)

        head = coin.SoCone()
        head.bottomRadius = head_radius
        head.height = head_length
        sep.addChild(head)

        target.addChild(sep)

        self._coin_root.touch()

        import FreeCADGui as gui

        gui.updateGui()

    def _wavelength_to_rgb(self, wavelength_nm):
        """
        Approximerar synligt spektrum 380–750 nm till RGB.
        Returnerar (r, g, b) i intervallet 0–1.
        """
        wl = float(wavelength_nm)

        if wl < 380 or wl > 750:
            return (0.5, 0.5, 0.5)  # grå: utanför synligt

        if wl < 440:
            r = -(wl - 440) / (440 - 380)
            g = 0.0
            b = 1.0
        elif wl < 490:
            r = 0.0
            g = (wl - 440) / (490 - 440)
            b = 1.0
        elif wl < 510:
            r = 0.0
            g = 1.0
            b = -(wl - 510) / (510 - 490)
        elif wl < 580:
            r = (wl - 510) / (580 - 510)
            g = 1.0
            b = 0.0
        elif wl < 645:
            r = 1.0
            g = -(wl - 645) / (645 - 580)
            b = 0.0
        else:
            r = 1.0
            g = 0.0
            b = 0.0

        return (r, g, b)

    def _bounce_to_rgb(self, bounce, data_min, data_max):
        """
        Röd → ljusgul colormap.
        Bounce 0  → mörkröd
        Max bounce → ljusgul
        """
        if data_max <= data_min:
            t = 0.0
        else:
            t = (bounce - data_min) / float(data_max - data_min)

        t = max(0.0, min(1.0, t))

        # R: alltid 1 (röd kanal)
        r = 1.0

        # G: ökar mjukt mot gult
        g = 0.15 + 0.85 * t  # startar mörkt, slutar ljust

        # B: låg, ökar lite för ljusgult
        b = 0.05 + 0.25 * t

        return (r, g, b)

    def _bounce_to_rgb_old(self, bounce, data_min, data_max):
        """Mappar bounce_count till RGB (0–1) med varm–kall colormap."""

        # Färdig viridis-liknande colormap (LUT)
        # Känt bra perceptuellt beteende
        _VIRIDIS_LUT = [
            (0.267, 0.005, 0.329),
            (0.283, 0.141, 0.458),
            (0.254, 0.265, 0.530),
            (0.207, 0.372, 0.553),
            (0.164, 0.471, 0.558),
            (0.128, 0.567, 0.551),
            (0.135, 0.659, 0.518),
            (0.267, 0.749, 0.441),
            (0.478, 0.821, 0.318),
            (0.741, 0.873, 0.150),
        ]

        _INFERNO_LUT = [
            (0.001, 0.000, 0.014),
            (0.120, 0.030, 0.271),
            (0.316, 0.069, 0.485),
            (0.523, 0.156, 0.445),
            (0.722, 0.328, 0.360),
            (0.888, 0.540, 0.200),
            (0.988, 0.788, 0.082),
        ]

        if data_max <= data_min:
            t = 0.0
        else:
            t = (bounce - data_min) / float(data_max - data_min)

        t = max(0.0, min(1.0, t))

        lut = _VIRIDIS_LUT
        lut = _INFERNO_LUT
        n = len(lut) - 1
        idx = t * n
        i0 = int(idx)
        i1 = min(i0 + 1, n)
        f = idx - i0

        r0, g0, b0 = lut[i0]
        r1, g1, b1 = lut[i1]

        # Linear interpolation
        return (
            r0 + f * (r1 - r0),
            g0 + f * (g1 - g0),
            b0 + f * (b1 - b0),
        )

    def get_hit_mapping(self, mode="final"):
        """
        Returnerar mapping:
        emitter_id -> set(object_names)
        """
        mapping = {}

        for ray in self.rays:
            if ray.mode != mode:
                continue

            eid = ray.emitter_id
            if not eid:
                continue

            for h in ray.history:
                if isinstance(h, dict) and "object_name" in h:
                    mapping.setdefault(eid, set()).add(h["object_name"])

        return mapping
