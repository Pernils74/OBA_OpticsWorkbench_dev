# -*- coding: utf-8 -*-
# optimize_worker.py — SLUTLIG VERSION (equal-distance: 2D/3D, UI-styrd paus/resume)

from PySide import QtCore
import FreeCAD as App

import numpy as np
import os, sys, re

from .optimize_metrics import (
    aggregate_from_metrics_dict,
    equal_distance_score_2d,
    equal_distance_score_3d,
    roundness_score_from_cov,
    density_score,
)

from .optimize_scoring import score_clusters

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
LIBDIR = os.path.join(BASE_DIR, "vendor_optuna")
if LIBDIR not in sys.path:
    sys.path.insert(0, LIBDIR)

import optuna

db_path = f"sqlite:///{os.path.join(BASE_DIR, 'optimization.db')}"


# ----------------------------------
# Helpers
# ----------------------------------


def is_valid_cluster_old(m: dict) -> bool:
    """
    Validerar kluster baserat på rådata (inte scores).
    """

    if not isinstance(m, dict):
        return False

    # 1) Måste ha minst en träff
    count = int(m.get("count", 0) or 0)
    if count <= 0:
        print("[Worker] Invalid cluster: count <= 0")
        return False

    # 2) Måste ha centroid i 3D
    c3d = m.get("centroid", {}).get("3D")
    if not c3d or len(c3d) < 3:
        print("[Worker] Invalid cluster: invalid centroid")
        return False

    # 3) Måste ha någon form av spridningsinfo
    spread = m.get("spread", {})
    if not spread:
        print("[Worker] Invalid cluster: no spread info")
        return False

    # 4) Antingen 3D‑radie eller kovarians i något plan
    has_radius = "3D" in spread and spread["3D"].get("radius", 0.0) > 0.0

    has_cov = any(isinstance(v, dict) and "cov" in v for v in spread.values())

    print(f"[Worker] Cluster validation: has_radius={has_radius}, has_cov={has_cov}")
    return has_radius or has_cov


# m = {
#     "count": ...,
#     "centroid": {"3D": [...]},
#     "spread": {
#         "3D": {"radius": ...},
#         "XY": {"cov": ...},
#         ...
#     }
# }


def is_valid_cluster(m: dict) -> bool:
    if not isinstance(m, dict):
        return False

    # 1) minst 2 hits
    count = int(m.get("hit_count", 0) or 0)
    if count <= 1:
        return False

    # 2) centroid 3D
    c3d = m.get("centroid_3d")
    if c3d is None or len(c3d) < 3:
        return False

    # 3) radius
    radius = float(m.get("radius_3d", 0.0) or 0.0)
    if radius <= 0.0:
        return False

    return True


# m = {
#     "hit_count": ...,
#     "centroid_3d": ...,
#     "radius_3d": ...,
# }


def _slot_sort_key(slot: str):
    try:
        a, b = str(slot).split(":")
        return (int(a), int(b))
    except Exception:
        return (0, 0)


