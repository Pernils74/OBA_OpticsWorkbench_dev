# -*- coding: utf-8 -*-
# batch_runner.py

import json
import math


import time


import FreeCAD as App

from oba_objects.oba_base import _trigger_ray_engine
from oba_rayengine.oba_ray_analyser import collect_ray_hits_and_stats
from oba_rayengine.oba_ray_engine import OBARayEngine


from .scan_db import HitsDB

BATCH_OFFSET_OBJ = "__OBABatchOffset__"

TARGET_TYPES = {
    "Mirror",
    "Lens",
    "Absorber",
    "Detector",
    "Grating",
}

EMITTER_TYPES = {
    "Beam",
    "Emitter",
}


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
# STEP OFFSET STATE / EXPRESSION INSTALLER
# ============================================================

# Runtime-only state.  The snapshot belongs to BatchRunner, not HeatmapViewer.
# Keyed by document + step so several viewers/documents do not share state.
_STEP_OFFSET_STATES = {}


def _step_state_key(step):
    doc = getattr(step, "Document", None)
    doc_name = getattr(doc, "Name", None) or str(id(doc))
    return (doc_name, getattr(step, "Name", str(id(step))))


def _get_step_state(step):
    return _STEP_OFFSET_STATES.get(_step_state_key(step))


def _numeric_expression(value):
    """Return a FreeCAD expression for a length-valued numeric component."""
    return f"{float(value):.15g} mm"


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
    """Remove all Placement expressions. Intended primarily for restore."""
    ee = obj.ExpressionEngine
    if not ee:
        return

    for path, _expr in list(ee):
        if path.startswith(".Placement"):
            obj.setExpression(path.lstrip("."), None)


def _clear_base_expressions(obj):
    """Remove only the three temporary Base component expressions."""
    ee = obj.ExpressionEngine
    if not ee:
        return

    for path, _expr in list(ee):
        normalized = path.lstrip(".")
        if normalized in {
            "Placement.Base.x",
            "Placement.Base.y",
            "Placement.Base.z",
        }:
            obj.setExpression(normalized, None)


def _original_base_expression(snap, component, value):
    path = f"Placement.Base.{component}"
    expr = snap["expressions"].get(path)

    if expr:
        return f"({expr}) + Step.StepOffset.{component}"

    return f"{_numeric_expression(value)} + Step.StepOffset.{component}"


def install_step_offset_expressions(step):
    """
    Install temporary Placement.Base expressions for all objects belonging
    to this step.

    The original Placement is snapshotted exactly once per activation.
    The installed expressions are always derived from that snapshot and
    Step.StepOffset.
    """
    if not step:
        return []

    state = _get_step_state(step)
    if state is None:
        state = _activate_step_state(step)

    for name, obj in state["objects"].items():
        snap = state["snapshots"][name]
        _clear_base_expressions(obj)

        base = snap["base"]
        obj.setExpression(
            "Placement.Base.x",
            _original_base_expression(snap, "x", base.x),
        )
        obj.setExpression(
            "Placement.Base.y",
            _original_base_expression(snap, "y", base.y),
        )
        obj.setExpression(
            "Placement.Base.z",
            _original_base_expression(snap, "z", base.z),
        )

    return list(state["objects"].values())


def apply_step_offset(step, offset=None, recompute=True):
    """
    Set the single source of truth for movement and ensure the temporary
    expressions are installed.

    `offset` is an optional App.Vector. If omitted, the current StepOffset
    property is used unchanged.
    """
    if not step:
        return []

    if offset is not None:
        step.StepOffset = App.Vector(offset.x, offset.y, offset.z)

    objects = install_step_offset_expressions(step)

    if recompute:
        doc = getattr(step, "Document", None) or App.ActiveDocument
        if doc:
            doc.recompute()

    return objects


def _activate_step_state(step):
    doc = getattr(step, "Document", None)
    if not doc:
        return {
            "objects": {},
            "snapshots": {},
            "step_offset": App.Vector(0, 0, 0),
        }

    data = {}
    try:
        data = json.loads(getattr(step, "DataJSON", "") or "{}")
    except Exception:
        data = {}

    label_to_name = {o.Label: o.Name for o in doc.Objects}
    objects = {}

    for lbl in (
        data.get("move"),
        data.get("move1"),
        data.get("move2"),
    ):
        if not lbl or lbl == "none":
            continue

        name = label_to_name.get(lbl)
        raw = doc.getObject(name) if name else None
        obj = resolve_move_target(raw)

        if obj and obj.Name not in objects:
            objects[obj.Name] = obj

    snapshots = {name: snapshot_placement(obj) for name, obj in objects.items()}

    step_offset = getattr(step, "StepOffset", App.Vector(0, 0, 0))
    state = {
        "objects": objects,
        "snapshots": snapshots,
        "step_offset": App.Vector(step_offset.x, step_offset.y, step_offset.z),
    }
    _STEP_OFFSET_STATES[_step_state_key(step)] = state

    install_step_offset_expressions(step)
    return state


