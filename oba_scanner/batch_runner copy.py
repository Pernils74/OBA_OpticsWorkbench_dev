# -*- coding: utf-8 -*-
# batch_runner.py

import json
import math
from pydoc import doc
import time


import FreeCAD as App

from oba_objects.oba_base import _trigger_ray_engine
from oba_rayengine.oba_ray_analyser import collect_ray_hits_and_stats

from .scan_db import HitsDB

BATCH_OFFSET_OBJ = "__OBABatchOffset__"


# ============================================================
# Math helper
# ============================================================


def rotate(x, y, z, axis, angle_rad):
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    axis = axis.upper()
    if axis == "X":
        return (x, y * c - z * s, y * s + z * c)
    elif axis == "Y":
        return (x * c + z * s, y, -x * s + z * c)
    else:
        return (x * c - y * s, x * s + y * c, z)


# ============================================================
# Batch offset controller
# ============================================================


def dump_placement_text(obj, header=None):
    """
    Skriver ut Placement-innehållet för ett objekt:
    - numeriska värden
    - expressions (om de finns)
    som ren text i FreeCAD-konsolen.
    """
    if not obj:
        App.Console.PrintError("❌ dump_placement_text: inget objekt\n")
        return

    if header:
        App.Console.PrintLog(f"\n=== {header} ===\n")
    else:
        App.Console.PrintLog(f"\n=== Placement dump: {obj.Name} ===\n")

    pl = obj.Placement
    base = pl.Base
    rot = pl.Rotation

    App.Console.PrintLog(f"Base values:\n" f"  x = {base.x}\n" f"  y = {base.y}\n" f"  z = {base.z}\n")

    axis = rot.Axis
    App.Console.PrintLog(f"Rotation values:\n" f"  axis = ({axis.x}, {axis.y}, {axis.z})\n" f"  angle(rad) = {rot.Angle}\n" f"  angle(deg) = {math.degrees(rot.Angle)}\n")

    # --------------------------------------------------
    # Expressions (om några)
    # --------------------------------------------------
    ee = obj.ExpressionEngine
    if ee:
        App.Console.PrintLog("Placement expressions:\n")
        for path, expr in ee:
            if path.startswith(".Placement"):
                App.Console.PrintLog(f"  {path} = {expr}\n")
    else:
        App.Console.PrintLog("No expressions on Placement\n")


def set_batch_offsets(batch_obj, dx, dy, dz):
    batch_obj.OffsetX = dx
    batch_obj.OffsetY = dy
    batch_obj.OffsetZ = dz


# ============================================================
# SAFE EXPRESSION INSTALLER
# ============================================================


def snapshot_placement(obj):
    """
    Returnerar en snapshot av Placement:
    - numeriska värden
    - alla placement-expressions som ren text
    """
    pl = obj.Placement
    b = pl.Base
    snap = {
        "base": App.Vector(b.x, b.y, b.z),
        "rotation": App.Rotation(pl.Rotation),
        "expressions": {},
    }
    ee = obj.ExpressionEngine
    if ee:
        for path, expr in ee:
            if path.startswith(".Placement"):
                snap["expressions"][path.lstrip(".")] = expr

    return snap


def clear_placement_expressions(obj):
    ee = obj.ExpressionEngine
    if not ee:
        return

    for path, _expr in list(ee):  # list() ← viktigt
        if path.startswith(".Placement"):
            obj.setExpression(path.lstrip("."), None)


def apply_direct_offset(obj, snap, dx, dy, dz):
    base0 = snap["base"]
    obj.Placement.Base = App.Vector(
        base0.x + dx,
        base0.y + dy,
        base0.z + dz,
    )


def restore_placement(obj, snap):
    # Återställ värden först
    obj.Placement.Base = snap["base"]
    obj.Placement.Rotation = snap["rotation"]

    # Återställ expressions
    for path, expr in snap["expressions"].items():
        obj.setExpression(path, expr)


