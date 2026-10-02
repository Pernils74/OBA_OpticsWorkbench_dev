Scanning the optimization and ray-tracing code for sync, cache, and stale-state risks.

Searched for regex `class EvaluationService|def evaluate|apply_cad_params|aggregate_interaction_clusters|_trigger_ray_engine|OBARayEngine|notify_event|_run\(|_trace_scene|QTimer|singleShot|processEvents|invokeMethod|emit\(|signal|OBARealtimeObserver|slotChangedObject|_flush|RunMode|global |singleton|cache|static|class variable` (`**/*.py`), 988 results

Searched for regex `trial\.params|trial\.values|trial\.user_attrs|unselected_params|save|study|Optuna|optuna` (`**/*.py`), 897 results

Gathering the main evaluation and ray-engine code paths, plus related CAD parameter and cluster functions.

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/OPTIMIZER/evaluation_service.py#1-1), lines 1 to 220

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/oba_objects/oba_base.py#1-1), lines 1 to 220

Searched for regex `def apply_cad_params|apply_cad_params\(|def aggregate_interaction_clusters|aggregate_interaction_clusters\(|RunMode|_trigger_ray_engine\(|class OBARealtimeObserver|slotChangedObject|_flush|singleShot|QTimer` (`**/*.py`), 269 results

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/oba_rayengine/oba_ray_engine.py#1-1), lines 1 to 260

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/oba_rayengine/oba_ray_analyser.py#1-1), lines 1 to 260

Collecting CAD param, observer flush, and ray-manager state details to pinpoint stale/trial mismatch sources.

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/oba_objects/oba_base.py#220-220), lines 220 to 360

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/OPTIMIZER/spreadsheet_utils.py#300-300), lines 300 to 460

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/oba_rayengine/oba_ray_core.py#1-1), lines 1 to 260

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/oba_rayengine/oba_ray_core.py#260-260), lines 260 to 520

Reviewing spreadsheet parameter write path for deferred updates or incomplete recomputation.

Searched for regex `def set_params_by_name|set_params_by_name\(|Spreadsheet::Sheet|ss.set` (`**/*.py`), 80 results

Found `set_params_by_name` implementation; now reading it to confirm whether parameter writes are atomic or deferred.

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/OPTIMIZER/spreadsheet_utils.py#1-1), lines 1 to 140

Searched for regex `apply_cad_params(params)|restore|trial.params|targetWeights|run_single_metric|evaluationReady` (`**/OPTIMIZER/*.py`), 47 results

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/OPTIMIZER/optimize_dialog.py#430-430), lines 430 to 980

Searched for regex `def compute_baseline|compute_baseline\(` (`**/*.py`), 3 results

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/OPTIMIZER/evaluation_service.py#220-220), lines 220 to 360

Now inspecting the Optuna worker and trial saving path to see if state gets stored after side effects or with wrong params.

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/OPTIMIZER/optimize_worker.py)

Next I’m checking restore and read-back paths for trial params and metric re-evaluation, including any stale param handling.

Searched for regex `restore|apply_cad_params\(best_trial\.params\)|best_trial\.params|trial\.params|user_attrs|metrics|recompute\(` (`**/OPTIMIZER/*.py`), 89 results

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/OPTIMIZER/optuna_plotting.py#430-430), lines 430 to 520

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/OPTIMIZER/optimize_dialog.py#460-460), lines 460 to 540

Now checking mesh intersection caching and trace code for geometry reuse that can persist between evaluations.

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/oba_rayengine/oba_intersect_mesh.py#1-1), lines 1 to 260

Checking async or timer-based behavior inside ray tracing and scene collection.

Searched for regex `QtCore|QTimer|singleShot|invokeMethod|emit\(|signal|processEvents|updateGui|Gui.updateGui|_pending|schedule\(` (`**/oba_rayengine/*.py`), 30 results

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/oba_rayengine/oba_ray_core.py#420-420), lines 420 to 660

Searched for regex `requestEvaluate.connect|requestEvaluate.connect\(|on_evaluated|self\.worker|EvaluationService` (`**/OPTIMIZER/*.py`), 10 results

