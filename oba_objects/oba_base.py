# oba_ray_base.py

# Document
#  ├─ OBAElementProxy        ← optisk logik
#  │    └─ Binders           ← koppling till geometri
#  │
#  ├─ OBAViewProviderBase    ← ikon + dubbelklick
#  │
#  ├─ OBABaseDialog          ← användar‑UI
#  │    └─ OBASelectionObserver
#  │
#  └─ OBARealtimeObserver    ← global reaktion på förändringar


import os
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore

from oba_rayengine.oba_ray_engine import OBARayEngine

BASE_PATH = os.path.dirname(__file__)

# ============================================================
# Ray engine trigger (central point)
# ============================================================


def _rayengine_debug_hook(reason="", source=None, engine=None):
    """
    Hook för debug / logging / metrics.

    - Kallas ALLTID före trace
    - Kan bytas ut, utökas eller kopplas bort helt
    """
    if not App.ParamGet("User parameter:BaseApp/Preferences/OBA").GetBool("RayDebug", False):
        return
    src = source.Name if source else "<None>"
    App.Console.PrintMessage(f"[OBA-RAY] trigger from={src} reason='{reason}'\n")


def _trigger_ray_engine(reason="", source=None, force=False):
    """
    Central dispatcher för ray tracing.

    - Anropas av DocumentObserver, Proxy, Dialoger
    - Innehåller ALL routing, debug och policy
    """

    doc = source.Document if source else App.ActiveDocument
    if not doc:
        return

    # if hasattr(App, "_OBARealtimeObserver"):
    #     if App._OBARealtimeObserver.drag_active:
    #         # 🔕 All ray triggers blocked during drag
    #         return

    # engine = doc.getObject("OBARayConfig")  # framtida RayConfig
    # if not engine or not hasattr(engine.Proxy, "trigger_recompute"):
    #     return

    # --------------------------------------------------
    # 🔎 DEBUG / HOOK
    # --------------------------------------------------
    # _rayengine_debug_hook(
    #     reason=reason,
    #     source=source,
    #     engine=engine,
    # )

    # --------------------------------------------------
    # 🔥 DELEGATION – här slutar observerns ansvar
    # --------------------------------------------------
    # engine.Proxy.trigger_recompute()

    # if reason == "show_surface_normal_toggled":
    #     OBARayEngine.instance()._visualize_surface_normals(source)

    OBARayEngine.instance().notify_event(
        reason=reason,
        source=source,
        force=force,
    )


# ============================================================
# GLOBAL Document observer (endast EN)
# ============================================================


def is_interactive_transform():
    # 1. GUI‑kommandon (kan vara instabila!)
    cmds = (
        "Std_TransformManip",
        "Std_Transform",
        "Draft_Move",
        "Draft_Rotate",
        "Draft_Translate",
    )

    active_cmd = False
    for cmd in cmds:
        try:
            if Gui.isCommandActive(cmd):
                active_cmd = True
                break
        except Exception:
            # FreeCAD GUI är inte redo / kommando saknas
            continue

    # 2. Aktiv dialog (TaskPanel)
    try:
        is_editing = Gui.Control.activeDialog() is not None
    except Exception:
        is_editing = False

    return active_cmd or is_editing