def activate_step_offset(step):
    """
    Public activation entry point for clients such as HeatmapViewer.

    Returns the resolved objects so the caller can update labels/UI without
    owning any movement logic.
    """
    state = _get_step_state(step)
    if state is None:
        state = _activate_step_state(step)
    else:
        install_step_offset_expressions(step)

    return list(state["objects"].values())


def restore_step_state(step, recompute=True):
    """
    Restore the exact Placement/expression snapshot and the original
    StepOffset captured when the step was first activated.

    This is the only normal runtime path that writes Placement.Base directly.
    """
    if not step:
        return

    state = _get_step_state(step)
    if state is None:
        return

    for name, snap in state["snapshots"].items():
        obj = state["objects"].get(name)
        if not obj:
            continue

        # Expressions must be removed before direct Placement writes.
        clear_placement_expressions(obj)
        obj.Placement.Base = snap["base"]
        obj.Placement.Rotation = snap["rotation"]

        for path, expr in snap["expressions"].items():
            obj.setExpression(path, expr)

    step.StepOffset = App.Vector(state["step_offset"].x, state["step_offset"].y, state["step_offset"].z)

    if recompute:
        doc = getattr(step, "Document", None) or App.ActiveDocument
        if doc:
            doc.recompute()


def clear_step_offset_state(step):
    """Restore and forget runtime state for a step."""
    if not step:
        return
    restore_step_state(step)
    _STEP_OFFSET_STATES.pop(_step_state_key(step), None)


def restore_all_step_states(doc=None, recompute=True, forget=True):
    """Restore every active StepOffset state belonging to a document."""
    doc = doc or App.ActiveDocument
    if not doc:
        return

    keys = [key for key in list(_STEP_OFFSET_STATES) if key[0] == getattr(doc, "Name", None)]

    for key in keys:
        step = doc.getObject(key[1])
        if step:
            restore_step_state(step, recompute=False)
        if forget:
            _STEP_OFFSET_STATES.pop(key, None)

    if recompute:
        doc.recompute()


def commit_step_offset(step):
    """
    Explicitly make the current evaluated placement permanent.

    This operation removes the temporary StepOffset expressions and resets
    StepOffset. It does not use direct Placement writes.
    """
    if not step:
        return

    state = _get_step_state(step)
    if state is None:
        return

    for obj in state["objects"].values():
        _clear_base_expressions(obj)

    step.StepOffset = App.Vector(0, 0, 0)

    doc = getattr(step, "Document", None) or App.ActiveDocument
    if doc:
        doc.recompute()

    _STEP_OFFSET_STATES.pop(_step_state_key(step), None)


def restore_placement(obj, snap):
    """Compatibility wrapper for legacy internal callers."""
    clear_placement_expressions(obj)
    obj.Placement.Base = snap["base"]
    obj.Placement.Rotation = snap["rotation"]

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


def run_steps_for_batch(batch, prog_bar, status_lbl, pump_events_func, stop_flag_func, only_step_id=None):
    App.Console.PrintLog("▶ Starting batch run\n")

    doc = batch.Document
    db = HitsDB()

    collector = _find_ray_config(doc)

    if not collector:
        status_lbl.setText("No OBARayConfig – aborting")
        App.Console.PrintError("❌ OBARayConfig missing\n")
        return

    old_run_mode = collector.RunMode
    collector.RunMode = "MANUAL"
    parsed_steps, total_iters = _parse_steps(batch)

    # print("[runs_steps_for_batch] TOTAL_ITERS =", total_iters)
    # print("[runs_steps_for_batch] PARSED_STEPS =", len(parsed_steps))

    prog_bar.setRange(0, total_iters)
    prog_bar.setValue(0)

    label_to_name = {o.Label: o.Name for o in doc.Objects}

    move_objects, _ = _prepare_move_objects(doc, parsed_steps, label_to_name)

    doc.recompute()
    done_iters = 0
    trace_count = 0
    previous_step = None
    try:
        for step, data, A, rf, rt, R in parsed_steps:
            if stop_flag_func():
                break

            if only_step_id and step.Id != only_step_id:
                continue

            # Heatmap/interactive offset is the current StepOffset.
            step_offset = getattr(step, "StepOffset", App.Vector(0, 0, 0))

            moved_str, step_move_objects = _resolve_step_objects(step, data, label_to_name, move_objects)

            # If another step was active, restore it before taking/using
            # the next step's snapshot. This keeps object snapshots original.
            if previous_step is not None and previous_step is not step:
                restore_step_state(previous_step, recompute=False)

            # BatchRunner owns activation/expression installation.
            apply_step_offset(step, recompute=False)
            previous_step = step

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

                    # APPLY: StepOffset is the only movement source.
                    step.StepOffset = App.Vector(step_offset.x + dx, step_offset.y + dy, step_offset.z + dz)
                    apply_step_offset(step, recompute=True)

                    # world_positions = {}
                    # for obj in step_move_objects.values():
                    #     b = obj.Placement.Base
                    #     world_positions[obj.Name] = (
                    #         b.x,
                    #         b.y,
                    #         b.z,
                    #     )

                    # first_obj = next(iter(step_move_objects.values()), None)
                    # if first_obj:
                    #     world_x = first_obj.Placement.Base.x
                    #     world_y = first_obj.Placement.Base.y
                    #     world_z = first_obj.Placement.Base.z
                    # else:
                    #     world_x = world_y = world_z = 0.0

                    # snap = state["snapshots"][first_obj.Name]
                    # base_x = snap["base"].x
                    # base_y = snap["base"].y
                    # base_z = snap["base"].z

                    # TRACE
                    hits = run_trace()
                    trace_count += 1

                    # STORE

                    step_id = step.Id
                    dx_eff = dx + step_offset.x
                    dy_eff = dy + step_offset.y
                    dz_eff = dz + step_offset.z
                    store_hits(db, step_id, hits, dx_eff, dy_eff, dz_eff, moved_str)

                    done_iters += 1
                    prog_bar.setValue(done_iters)

        # print(f"[run_steps_for_batch] DONE: {done_iters} iterations, {trace_count} traces")

    except Exception as e:
        import traceback

        traceback.print_exc()
        print("BATCH CRASH:", e)
        raise

    finally:
        db.commit()
        # Restore the exact state captured by BatchRunner.
        for step, *_ in parsed_steps:
            if _get_step_state(step) is not None:
                restore_step_state(step, recompute=False)
        doc.recompute()

        _trigger_ray_engine(reason="batch_finished", force=True)

        collector.RunMode = old_run_mode
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


