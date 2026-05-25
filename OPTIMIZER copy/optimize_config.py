# Configuration constants for ObaOptimize
SHEET_CTRL = "Spreadsheet"  # styr-Spreadsheet (A: name, B: value, C: min, D: max)
RAY_SHEET = "RayHits"  # skapas av OpticsWorkbench.Hits2CSV()
HIT_SHEET = "HitAnalysis_iter"  # gemensamt ark (append: en rad per kluster & iteration)

SPREADSHEET_NAME = "Spreadsheet"  # styr-Spreadsheet (A: name, B: value, C: min, D: max)
SOURCE_SHEET_NAME = "RayHits"  # skapas av OpticsWorkbench.Hits2CSV()
# gemensamt ark (append: en rad per kluster & iteration)
RESULT_SHEET_NAME = "HitScores"

METRIC_COLS = {
    "roundness": "K",
    "density": "L",
    "score": "N",
    "cv_radial": "M",
    "sigma1": "I",
    "sigma2": "J",
    "r_mean": "G",
    "resid": "H",
}

METRIC_COLORS = {
    "roundness": "#1f77b4",
    "density": "#ff7f0e",
    "score": "#2ca02c",
    "cv_radial": "#d62728",
    "sigma1": "#9467bd",
    "sigma2": "#8c564b",
    "r_mean": "#e377c2",
    "resid": "#7f7f7f",
}

CLUSTER_LINESTYLES = ["-", "--", "-.", ":"]


# class OptimizationState:
#     # --- CAD ---
#      cad_params: Dict[str, float]
#     # # aktuella värden
#     (Spreadsheet kol B) bounds: Dict[str, (min, max)]
#     # # Spreadsheet kol C/D
#     # # --- Raytracing ---
#     rayhits: List[Hit]
#     # # x, y, cluster_id
#     # # --- Analysis ---
#     clusters: Dict[cluster_id, ClusterData]
#     hitscores: Dict[cluster_id, { "density": float, "roundness": float, "score": float }]

#      # --- Objective ---
#     weight_density: float
#       # från slider
#     weight_roundness: float
#     global_score: float # = min(cluster_scores)
#        # --- Optimization memory ---
#     history: List[(cad_params, hitscores, global_score)]
#         # --- LHS / candidate pool ---
#     lhs_samples: List[cad_params]
#     unused_candidates: Queue[cad_params]
#          # --- Optimizer internal ---
#     optimizer_state: Any # CMA-ES / Bayesian / random local


#           # --- Control ---
#     running: bool
#     paused: bool