# för att hantera drag/placement
class OBARealtimeObserver:
    """
    Global DocumentObserver för OBA.

    PRINCIP:
    - ShapeBinders är derivat → ignoreras som triggers
    - Källobjekt (Body / optiskt objekt) är trigger-enheter
    - Flera binder-uppdateringar samlas → EXAKT EN ray trace
    """

    enabled = True

    def __init__(self):
        # Samlar "sources" som ändrats under samma FreeCAD-update
        self._dirty_sources = set()

        self.drag_active = False

        # QTimer används för att låta FreeCAD färdigställa
        # ALLA interna ShapeBinder-uppdateringar först
        self._flush_timer = QtCore.QTimer()
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush)

    # --------------------------------------------------
    # HUVUDEVENT: objekt ändrat
    # --------------------------------------------------

    def is_manual_translation_old(self):
        import FreeCADGui as Gui

        # 1. Kolla om ett relevant GUI-kommando körs
        active_cmd = any(Gui.isCommandActive(cmd) for cmd in ("Std_TransformManip", "Std_Transform", "Draft_Move", "Draft_Rotate"))

        # 2. Kolla om användaren aktivt redigerar ett värde i Task-panelen
        # (Hjälper om de ändrar Placement manuellt i panelen)
        is_editing = Gui.Control.activeDialog() is not None

        return active_cmd or is_editing

    def is_manual_translation(self):
        import FreeCADGui as Gui

        # 1. Kolla om ett relevant GUI-kommando körs (med felsäkring)
        active_cmd = False
        for cmd_name in ("Std_TransformManip", "Std_Transform", "Draft_Move", "Draft_Rotate"):
            try:
                # Kontrollera först att kommandot finns för att undvika 'NoneType'-fel internt
                cmd = Gui.Command.get(cmd_name)
                if cmd and Gui.isCommandActive(cmd_name):
                    active_cmd = True
                    break
            except Exception:
                continue

        # 2. Kolla om användaren aktivt redigerar ett värde i Task-panelen
        is_editing = Gui.Control.activeDialog() is not None

        return active_cmd or is_editing

    def slotChangedObject(self, obj, prop):
        if not self.enabled:
            return

        if prop not in ("Placement", "Shape"):
            return

        doc = obj.Document
        if not doc:
            return

        # print("[oba base] slotchangedobject", obj.Name, prop, is_interactive_transform())

        affected = self._affected_optical_objects(doc, obj)
        if not affected:
            return

        # ✅ GUARD: endast MANUELL translation
        if not self.is_manual_translation():
            # Python / script / recompute → ignorera
            # print("[oba base] manual translation")
            return

        # print("\n drag_körs..")

        # 👉 vi gör INGENTING under drag
        # vi markerar bara dirty
        self.drag_active = True  # sätter flagga för drag
        for opt in affected:
            self._dirty_sources.add(opt)

        # if self._flush_timer.isActive():
        #     self._flush_timer.stop()
        # # debounce till commit-fasen
        self._flush_timer.start(0)

    def _affected_optical_objects(self, doc, changed_obj):
        """
        Returnerar lista av optiska objekt som påverkas
        av förändringen i changed_obj.
        """
        affected = []

        for opt in doc.findObjects("App::DocumentObjectGroupPython"):
            if not hasattr(opt, "Binders"):
                continue
            for b in opt.Binders:
                if not b.Support:
                    continue
                src = b.Support[0][0]
                # Direkta träffen
                if src is changed_obj:
                    affected.append(opt)
                    break
                # Body → Feature → Binder
                if changed_obj.isDerivedFrom("PartDesign::Body") and src.isDerivedFrom("PartDesign::Feature") and src.getParentGeoFeatureGroup() is changed_obj:
                    affected.append(opt)
                    break
        return affected

    def _affected_optical_objects_old(self, doc, changed_obj):
        """
        Returnerar lista av optiska objekt som påverkas
        av förändringen i changed_obj.
        """
        affected = []
        for opt in doc.findObjects("App::DocumentObjectGroupPython"):
            if not hasattr(opt, "Binders"):
                continue
            for b in opt.Binders:
                if not b.Support:
                    continue
                src = b.Support[0][0]
                print(f"Checking {opt.Name} binder source {src.Name} against changed {changed_obj.Name}, src type {type(src)}, changed type {type(changed_obj)}")

                if src is changed_obj:
                    affected.append(opt)
                    break

        return affected

    # --------------------------------------------------
    # RESOLVER: vad är den verkliga källan?
    # --------------------------------------------------

    def _resolve_source_object(self, doc, changed_obj):
        """
        Returnerar det objekt som skall betraktas som
        geometrisk källa för förändringen.
        """
        # Fall 1: Optiskt objekt flyttades direkt
        if hasattr(changed_obj, "OpticalType"):
            return changed_obj

        # Fall 2: Käll-Body till ShapeBinder flyttades
        for g in doc.findObjects("App::DocumentObjectGroupPython"):
            for b in getattr(g, "Binders", []):
                if not b.Support:
                    continue
                src = b.Support[0][0]
                if src is changed_obj:
                    return src

        # Inget optiskt relevant
        return None

    # --------------------------------------------------
    # FLUSH: kör EN ray trace när allt lugnat sig
    # --------------------------------------------------

    # IMPORTANT:
    # We explicitly force a document recompute BEFORE ray tracing.
    # This reproduces the historical RayCollector.execute() behavior.
    # Ray tracing during interactive transforms is invalid because
    # the geometric model is not yet committed in FreeCAD.
    def _flush(self):
        if self.drag_active is False:
            return
        if not self._dirty_sources:
            return
        doc = App.ActiveDocument
        if not doc:
            self._dirty_sources.clear()
            return
        # plocka EN representativ källa
        source = next(iter(self._dirty_sources))
        self._dirty_sources.clear()

        # 🔑 DETTA ÄR NYCKELN
        # exakt samma effekt som gamla RayCollector
        try:
            App.Console.PrintLog("[OBA] Commit recompute before trace\n")
            doc.recompute()
        except Exception:
            pass
        # print("\n flush_körs")
        # 👉 NU är geometrin konsistent

        self.drag_active = False  # ✅ drag slutar HÄR

        _trigger_ray_engine(
            reason="geometry_committed",
            source=source,
        )

    # --------------------------------------------------
    # OPTIONAL: deletion (kan förenklas eller tas bort)
    # --------------------------------------------------

    def slotDeletedObject_old(self, obj):
        if not self.enabled:
            return
        doc = App.ActiveDocument
        if not doc:
            return
        # Endast optiskt relevanta objekt
        if not hasattr(obj, "OpticalType"):
            return
        _trigger_ray_engine(
            reason=f"object_deleted:{obj.Name}",
            source=obj,
        )

    def slotDeletedObject(self, obj):
        if not self.enabled:
            return

        doc = App.ActiveDocument
        if not doc:
            return

        # samla alla binder-namn först (för safety)
        binder_names = []

        if hasattr(obj, "Binders"):
            binder_names = [b.Name for b in obj.Binders if b]

        for name in binder_names:
            if doc.getObject(name):
                try:
                    doc.removeObject(name)
                except Exception:
                    pass

        if hasattr(obj, "OpticalType"):
            _trigger_ray_engine(
                reason=f"object_deleted:{obj.Name}",
                source=obj,
            )