# def _compute_offset(ai, A, radius, plan, rot_axis, rot_angle):
#     ang = (2.0 * math.pi / A) * ai

#     dx = radius * math.cos(ang)
#     dy = radius * math.sin(ang)
#     dz = 0.0

#     if plan == "XZ":
#         dz, dy = dy, 0.0
#     elif plan == "YZ":
#         dx, dy, dz = 0.0, dx, dy

#     return rotate(dx, dy, dz, rot_axis, rot_angle)


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


def _prepare_move_objects(doc, parsed_steps, label_to_name):
    """Resolve move targets for the batch without creating a second snapshot."""
    move_objects = {}

    for _, data, *_ in parsed_steps:
        for lbl in (data.get("move"), data.get("move1"), data.get("move2")):
            if not lbl or lbl == "none":
                continue

            raw = doc.getObject(label_to_name.get(lbl, ""))
            obj = resolve_move_target(raw)

            if obj:
                move_objects[obj.Name] = obj

    return move_objects, {}


def run_trace():
    _trigger_ray_engine(reason="batch_trace", source=None, force=True)
    hits, _stats = collect_ray_hits_and_stats(mode="final")
    return hits


def store_hits(db, step_id, hits, dx, dy, dz, moved_objects_str):

    doc = App.ActiveDocument

    all_emitters = collect_scene_emitters(doc)
    all_targets = collect_scene_targets(doc)

    # ==========================================
    # Initiera ALLA kombinationer med nollor
    # ==========================================

    accum = {}

    for target in all_targets:
        for emitter in all_emitters:
            accum[(target, emitter)] = {
                "count": 0,
                "power_in": 0.0,
                "power_out": 0.0,
                "absorbed_power": 0.0,
            }

    # ==========================================
    # Lägg på riktiga träffar
    # ==========================================

    for hit in hits:

        target = hit.get("object")
        if not target:
            continue

        emitter = hit.get("emitter_id") or "__UNKNOWN__"

        key = (target, emitter)

        # Skydd om target/emitter inte finns i scensamlingen
        if key not in accum:
            accum[key] = {
                "count": 0,
                "power_in": 0.0,
                "power_out": 0.0,
                "absorbed_power": 0.0,
            }

        accum[key]["count"] += 1
        accum[key]["power_in"] += hit.get("power_in") or 0.0
        accum[key]["power_out"] += hit.get("power_out") or 0.0
        accum[key]["absorbed_power"] += hit.get("absorbed_power") or 0.0

    # ==========================================
    # Bygg databasrader
    # ==========================================

    rows = []

    for (target, emitter), info in accum.items():

        rows.append(
            (
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
        )

    if rows:
        db.write_hits_batch(rows)
        db.flush_if_needed()


# ============================================================
# UTILS
# ============================================================


def collect_scene_targets(doc):
    targets = []
    for obj in doc.Objects:
        otype = getattr(obj, "OpticalType", None)
        if otype not in TARGET_TYPES:
            continue
        if not obj.ViewObject.Visibility:
            continue
        targets.append(obj.Name)
    return targets


def collect_scene_emitters(doc):
    emitters = []
    for obj in doc.Objects:
        if getattr(obj, "OpticalType", None) not in EMITTER_TYPES:
            continue
        if hasattr(obj, "ViewObject") and not obj.ViewObject.Visibility:
            continue
        emitters.append(obj.Name)
    return emitters


def find_batch_object(doc):
    if not doc:
        return None

    for obj in doc.Objects:
        if obj.TypeId == "App::DocumentObjectGroupPython" and hasattr(obj, "GroupId"):
            return obj

    return None


def find_step_by_id(doc, step_id):
    if not doc:
        return None

    for obj in doc.Objects:
        if getattr(obj, "Id", "") == step_id:
            return obj

    return None