Read [](file:///c%3A/Users/psnygg/AppData/Roaming/FreeCAD/v1-1/Mod/OBA_OpticsWorkbench_dev/OPTIMIZER/optimize_dialog.py#80-80), lines 80 to 220

I have enough code context to start the risk analysis now.

## Investigation Summary

I reviewed the key files and found several real risk points that can explain why:

> `Optuna` saved result X  
> restore same trial  
> re-evaluate  
> get result Y

The main problems are stale geometry/mesh state, asynchronous trace timing, singleton ray storage, and possible hidden recompute/observer interactions.

---

## 1. evaluation_service.py

### 1.1 `EvaluationService.evaluate()`

- Risk: **HIGH**
- Issue: `apply_cad_params(params)` → `doc.recompute()` → `_trigger_ray_engine(... force=True)` → `aggregate_interaction_clusters(...)`
- Why dangerous:
  - `App.ActiveDocument.recompute()` must finish, but FreeCAD may still have deferred updates, expression evaluation, or link propagation after return.
  - `_trigger_ray_engine(force=True)` runs a ray trace, but the engine uses `OBARayEngine.instance()` and shared state; no explicit sync barrier ensures all ray generation is finished before cluster extraction.
- Failure scenario:
  - Trial N applies params, recompute returns before all shape binders are committed, trace runs over partly updated geometry, then metrics are extracted from wrong rays.
- Suggested fix:
  - Add explicit scene/shape validation after recompute, before trace.
  - Ensure `_trigger_ray_engine(force=True)` returns only after ray trace and all internal state are stable.
  - Possibly call `Gui.updateGui()` or FreeCAD internals only if necessary, and avoid returning until `_run()` completes.

### 1.2 `EvaluationService.evaluate()` early `return` on `_busy`

- Risk: **MEDIUM**
- Issue: if `_busy` is true, evaluation request is silently ignored.
- Why dangerous:
  - If an evaluation starts while a previous one is still running, the later request may be dropped, causing trial state mismatch or lost evaluations.
- Failure scenario:
  - Optuna asks for trial N+1 before trial N is fully finished. The request is skipped, leaving the worker stuck or using stale results.
- Suggested fix:
  - Queue requests or reject them with an explicit error rather than silent return.

### 1.3 Scanner path separated from fast metrics

- Risk: **LOW/MEDIUM**
- Issue: scanner metrics are computed on the cluster result from the same `aggregate_interaction_clusters()` snapshot.
- Why dangerous:
  - If scanner metrics depend on config or geometry not reflected in the cluster extraction mode, they may diverge.
- Suggested fix:
  - Confirm scanner-specific rays are not required to be traced separately, or add a dedicated trace+cluster step for scanner metrics.

---

## 2. oba_base.py

### 2.1 `_trigger_ray_engine()`

- Risk: **HIGH**
- Issue: engine logic simply calls `OBARayEngine.instance().notify_event(...)`. `force=True` means `_run(force=True)` inside engine, but there is no external guarantee that this trace completed before returning from `_trigger_ray_engine()`.
- Why dangerous:
  - The public `evaluate()` path relies on `_trigger_ray_engine` being synchronous.
- Suggested fix:
  - Make `_trigger_ray_engine(force=True)` explicitly synchronous if `force=True`, with return only after `_trace_scene()` and any pending `_dirty` processing are finished.
  - Add logging around `notify_event` and `_run` entry/exit.

### 2.2 `OBARealtimeObserver._flush()`

- Risk: **MEDIUM**
- Issue: observer flushes after a `QTimer.singleShot(0, ...)` delay, and then triggers a ray trace after `doc.recompute()`. If optimization also calls recompute and `_trigger_ray_engine`, this can interleave.
- Why dangerous:
  - Manual-or-script changes could still cause observer-triggered traces at the same time as Optuna evaluations.
  - Observers may trigger a trace after parameters already changed again, overwriting the desired trace state.
- Failure scenario:
  - Trial restore triggers recompute, observer flush triggers a second trace from previous dirty state; cluster extraction reads the later trace or mixed ray manager contents.
- Suggested fix:
  - Disable or isolate `OBARealtimeObserver` during optimization/replay (`enabled = False`) and ensure no UI observer triggers run.
  - Add a global “optimization trace lock” around `apply_cad_params()` and `_trigger_ray_engine()`.

### 2.3 `OBARealtimeObserver.slotChangedObject`

- Risk: **MEDIUM**
- Issue: it allows trace on `Placement`/`Shape` changes if `is_manual_translation()` returns true.
- Why dangerous:
  - Even in manual mode, if some CAD update is seen as manual, a trace can run asynchronously.
- Suggested fix:
  - During optimization, set observer to disabled or ensure `slotChangedObject` does not trigger a trace from script-based updates.

---

## 3. oba_ray_engine.py

### 3.1 `notify_event()`

- Risk: **HIGH**
- Issue: `notify_event()` returns immediately in many cases; trace may be scheduled asynchronously through `_debounce`.
- Why dangerous:
  - If `force=False` or `cfg.DisableDebounce` is false, a scheduled trace may run later and interfere with the next evaluation.
- Failure scenario:
  - A previous trace is waiting in debounce; next evaluation begins and reuses old ray manager state.
- Suggested fix:
  - Ensure `force=True` path does not use debounce.
  - Add a trace state flag and maybe clear pending debounce timers before running new trace.

### 3.2 `_run()` and `_dirty`

- Risk: **HIGH**
- Issue:
  - `_run()` handles `_dirty` by re-running after the first run completes.
  - It does not track whether a new `notify_event()` arrived while the current trace was running.
- Why dangerous:
  - If `notify_event` occurs during `_in_compute`, it sets `_dirty=True` and exits. Then `_run(force=True)` is called after completion, but this may produce a second trace from stale or partial state.
- Failure scenario:
  - Trial N triggers trace; while trace is running, a second geometry change arrives; the second run may trace late geometry or stale scene data and overwrite the first result.
- Suggested fix:
  - Add a queue of trace requests or version numbers. Ensure `notify_event` during compute captures the latest scene and only re-traces once.
  - Make `_dirty` clear only after the re-run completes, not before.

### 3.3 `_trace_scene()`

- Risk: **MEDIUM/HIGH**
- Issue:
  - It collects scene with `collect_scene(doc)` and then builds BVH based on `ray_targets`.
  - It clears `OBARayManager` before tracing.
- Why dangerous:
  - If `collect_scene(doc)` returns stale objects due to recompute not fully committed, the ray set will be wrong.
  - `rm.clear(mode="final"); rm.clear(mode="preview")` clears all ray data, but if another trace completed concurrently, you may delete desired data.
- Suggested fix:
  - Make scene collection and clearing tied to a trace version ID.
  - Validate that `doc` is stable before `collect_scene()`.

### 3.4 `OBARayManager.clear(mode="final")`

- Risk: **MEDIUM**
- Issue:
  - It clears stored rays by list filtering, but if rays from different run modes or evaluations persist, cluster extraction may see mixed modes if mode is wrong.
- Why dangerous:
  - If a previous trace left `ray.mode="preview"` and the new evaluation uses `mode="final"`, cluster extraction only filters by final, but stale preview rays may still exist for other evaluation code or side effects.
- Suggested fix:
  - Use a dedicated per-evaluation timestamp or run-id to isolate rays.
  - Perhaps clear all modes before each new forced evaluation to avoid mixing old rays.

### 3.5 `OBAGuiDispatcher.schedule()`

- Risk: **LOW**
- Issue:
  - Uses QTimer.singleShot(0) to update preview visuals later.
- Why dangerous:
  - Not directly tied to metric evaluation, but can cause UI callbacks after ray traces.
- Suggested fix:
  - Keep UI update separate from evaluation logic.

---

## 4. oba_intersect_mesh.py

### 4.1 Global mesh cache `_GLOBAL_MESH_CACHE`

- Risk: **HIGH**
- Issue:
  - The cache key is `(geo_hash, round(tolerance,7))`.
  - `geo_hash` from a FreeCAD face may not change for geometry updates, or may be reused across object changes.
- Why dangerous:
  - If geometry changes but `face.hashCode()` remains identical or if the face object is reused, the engine may use stale mesh geometry.
- Failure scenario:
  - Trial N changes object shape fractionally; `hashCode()` equals previous value; old triangle mesh is reused, leading to wrong ray intersections and metrics on stale geometry.
- Suggested fix:
  - Invalidate the cache on document recompute or when object geometry changes.
  - Use a stronger cache key such as `(face.hashCode(), face.Shape.hashCode(), face.BoundBox tuple)` or simply clear cache per trace.
  - Do not rely on a global cache across evaluations unless you can guarantee cache invalidation on geometry change.

### 4.2 `target.update(cache_entry)`

- Risk: **MEDIUM**
- Issue:
  - Cached mesh data is injected back into target objects. If a target object is reused in multiple evaluation calls, stale fields may persist.
- Suggested fix:
  - If caching, clone target dictionaries rather than mutate existing scene objects in place.
  - Use fresh target dictionaries each trace.

---

## 5. oba_ray_analyser.py

### 5.1 `aggregate_interaction_clusters()`

- Risk: **HIGH**
- Issue:
  - It uses `rm = OBARayManager()` and `rays = [r for r in rm.get_all_rays() if r.mode == mode]`.
  - The ray manager is a singleton per document, and rays from previous evaluations remain until cleared.
- Why dangerous:
  - If some rays are not cleared or if a preview trace overlaps with final trace, metrics can read stale rays.
  - There is no explicit check that `get_all_rays()` returns only the latest evaluation’s rays.
- Failure scenario:
  - Trial restore loads params and recompute. If old rays are still present in `rm.rays`, cluster extraction may include them if mode matches.
- Suggested fix:
  - Use an evaluation or trace id in `OBARay` objects.
  - Track current final rays by ID and filter by current run.
  - Clear `OBARayManager` completely before every forced optimization trace, not just `mode="final"` and `mode="preview"` separately.

### 5.2 `mode="final"` vs `mode="preview"`

- Risk: **MEDIUM**
- Issue:
  - The engine sets ray.mode based on trace type. If mode selection is wrong, cluster aggregation may ignore rays or use wrong rays.
- Why dangerous:
  - On optimization, evaluation uses mode="final"; if `run_final` is wrong due to GUI visibility or config bug, actual trace may be preview while cluster extraction only sees final.
- Suggested fix:
  - Ensure `run_final` is deterministic during evaluation and does not depend on `App.GuiUp` or view visibility.

---

## 6. spreadsheet_utils.py

### 6.1 `apply_cad_params()`

- Risk: **MEDIUM**
- Issue:
  - It writes into spreadsheet cells but does not recompute or validate after writing.
- Why dangerous:
  - FreeCAD spreadsheet formula evaluation may happen lazily or after `doc.recompute()`, but if a shape binder depends on sheet values, that recompute may need additional passes.
- Failure scenario:
  - Trial restore writes params to sheet and calls `doc.recompute()`, but some dependent geometry formulas or expressions update only later, causing trace to use partially updated geometry.
- Suggested fix:
  - After `set_params_by_name`, optionally call `App.ActiveDocument.recompute()` again or verify dependent object's shape.
  - Use `doc.recompute()` after param writes in every apply path.
  - Consider `App.ActiveDocument.recompute()` twice when formulas cascade.

### 6.2 `set_params_by_name()` atomicity

- Risk: **LOW/MEDIUM**
- Issue:
  - `set_params_by_name()` loops over params and writes them individually to spreadsheet cells.
- Why dangerous:
  - If formulas respond to intermediate values or spreadsheet cells are observed, the document may recompute partially between writes.
- Suggested fix:
  - Disable observers during parameter application.
  - Set all cell values first, then force a single recompute.
  - If possible, suspend document recompute while writing.

---

## 7. optimize_dialog.py restore and manual mode

### 7.1 `_enable_manual_raytrace_mode()` and `_restore_manual_raytrace_mode()`

- Risk: **MEDIUM**
- Issue:
  - Optimization sets `OBARayConfig.RunMode = "MANUAL"`, but the restore logic only resets it later. There is no guarantee the config is read consistently everywhere.
- Why dangerous:
  - If other code bypasses `RunMode` or the config is missing, a trace may still run automatically.
- Suggested fix:
  - Explicitly disable observer triggers during optimization and restore only once.
  - Add a debug assertion that `RunMode` is actually manual before each optimization.

### 7.2 `apply_trial()` in optuna_plotting.py

- Risk: **MEDIUM**
- Issue:
  - Restoring a trial only applies `trial.params` and optionally unselected params, then `doc.recompute()`.
  - It does not disable observers or force a fresh ray trace before plotting or metrics.
- Why dangerous:
  - This restore path may not match optimization evaluation path, so the displayed result may differ even if `trial.params` are equal.
- Suggested fix:
  - Restore with the same evaluation path used during optimization: disable observer auto traces, apply params, recompute, force trace, aggregate clusters.
  - Use `trial.user_attrs["metrics"]` as reference.

### 7.3 `trial.set_user_attr("params", params)` in worker

- Risk: **LOW**
- Issue:
  - It records params separately from `trial.params`.
- Why dangerous:
  - If parameter suggestion or `trial` param storage mismatches, saved user_attrs and `trial.params` may diverge.
- Suggested fix:
  - Only use `trial.params`, or ensure `user_attrs["params"]` is identical to `trial.params` after `study.tell()`.

---

## 8. optimize_worker.py

### 8.1 `requestEvaluate.emit(params, self.unselected_params)`

- Risk: **MEDIUM**
- Issue:
  - The worker emits evaluation requests and then busy-waits in the thread until `_waiting` is cleared.
- Why dangerous:
  - If signal delivery crosses thread boundaries or `_waiting` remains true because of a missed result, the worker may hang or mis-associate results.
- Suggested fix:
  - Use a proper queued connection and a response signal; avoid busy wait.
  - Confirm `results` are always delivered and `on_evaluated` is connected.

### 8.2 `trial.set_user_attr("metrics", results)`

- Risk: **LOW**
- Issue:
  - This writes metric result snapshot after evaluation.
- Why dangerous:
  - If metrics are computed again later from same trial, you may compare against stale user_attrs.
- Suggested fix:
  - This is fine if results are correct and no later side effects change metrics. But use it carefully.

### 8.3 `self.study.tell(trial, values)`

- Risk: **LOW**
- Issue:
  - `values` are computed from `results`; if `results` is stale or wrong, trial optimization is corrupted.
- Why dangerous:
  - The core issue is upstream in evaluation, not here.
- Suggested fix:
  - Validate with a second trace or consistency check before telling.

---

## 9. Global State and Singleton Issues

### 9.1 `OBARayEngine._instance` and `OBARayManager` singleton

- Risk: **HIGH**
- Issue:
  - `OBARayEngine.instance()` is global per process.
  - `OBARayManager` is document-scoped, but rays are stored globally within a doc instance until cleared.
- Why dangerous:
  - If multiple traces or tests run in the same document, old rays remain until explicit clear.
- Suggested fix:
  - Add explicit evaluation/trace IDs to rays and use them in aggregation.
  - Clear `OBARayManager` before any forced eval trace. Consider `rm.clear(mode=None)` before `trace_emitter/trace_beam`.

### 9.2 FreeCAD doc state vs ray engine content

- Risk: **HIGH**
- Issue:
  - There is no atomic transaction tying param application, recompute, and ray engine state.
- Why dangerous:
  - The system can have “document geometry changed, trace triggered, ray manager not cleared, aggregate clusters reads old/new mix”.
- Suggested fix:
  - Define an explicit “evaluation session”:
    1. disable observers
    2. apply params
    3. recompute
    4. clear ray manager fully
    5. trigger forced ray trace
    6. wait for completion
    7. aggregate clusters from current trace id
    8. re-enable observers

---

## 10. Potential Root Causes for mismatched restore vs rerun

### 10.1 Stale mesh cache

- Most plausible: `oba_intersect_mesh._GLOBAL_MESH_CACHE` may serve an outdated `tri_array` for a changed face.
- Risk: **HIGH**
- Reason: face geometry may be different while `geo_hash` is unchanged or cache not invalidated.
- Example: Trial N changes mirror shape, trace uses cached mesh from Trial N-1.

### 10.2 Incomplete geometry commit after recompute

- Most plausible: `doc.recompute()` does not guarantee all binder/formula propagation is complete.
- Risk: **HIGH**
- Reason: FreeCAD internal update and observer flush may still be pending.
- Example: `apply_cad_params()` writes spreadsheet values, recompute returns, but some dependent shape still uses old param until next recompute.

### 10.3 Mixed ray manager state

- Most plausible: `aggregate_interaction_clusters()` uses `rm.get_all_rays()` and old rays may remain.
- Risk: **HIGH**
- Reason: no run-id or strict clear.
- Example: Trial restore gets rays from previous trace plus current trace.

### 10.4 Observer-triggered extra traces

- Most plausible: manual observer flush or `OBARealtimeObserver` triggers while optimization is running.
- Risk: **MEDIUM/HIGH**
- Reason: observer may run `doc.recompute()` → trace asynchronously.
- Example: a parameter update triggers observer which sets `_dirty`, then evaluation trace runs, then observer-driven trace overwrites the state.

### 10.5 Forced vs manual run mode mismatch

- Most plausible: `force=True` semantics assume synchronous trace, but engine does not fully isolate state.
- Risk: **MEDIUM**
- Reason: `_dirty` rerun or debounce could still occur.
- Example: trace from N is still computing when another event arrives, causing late overwrite.

---

## 11. Specific suspicious code locations

| File                  | Function                           | Risk   | Why                                                                |
| --------------------- | ---------------------------------- | ------ | ------------------------------------------------------------------ |
| evaluation_service.py | `evaluate()`                       | HIGH   | Assumes recompute+trace are fully complete before metrics.         |
| oba_base.py           | `_trigger_ray_engine()`            | HIGH   | No external sync guarantee for forced trace.                       |
| oba_base.py           | `OBARealtimeObserver._flush()`     | MEDIUM | observer can inject traces after optimization changes.             |
| oba_ray_engine.py     | `notify_event()`                   | HIGH   | debounce and dirty flags permit async traces.                      |
| oba_ray_engine.py     | `_run()` / `_dirty`                | HIGH   | stale or overlapping re-run conditions.                            |
| oba_ray_analyser.py   | `aggregate_interaction_clusters()` | HIGH   | uses singleton ray storage with no run isolation.                  |
| oba_intersect_mesh.py | `build_mesh_engine()`              | HIGH   | global mesh cache may reuse stale CAD geometry.                    |
| spreadsheet_utils.py  | `apply_cad_params()`               | MEDIUM | writes are not batched/isolated; may leave doc in transient state. |
| optimize_worker.py    | worker loop / signal wait          | MEDIUM | thread signaling may miss or delay results.                        |
| optuna_plotting.py    | `apply_trial()`                    | MEDIUM | restore path differs from evaluation path.                         |

---

## 12. Recommended fixes

1. **Make evaluation path atomic**
   - disable observers
   - apply params
   - recompute
   - clear ray manager fully
   - force trace synchronously
   - wait for trace completion
   - aggregate on current trace id
   - re-enable observers

2. **Invalidate or remove mesh caching**
   - clear `_GLOBAL_MESH_CACHE` on param/recompute or use stronger cache keys.

3. **Add ray-trace session IDs**
   - tag rays with evaluation/run id
   - aggregate only current run’s rays

4. **Enforce `force=True` as synchronous**
   - add wait and version logic in `OBARayEngine._run()` and `notify_event()`.

5. **Lock the observer during optimization**
   - set `OBARealtimeObserver.enabled = False`
   - restore after evaluation
   - ensure script changes do not trigger manual-mode trace.

6. **Improve `apply_cad_params()`**
   - batch writes
   - call `doc.recompute()` after all writes
   - maybe call a second recompute if there are dependents

7. **Validate restored trial path**
   - use exact same trace path used for optimization
   - compare `trial.params`, `user_attrs["params"]`, and stored metrics
   - maybe recompute before comparing

---

## 13. Most likely root cause combination

The most credible explanation for `X != Y` is:

- stale mesh cache + old ray data in `OBARayManager`
- incorrect assumption that `force=True` = complete trace
- observer or leftover trace state causing mixed ray sources
- re-run or debounce from `_dirty` overwriting the intended trace result

That combination can yield different hit counts for the same restored `trial.params`.

If you want, I can now make concrete patch suggestions for the top 3 fixes:

- synchronous forced trace
- full ray-manager clear / trace ID
- cache invalidation on recompute.
