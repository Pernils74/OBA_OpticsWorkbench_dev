# OptimizationState.py

from dataclasses import dataclass, field
from typing import Dict, List, Any, Tuple
import threading


@dataclass
class OptimizationState:
    """
    Minimal och ren state-behållare för optimering, synkad mot nuvarande worker.py.

    Borttaget:
      - Phase/last_announced_phase/phase_messages
      - eval_counter/best_eval_counter
      - LHS-relaterat (lhs_samples, unused_candidates)
    Behållet:
      - best_* (elitism)
      - cad_params/bounds/active_params
      - hitscores/global_score
      - vikter (weight_density, weight_roundness)
      - history
      - optimizer_state, running/paused, lock
    """

    # --- Best ever ---
    best_params: Dict[str, float] | None = None
    best_score: float = -float("inf")
    best_metrics: Dict[Any, Dict[str, float]] | None = None

    # --- Aktiva CAD-parametrar ---
    active_params: List[str] = field(default_factory=list)

    # --- CAD ---
    cad_params: Dict[str, float] = field(default_factory=dict)
    bounds: Dict[str, Tuple[float, float]] = field(default_factory=dict)

    # --- Evaluation results ---
    rayhits: list = field(default_factory=list)  # valfritt om du behöver dem
    clusters: Dict[Any, Any] = field(default_factory=dict)

    hitscores: Dict[Any, Dict[str, float]] = field(default_factory=dict)
    global_score: float | None = None

    # --- Objective-vikter ---
    weight_density: float = 0.5
    weight_roundness: float = 0.5
    weight_equal_distance = 0.33

    # --- Extra objective-vikter ---
    weight_separation: float = 0.5
    weight_overlap: float = 1.0
    weight_density_global: float = 1.0

    # --- Optimization memory (för UI/logg) ---
    history: List[
        Tuple[
            Dict[str, float],  # cad_params
            Dict[Any, Dict[str, float]],  # hitscores
            float,  # global_score
        ]
    ] = field(default_factory=list)

    # --- Optimizer ---
    optimizer_state: Any = None

    # --- Control flags ---
    running: bool = False
    paused: bool = False

    # --- Projection plane (delad sanning mellan UI/worker/evaluation) ---
    plane: str = "XY"  # ⬅️ NYTT: "XY" | "XZ" | "YZ"

    # --- Sync ---
    lock: threading.Lock = field(default_factory=threading.Lock)