# Säkerställ exakt EN registrerad observer
if hasattr(App, "_OBARealtimeObserver"):
    App.removeDocumentObserver(App._OBARealtimeObserver)

App._OBARealtimeObserver = OBARealtimeObserver()
App.addDocumentObserver(App._OBARealtimeObserver)

# ============================================================
# Base Proxy (optiskt objekt)
# ============================================================


# för att hantera props och binders
class OBAElementProxy:
    """
    Basklass för Mirror / Absorber / Lens etc
    """

    def __init__(self, obj, use_binders=True):
        obj.Proxy = self
        self.Object = obj

        if use_binders and not hasattr(obj, "Binders"):
            obj.addProperty("App::PropertyLinkList", "Binders", "Optics", "Länkade ytor")

    def onChanged(self, obj, prop):
        """
        Körs när en property på objektet ändras
        """

        # print("\n [oba_base] onchanged_körs", is_interactive_transform())

        # Ignorera interna FreeCAD-properties
        if prop.startswith("_"):
            return

        if prop in ("Proxy", "Binders", "Label"):
            return

        # 🔒 KRITISKT: ignorera ALLT under interactive drag
        # if is_interactive_transform():
        #     return

        # if prop == "FlipNormal":
        #     _trigger_ray_engine(
        #         reason="flip_normal_changed",
        #         source=obj,
        #     )
        #     return

        _trigger_ray_engine(f"Property changed: {obj.Name}.{prop}", obj)

    # def onDelete(self, obj, subelements):
    #     doc = obj.Document
    #     if not doc:
    #         return True
    #     for b in list(getattr(obj, "Binders", [])):
    #         if b:
    #             try:
    #                 doc.removeObject(b.Name)
    #             except Exception:
    #                 pass
    #     return True

    def add_binders(self, obj, source_obj, sub_elements):
        """
        Lägg till ShapeBinders till det optiska objektet.

        POLICY:
        - Alla binders MÅSTE komma från samma källobjekt
        - Första bindern definierar 'geometrisk ägare'
        - Objektets Label uppdateras till <OpticalType>_<SourceName>
        """

        if not source_obj:
            return

        doc = obj.Document
        if not doc:
            return

        # Resolva källobjekt
        actual = doc.getObject(source_obj) if isinstance(source_obj, str) else source_obj
        if not actual:
            App.Console.PrintError("[OBA] Invalid source object for binder\n")
            return

        # --------------------------------------------------
        # 🔒 KONSISTENSKONTROLL:
        # tillåt inte binders från olika källor
        # --------------------------------------------------
        existing_source = self._get_binder_source_object(obj)
        if existing_source and existing_source is not actual:
            App.Console.PrintError(f"[OBA] Cannot add binders from different objects:\n" f"      existing = {existing_source.Name}\n" f"      new      = {actual.Name}\n")
            return

        # --------------------------------------------------
        # Bygg target-lista (face/subelement)
        # --------------------------------------------------
        targets = [(sub,) for sub in sub_elements] if sub_elements else [("",)]
        current = list(getattr(obj, "Binders", []))

        # --------------------------------------------------
        # Skapa ShapeBinders
        # --------------------------------------------------
        for target in targets:
            label = target[0] if target[0] else "Body"

            name = f"Binder_{actual.Name}_{label.replace('.', '_')}_{len(current)}"
            if doc.getObject(name):
                name = f"{name}_{len(current)}"

            try:
                b = doc.addObject("PartDesign::ShapeBinder", name)
            except Exception as e:
                App.Console.PrintError(f"[OBA] Failed to create ShapeBinder: {e}\n")
                continue

            # Koppla binder
            b.Support = [(actual, target)]
            b.TraceSupport = True
            b.ViewObject.Visibility = False

            # Lägg till till optiskt objekt
            obj.addObject(b)
            current.append(b)

        # Uppdatera binder-listan samlat
        obj.Binders = current

        # --------------------------------------------------
        # ✅ Uppdatera objektets LABEL baserat på källa
        # --------------------------------------------------
        self._update_label_from_binders(obj)

    def clear_binders(self, obj):
        """Rensa alla binder-objekt"""
        if not hasattr(obj, "Group"):
            return

        to_remove = [o for o in obj.Group if o.Name.startswith("Binder")]
        for o in to_remove:
            App.ActiveDocument.removeObject(o.Name)

    def _get_binder_source_object(self, obj):
        """
        Returnerar det objekt som binder-ytorna kommer ifrån.
        Antagande: alla binders pekar på samma källa.
        """
        binders = getattr(obj, "Binders", [])
        if not binders:
            return None
        b = binders[0]
        if not b.Support:
            return None

        return b.Support[0][0]

    def _resolve_geometry_root(self, src):
        """
        Returnerar ett stabilt geometriskt rotobjekt
        (Body, importerad STEP, eller primär Form).
        """
        # PartDesign Feature → Body
        if src.isDerivedFrom("PartDesign::Feature"):
            body = src.getParentGeoFeatureGroup()
            if body:
                return body
        # Binder → dess Support
        if hasattr(src, "Support") and src.Support:
            return self._resolve_geometry_root(src.Support[0][0])
        # Importerat STEP / Compound
        if src.isDerivedFrom("Part::Feature"):
            return src
        # Fallback
        return src

    def _optical_prefix(self, obj):
        ot = getattr(obj, "OpticalType", "OPT").upper()
        return ot[:3]  # MIR, LEN, ABS, GRA…

    def _update_label_from_binders(self, obj):
        src = self._get_binder_source_object(obj)
        if not src:
            return
        root = self._resolve_geometry_root(src)
        prefix = self._optical_prefix(obj)
        geom_name = root.Label or root.Name
        new_label = f"{prefix}_{geom_name}"
        if obj.Label != new_label:
            obj.Label = new_label

    def update_icon(self, obj):
        """
        Tvinga uppdatering av ikon i GUI
        """

        try:
            if hasattr(obj, "ViewObject") and obj.ViewObject:
                obj.ViewObject.signalChangeIcon()
        except Exception:
            pass

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


