# optimize_worker.py

# Optuna trial
#     ↓
# Worker → requestEvaluate
#     ↓
# EvaluationService
#     - sätter CAD‑params
#     - recompute
#     - trace
#     - cluster
#     ↓
# Worker.on_evaluated
#     - score
#     - tell Optuna
#     ↓
# nästa trial


import os, sys, re
import FreeCAD as App

from PySide import QtCore


from .optimize_metrics import (
    aggregate_from_metrics_dict,
    equal_distance_score_2d,
    equal_distance_score_3d,
    roundness_score_from_cov,
    density_score,
)

from .optimize_scoring import score_clusters
from .evaluation_service import EvaluationService

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
LIBDIR = os.path.join(BASE_DIR, "vendor_optuna")
if LIBDIR not in sys.path:
    sys.path.insert(0, LIBDIR)

import optuna

db_path = f"sqlite:///{os.path.join(BASE_DIR, 'optimization.db')}"


# ⚠️ Glöm inte denna import i din riktiga fil
# från .scoring import score_clusters
class OptimizationWorker(QtCore.QObject):

    requestEvaluate = QtCore.Signal(dict)
    progress = QtCore.Signal(dict)
    finished = QtCore.Signal()

    def __init__(self, state, param_names=None, bounds=None):
        super().__init__()

        self.state = state
        self.param_names = param_names or []
        self.bounds = bounds or {}

        self.target_cluster_count_map = {}
        self.metric_config = {}

        self._stop = False
        self._paused = False
        self._waiting = False
        self._abort_trial = False

        self.current_trial = None
        self.study = None

    # --------------------------------------------------

    @QtCore.Slot()
    def start(self):
        self._stop = False
        print("🔥 Worker STARTED ", " self.study:", self.study)

        if not self.metric_config:
            print("⏳ Waiting for metric_config before starting...")
            return

        if self.study is None:
            self._init_study()

        print("🔥 Worker: Starting optimization loop")
        self._start_next_trial()

    # --------------------------------------------------

    def _build_baseline(self, clusters):
        self.target_cluster_count_map = {}

        for entry in self.metric_config.values():
            targets = entry["targets"]
            key = tuple(sorted(targets))

            if key in self.target_cluster_count_map:
                continue

            sub = {k: c for k, c in clusters.items() if c.get("object") in targets}

            valid = [c for c in sub.values() if c.get("hit_count", 0) > 1]
            self.target_cluster_count_map[key] = len(valid)

        print("Baseline:", self.target_cluster_count_map)
        self._start_next_trial()

    # --------------------------------------------------

    @QtCore.Slot(dict)
    def on_evaluated(self, payload):
        # kommer ifrån EvaluationsService -> Worker.on_evaluted

        # payload:
        #
        # {"clusters" : clusters}

        # print("🔥 [worker] on_evaluated CALLED")

        if self._abort_trial:
            self._abort_trial = False
            self._prune_current_trial()
            self._start_next_trial()
            return

        if self._stop:
            return
        clusters = payload.get("clusters", {})
        # ------------------------
        # BASELINE RESULT
        # ------------------------
        if not self.target_cluster_count_map:
            self._build_baseline(clusters)
            return

        # ------------------------
        # TOMT RESULT → PRUNE
        # ------------------------
        if not clusters:
            self._prune_current_trial()
            self._start_next_trial()
            return
        # ------------------------
        # NORMAL SCORING
        # ------------------------
        result = score_clusters(
            metrics=clusters,
            target_cluster_count_map=self.target_cluster_count_map,
            metric_config=self.metric_config,
        )

        score = result["score"]

        # ========================================================
        # ✅ SPARA DATA I OPTUNA-TRIAL (KRITISKT)
        # ========================================================
        t = self.current_trial

        # parametrar (för CAD-återspelning)
        t.set_user_attr("cad_params", dict(t.params))

        # krävs av plotten
        t.set_user_attr("canonical_slots", result.get("slot_keys"))
        t.set_user_attr("slot_scores", result.get("slot_scores"))
        t.set_user_attr("cluster_metrics", result.get("cluster_metrics"))

        # globala komponenter
        t.set_user_attr("metric_config", self.metric_config)
        t.set_user_attr("components", result["components"])

        # t.set_user_attr(
        #     "global_components",
        #     {
        #         "equal_distance_global": result.get("equal_distance"),
        #         "density_global": result.get("density"),
        #         "roundness_global": result.get("roundness"),
        #         "weights": {
        #             "cluster_count": self.state.weight_cluster_count,
        #             "density": self.state.weight_density,
        #             "roundness": self.state.weight_roundness,
        #             "equal_distance": self.state.weight_equal_distance,
        #         },
        #     },
        # )

        # ✅ nu först tala om score
        self.study.tell(t, score)
        # self.study.tell(self.current_trial, score)

        self.progress.emit({"type": "step", "score": score})

        self.current_trial = None
        self._start_next_trial()

    # --------------------------------------------------
    # NEXT TRIAL (EVENT-DRIVEN)
    # --------------------------------------------------

    def _start_next_trial(self):
        if not self.metric_config:
            print("⚠️ No metric_config → skipping trial")
            return

        if self.study is None:  # ✅ Lazy init
            self._init_study()
            if self.study is None:
                print("⚠️ Study still not initialized")
                return

        if self._stop:
            print("[worker] Finished")
            self.finished.emit()
            return

        if self._paused:
            return

        self.current_trial = self.study.ask()
        params = self._suggest_params(self.current_trial)
        print(f"[worker] → Trial {self.current_trial.number}, params={params}")
        with self.state.lock:
            self.state.cad_params = params.copy()
        self.requestEvaluate.emit({"params": params})

    # --------------------------------------------------
    @QtCore.Slot(object)
    def update_weights_old(self, payload):
        self.metric_config = {}
        for entry in payload["entries"]:
            self.metric_config[entry["metric"]] = entry
        # with self.state.lock:
        #     self.state.weight_cluster_count = wc
        #     self.state.weight_density = wd
        #     self.state.weight_roundness = wr
        #     self.state.weight_equal_distance = we

        self._abort_trial = True

    @QtCore.Slot(object)
    def update_weights(self, payload):
        self.metric_config = {e["metric"]: e for e in payload["entries"]}

        self._abort_trial = True

        # ✅ STARTA om vi inte kör än
        if self.study is None:
            print("🚀 Metric config received → starting worker")
            self.start()

    @QtCore.Slot()
    def stop(self):
        self._stop = True
        self._paused = False
        self._abort_trial = True
        self._waiting = False  # 🔥 viktig
        # ✅ återställ

    @QtCore.Slot()
    def pause(self):
        self._paused = True

    @QtCore.Slot()
    def resume(self):
        self._paused = False

    def _prune_current_trial(self):
        try:
            if self.current_trial:
                self.study.tell(self.current_trial, state=optuna.trial.TrialState.PRUNED)
        except:
            pass
        self.current_trial = None

    def _suggest_params(self, trial):
        return {name: trial.suggest_float(name, *self.bounds[name]) for name in self.param_names}

    # @staticmethod
    # def _sanitize(s):
    #     s = re.sub(r"[^A-Za-z0-9_\- ]+", "-", s)
    #     s = s.replace(" ", "-")
    #     s = re.sub(r"-{2,}", "-", s)
    #     return s.strip("-")

    def _make_study_name(self):
        parts = []

        for k, v in sorted(self.metric_config.items()):
            p = v.get("plane", "X")
            parts.append(f"{k}-{p}")
        metrics_part = "__".join(parts)
        params_part = "__".join(sorted(self.param_names))

        return f"{metrics_part}__{params_part}"

    # def _init_study(self):
    #     self.study = optuna.create_study(direction="maximize")
    def _init_study(self, remove_old=False):
        # if not self.metric_config:
        #     return

        name = self._make_study_name()

        if remove_old:
            try:
                optuna.delete_study(study_name=name, storage=db_path)
            except:
                pass
            load = False
        else:
            load = True

        sampler = optuna.samplers.TPESampler(
            n_startup_trials=40,
            constant_liar=True,
        )

        self.study = optuna.create_study(
            direction="maximize",
            sampler=sampler,
            storage=db_path,
            study_name=name,
            load_if_exists=load,
        )

        print(f"[Optuna] Using study: {name}")
