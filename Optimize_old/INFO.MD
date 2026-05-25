```mermaid
flowchart TD

UI["OptimizeDialogDock<br/>
optimize_dialog.py"]

WORKER["OptimizationWorker<br/>
optimize_worker.py<br/>
(+ optuna_optimizer.py)"]

STATE["OptimizationState<br/>
optimize_state.py"]

EVAL["EvaluationService<br/>
optimize_evaluator.py"]

COLLECTOR["Ray Collector<br/>
optimize_ray_collector.py"]

METRICS["Metrics Layer<br/>
optimize_evaluator_metrics.py"]

AGG["Aggregator / Scorer<br/>
(optimize_worker.py)"]

UI -->|vikter, targets, plan| WORKER
UI --> STATE

WORKER --> EVAL
WORKER --> STATE

EVAL -->|apply params + recompute<br/>spreadsheet_utils.py<br/>cad_refresh.py| COLLECTOR

COLLECTOR -->|ClusterData| METRICS
METRICS -->|metric values| AGG
AGG -->|global score| WORKER
```

#### Träd

    UI
    └─ optimize_dialog.py
    ├─ sliders (weights)
    ├─ target editor
    ├─ plane / eq‑mode
    └─ skickar signaler till worker

    State
    └─ optimize_state.py
    └─ håller targets, plane, historia, aktiv status

    Worker / Orchestrator
    └─ optimize_worker.py
    ├─ Optuna-loop
    ├─ viktning
    ├─ global score
    └─ equal-distance-logik

    Evaluation
    └─ optimize_evaluator.py
    ├─ apply_cad_params (spreadsheet_utils.py)
    ├─ recompute_doc (cad_refresh.py)
    └─ anropar collector

    Collector
    └─ optimize_ray_collector.py
    └─ samlar kluster, centroider, rådata

    Metrics
    └─ optimize_evaluator_metrics.py
    ├─ density_score
    ├─ roundness_score_from_cov
    └─ (framtida metrics)

    Optuna
    └─ optuna_optimizer.py
    └─ trial / suggest / report

#### Nästa ..

```mermaid
flowchart LR

subgraph Metrics
    D["DensityMetric<br/>per‑cluster"]
    R["RoundnessMetric<br/>per‑cluster"]
    E["EqualDistanceMetric<br/>global"]
    A["FutureMetric<br/>absorption, etc."]
end

Clusters --> D
Clusters --> R
Clusters --> E
Clusters --> A

D --> Results
R --> Results
E --> Results
A --> Results
```
