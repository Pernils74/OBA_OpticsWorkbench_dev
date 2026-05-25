oba_ray_view.py
GUI‑ingång: ViewProvider + CreateRayCollector() + Gui.addCommand(...) + visualize_rays(...).


oba_ray_collector.py
Proxy/Motor: OBARayCollector (debounce, trigger_recompute(), execute()).


oba_ray_scene.py
Sceninsamling: collect_scene(doc) → returnerar emitters, mirrors, lenses, absorbers.


oba_ray_tracer.py
Raytracing: trace_emitter(...), propagate(...) (bounces, reflektion/absorption, mm).


_trigger_ray_engine(...)
Global trigger från dina optiska objekt (Emitter, Lense, Mirror, Absorber) efter ändringar.


## oba_ray_scene.py      → samlar scen
## oba_rays_phys.py      → OCC ray intersection
## ray_tracer.py         → emitter + ray propagation


collect_scene(doc)
        │
        ▼
emitters
mirrors
lenses
absorbers
world_shape
face_map
        │
        ▼
trace_emitter()
        │
        ▼
populate_emitter_rays()
        │
        ▼
propagate()
        │
        ▼
find_nearest_intersection()
        │
        ▼
OCC geometry engine


scene.py
   ↓
build OCC compound

ray_emitter.py
   ↓
generate rays

rays_phys.py
   ↓
OCC intersection

ray_propagate.py
   ↓
physics






[User clicks "Create Ray Collector" command]
                |
                v
    [oba_ray_view.CreateRayCollector()]
                |
                +--> create Part::FeaturePython "OBARayCollector"
                |        |
                |        +--> attach proxy: OBARayCollector (oba_ray_collector.py)
                |        +--> attach view:  ViewProviderRayCollector (oba_ray_view.py)
                |
                v
           [Command registered: Gui.addCommand("CreateRayCollector")]

-- RUNTIME FLOW ----------------------------------------------------------

[Optical property changed (Emitter/Lense/Mirror/Absorber)]
                |
                v
      [_trigger_ray_engine(msg, obj_context)]
                |
                +--> Find doc; getObject("OBARayCollector")
                |    if missing: [Notice] "No Ray Collector..."
                |
                +--> engine.Proxy.trigger_recompute()
                |
                v
     [Debounce Timer 300 ms in OBARayCollector]
                |
                v
   [_run_raytrace(): touch() -> document.recompute()]
                |
                v
        [execute(obj) in OBARayCollector]
                |
                +--> collect_scene(doc)          (oba_ray_scene.py)
                |       -> emitters, mirrors, lenses, absorbers
                |
                +--> for each emitter:
                |        trace_emitter(...)      (oba_ray_tracer.py)
                |            -> propagate(...)   (bounces/reflection/absorption)
                |            -> rays list
                |
                +--> visualize_rays(obj, rays)   (oba_ray_view.py)
                |        -> build Part.Compound from edges
                |
                v
         [3D view updates with ray geometry]



         graph TD
    subgraph "INITIALIZATION (oba_ray_view.py)"
        Cmd[Command: CreateRayCollector] --> CreateObj[Create Part::FeaturePython]
        CreateObj --> AttachProxy[Attach Proxy: OBARayCollector]
        CreateObj --> AttachView[Attach View: ViewProviderRayCollector]
        AttachView --> Reg[Gui.addCommand]
    end

    subgraph "EVENT TRIGGER (oba_base.py)"
        Change[Property/Placement Change] --> Trigger[_trigger_ray_engine]
        Trigger --> FindEngine{Find OBARayCollector?}
        FindEngine -- No --> Notice[Print: No Ray Collector]
        FindEngine -- Yes --> ProxyTrigger[engine.Proxy.trigger_recompute]
    end

    subgraph "DEBOUNCE & RECOMPUTE (oba_ray_collector.py)"
        ProxyTrigger --> Timer[Debounce Timer 300ms]
        Timer --> RunTrace[_run_raytrace]
        RunTrace --> Touch[obj.touch]
        Touch --> Recompute[document.recompute]
        Recompute --> Execute[execute]
    end

    subgraph "PROCESSING (oba_ray_scene.py & oba_ray_tracer.py)"
        Execute --> Collect[collect_scene: emitters, mirrors, lenses, absorbers]
        Collect --> ForEach[For each emitter]
        ForEach --> Trace[trace_emitter]
        Trace --> Propagate[propagate: bounces/reflection/absorption]
        Propagate --> RayList[Generate OBARay list]
    end

    subgraph "VISUALIZATION (oba_ray_view.py)"
        RayList --> Visualize[visualize_rays]
        Visualize --> Build[Build Part.Compound from edges]
        Build --> ViewUpdate[3D View updates with ray geometry]
    end




### 5. riktig propagation loop

### Din propagate bör vara:

for bounce in range(max_bounce):

    hit = find_nearest_intersection(...)

    if not hit:
        ray.add_segment(...)
        break

    obj, hit_p, normal = hit

    ray.add_segment(hit_p, obj.OpticalType)

    if obj.OpticalType == "Mirror":
        ray.direction = reflect(ray.direction, normal)

    elif obj.OpticalType == "Lense":
        ray.direction = refract(...)

    elif obj.OpticalType == "Absorber":
        ray.is_terminated = True
        break

    ray.last_point = hit_p




### 9. pipeline (din kod)

### Flödet blir:

collect_scene()

emitters
mirrors
lenses
absorbers
world_shape
face_map

↓

trace_emitter()

↓

populate_emitter_rays()

↓

propagate()

↓

find_nearest_intersection()

↓

OCC geometry

↓

update ray