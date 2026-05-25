# -*- coding: utf-8 -*-
# optimize_worker.py — SLUTLIG VERSION (equal-distance: 2D/3D, UI-styrd paus/resume)

from PySide import QtCore
import FreeCAD as App

import numpy as np
import os, sys, re

from .optimize_evaluator_metrics import (
    aggregate_from_metrics_dict,
    equal_distance_score_2d,
    equal_distance_score_3d,
    roundness_score_from_cov,
    density_score,
)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
LIBDIR = os.path.join(BASE_DIR, "vendor_optuna")
if LIBDIR not in sys.path:
    sys.path.insert(0, LIBDIR)

import optuna

db_path = f"sqlite:///{os.path.join(BASE_DIR, 'optimization.db')}"


# ----------------------------------
# Helpers
# ----------------------------------


def is_valid_cluster(m):
    d = float(m.get("density", 0.0) or 0.0)
    r = float(m.get("roundness", 0.0) or 0.0)
    return (d > 0) and (r > 0)


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
        self.required_clusters = None
        self._probe_for_required = True

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

        if self.fresh:
            with self.state.lock:
                self.state.required_clusters = None
            self.required_clusters = None
            self._canonical_slots = None
            self._probe_for_required = True
            try:
                with self.state.lock:
                    self._plane = getattr(self.state, "plane", self._plane)
            except Exception:
                pass

        # Initial PROBE
        if self.required_clusters is None:
            self._probe_for_required = True
            self._waiting_for_eval = True
            self.requestEvaluate.emit({"params": {}, "mode": "probe", "plane": self._plane})
            return

        self._init_study(remove_old=self.fresh)
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

    @QtCore.Slot(float, float, float)
    def update_weights(self, wd, wr, we):
        with self.state.lock:
            self.state.weight_density = wd
            self.state.weight_roundness = wr
            self.state.weight_equal_distance = we
            self._weight_version += 1

        self.progress.emit({"type": "weights", "weights": {"density": wd, "roundness": wr, "equal_distance": we}})

    @QtCore.Slot(str)
    def update_plane(self, plane):
        p = (plane or "XY").upper()
        self._plane = p
        with self.state.lock:
            self.state.plane = p

        self._probe_for_required = True
        self._prune_with_reason("plane_changed", {"new_plane": p})

        if not self._waiting_for_eval and not self._stop:
            self._waiting_for_eval = True
            self.requestEvaluate.emit({"params": {}, "mode": "probe", "plane": p})

        self.progress.emit({"type": "plane", "plane": p})

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

        if self._weight_version != self._trial_weight_version:
            self._prune_with_reason("objective_changed_mid_trial")
            self._tick.start(0)
            return

        if self._stop:
            self.finished.emit()
            return

        self._waiting_for_eval = False
        metrics = payload.get("metrics", {})

        if self._probe_for_required:
            self._handle_probe(metrics)
            return

        valid = [m for m in metrics.values() if is_valid_cluster(m)]
        n_valid = len(valid)

        if self.required_clusters is not None and n_valid != self.required_clusters:
            self._handle_cluster_mismatch(metrics, n_valid)
            self._tick.start(0)
            return

        # Score!
        score = self._compute_and_update_state(metrics)
        if score is None:
            self._prune_with_reason("no_valid_clusters")
            self.progress.emit({"type": "step", "params": self.state.cad_params.copy(), "metrics": metrics, "score": None, "reason": "no_valid_clusters_pruned"})
            self._tick.start(0)
            return

        # Spara cluster-data till trial
        try:
            self._save_cluster_data(metrics)
        except Exception as e:
            App.Console.PrintError(f"[Worker] save cluster info error: {e}\n")

        self._tell_current_trial(score)

        try:
            self.requestPlot.emit(self.study.study_name)
        except:
            pass

        self.progress.emit({"type": "step", "params": self.state.cad_params.copy(), "metrics": metrics, "score": score})

        self._tick.start(0)

    # ----------------------------------
    # MAIN OPTUNA LOOP
    # ----------------------------------

    def _step(self):

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
    # PROBE
    # ----------------------------------

    def _handle_probe(self, metrics):

        valid_keys = [k for k, m in metrics.items() if is_valid_cluster(m)]
        req = len(valid_keys)

        self.required_clusters = req if req > 0 else None
        with self.state.lock:
            self.state.required_clusters = self.required_clusters

        self.progress.emit({"type": "probe", "required_total": self.required_clusters})

        try:
            keys = list(metrics.keys())
            self._canonical_slots = sorted(keys, key=lambda s: (int(str(s).split(":")[0]), int(str(s).split(":")[1])))
        except:
            self._canonical_slots = None

        self._init_study(remove_old=self.fresh)
        self.fresh = False
        self._probe_for_required = False
        self._tick.start(0)

    # ----------------------------------
    # CLUSTER MISMATCH
    # ----------------------------------

    def _handle_cluster_mismatch(self, metrics, n_valid):
        expected = int(self.required_clusters or 0)
        self._prune_with_reason("cluster_mismatch", {"n_valid": n_valid, "expected": expected})

        self.progress.emit({"type": "step", "params": self.state.cad_params.copy(), "metrics": metrics, "score": None, "reason": "cluster_mismatch_pruned"})

    # ----------------------------------
    # SCORE COMPOSITION
    # ----------------------------------

    def _compute_and_update_state(self, metrics):

        valid = [(k, m) for k, m in metrics.items() if is_valid_cluster(m)]
        if not valid:
            return None

        # NYTT: aggregate returnerar: (density_global, roundness_global, centroids)
        density_global, roundness_global, centroids = aggregate_from_metrics_dict(metrics, plane_for_roundness=self._plane)

        # UI väljer equal-distance metod
        if self.equal_distance_mode == "2D":
            equal_dist_global = equal_distance_score_2d(centroids, plane=self._plane)
        else:
            equal_dist_global = equal_distance_score_3d(centroids)

        # Poäng
        global_score = self.state.weight_density * density_global + self.state.weight_roundness * roundness_global + self.state.weight_equal_distance * equal_dist_global

        with self.state.lock:
            self.state.hitscores = metrics
            self.state.global_score = global_score
            self.state.history.append((self.state.cad_params.copy(), metrics, global_score))

        return global_score

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
