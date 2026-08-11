# oba_ray_collector_view.py

import os
import FreeCAD as App
import FreeCADGui as Gui
import Part
import math
import time
from pivy import coin

BASE_PATH = os.path.dirname(__file__)


# ============================================================
#   V I S U A L I Z E   R A Y S  (MED TIMING)
# ============================================================


def visualize_rays_local(obj, rays):
    edges = []
    inv_pl = obj.Placement.inverse()

    for ray in rays:
        pts = ray.points
        if len(pts) < 2:
            continue

        for i in range(len(pts) - 1):
            p1 = inv_pl.multVec(pts[i])
            p2 = inv_pl.multVec(pts[i + 1])

            if (p1 - p2).Length < 1e-7:
                continue

            edges.append(Part.makeLine(p1, p2))

    obj.Shape = Part.Compound(edges) if edges else Part.Shape()


def visualize_rays(obj, rays):
    edges = []
    error_count = 0

    for ray_idx, ray in enumerate(rays):

        pts = ray.points
        if len(pts) < 2:
            continue

        for i in range(len(pts) - 1):
            p1 = pts[i]
            p2 = pts[i + 1]
            try:
                if (p1 - p2).Length < 1e-7:
                    continue

                line = Part.makeLine(p1, p2)
                edges.append(line)

            except Exception as e:
                error_count += 1
                if error_count <= 5:
                    App.Console.PrintError(f"[DEBUG] visualize_rays: Fel vid segment {i} i stråle {ray_idx}.\n" f"P1: {p1}, P2: {p2}\n" f"Error: {str(e)}\n")

    if error_count > 5:
        App.Console.PrintWarning(f"[DEBUG] Totalt {error_count} geometrifel ignorerade.\n")

    try:
        if edges:
            obj.Shape = Part.Compound(edges)
        else:
            obj.Shape = Part.Compound([])

    except Exception as e:
        App.Console.PrintError(f"[CRITICAL] Kunde inte skapa Compound: {str(e)}\n")


# ============================================================
#   V I E W   P R O V I D E R
# ============================================================


class ViewProviderRayCollector:
    """Coin3D ViewProvider för snabb ray-visualisering."""

    print("+++ USING COIN VIEWPROVIDER +++")

    def __init__(self, vobj):
        vobj.Proxy = self

        # Root för ALL rendering vi kontrollerar
        # self.root = coin.SoSeparator()

        # Här lagrar vi aktuella rays-noden (så vi kan byta ut den snabbt)
        # self.ray_root = None

        # Koppla in i FreeCAD
        # vobj.addDisplayMode(self.root, "Rays")
        vobj.DisplayMode = "Flat Lines"  # vanlig freecad

        # Standardutseende (fallback)
        vobj.LineColor = (1.0, 1.0, 0.0)
        vobj.LineWidth = 6.0
        vobj.PointSize = 2.0

    def attach(self, vobj):
        """Kallas när ViewProvider kopplas till objektet."""
        self.vobj = vobj

    def updateData(self, obj, prop):
        """Inte använd – vi styr rendering manuellt via visualize_rays."""
        return

    def getDisplayModes(self, vobj):
        return ["Rays"]

    def getDefaultDisplayMode(self):
        return "Rays"

    def setDisplayMode(self, mode):
        return mode

    def onChanged(self, vobj, prop):
        """Hantera ev. property-ändringar."""

        return

    def onDelete(self, vobj, prop):
        from .oba_ray_core import OBARay, OBARayManager

        OBARayManager().clear_all()
        #     proxy = vobj.Object.Proxy
        #     proxy.enable_all_beam_previews()
        return True  # Returnera True för att tillåta borttagning, False för att stoppa den

    def getIcon(self):
        icon = os.path.normpath(os.path.join(BASE_PATH, "..", "icons", "oba_ray_collector.svg"))
        if os.path.exists(icon):
            return icon
        return ""

    def __getstate__(self):
        """För att undvika save/load-problem."""
        return None

    def __setstate__(self, state):
        """För att undvika restore-problem."""
        return None


# ============================================================
#   C R E A T I O N  F U N C T I O N
# ============================================================


def OBA_CreateRayCollector():
    """Skapar OBARayCollector-objektet om det saknas."""
    doc = App.ActiveDocument
    if not doc:
        App.Console.PrintWarning("Inget aktivt dokument hittades.\n")
        return None

    existing = doc.getObject("OBARayCollector")
    if existing:
        App.Console.PrintLog("ℹ️ RayCollector finns redan i dokumentet.\n")
        return existing

    # Skapa en Part::FeaturePython så att vi kan visa Shape (strålarna)
    obj = doc.addObject("Part::FeaturePython", "OBARayCollector")

    # Importera proxyn lokalt för att undvika cirkulära beroenden
    from .oba_ray_collector import OBARayCollector

    OBARayCollector(obj)

    if App.GuiUp:
        # Koppla ViewProvidern för GUI-funktionalitet
        obj.ViewObject.Proxy = ViewProviderRayCollector(obj.ViewObject)
        # ViewProviderRayCollector(obj.ViewObject)

    doc.recompute()
    App.Console.PrintLog("✅ RayCollector skapad och redo.\n")
    return obj


# ============================================================
#   F R E E C A D   C O M M A N D
# ============================================================


# class _CmdCreateRayCollector:
#     def GetResources(self):
#         return {
#             "MenuText": "Create Ray Collector",
#             "ToolTip": "Skapar den centrala strålspårningsmotorn",
#         }

#     def Activated(self):
#         OBA_CreateRayCollector()

#     def IsActive(self):
#         return Gui.ActiveDocument is not None


# # Registrera kommandot i FreeCADs GUI
# if "OBA_CreateRayCollector" not in Gui.listCommands():
#     Gui.addCommand("OBA_CreateRayCollector", _CmdCreateRayCollector())  # Obs: Kolla namn här vid copy-paste
