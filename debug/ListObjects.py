import FreeCAD as App
import FreeCADGui as Gui


def OBA_ListObjects():
    doc = App.ActiveDocument
    if doc is None:
        App.Console.PrintError("⚠️ Inget aktivt dokument.\n")
        return

    App.Console.PrintMessage("\n==============================\n")
    App.Console.PrintMessage("📋 LISTA ÖVER ALLA OBJEKT\n")
    App.Console.PrintMessage("==============================\n\n")

    for obj in doc.Objects:

        App.Console.PrintMessage(f"🔹 Objekt: {obj.Name}  (Label: {obj.Label})\n")
        App.Console.PrintMessage(f"   ├─ TypeId: {obj.TypeId}\n")

        # Shape info
        if hasattr(obj, "Shape") and obj.Shape is not None:
            stype = obj.Shape.ShapeType
            App.Console.PrintMessage(f"   ├─ Shape typ: {stype}\n")

            if stype == "Solid":
                App.Console.PrintMessage(f"   │    Volym: {obj.Shape.Volume:.3f}\n")
            if stype == "Face":
                App.Console.PrintMessage(f"   │    Area: {obj.Shape.Area:.3f}\n")
        else:
            App.Console.PrintMessage("   ├─ Ingen shape\n")

        # Proxy info
        if hasattr(obj, "Proxy") and obj.Proxy is not None:
            proxy = obj.Proxy
            App.Console.PrintMessage(f"   ├─ Proxy klass: {proxy.__class__.__name__}\n")

            if hasattr(obj, "OpticalType"):
                App.Console.PrintMessage(f"   ├─ OpticalType: {obj.OpticalType}\n")

        App.Console.PrintMessage("   └────────────────────────────\n\n")

        from oba_rayengine.oba_ray_core import OBARayManager

        mgr = OBARayManager()
        name = "Absorber"
        total = 0.0

        for ray in mgr.rays:
            for h in ray.history:
                if isinstance(h, dict) and h.get("object_name") == name:
                    total += float(h.get("power", 0.0))

        print("total rayshits", total)


# ============================================================
#  COMMAND  (passar ditt schema för hot_reload)
# ============================================================


class _CmdListObjects:

    def GetResources(self):
        return {"MenuText": "Lista objekt", "ToolTip": "Lista alla objekt och deras typer i dokumentet", "Pixmap": ""}  # lägg ikon här om du vill

    def Activated(self):
        OBA_ListObjects()


# Registrering — låter hot_reload hantera reloadern
if "OBA_ListObjects" not in Gui.listCommands():
    Gui.addCommand("OBA_ListObjects", _CmdListObjects())
