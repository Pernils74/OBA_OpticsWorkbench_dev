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


from ._dddd_optimize_scoring import score_clusters
from ..evaluation_service import EvaluationService

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

        self._stop = False
        self._paused = False
        self._waiting = False
        self._abort_trial = False

        self.current_trial = None
        self.study = None

        self._plane = getattr(state, "plane", "XY")
        self.equal_distance_mode = "3D"

    # --------------------------------------------------

    @QtCore.Slot()
    def start(self):
        self._stop = False
        print("🔥 Worker STARTED")

        # ✅ SÄKERSTÄLL STUDY
        if self.study is None:
            self._init_study()

        if self.state.target_cluster_count is None:
            self._run_baseline()
            # return
        else:
            self._start_next_trial()  # 🔥 DENNA SAKNAS

    # --------------------------------------------------

    def _run_baseline(self):
        self._waiting = True
        self.requestEvaluate.emit({"params": {}, "plane": self._plane})

    # --------------------------------------------------

    @QtCore.Slot(dict)
    def on_evaluated(self, payload):
        print("🔥 [worker] on_evaluated CALLED")

        if self._stop:
            return

        clusters = payload.get("clusters", {})

        # ------------------------
        # BASELINE RESULT
        # ------------------------
        if self.state.target_cluster_count is None:

            valid = [c for c in clusters.values() if c.get("hit_count", 0) > 1]

            if not valid:
                self.progress.emit({"type": "error", "reason": "Baseline misslyckades"})
                self._stop = True
                self.finished.emit()
                return

            self.state.target_cluster_count = len(valid)
            self.progress.emit({"type": "baseline", "cluster_count": len(valid)})

            # ✅ fortsätt direkt
            self._start_next_trial()
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
            plane=self._plane,
            equal_distance_mode=self.equal_distance_mode,
            target_cluster_count=self.state.target_cluster_count,
            weights={
                "cluster_count": self.state.weight_cluster_count,
                "density": self.state.weight_density,
                "roundness": self.state.weight_roundness,
                "equal_distance": self.state.weight_equal_distance,
            },
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
        t.set_user_attr(
            "global_components",
            {
                "equal_distance_global": result.get("equal_distance"),
                "equal_distance_mode": self.equal_distance_mode,
                "density_global": result.get("density"),
                "roundness_global": result.get("roundness"),
                "weights": {
                    "cluster_count": self.state.weight_cluster_count,
                    "density": self.state.weight_density,
                    "roundness": self.state.weight_roundness,
                    "equal_distance": self.state.weight_equal_distance,
                },
            },
        )

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
        if self._stop:
            print("[worker] Finished")

            self.finished.emit()
            return

        if self._paused:
            return

        if self.study is None:  # ✅ failsafe
            self._init_study()

        self.current_trial = self.study.ask()
        params = self._suggest_params(self.current_trial)

        print(f"[worker] → Trial {self.current_trial.number}, params={params}")

        with self.state.lock:
            self.state.cad_params = params.copy()

        self.requestEvaluate.emit({"params": params, "plane": self._plane})

    # --------------------------------------------------
    @QtCore.Slot(float, float, float, float)
    def update_weights(self, wc, wd, wr, we):
        with self.state.lock:
            self.state.weight_cluster_count = wc
            self.state.weight_density = wd
            self.state.weight_roundness = wr
            self.state.weight_equal_distance = we

        self._abort_trial = True

    @QtCore.Slot(str)
    def update_plane(self, plane):
        self._plane = plane

    @QtCore.Slot(str)
    def update_equal_distance_mode(self, mode):
        self.equal_distance_mode = mode

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

    @staticmethod
    def _sanitize(s):
        s = re.sub(r"[^A-Za-z0-9_\- ]+", "-", s)
        s = s.replace(" ", "-")
        s = re.sub(r"-{2,}", "-", s)
        return s.strip("-")

    def _make_study_name(self):
        plane = self._sanitize(self._plane)
        mode = self.equal_distance_mode
        params = "__".join(sorted(self.param_names))
        return f"{plane}__{mode}__{params}"

    # def _init_study(self):
    #     self.study = optuna.create_study(direction="maximize")

    def _init_study(self, remove_old=False):
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
