# -*- coding: utf-8 -*-
# example_herriott.py   (SA-version)

from pydoc import doc
import FreeCAD as App
import FreeCADGui as Gui

import Part

# import Spreadsheet
import liveSheet


from oba_plots import power_density_plot
from oba_objects.oba_mirror import OBA_CreateMirror
from oba_objects.oba_emitter import OBA_CreateEmitter
from oba_objects.oba_absorber import OBA_CreateAbsorber
from oba_objects.oba_ray_config import OBA_CreateRayConfig

from FreeCAD import Vector, Placement, Rotation
from PySide import QtWidgets
import os
import math

# Icon directory
_icondir_ = os.path.join(os.path.dirname(__file__), "..")


def find_concave_face(obj):
    """
    Returnerar FaceN för den stora konkava spegelytan
    """

    shape = obj.Shape
    candidates = []

    for i, face in enumerate(shape.Faces, start=1):
        surf = face.Surface

        # 1. Måste vara sfär
        if not hasattr(surf, "Radius"):
            continue

        # 2. Hoppa över väldigt små ytor (typiska rest-faces)
        if face.Area < 0.1 * max(f.Area for f in shape.Faces):
            continue

        # 3. Kontrollera konkavitet via normal riktning
        u, v = 0.5, 0.5
        normal = face.normalAt(u, v)

        # Vektor från yta till sfärens centrum
        center_vec = surf.Center.sub(face.valueAt(u, v))

        # Konkav yta: normal pekar MOT sfärcentrum
        if normal.dot(center_vec) > 0:
            candidates.append((face.Area, f"Face{i}"))

    if not candidates:
        raise ValueError(f"Ingen giltig konkav yta hittades på {obj.Name}")

    # 4. Välj den största konkava ytan
    candidates.sort(reverse=True)
    return candidates[0][1]


def create_oba_mirror_from_faces(face_refs):
    """
    Skapar ETT OBA Mirror från flera (obj, face_name)
    face_refs = [(obj1, "Face4"), (obj2, "Face7"), ...]
    """
    Gui.Selection.clearSelection()

    for obj, face_name in face_refs:
        Gui.Selection.addSelection(obj, face_name)

    # Skapa exakt ett Mirror-objekt
    OBA_CreateMirror(show_dialog=False)

    Gui.Selection.clearSelection()


def create_oba_emitter_from_face(obj, face_name="Face1"):
    """
    Skapar ett OBA Emitter-objekt bundet till exakt en face.
    Används i script / batch (ingen dialog).
    """
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj, face_name)

    emitter = OBA_CreateEmitter(show_dialog=False)

    Gui.Selection.clearSelection()

    return emitter


def create_oba_absorber_from_face(obj, face_name="Face1"):
    """
    Skapar ett OBA Absorber-objekt bundet till exakt en face.
    Används i script / batch (ingen dialog).
    """
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj, face_name)

    absorber = OBA_CreateAbsorber(show_dialog=False)

    Gui.Selection.clearSelection()
    return absorber


def create_spreadsheet(doc):

    ss = doc.addObject("Spreadsheet::Sheet", "Spreadsheet")

    ss.set("A1", "Mirror radius (R)")
    ss.set("B1", "250 mm")

    ss.set("A2", "Distance between mirrors (D)")
    ss.set("B2", "230 mm")

    ss.set("A3", "Mirror diameter (W)")
    ss.set("B3", "100 mm")

    ss.set("A4", "Thickness (T)")
    ss.set("B4", "20 mm")

    ss.set("B5", "___Beamhole settings___")

    ss.set("A6", "Beamhole radius")
    ss.set("B6", "8 mm")

    ss.set("A7", "Beam hole #1 offset X")
    ss.set("B7", "55 mm")

    # ✅ NYTT: Beam hole #2 offset X (default = spegling av #1)
    ss.set("A8", "Beam hole #2 offset Y")
    ss.set("B8", "55 mm")

    doc.recompute()
    return ss


