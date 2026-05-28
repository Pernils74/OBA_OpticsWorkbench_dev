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


# run_steps_for_batch
#  ├── parse
#  ├── prepare
#  ├── loop
#  │    ├── compute offset
#  │    ├── apply
#  │    ├── trace
#  │    └── store
#  └── restore


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
# Debug
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

    collector = _find_ray_config(doc)
    if not collector:
        status_lbl.setText("No OBARayConfig – aborting")
        App.Console.PrintError("❌ OBARayConfig missing\n")
        return

    collector.RunMode = "MANUAL"

    parsed_steps, total_iters = _parse_steps(batch)

    prog_bar.setRange(0, total_iters)
    prog_bar.setValue(0)

    label_to_name = {o.Label: o.Name for o in doc.Objects}

    move_objects, placement_snaps = _prepare_move_objects(doc, parsed_steps, label_to_name)

    doc.recompute()

    done_iters = 0

    try:
        for step, data, A, rf, rt, R in parsed_steps:
            if stop_flag_func():
                break

            step_offset = getattr(step, "StepOffset", App.Vector(0, 0, 0))  # offset utifall man har klickat i heatmap

            moved_str, step_move_objects = _resolve_step_objects(step, data, label_to_name, move_objects)

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

                    dx, dy, dz = _compute_offset(ai, A, radius, plan, rot_axis, rot_angle)

                    # APPLY
                    _apply_offset(step_move_objects, placement_snaps, dx, dy, dz, step_offset)
                    doc.recompute()

                    # TRACE
                    hits = run_trace()

                    # STORE

                    step_id = step.Id
                    dx_eff = dx + step_offset.x
                    dy_eff = dy + step_offset.y
                    dz_eff = dz + step_offset.z
                    store_hits(db, step_id, hits, dx_eff, dy_eff, dz_eff, moved_str)

                    done_iters += 1
                    prog_bar.setValue(done_iters)

    finally:
        db.commit()
        _restore_all(move_objects, placement_snaps)
        doc.recompute()

        collector.RunMode = "AUTO"
        _trigger_ray_engine(reason="batch_finished", force=True)

        status_lbl.setText("Stopped" if stop_flag_func() else "Done")


def _parse_steps(batch):
    parsed = []
    total = 0

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
        total += iters

        parsed.append((step, data, A, rf, rt, R))

    return parsed, total


def _find_ray_config(doc):
    for o in doc.Objects:
        if hasattr(o, "Proxy") and o.Proxy and o.Proxy.__class__.__name__ == "OBARayConfig":
            return o
    return None


def _resolve_step_objects(step, data, label_to_name, move_objects):
    names = []

    for lbl in (data.get("move"), data.get("move1"), data.get("move2")):
        if not lbl or lbl == "none":
            continue

        name = label_to_name.get(lbl)
        if name:
            names.append(name)

    moved_str = ";".join(sorted(names))

    objs = {n: move_objects[n] for n in names if n in move_objects}

    return moved_str, objs


def _compute_offset(ai, A, radius, plan, rot_axis, rot_angle):
    ang = (2.0 * math.pi / A) * ai

    dx = radius * math.cos(ang)
    dy = radius * math.sin(ang)
    dz = 0.0

    if plan == "XZ":
        dz, dy = dy, 0.0
    elif plan == "YZ":
        dx, dy, dz = 0.0, dx, dy

    return rotate(dx, dy, dz, rot_axis, rot_angle)


def _compute_offset(ai, A, radius, plan, rot_axis, rot_angle):
    ang = (2.0 * math.pi / A) * ai

    dx = radius * math.cos(ang)
    dy = radius * math.sin(ang)
    dz = 0.0

    if plan == "XZ":
        dz, dy = dy, 0.0
    elif plan == "YZ":
        dx, dy, dz = 0.0, dx, dy

    return rotate(dx, dy, dz, rot_axis, rot_angle)


def _apply_offset(objects, snaps, dx, dy, dz, step_offset):
    for name, obj in objects.items():
        apply_direct_offset(
            obj,
            snaps[name],
            dx + step_offset.x,
            dy + step_offset.y,
            dz + step_offset.z,
        )
        # apply_direct_offset(obj, snaps[name], dx, dy, dz)


def _restore_all(move_objects, snaps):
    for name, snap in snaps.items():
        obj = move_objects.get(name)
        if obj:
            App.Console.PrintLog(f"Restoring {obj.Name}\n")
            restore_placement(obj, snap)


def _prepare_move_objects(doc, parsed_steps, label_to_name):
    move_objects = {}
    snaps = {}

    for _, data, *_ in parsed_steps:
        for lbl in (data.get("move"), data.get("move1"), data.get("move2")):
            if not lbl or lbl == "none":
                continue

            raw = doc.getObject(label_to_name.get(lbl, ""))
            obj = resolve_move_target(raw)

            if not obj:
                continue

            if obj.Name in move_objects:
                continue

            move_objects[obj.Name] = obj
            snaps[obj.Name] = snapshot_placement(obj)

            clear_placement_expressions(obj)

    return move_objects, snaps


def run_trace():
    _trigger_ray_engine(reason="batch_trace", source=None, force=True)
    hits, _stats = collect_ray_hits_and_stats(mode="final")
    return hits


def store_hits(db, step_id, hits, dx, dy, dz, moved_objects_str):
    accum = {}
    for hit in hits:
        target = hit.get("object")
        if not target:
            continue
        emitter = hit.get("emitter_id") or "__UNKNOWN__"
        key = (target, emitter)
        acc = accum.setdefault(
            key,
            {"count": 0, "power_in": 0.0, "power_out": 0.0, "absorbed_power": 0.0},
        )
        acc["count"] += 1
        acc["power_in"] += hit.get("power_in") or 0.0
        acc["power_out"] += hit.get("power_out") or 0.0
        acc["absorbed_power"] += hit.get("absorbed_power") or 0.0
    rows = []
    for (target, emitter), info in accum.items():
        row = (
            step_id,
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
        rows.append(row)
    if rows:
        db.write_hits_batch(rows)
        db.flush_if_needed()