# ----------------------------------
# Worker
# ----------------------------------
class OptimizationWorker(QtCore.QObject):

    requestEvaluate = QtCore.Signal(dict)
    progress = QtCore.Signal(dict)
    finished = QtCore.Signal()
    requestPlot = QtCore.Signal(str)

    def __init__(self, state, param_names, bounds):
        super().__init__()

        self._paused_by_slider = False

        self.state = state
        self.param_names = list(param_names)
        self.bounds = dict(bounds)

        self.fresh = False
        # self.required_clusters = None
        # self._probe_for_required = True

        self._plane = getattr(state, "plane", "XY")

        self.equal_distance_mode = "3D"  # <-- NYTT (UI ändrar detta)

        self._stop = False
        self._waiting_for_eval = False

        self._weight_version = 0
        self._trial_weight_version = 0

        self._canonical_slots = None
        self.study = None
        self.current_trial = None

        self._tick = QtCore.QTimer(self)
        self._tick.setSingleShot(True)
        self._tick.timeout.connect(self._step)

    # ----------------------------------
    # INIT / STOP / PAUSE
    # ----------------------------------

    @QtCore.Slot()
    def start(self):
        self._stop = False
        self._waiting_for_eval = False

        # --------------------------------------------------
        # Reset vid ny körning
        # --------------------------------------------------
        if self.fresh:
            with self.state.lock:
                self.state.target_cluster_count = None
                self.state.global_score = None
                self.state.history.clear()

            self._canonical_slots = None

            try:
                with self.state.lock:
                    self._plane = getattr(self.state, "plane", self._plane)
            except Exception:
                pass

        # --------------------------------------------------
        # 1) BASELINE-KÖRNING (EN GÅNG)
        # --------------------------------------------------
        if self.state.target_cluster_count is None:
            # Kör en passiv evaluering för att fastställa baseline
            self._waiting_for_eval = True
            self.requestEvaluate.emit(
                {
                    "params": {},  # baseline-parametrar
                    "plane": self._plane,
                }
            )
            return

        # --------------------------------------------------
        # 2) Optuna-studyn är redo → starta optimering
        # --------------------------------------------------
        if self.study is None:
            self._init_study(remove_old=self.fresh)
            self.fresh = False

        self._tick.start(0)

    @QtCore.Slot()
    def pause(self):
        self._paused_by_slider = True

    @QtCore.Slot()
    def resume(self):
        self._paused_by_slider = False
        try:
            if not self._waiting_for_eval:
                self._tick.start(0)
        except Exception:
            pass

    @QtCore.Slot()
    def stop(self):
        self._stop = True
        self._waiting_for_eval = False
        self._prune_current_trial()
        self._restore_best_from_study()
        self.finished.emit()

    @QtCore.Slot()
    def shutdown(self):
        self._stop = True
        self._tick.stop()
        self.finished.emit()

    # ----------------------------------
    # RECEIVE FROM UI
    # ----------------------------------

    @QtCore.Slot(float, float, float, float)
    def update_weights(self, wc, wd, wr, we):
        with self.state.lock:
            self.state.weight_cluster_count = wc
            self.state.weight_density = wd
            self.state.weight_roundness = wr
            self.state.weight_equal_distance = we
            self._weight_version += 1

        self.progress.emit(
            {
                "type": "weights",
                "weights": {
                    "cluster_count": wc,
                    "density": wd,
                    "roundness": wr,
                    "equal_distance": we,
                },
            }
        )

    @QtCore.Slot(str)
    def update_plane(self, plane):
        p = (plane or "XY").upper()
        self._plane = p

        with self.state.lock:
            self.state.plane = p

            # 🔥 Plane-byte ändrar white-cell-topologin:
            # baseline för studsantal måste sättas om
            self.state.target_cluster_count = None

        # Avsluta ev. pågående trial på ett kontrollerat sätt
        self._prune_with_reason("plane_changed", {"new_plane": p})

        # Förbered ny baseline-evaluering
        if not self._stop:
            self._waiting_for_eval = True
            self.study = None  # tvinga ny study efter ny baseline
            self.requestEvaluate.emit(
                {
                    "params": {},  # baseline-parametrar
                    "plane": p,
                }
            )

        self.progress.emit(
            {
                "type": "plane",
                "plane": p,
            }
        )

    # --- NY SLOT ---
    @QtCore.Slot(str)
    def update_equal_distance_mode(self, mode):
        """
        mode = "2D" eller "3D" (kommer från UI)
        """
        if mode not in ("2D", "3D"):
            return
        self.equal_distance_mode = mode
        self.progress.emit({"type": "eq_mode", "mode": mode})

    # ----------------------------------
    # Evaluation callback
    # ----------------------------------

    @QtCore.Slot(dict)
    def on_evaluated(self, payload):

        App.Console.PrintMessage(f"[Worker] on_evaluated payload keys: {list(payload.keys())}\n")

        # --------------------------------------------------
        # 0) Säkerhet: stopp / vikter ändrade
        # --------------------------------------------------
        if self._weight_version != self._trial_weight_version:
            self._prune_with_reason("objective_changed_mid_trial")
            return

        if self._stop:
            self.finished.emit()
            return

        self._waiting_for_eval = False

        # --------------------------------------------------
        # 1) Rådata: clusters (enda sanningen)
        # --------------------------------------------------
        clusters = payload.get("clusters", {})
        if not clusters:
            self._prune_with_reason("no_clusters_received")
            return

        metrics = clusters  # clusters är metrics-kontraktet

        # --------------------------------------------------
        # 2) BASELINE-FAS (körs exakt en gång)
        # --------------------------------------------------

        if self.state.target_cluster_count is None:

            valid = [m for m in metrics.values() if is_valid_cluster(m)]
            if not valid:
                self.progress.emit(
                    {
                        "type": "error",
                        "reason": "no_valid_clusters_in_baseline",
                    }
                )
                self.finished.emit()
                return

            self.state.target_cluster_count = len(valid)
            App.Console.PrintMessage(f"[Worker] Baseline cluster count set to {self.state.target_cluster_count}\n")

            # ✅ VIKTIGHET 1: synka vikt-versioner (annars blockerar guard)
            self._trial_weight_version = self._weight_version

            # ✅ VIKTIGHET 2: baseline är klar – vi väntar INTE längre
            self._waiting_for_eval = False

            # ✅ VIKTIGHET 3: informera UI
            self.progress.emit(
                {
                    "type": "baseline",
                    "cluster_count": self.state.target_cluster_count,
                }
            )

            # Initiera Optuna-studyn NU – exakt en gång
            self._init_study(remove_old=self.fresh)
            self.fresh = False

            # Starta Optuna-loop
            self._tick.start(0)
            return

        # --------------------------------------------------
        # 3) Validering (lättviktig)
        # --------------------------------------------------
        valid = [m for m in metrics.values() if is_valid_cluster(m)]
        if not valid:
            self._prune_with_reason("all_clusters_invalid")
            return

        # --------------------------------------------------
        # 4) SCORING – ALLT ÄR METRICS
        # --------------------------------------------------
        result = score_clusters(
            metrics=metrics,
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

        if result is None:
            self._prune_with_reason("scoring_returned_none")
            return

        score = result["score"]

        # --------------------------------------------------
        # 5) Uppdatera state
        # --------------------------------------------------
        with self.state.lock:
            self.state.hitscores = metrics
            self.state.global_score = score
            self.state.history.append((self.state.cad_params.copy(), metrics, score))

        # --------------------------------------------------
        # 6) Spara till Optuna
        # --------------------------------------------------
        try:
            self._save_cluster_data(metrics)
        except Exception as e:
            App.Console.PrintError(f"[Worker] save cluster info error: {e}\n")

        self._tell_current_trial(score)

        # --------------------------------------------------
        # 7) UI / plotting / nästa steg
        # --------------------------------------------------
        try:
            self.requestPlot.emit(self.study.study_name)
        except Exception:
            pass

        self.progress.emit(
            {
                "type": "step",
                "params": self.state.cad_params.copy(),
                "metrics": metrics,
                "score": score,
            }
        )

        self._tick.start(0)

    # ----------------------------------
    # MAIN OPTUNA LOOP
    # ----------------------------------

    def _step(self):

        if self.study is None:
            App.Console.PrintMessage("[Worker] _step called before study init, waiting…\n")
            # Vänta tills study är initierad (efter probe)
            self._tick.start(25)
            return

        if self._paused_by_slider:
            self._tick.start(50)
            return

        if self._stop:
            self.finished.emit()
            return

        if self._waiting_for_eval:
            self._tick.start(25)
            return

        try:
            trial = self.study.ask()
            self.current_trial = trial
            self._trial_weight_version = self._weight_version

            params = self._suggest_params(trial)
            with self.state.lock:
                self.state.cad_params = params.copy()

            self._waiting_for_eval = True
            self.requestEvaluate.emit({"params": params, "plane": self._plane})
            self.progress.emit({"type": "loop", "phase": "ask", "params": params})

        except Exception as e:
            App.Console.PrintError(f"[Worker] step error: {e}\n")
            self.current_trial = None
            self._waiting_for_eval = False

        self._tick.start(50)

    # ----------------------------------
    # SAVE PER-CLUSTER DATA
    # ----------------------------------

    def _save_cluster_data(self, metrics):

        wd = float(self.state.weight_density or 0.0)
        wr = float(self.state.weight_roundness or 0.0)
        s = wd + wr
        if s <= 1e-12:
            wd_n = wr_n = 0.5
        else:
            wd_n, wr_n = wd / s, wr / s

        per_cluster_scores = {}
        cluster_metrics = {}

        for key, m in metrics.items():
            cnt = int(m.get("count", 0) or 0)
            radius3d = float(m.get("spread", {}).get("3D", {}).get("radius", 0.0) or 0.0)
            cov_plane = (m.get("spread", {}).get(self._plane, {}) or {}).get("cov")
            centroid3d = (m.get("centroid", {}) or {}).get("3D")

            dens_i = density_score(cnt, radius3d)
            round_i = roundness_score_from_cov(cov_plane) if cov_plane is not None else 0.0

            per_cluster_scores[key] = wd_n * dens_i + wr_n * round_i

            cluster_metrics[key] = {
                "density": float(dens_i),
                "roundness": float(round_i),
                "radius3d": float(radius3d),
                "centroid3d": tuple(centroid3d) if centroid3d else None,
            }

        if self._canonical_slots:
            slot_order = list(self._canonical_slots)
        else:
            slot_order = sorted(list(metrics.keys()), key=_slot_sort_key)

        slot_scores_ordered = [float(per_cluster_scores.get(k, float("nan"))) for k in slot_order]

        # Hämta global metrics igen för sparning
        dg, rg, centroids = aggregate_from_metrics_dict(metrics, plane_for_roundness=self._plane)

        if self.equal_distance_mode == "2D":
            eg = equal_distance_score_2d(centroids, plane=self._plane)
        else:
            eg = equal_distance_score_3d(centroids)

        global_components = {
            "density_global": float(dg),
            "roundness_global": float(rg),
            "equal_distance_global": float(eg),
            "weights": {
                "density": float(self.state.weight_density or 0.0),
                "roundness": float(self.state.weight_roundness or 0.0),
                "equal_distance": float(self.state.weight_equal_distance or 0.0),
            },
            "equal_distance_mode": self.equal_distance_mode,
        }

        if self.current_trial is not None:
            self.current_trial.set_user_attr("canonical_slots", slot_order)
            self.current_trial.set_user_attr("slot_scores", slot_scores_ordered)
            self.current_trial.set_user_attr("cluster_metrics", cluster_metrics)
            self.current_trial.set_user_attr("global_components", global_components)

    # ----------------------------------
    # TRIAL CONTROL
    # ----------------------------------

    def _prune_current_trial(self):
        if self.current_trial:
            try:
                self.study.tell(self.current_trial, state=optuna.trial.TrialState.PRUNED)
            except:
                pass
            self.current_trial = None

    def _tell_current_trial(self, score):
        if self.current_trial is None:
            return
        try:
            self.study.tell(self.current_trial, float(score))
        except Exception as e:
            App.Console.PrintError(f"[Optuna] tell error: {e}\n")
        self.current_trial = None

    def _restore_best_from_study(self):
        try:
            best = self.study.best_trial
        except Exception:
            return

        if not best:
            return

        with self.state.lock:
            self.state.cad_params = best.params.copy()
            try:
                self.state.global_score = float(best.value)
            except:
                pass

        self.progress.emit(
            {
                "type": "best_params",
                "params": best.params.copy(),
                "score": float(best.value) if best.value is not None else None,
            }
        )

    def _prune_with_reason(self, reason, extra=None):
        if not self.current_trial:
            return
        try:
            self.current_trial.set_user_attr("prune_reason", reason)
            if extra:
                for k, v in extra.items():
                    self.current_trial.set_user_attr(k, v)
            self.study.tell(self.current_trial, state=optuna.trial.TrialState.PRUNED)
        except:
            pass
        self.current_trial = None

    # ----------------------------------
    # PARAM GENERATION
    # ----------------------------------

    def _suggest_params(self, trial):
        params = {}
        for name in self.param_names:
            lo, hi = self.bounds[name]
            params[name] = trial.suggest_float(name, lo, hi)
        return params

    # ----------------------------------
    # STUDY INIT
    # ----------------------------------

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
            multivariate=False,
            group=False,
            n_startup_trials=50,
            n_ei_candidates=128,
            consider_prior=True,
            prior_weight=1.0,
            constant_liar=True,
        )

        self.study = optuna.create_study(
            direction="maximize",
            sampler=sampler,
            storage=db_path,
            study_name=name,
            load_if_exists=load,
        )

    # ----------------------------------
    # UTIL
    # ----------------------------------

    @staticmethod
    def _sanitize(s):
        s = re.sub(r"[^A-Za-z0-9_\- ]+", "-", s)
        s = s.replace(" ", "-")
        s = re.sub(r"-{2,}", "-", s)
        return s.strip("-")

    def _make_study_name(self):
        plane_s = self._sanitize(self._plane)
        pnames = [self._sanitize(p) for p in sorted(self.param_names)]
        return plane_s + "__" + "__".join(pnames)

    def update_metric_targets(self, metric_key, targets):
        with self.state.lock:
            self.state.metric_targets[metric_key] = list(targets)