def dump_snapshot(snap):
    App.Console.PrintLog(f"Base: {snap['base']}\n" f"Rotation: {snap['rotation']}\n")
    for p, e in snap["expressions"].items():
        App.Console.PrintLog(f"Expr {p} = {e}\n")


def resolve_move_target(obj):
    """
    Returnerar det objekt vars Placement faktiskt styr geometrin.
    """
    if not obj:
        return None

    # Case 1: PartDesign Body
    if obj.TypeId == "PartDesign::Body":
        return obj

    # Case 2: Feature inne i Body → flytta Body
    try:
        body = obj.getParentGeoFeatureGroup()
        if body and body.TypeId == "PartDesign::Body":
            return body
    except Exception:
        pass

    # Case 3: App::Link
    if obj.TypeId == "App::Link":
        return obj  # eller obj.LinkedObject beroende på policy

    # Case 4: Vanligt Part / Feature
    if hasattr(obj, "Placement"):
        return obj

    # Annars: ogiltigt
    return None


# ============================================================
# MAIN RUN FUNCTION
# ============================================================


def run_steps_for_batch(batch, prog_bar, status_lbl, pump_events_func, stop_flag_func):
    App.Console.PrintLog("▶ Starting batch run\n")

    doc = batch.Document
    db = HitsDB()

    # ----------------------------------------------------------
    # Find OBARayConfig
    # ----------------------------------------------------------

    collector = None
    for o in doc.Objects:
        if hasattr(o, "Proxy") and o.Proxy and o.Proxy.__class__.__name__ == "OBARayConfig":
            collector = o
            break

    if not collector:
        status_lbl.setText("No OBARayConfig – aborting")
        App.Console.PrintError("❌ OBARayConfig missing\n")
        return

    collector.RunMode = "MANUAL"

    # ----------------------------------------------------------
    # Collect active steps
    # ----------------------------------------------------------

    parsed_steps = []
    total_iters = 0

    for step in batch.Group:
        if not getattr(step, "Active", True):
            continue

        try:
            data = json.loads(step.DataJSON or "{}")
        except Exception:
            data = {}

        A = max(1, int(data.get("angle", 5)))
        rf = float(data.get("rf", 0.0))
        rt = float(data.get("rt", 0.4))
        R = max(1, int(data.get("rs", 4)))

        iters = A * R - (A - 1) if rf == 0 else A * R
        total_iters += iters

        parsed_steps.append((step, data, A, rf, rt, R))

    prog_bar.setRange(0, total_iters)
    prog_bar.setValue(0)

    # ----------------------------------------------------------
    # Label → Name map
    # ----------------------------------------------------------

    label_to_name = {o.Label: o.Name for o in doc.Objects}

    # ----------------------------------------------------------
    # Collect move-objects + snapshot Placement
    # ----------------------------------------------------------

    move_objects = {}
    placement_snaps = {}

    for step, data, *_ in parsed_steps:

        for lbl in (data.get("move"), data.get("move1"), data.get("move2")):
            if not lbl or lbl == "none":
                continue

            raw_obj = doc.getObject(label_to_name.get(lbl, ""))
            move_obj = resolve_move_target(raw_obj)

            if not move_obj:
                App.Console.PrintWarning(f"[Batch] Object '{lbl}' cannot be moved (ignored)\n")
                continue

            key = move_obj.Name
            if key in move_objects:
                continue

            move_objects[key] = move_obj
            placement_snaps[key] = snapshot_placement(move_obj)  # tar snapshot frö varje objekt som skall flyttas.

            dump_placement_text(move_obj, header=f"Original placement for {move_obj.Name}")
            clear_placement_expressions(move_obj)

    doc.recompute()
    # ----------------------------------------------------------
    # RUN
    # ----------------------------------------------------------
    done_iters = 0

    try:
        for step, data, A, rf, rt, R in parsed_steps:
            if stop_flag_func():
                break

            step_move_names = []  # för att lagra i DB senare
            for lbl in (data.get("move"), data.get("move1"), data.get("move2")):
                if not lbl or lbl == "none":
                    continue
                name = label_to_name.get(lbl)
                if name:
                    step_move_names.append(name)

            moved_objects_as_str = ";".join(sorted(step_move_names))

            plan = data.get("plan", "XY")
            rot_axis = data.get("rotAxis", "X")
            rot_angle = math.radians(float(data.get("rotAngle", 0.0)))

            r_step = 0 if R <= 1 else (rt - rf) / float(R - 1)

            for ri in range(R):
                radius = rf + r_step * ri
                ai_range = range(1) if ri == 0 and abs(radius) < 1e-12 else range(A)

                for ai in ai_range:
                    if stop_flag_func():
                        break
                    pump_events_func()

                    ang = (2.0 * math.pi / A) * ai
                    dx = radius * math.cos(ang)
                    dy = radius * math.sin(ang)
                    dz = 0.0

                    if plan == "XZ":
                        dz, dy = dy, 0.0
                    elif plan == "YZ":
                        dx, dy, dz = 0.0, dx, dy
                    dx, dy, dz = rotate(dx, dy, dz, rot_axis, rot_angle)
                    # ----------------------------------------------
                    # Apply offset ONLY to move objects
                    # Select ONLY objects for THIS step
                    # ----------------------------------------------
                    step_move_objects = {}
                    for lbl in (data.get("move"), data.get("move1"), data.get("move2")):
                        if not lbl or lbl == "none":
                            continue
                        name = label_to_name.get(lbl)
                        if not name:
                            continue
                        obj = move_objects.get(name)
                        if obj:
                            step_move_objects[name] = obj

                    # APPLY OFFSETS
                    for name, move_obj in step_move_objects.items():
                        snap = placement_snaps[name]
                        # print("Moving", move_obj.Name, move_obj.TypeId)
                        apply_direct_offset(move_obj, snap, dx, dy, dz)
                        # dump_placement_text(move_obj, f"After offset dx={dx:.3f} dy={dy:.3f}")
                    doc.recompute()

                    # TRACE
                    hits = run_trace()
                    print("HITS", len(hits))

                    # STORE
                    doc_name = f"{doc.Name}_{batch.Label}_{step.Id}"
                    store_hits(db, doc_name, hits, dx, dy, dz, moved_objects_as_str)

                    done_iters += 1
                    prog_bar.setValue(done_iters)

    finally:
        # ------------------------------------------------------
        # RESTORE ORIGINAL PLACEMENT
        # ------------------------------------------------------
        db.commit()

        for name, snap in placement_snaps.items():
            obj = move_objects.get(name)
            if obj:
                App.Console.PrintLog(f"Restoring {obj.Name}\n")
                restore_placement(obj, snap)

        doc.recompute()

        collector.RunMode = "AUTO"
        _trigger_ray_engine(reason="batch_finished", force=True)

        status_lbl.setText("Stopped" if stop_flag_func() else "Done")


