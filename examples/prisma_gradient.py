# -*- coding: utf-8 -*-
# example_prism_gradient.py   (SA-version)

import FreeCAD as App
import FreeCADGui as Gui
import Part

from FreeCAD import Vector, Placement, Rotation

from oba_objects.oba_emitter import OBA_CreateEmitter
from oba_objects.oba_grating import OBA_CreateGrating
from oba_objects.oba_ray_config import OBA_CreateRayConfig


# ------------------------------------------------------------
# Geometry helpers
# ------------------------------------------------------------


def create_prism(doc):
    """
    Skapar ett triangulärt prisma:
    - bas i XY-planet
    - extruderat i +Z
    """
    tri = Part.makePolygon(
        [
            Vector(0, 0, 0),
            Vector(30, 0, 0),
            Vector(15, 25, 0),
            Vector(0, 0, 0),
        ]
    )

    base_face = Part.Face(tri)
    solid = base_face.extrude(Vector(0, 0, 20))

    prism = doc.addObject("Part::Feature", "Prism")
    prism.Shape = solid

    prism.ViewObject.ShapeColor = (0.6, 0.8, 1.0)
    prism.ViewObject.Transparency = 70

    doc.recompute()
    return prism


def find_face_by_normal(obj, target_normal, tol=0.98):
    """
    Returnerar FaceN för den plana yta
    vars normal pekar i target_normal-riktningen.
    """
    target_normal = target_normal.normalize()

    for i, face in enumerate(obj.Shape.Faces, start=1):
        if not isinstance(face.Surface, Part.Plane):
            continue

        u, v = 0.5, 0.5
        n = face.normalAt(u, v).normalize()

        if abs(n.dot(target_normal)) > tol:
            return f"Face{i}"

    raise ValueError("Ingen yta med matchande normal hittades")


def create_prism_emitter(doc):
    """
    Skapar emitter med exakt samma Translation och Rotation
    som visas i Transform-dialogen.
    """
    emitter_plane = doc.addObject("Part::Plane", "PrismEmitterPlane")
    emitter_plane.Length = 6
    emitter_plane.Width = 6

    # --- Translation (Global) ---
    base = Vector(40, -20, 10)

    # --- Rotation (Global Euler XYZ från Transform-panelen) ---
    rx = Rotation(Vector(1, 0, 0), -135)
    ry = Rotation(Vector(0, 1, 0), 90)
    rz = Rotation(Vector(0, 0, 1), 0)

    # IMPORTANT:
    # Transform-dialogen använder R = Rz * Ry * Rx
    rot = rz.multiply(ry).multiply(rx)

    emitter_plane.Placement = Placement(base, rot)

    doc.recompute()
    return emitter_plane


# ------------------------------------------------------------
# OBA helpers (selection-wrappers)
# ------------------------------------------------------------


def create_oba_emitter_from_face(obj, face_name="Face1"):
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj, face_name)
    emitter = OBA_CreateEmitter(show_dialog=False)
    Gui.Selection.clearSelection()
    return emitter


def create_oba_grating_from_prism(prism):
    """
    Skapar grating på prismaytan som ligger i XY-planet
    (normal ≈ +Z).
    """
    face_name = find_face_by_normal(prism, App.Vector(0, 1, 0))

    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(prism, face_name)

    grating = OBA_CreateGrating(show_dialog=False)
    grating.LinesPerMM = 1000
    grating.SpectrumRays = 50
    Gui.Selection.clearSelection()

    return grating


# ------------------------------------------------------------
# Optics setup
# ------------------------------------------------------------


def setup_prism_optics(doc, prism, emitter_plane):
    """
    Kopplar emitter, grating och rayconfig.
    """

    # --- Emitter ---
    emitter = create_oba_emitter_from_face(emitter_plane, "Face1")
    emitter.MaxRays = 50
    emitter.SpreadAngle = 0
    emitter.MaxBounce = 5

    # --- Grating (på prisma) ---
    grating = create_oba_grating_from_prism(prism)
    grating.LinesPerMM = 600
    grating.SpectrumRays = 9

    # --- Ray config ---
    rayconfig = OBA_CreateRayConfig(doc, show_dialog=False)
    rayconfig.ColorByBounce = False

    doc.recompute()


# ------------------------------------------------------------
# Example command
# ------------------------------------------------------------


def OBA_ExamplePrismGradient():
    """
    Example: Prisma + spektral gradient via grating
    """

    doc = App.newDocument("PrismGradientExample")

    prism = create_prism(doc)
    emitter_plane = create_prism_emitter(doc)

    setup_prism_optics(doc, prism, emitter_plane)

    Gui.ActiveDocument.ActiveView.fitAll()