def build_geometry(doc):
    def create_mirror_base(name):
        cyl = doc.addObject("Part::Cylinder", name + "_Body")
        cyl.setExpression("Radius", "Spreadsheet.B3")
        cyl.setExpression("Height", "Spreadsheet.B4")

        sph = doc.addObject("Part::Sphere", name + "_Sphere")
        sph.setExpression("Radius", "Spreadsheet.B1")
        sph.setExpression("Placement.Base.z", "Spreadsheet.B1")

        cut = doc.addObject("Part::Cut", name + "_Concave")
        cut.Base = cyl
        cut.Tool = sph

        cyl.Visibility = False
        sph.Visibility = False
        return cut

    # --- Mirror 1 ---
    m1_base = create_mirror_base("Mirror1_Base")

    hole1 = doc.addObject("Part::Cylinder", "BeamHole")
    hole1.setExpression("Radius", "Spreadsheet.B6")
    hole1.setExpression("Height", "Spreadsheet.B4 * 2")
    hole1.setExpression("Placement.Base.x", "Spreadsheet.B7")
    hole1.Placement.Base.z = -5

    hole2 = doc.addObject("Part::Cylinder", "BeamHole_Mirrored")
    hole2.setExpression("Radius", "Spreadsheet.B6")
    hole2.setExpression("Height", "Spreadsheet.B4 * 2")
    hole2.setExpression("Placement.Base.y", "-Spreadsheet.B8")  # 🔑 spegling
    hole2.Placement.Base.z = -5

    # Första cut: spegelbas - hole1
    mirror1_cut1 = doc.addObject("Part::Cut", "Mirror1_Cut1")
    mirror1_cut1.Base = m1_base
    mirror1_cut1.Tool = hole1

    # Andra cut: resultat - hole2
    mirror1 = doc.addObject("Part::Cut", "Mirror1")
    mirror1.Base = mirror1_cut1
    mirror1.Tool = hole2

    m1_base.Visibility = False
    hole1.Visibility = False
    hole2.Visibility = False
    mirror1_cut1.Visibility = False

    mirror1.ViewObject.Transparency = 70
    mirror1.ViewObject.ShapeColor = (0.7, 0.7, 0.8)

    # --- Mirror 2 ---
    mirror2 = create_mirror_base("Mirror2")
    mirror2.Placement.Rotation = Rotation(Vector(1, 0, 0), 180)
    mirror2.setExpression("Placement.Base.z", "Spreadsheet.B2")

    # --- Single planar surface (emitter ) ---
    emitter = doc.addObject("Part::Plane", "EmitterTargetPlane")
    emitter.Length = 5
    emitter.Width = 5
    x_pos = 52
    y_pos = -emitter.Length / 2
    z_pos = -12
    emitter.Placement.Base = Vector(x_pos, y_pos, z_pos)

    pitch = -10.8
    yaw = -1.3
    roll = 0

    rot_pitch = Rotation(Vector(1, 0, 0), pitch)
    rot_yaw = Rotation(Vector(0, 1, 0), yaw)
    rot_roll = Rotation(Vector(0, 0, 1), roll)

    emitter.Placement = Placement(emitter.Placement.Base, rot_pitch.multiply(rot_yaw).multiply(rot_roll))

    # --- Single planar surface ( detector) ---
    detector = doc.addObject("Part::Plane", "DetectorTargetPlane")
    detector.Length = 25
    detector.Width = 25
    x_pos = -10
    y_pos = -75
    z_pos = -12
    detector.Placement.Base = Vector(x_pos, y_pos, z_pos)

    doc.recompute()
    return mirror1, mirror2, emitter, detector


def setup_optics(doc, mirror1, mirror2, emitter, detector):

    face1 = find_concave_face(mirror1)
    face2 = find_concave_face(mirror2)

    # print(f"Mirror 1 concave face: {face1}")
    # print(f"Mirror 2 concave face: {face2}")

    create_oba_mirror_from_faces([(mirror1, face1)])
    create_oba_mirror_from_faces([(mirror2, face2)])

    emitter = create_oba_emitter_from_face(emitter, "Face1")
    emitter.MaxRays = 5
    emitter.SpreadAngle = 0
    emitter.MaxBounce = 100

    create_oba_absorber_from_face(detector, "Face1")

    OBA_CreateRayConfig(doc, show_dialog=False)

    doc.recompute()


def setup_ui(doc):
    view = Gui.ActiveDocument.ActiveView

    iso_rot = Rotation(0.11591698929143902, 0.8804762329080508, 0.2798481572676507, -0.3647051737384002)

    view.setCameraOrientation(iso_rot.Q)
    view.fitAll()

    liveSheet.OBA_ShowLiveSheetsDock()


# --------------------------------------------
# ------- Main Herriott Cell Function -------
# --------------------------------------------


def make_herriott():
    doc = App.newDocument("HerriottCell")

    # 1. Parametrar
    create_spreadsheet(doc)

    # 2. Geometri
    mirror1, mirror2, emitter, detector = build_geometry(doc)

    # 3. Optiska objekt
    setup_optics(doc, mirror1, mirror2, emitter, detector)

    # 4. UI / analys
    setup_ui(doc)

    return True


def OBA_ExampleHerriottCell():
    make_herriott()
    Gui.runCommand("Std_OrthographicCamera", 1)