def run_trace():
    _trigger_ray_engine(reason="batch_trace", source=None, force=True)
    hits, _stats = collect_ray_hits_and_stats(mode="final")
    return hits


# def trace_and_store(doc_name, db, move_objects, placement_snaps, dx, dy, dz, moved_objects_str):
def store_hits(db, doc_name, hits, dx, dy, dz, moved_objects_str):

    accum = {}

    for hit in hits:
        target = hit.get("object")
        if not target:
            continue

        emitter = hit.get("emitter_id") or "__UNKNOWN__"
        key = (target, emitter)

        acc = accum.setdefault(
            key,
            {
                "count": 0,
                "power_in": 0.0,
                "power_out": 0.0,
                "absorbed_power": 0.0,
            },
        )

        acc["count"] += 1
        acc["power_in"] += hit.get("power_in") or 0.0
        acc["power_out"] += hit.get("power_out") or 0.0
        acc["absorbed_power"] += hit.get("absorbed_power") or 0.0

    rows = []

    for (target, emitter), info in accum.items():
        rows.append(
            (
                doc_name,
                target,
                emitter,
                "",
                moved_objects_str,
                dx,
                dy,
                dz,
                info["count"],
                info["power_in"],
                info["power_out"],
                info["absorbed_power"],
            )
        )

        rows.append(
            (
                doc_name,
                target,
                "__ALL__",
                "",
                moved_objects_str,
                dx,
                dy,
                dz,
                info["count"],
                info["power_in"],
                info["power_out"],
                info["absorbed_power"],
            )
        )

    if rows:
        db.write_hits_batch(rows)
        db.flush_if_needed()