# ============================================================
# Base ViewProvider
# ============================================================


class OBAViewProviderBase:
    """
    Hanterar ikon + dubbelklick
    """

    def __init__(self, vobj):
        vobj.Proxy = self
        self.Object = vobj.Object

        # Gemensam preview-root (Coin3D)
        # self._preview_root = None
        # self._final_root = None

    # def claimChildren(self):
    #     obj = self.Object
    #     if hasattr(obj, "Binders"):
    #         return obj.Binders
    #     return []

    def attach(self, vobj):
        """Called when ViewProvider is attached to ViewObject."""
        self.ViewObject = vobj
        # Ensure attributes are initialized
        if not hasattr(self, "_preview_root"):
            self._preview_root = None
        if not hasattr(self, "_final_root"):
            self._final_root = None

    def getIcon(self):
        try:
            obj = self.Object
            ot = getattr(obj, "OpticalType", "").lower()
            if not ot:
                return ""

            # print("ikooon", ot)
            path = os.path.join(BASE_PATH, "..", "icons", f"oba_{ot}.svg")
            if os.path.exists(path):
                return path
        except Exception:
            pass
        return ""

    def doubleClicked(self, vobj):
        if hasattr(self, "dialog_class"):
            dlg = self.dialog_class(vobj.Object)
            dlg.show()
            return True
        return False

    def onDocumentRestored(self, vobj):
        vobj.Proxy = self
        self.Object = vobj.Object
        vobj.update()

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


# ============================================================
# Selection observer (endast aktiv när dialog är öppen)
# ============================================================


class OBASelectionObserver:
    def __init__(self, dlg):
        self.dlg = dlg

    def addSelection(self, doc, obj, sub, pnt):
        if hasattr(self.dlg, "add_selection"):
            self.dlg.add_selection(obj, sub)


# ============================================================
# Base Dialog
# ============================================================


class OBABaseDialog(QtWidgets.QDialog):
    """
    Basklass för alla dialoger
    """

    ALLOW_SURFACE_SELECTION = True  # 🔑 FLAGGA för att visa select listan av face

    def __init__(self, obj, title="OBA Element", parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.obj = obj

        self.setWindowTitle(title)
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        # -------------------------------------------------
        # Layout
        # -------------------------------------------------
        self.layout = QtWidgets.QVBoxLayout(self)

        self.custom_layout = QtWidgets.QVBoxLayout()
        self.layout.addLayout(self.custom_layout)

        # -------------------------------------------------
        # Surface selection / binders (valbart)
        # -------------------------------------------------
        self.list_binders = None
        self._sel_observer = None

        if self.ALLOW_SURFACE_SELECTION:
            self.layout.addWidget(QtWidgets.QLabel("Linked surfaces (same target only):"))

            self.list_binders = QtWidgets.QListWidget()
            self.layout.addWidget(self.list_binders)

            self.list_binders.itemClicked.connect(self._remove_binder)
            self._reload_list()

            # Selection observer används endast om ytväljning är tillåten
            self._sel_observer = OBASelectionObserver(self)
            Gui.Selection.addObserver(self._sel_observer)

        # -------------------------------------------------
        # OK / Close
        # -------------------------------------------------
        btn = QtWidgets.QPushButton("Done/Close")
        btn.clicked.connect(self.accept)
        self.layout.addWidget(btn)

    # ====================================================
    # Binder / surface helpers
    # (används bara om ALLOW_SURFACE_SELECTION=True)
    # ====================================================

    def _reload_list(self):
        if not self.list_binders:
            return

        self.list_binders.clear()
        for b in getattr(self.obj, "Binders", []):
            item = QtWidgets.QListWidgetItem(b.Label)
            item.setData(QtCore.Qt.UserRole, b.Name)
            self.list_binders.addItem(item)

    def add_selection(self, src_obj, sub):
        if not self.ALLOW_SURFACE_SELECTION:
            return

        self.obj.Proxy.add_binders(self.obj, src_obj, [sub] if sub else [])
        self._reload_list()
        self.obj.Document.recompute()

        # _trigger_ray_engine(
        #     reason="binder_added",
        #     source=self.obj,
        # )

    def _remove_binder(self, item):
        if not self.list_binders:
            return

        name = item.data(QtCore.Qt.UserRole)
        tgt = self.obj.Document.getObject(name)

        if tgt:
            binders = list(self.obj.Binders)
            binders.remove(tgt)
            self.obj.Binders = binders
            self.obj.Document.removeObject(name)

        self._reload_list()
        self.obj.Document.recompute()

        # _trigger_ray_engine(
        #     reason="binder_added",
        #     source=self.obj,
        # )

    # -------------------------------------------------
    # Cleanup
    # -------------------------------------------------
    def done(self, r):
        if self._sel_observer:
            try:
                Gui.Selection.removeObserver(self._sel_observer)
            except RuntimeError:
                pass
        super().done(r)