def run_steps_for_batch_old(batch, prog_bar, status_lbl, pump_events_func, stop_flag_func):

    App.Console.PrintLog("▶ Starting batch run\n")

    from oba_rayengine.oba_ray_analyser import collect_ray_hits_and_stats
    from .scan_db import HitsDB

    doc = batch.Document
    db = HitsDB()

    # ----------------------------------------------------------
    # Find OBARayConfig
    # ----------------------------------------------------------

    collector = None
    for o in doc.Objects:
        if hasattr(o, "Proxy") and o.Proxy and o.Proxy.__class__.__name__ == "OBARayConfig":
            collector = o
            break

    if not collector:
        status_lbl.setText("No OBARayConfig – aborting")
        App.Console.PrintError("❌ OBARayConfig missing\n")
        return

    collector.RunMode = "MANUAL"

    # ----------------------------------------------------------
    # Collect active steps
    # ----------------------------------------------------------

    parsed_steps = []
    total_iters = 0

    for step in batch.Group:
        if not getattr(step, "Active", True):
            continue

        try:
            data = json.loads(step.DataJSON or "{}")
        except Exception:
            data = {}

        A = max(1, int(data.get("angle", 5)))
        rf = float(data.get("rf", 0.0))
        rt = float(data.get("rt", 0.4))
        R = max(1, int(data.get("rs", 4)))

        iters = A * R - (A - 1) if rf == 0 else A * R
        total_iters += iters

        parsed_steps.append((step, data, A, rf, rt, R))

    prog_bar.setRange(0, total_iters)
    prog_bar.setValue(0)

    # ----------------------------------------------------------
    # Label → Name map
    # ----------------------------------------------------------

    label_to_name = {o.Label: o.Name for o in doc.Objects}

    # ----------------------------------------------------------
    # Collect move-objects + snapshot Placement
    # ----------------------------------------------------------

    move_objects = {}
    placement_snaps = {}

    for step, data, *_ in parsed_steps:

        for lbl in (data.get("move"), data.get("move1"), data.get("move2")):
            if not lbl or lbl == "none":
                continue

            raw_obj = doc.getObject(label_to_name.get(lbl, ""))
            move_obj = resolve_move_target(raw_obj)

            if not move_obj:
                App.Console.PrintWarning(f"[Batch] Object '{lbl}' cannot be moved (ignored)\n")
                continue

            key = move_obj.Name
            if key in move_objects:
                continue

            move_objects[key] = move_obj
            placement_snaps[key] = snapshot_placement(move_obj)

            dump_placement_text(move_obj, header=f"Original placement for {move_obj.Name}")
            clear_placement_expressions(move_obj)

    doc.recompute()
    # ----------------------------------------------------------
    # RUN
    # ----------------------------------------------------------
    done_iters = 0

    try:
        for step, data, A, rf, rt, R in parsed_steps:
            if stop_flag_func():
                break

            step_move_names = []  # för att lagra i DB senare
            for lbl in (data.get("move"), data.get("move1"), data.get("move2")):
                if not lbl or lbl == "none":
                    continue
                name = label_to_name.get(lbl)
                if name:
                    step_move_names.append(name)
            moved_objects_as_str = ";".join(sorted(step_move_names))

            plan = data.get("plan", "XY")
            rot_axis = data.get("rotAxis", "X")
            rot_angle = math.radians(float(data.get("rotAngle", 0.0)))

            r_step = 0 if R <= 1 else (rt - rf) / float(R - 1)

            for ri in range(R):
                radius = rf + r_step * ri
                ai_range = range(1) if ri == 0 and abs(radius) < 1e-12 else range(A)

                for ai in ai_range:
                    if stop_flag_func():
                        break
                    pump_events_func()

                    ang = (2.0 * math.pi / A) * ai
                    dx = radius * math.cos(ang)
                    dy = radius * math.sin(ang)
                    dz = 0.0

                    if plan == "XZ":
                        dz, dy = dy, 0.0
                    elif plan == "YZ":
                        dx, dy, dz = 0.0, dx, dy
                    dx, dy, dz = rotate(dx, dy, dz, rot_axis, rot_angle)
                    # ----------------------------------------------
                    # Apply offset ONLY to move objects
                    # Select ONLY objects for THIS step
                    # ----------------------------------------------
                    step_move_objects = {}
                    for lbl in (data.get("move"), data.get("move1"), data.get("move2")):
                        if not lbl or lbl == "none":
                            continue
                        name = label_to_name.get(lbl)
                        if not name:
                            continue
                        obj = move_objects.get(name)
                        if obj:
                            step_move_objects[name] = obj

                    for name, move_obj in step_move_objects.items():
                        snap = placement_snaps[name]
                        # print("Moving", move_obj.Name, move_obj.TypeId)
                        apply_direct_offset(move_obj, snap, dx, dy, dz)
                        # dump_placement_text(move_obj, f"After offset dx={dx:.3f} dy={dy:.3f}")
                    doc.recompute()
                    # ----------------------------------------------
                    # ANALYSIS
                    # ----------------------------------------------

                    _trigger_ray_engine(reason="Manual trace for scanner steps", source=None, force=True)

                    hits, _stats = collect_ray_hits_and_stats(mode="final")
                    doc_name = f"{doc.Name}_{batch.Label}_{step.Id}"
                    accum = {}

                    for hit in hits:
                        target = hit.get("object")
                        if not target:
                            continue

                        obj = doc.getObject(target)
                        if not obj:
                            continue

                        optical_type = getattr(obj, "OpticalType", "UNKNOWN")
                        emitter = hit.get("emitter_id") or "__UNKNOWN__"
                        key = (target, emitter)

                        acc = accum.setdefault(
                            key,
                            {
                                "count": 0,
                                "power_in": 0.0,
                                "power_out": 0.0,
                                "absorbed_power": 0.0,
                                "optical_type": optical_type,
                            },
                        )

                        acc["count"] += 1
                        acc["power_in"] += hit.get("power_in") or 0.0
                        acc["power_out"] += hit.get("power_out") or 0.0
                        acc["absorbed_power"] += hit.get("absorbed_power") or 0.0

                    rows = []
                    for (target, emitter), info in accum.items():
                        rows.append(
                            (
                                doc_name,
                                target,
                                emitter,
                                info["optical_type"],
                                moved_objects_as_str,  # exempel "Mirror001;Lens002"
                                dx,
                                dy,
                                dz,
                                info["count"],
                                info["power_in"],
                                info["power_out"],
                                info["absorbed_power"],
                            )
                        )
                        rows.append(
                            (
                                doc_name,
                                target,
                                "__ALL__",
                                info["optical_type"],
                                moved_objects_as_str,
                                dx,
                                dy,
                                dz,
                                info["count"],
                                info["power_in"],
                                info["power_out"],
                                info["absorbed_power"],
                            )
                        )

                    if rows:
                        db.write_hits_batch(rows)

                    done_iters += 1
                    if done_iters % 20 == 0:
                        db.commit()

                    prog_bar.setValue(done_iters)

    finally:
        # ------------------------------------------------------
        # RESTORE ORIGINAL PLACEMENT
        # ------------------------------------------------------
        db.commit()

        for name, snap in placement_snaps.items():
            obj = move_objects.get(name)
            if obj:
                App.Console.PrintLog(f"Restoring {obj.Name}\n")
                restore_placement(obj, snap)

        doc.recompute()

        collector.RunMode = "AUTO"
        _trigger_ray_engine(reason="batch_finished", force=True)

        status_lbl.setText("Stopped" if stop_flag_func() else "Done")
