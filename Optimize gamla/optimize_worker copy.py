# optimize_worker.py
# Refactored OptimizationWorker with clearer control flow, safer state handling,
# and separation between Optuna control, evaluation flow, and scoring.

from PySide import QtCore
import FreeCAD as App

import numpy as np
import os
import sys
import re
import math

from .cad_refresh import recompute_doc
from .spreadsheet_utils import apply_cad_params

from .optimize_evaluator_metrics import (
    aggregate_from_metrics_dict,
)


# -----------------------------
# Paths / Optuna storage
# -----------------------------

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
LIBDIR = os.path.join(BASE_DIR, "vendor_optuna")

if LIBDIR not in sys.path:
    sys.path.insert(0, LIBDIR)

import optuna

db_path = f"sqlite:///{os.path.join(BASE_DIR, 'optimization.db')}"

# -----------------------------
# Helper utilities
# -----------------------------


def is_valid_cluster(m):
    d = m.get("density", 0.0)
    r = m.get("roundness", 0.0)
    # App.Console.PrintMessage(f"[is_valid_cluster] d={d}, r={r}\n")
    return (d is not None and d > 0) and (r is not None and r > 0)


class MetricNormalizer:
    """Keeps running min/max and normalizes density/roundness to [0, 1]."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.d_min = float("inf")
        self.d_max = -float("inf")
        self.r_min = float("inf")
        self.r_max = -float("inf")

    def update(self, metrics: dict):
        for m in metrics.values():
            d = m.get("density", 0.0)
            r = m.get("roundness", 0.0)
            if d <= 0 or r <= 0:
                continue
            self.d_min = min(self.d_min, d)
            self.d_max = max(self.d_max, d)
            self.r_min = min(self.r_min, r)
            self.r_max = max(self.r_max, r)


# -----------------------------
# Main worker
# -----------------------------


class OptimizationWorker(QtCore.QObject):
    """
    Event-driven Optuna worker.

    Responsibilities:
      - Manage Optuna study / trials
      - Coordinate async evaluation loop
      - Maintain synchronization with shared `state`
      - Emit progress to UI
    """

    requestEvaluate = QtCore.Signal(dict)
    progress = QtCore.Signal(dict)
    finished = QtCore.Signal()
    requestPlot = QtCore.Signal(str)  # study_name

    # -------------------------
    # Construction
    # -------------------------

    def __init__(self, state, param_names, bounds):
        super().__init__()

        self.fresh = False

        self.state = state
        self.param_names = list(param_names)
        self.bounds = dict(bounds)

        self.required_clusters = None
        self._probe_for_required = True

        self._sep_scale = None  # separering av cluster
        self._ov_scale = None

        # vilken plane har valts
        self._plane = getattr(state, "plane", "XY")

        # Control flags
        self._stop = False
        self._paused_by_slider = False
        self._waiting_for_eval = False

        # Om objective ändras
        self._weight_version = 0

        # Kanoniska slots (stabil identitet): ["0:1","1:1","0:3","1:3", ...]
        self._canonical_slots = None

        # Optuna
        self.study = None
        self.current_trial = None

        # Scoring
        self.normalizer = MetricNormalizer()

        # Timer driving the loop
        self._tick = QtCore.QTimer(self)
        self._tick.setSingleShot(True)
        self._tick.timeout.connect(self._step)

    # -------------------------
    # Public slots (UI control)
    # -------------------------

    @QtCore.Slot()
    def start(self):
        self._stop = False
        self._waiting_for_eval = False

        # ⬇️ REAGERA på fresh: nollställ härledd status och tvinga ny probe
        if self.fresh:

            # Tvinga bort allt gammalt, oavsett vad state innehöll
            with self.state.lock:
                self.state.required_clusters = None
            self.required_clusters = None
            self._canonical_slots = None
            self._probe_for_required = True
            self.normalizer.reset()
            self._sep_scale = None
            self._ov_scale = None

            # tips: sätt även plane från state om du vill vara extra deterministisk
            try:
                with self.state.lock:
                    self._plane = getattr(self.state, "plane", self._plane)
            except Exception:
                pass

        # Probe first if needed
        if self.required_clusters is None:
            self._probe_for_required = True
            self._waiting_for_eval = True
            self.requestEvaluate.emit({"params": {}, "mode": "probe", "plane": self._plane})
            return

        # Init study and start loop
        self._init_study(remove_old=self.fresh)
        self._tick.start(0)

    @QtCore.Slot()
    def stop(self):
        self._stop = True
        self._waiting_for_eval = False

        # Avsluta ev pågående trial
        self._prune_current_trial()

        # 🔥 Återställ bästa trial
        self._restore_best_from_study()

        # 🔴 Avsluta ALLTID workern kontrollerat
        self.finished.emit()

    @QtCore.Slot()
    def shutdown(self):
        self._stop = True
        self._tick.stop()
        self.finished.emit()

    @QtCore.Slot()
    def pause_due_to_slider(self):
        self._paused_by_slider = True

    @QtCore.Slot()
    def resume_after_slider(self):
        self._paused_by_slider = False

    # -------------------------
    # Weight updates
    # -------------------------

    @QtCore.Slot(float, float, float)
    def update_weights(self, density: float, roundness: float, equal_dist: float):
        with self.state.lock:
            self.state.weight_density = density
            self.state.weight_roundness = roundness
            self.state.weight_equal_distance = equal_dist
            self._weight_version += 1  # <-- markerar att objektivet ändrats

        # Skicka tillbaka till UI för att uppdatera etiketter
        self.progress.emit(
            {
                "type": "weights",
                "weights": {
                    "density": density,
                    "roundness": roundness,
                    "equal_distance": equal_dist,
                },
            }
        )

    @QtCore.Slot(float, float, float)
    def update_extra_weights(self, w_sep, w_ov, w_dglob):
        with self.state.lock:
            self.state.weight_separation = w_sep
            self.state.weight_overlap = w_ov
            self.state.weight_density_global = w_dglob

    # Lägg till metod som UI kan anropa via signal:
    @QtCore.Slot(str)
    def update_plane(self, plane: str):
        p = (plane or "XY").upper()
        self._plane = p
        # skriv tillbaka till state
        try:
            with self.state.lock:
                self.state.plane = p
        except Exception:
            pass

        # Nollställ cache och normaliseringar relaterade till planet
        self._sep_scale = None
        self._ov_scale = None
        self._canonical_slots = None
        self.normalizer.reset()

        # Planbyte påverkar cluster‑antal/slots ⇒ gör ny probe
        self._probe_for_required = True

        # Pruna ev. pågående trial och märk orsak
        self._prune_with_reason("plane_changed", {"new_plane": p})

        # Om vi kan – trigga probe direkt
        if not self._waiting_for_eval and not self._stop:
            self._waiting_for_eval = True
            self.requestEvaluate.emit({"params": {}, "mode": "probe", "plane": p})

        # (valfritt) informera UI
        self.progress.emit({"type": "plane", "plane": p})

    # -------------------------
    # Evaluation callback
    # -------------------------
    # self._worker = OptimizationWorker(self.state, param_names, bounds)

    @QtCore.Slot(dict)
    def on_evaluated(self, payload: dict):
        # PRUNE om objektivet ändrats mitt i evaluate
        if self._weight_version != getattr(self, "_trial_weight_version", self._weight_version):
            self._prune_with_reason(
                "objective_changed_mid_trial",
                {
                    "old_version": getattr(self, "_trial_weight_version", -1),
                    "new_version": self._weight_version,
                },
            )
            self._tick.start(0)
            return

        if self._stop:
            self.finished.emit()
            return

        self._waiting_for_eval = False
        metrics = payload.get("metrics", {})

        # --- PROBE PHASE ---
        if self._probe_for_required:
            self._handle_probe(metrics)
            return

        # --- VALIDATION / CLUSTER COUNT ---
        valid = [m for m in metrics.values() if is_valid_cluster(m)]
        n_valid = len(valid)

        if self.required_clusters is not None and n_valid != self.required_clusters:
            self._handle_cluster_mismatch(metrics, n_valid)
            self._tick.start(0)
            return

        # --- NORMAL SCORE ---
        score = self._compute_and_update_state(metrics)

        if score is None:
            # Inga giltiga kluster enligt is_valid_cluster → pruna
            self._prune_with_reason(
                "no_valid_clusters",
                {
                    "n_rows_metrics": len(metrics),
                    "required_clusters": int(self.required_clusters or 0),
                },
            )
            # Rapportera till UI och gå vidare
            self.progress.emit(
                {
                    "type": "step",
                    "params": self.state.cad_params.copy(),
                    "metrics": metrics,
                    "score": None,
                    "reason": "no_valid_clusters_pruned",
                }
            )
            self._tick.start(0)

            return

        # score = self._compute_and_update_state(metrics)

        # Spara per-slot data i user_attrs för analys (om slots är definierade)
        try:
            if self.current_trial is not None and self._canonical_slots:
                slot_scores = self._scores_per_slot(metrics)

                self.progress.emit(
                    {
                        "type": "slot_scores",
                        "trial": (self.study.trials[-1].number if self.study and self.study.trials else None),
                        "slot_scores": (list(map(float, slot_scores)) if slot_scores else None),
                        "canonical_slots": (list(self._canonical_slots) if self._canonical_slots else None),
                    }
                )

                self.current_trial.set_user_attr("canonical_slots", list(self._canonical_slots))
                self.current_trial.set_user_attr("slot_scores", list(map(float, slot_scores)))
                # Spara råmätningar per slot
                self.current_trial.set_user_attr("slots", {s: metrics.get(s) for s in self._canonical_slots})

        except Exception as e:
            App.Console.PrintError(f"[Optuna] user_attrs (slots) error: {e}\n")

        # ⬇️ Spara per-kluster (densitet, roundness, ev. centroid/spread) som user_attrs
        # try:
        #     if self.current_trial is not None:
        #         # Skapa stabil ordning om du bryr dig om reproducerbarhet i listor/tabeller
        #         ordering = sorted(
        #             metrics.items(),
        #             key=lambda kv: (
        #                 float(kv[1].get("density", 0) or 0.0),
        #                 float(kv[1].get("roundness", 0) or 0.0),
        #             ),
        #         )
        #         clusters_payload = {}
        #         for cid, m in ordering:
        #             clusters_payload[str(cid)] = {
        #                 "density": (
        #                     float(m.get("density"))
        #                     if m.get("density") is not None
        #                     else None
        #                 ),
        #                 "roundness": (
        #                     float(m.get("roundness"))
        #                     if m.get("roundness") is not None
        #                     else None
        #                 ),
        #                 # Lägg till om du vill
        #                 "spread": (
        #                     float(m.get("spread"))
        #                     if m.get("spread") is not None
        #                     else None
        #                 ),
        #                 "centroid": m.get(
        #                     "centroid"
        #                 ),  # låt vara lista/tuple; Optuna json:ar detta
        #             }

        #         self.current_trial.set_user_attr("clusters", clusters_payload)
        #         self.current_trial.set_user_attr(
        #             "cluster_order_key", "sorted by (density, roundness)"
        #         )
        #         self.current_trial.set_user_attr(
        #             "n_valid_clusters",
        #             sum(1 for m in metrics.values() if is_valid_cluster(m)),
        #         )

        #         # Sammanfattningar för snabba frågor i SQL
        #         valid = [m for m in metrics.values() if is_valid_cluster(m)]
        #         if valid:
        #             dens = [float(m["density"]) for m in valid]
        #             rnds = [float(m["roundness"]) for m in valid]
        #             import numpy as _np

        #             self.current_trial.set_user_attr(
        #                 "median_density", float(_np.median(dens))
        #             )
        #             self.current_trial.set_user_attr(
        #                 "median_roundness", float(_np.median(rnds))
        #             )
        # except Exception as e:
        #     App.Console.PrintError(f"[Optuna] set_user_attr error: {e}\n")

        # Nu rapporterar vi objektivvärdet
        self._tell_current_trial(score)

        # direkt efter _tell_current_trial(score)
        App.Console.PrintMessage("[Plot] emitting requestPlot\n")

        self.requestPlot.emit(self.study.study_name)

        # # Samma db_uri som worker använder
        # plot_slot_scores(study_name="CompM-revolve_Split-M-revolve",
        #                  db_uri=db_path,     # eller "sqlite:///full/path/optimization.db"
        #                  ma_window=5,        # 1 = ingen utjämning
        #                  show_global=False)  # True om du vill se global_score också

        # --- Trigger plott efter tell (trial är COMPLETE i DB) ---
        try:
            # enkel throttle: rita var 3:e COMPLETE
            complete_count = sum(1 for t in self.study.get_trials(deepcopy=False) if t.state.name == "COMPLETE")
            if complete_count % 3 == 0:
                self.requestPlot.emit(self.study.study_name)  # main-tråden hanterar
        except Exception as e:
            App.Console.PrintError(f"[Plot] trigger error: {e}\n")

        self.progress.emit(
            {
                "type": "step",
                "params": self.state.cad_params.copy(),
                "metrics": metrics,
                "score": score,
            }
        )

        self._tick.start(0)

    # -------------------------
    # Main loop
    # -------------------------

    def _step(self):
        if self._stop:
            self.finished.emit()
            return

        if self._paused_by_slider or self._waiting_for_eval:
            self._tick.start(25)
            return

        try:

            # Force random exploration occasionally every 50 trials
            if len(self.study.trials) % 50 == 0:
                # Skapa slumpmässiga parametrar inom dina bounds
                rand_params = {name: float(np.random.uniform(low, high)) for name, (low, high) in self.bounds.items()}
                # Lägg i kö så nästa ask() returnerar dessa
                self.study.enqueue_trial(rand_params)

            trial = self.study.ask()

            # --- NORMAL SCORE ---
            # score = self._compute_and_update_state(metrics)

            self.current_trial = trial
            self._trial_weight_version = self._weight_version

            params = self._suggest_params(trial)

            with self.state.lock:
                self.state.cad_params = params.copy()

            self._waiting_for_eval = True
            self.requestEvaluate.emit({"params": params, "plane": self._plane})

            self.progress.emit(
                {
                    "type": "loop",
                    "phase": "ask",
                    "params": params.copy(),
                }
            )

        except Exception as e:
            App.Console.PrintError(f"[OptimizationWorker] _step error: {e}\n")
            self.current_trial = None
            self._waiting_for_eval = False

        self._tick.start(50)

    # -------------------------
    # Probe / mismatch handlers
    # -------------------------

    def _handle_probe(self, metrics):

        # frö att visa vad probe ger
        try:
            keys = list(metrics.keys())
            valid_keys = [k for k, m in metrics.items() if is_valid_cluster(m)]
            App.Console.PrintMessage("[Probe] metrics keys: " + ", ".join(map(str, keys)) + "\n")
            App.Console.PrintMessage("[Probe] valid keys: " + ", ".join(map(str, valid_keys)) + "\n")
            App.Console.PrintMessage(f"[Probe] valid_count={len(valid_keys)}\n")
        except Exception as e:
            App.Console.PrintError(f"[Probe] debug print error: {e}\n")

        req_total = self._count_valid_clusters(metrics)
        self.required_clusters = req_total if req_total > 0 else None

        with self.state.lock:
            self.state.required_clusters = self.required_clusters

        self.progress.emit({"type": "probe", "required_total": self.required_clusters})

        self.normalizer.reset()

        # 🔒 Frys kanoniska slots från probe-resultatet (stabil ID mellan trials)
        try:
            keys = list(metrics.keys()) if isinstance(metrics, dict) else []
            # sortera som (ClusterId, BounceCount)
            self._canonical_slots = (
                sorted(
                    keys,
                    key=lambda s: (
                        int(str(s).split(":")[0]),
                        int(str(s).split(":")[1]),
                    ),
                )
                if keys
                else None
            )
        except Exception:
            self._canonical_slots = None

        self._init_study(remove_old=self.fresh)
        self.fresh = False

        self._probe_for_required = False
        self._tick.start(0)

    def _handle_cluster_mismatch(self, metrics, n_valid):
        expected = int(self.required_clusters or 0)

        App.Console.PrintError(
            "\n[CLUSTER MISMATCH]\n" f"  Required clusters: {expected}\n" f"  Valid clusters found: {n_valid}\n" f"  All metrics keys: {list(metrics.keys())}\n" f"  Valid clusters keys: {[k for k,m in metrics.items() if is_valid_cluster(m)]}\n"
        )

        # Om vi har canonical slots – visa vad som saknas
        if self._canonical_slots:
            missing = [slot for slot in self._canonical_slots if slot not in metrics]
            bad = [slot for slot, m in metrics.items() if slot in self._canonical_slots and not is_valid_cluster(m)]

            App.Console.PrintError(f"  Canonical slots: {self._canonical_slots}\n" f"  Missing slots: {missing}\n" f"  Invalid slots: {bad}\n")

        # — PRUNE TRIAL —
        try:
            if self.current_trial is not None:
                self.current_trial.set_user_attr("mismatch_n_valid", int(n_valid))
                self.current_trial.set_user_attr("mismatch_required", expected)
                self.study.tell(self.current_trial, state=optuna.trial.TrialState.PRUNED)
        except Exception as e:
            App.Console.PrintError(f"[Optuna] mismatch prune error: {e}\n")
        finally:
            self.current_trial = None

        # rapportera till UI
        self.progress.emit(
            {
                "type": "step",
                "params": self.state.cad_params.copy(),
                "metrics": metrics,
                "score": None,
                "reason": "cluster_mismatch_pruned",
            }
        )

    def _plane_to_normal(self, plane: str):
        if plane == "XY":
            return (0, 0, 1)
        if plane == "XZ":
            return (0, 1, 0)
        if plane == "YZ":
            return (1, 0, 0)
        return (0, 0, 1)

    # -------------------------
    # Optuna helpers
    # -------------------------

    def _init_study(self, remove_old=False):
        # name = self._make_study_name(self.param_names)
        name = self._make_study_name()

        if remove_old:
            try:
                optuna.delete_study(study_name=name, storage=db_path)
                App.Console.PrintMessage(f"[Worker] Deleted old study '{name}'\n")
            except Exception:
                App.Console.PrintMessage(f"[Worker] No previous study to delete\n")
            load_flag = False
        else:
            load_flag = True

        # sampler = optuna.samplers.TPESampler(
        #     multivariate=True,
        #     group=True,
        #     n_startup_trials=25,  # lite mer utforskning
        #     n_ei_candidates=64,  # bättre kandidatbredd för brusiga mål
        #     consider_prior=True,
        #     prior_weight=1.0,
        #     seed=42,  # reproducerbarhet
        # )

        sampler = optuna.samplers.TPESampler(
            multivariate=False,  # viktigt!
            group=False,  # viktigt!
            n_startup_trials=50,  # mer initial utforskning
            n_ei_candidates=128,
            consider_prior=True,
            prior_weight=1.0,
            seed=None,  # TA BORT seed!
            constant_liar=True,
        )

        self.study = optuna.create_study(
            direction="maximize",
            sampler=sampler,
            # sampler=optuna.samplers.TPESampler(multivariate=True, group=True),
            storage=db_path,
            study_name=name,
            load_if_exists=load_flag,
        )

        App.Console.PrintMessage(f"[Worker] Study created '{name}' load_if_exists={load_flag}\n")

    def _prune_current_trial(self):
        if self.current_trial is None:
            return
        try:
            self.study.tell(
                self.current_trial,
                state=optuna.trial.TrialState.PRUNED,
            )
        except Exception:
            pass
        finally:
            self.current_trial = None

    def _tell_current_trial(self, score: float):
        if self.current_trial is None:
            return
        try:
            self.study.tell(self.current_trial, float(score))
            App.Console.PrintMessage(f"[OptimizationWorker] tell: score={score:.4f}\n")
        except Exception as e:
            App.Console.PrintError(f"[Optuna] tell error: {e}\n")
        finally:
            self.current_trial = None

    def _get_best_completed_trial(self):
        """Returnera bästa avslutade trial (robust för olika Optuna-versioner)."""
        try:
            # Funkar om det finns complete trials; kan kasta om inga finns
            return self.study.best_trial
        except Exception:
            pass

        try:
            # Fallback: plocka fram själv
            trials = self.study.get_trials(deepcopy=False)
            completed = [t for t in trials if t.state == optuna.trial.TrialState.COMPLETE]
            if not completed:
                return None
            # direction="maximize" redan satt -> högst value vinner
            return max(completed, key=lambda t: t.value)
        except Exception:
            return None

    def _restore_best_from_study(self):
        """Hämta bästa trial, uppdatera state, be UI-tråden applicera och recalc."""
        best = None
        try:
            best = self._get_best_completed_trial()
        except Exception:
            best = None

        if best is None:
            App.Console.PrintMessage("[OptimizationWorker] No finished Optuna trials yet.\n")
            return

        # Uppdatera state (i worker) så UI har konsistent data
        with self.state.lock:
            self.state.cad_params = best.params.copy()
            try:
                self.state.global_score = float(best.value)
            except Exception:
                pass

        self.progress.emit(
            {
                "type": "best_params",  # <- byt från 'best_applied' till 'best_params'
                "params": best.params.copy(),
                "score": float(best.value) if best.value is not None else None,
            }
        )

        App.Console.PrintMessage(f"[OptimizationWorker] Restore best (score={float(best.value):.4f})\n")
        # self._append_best_trial_to_study()

    def _prune_with_reason(self, reason_key: str, extra: dict | None = None):
        """Pruna current_trial och märk med user_attrs för diagnos."""
        try:
            if self.current_trial is not None:
                App.Console.PrintMessage(f"[OptimizationWorker] Pruning trial: {reason_key}\n")

                self.current_trial.set_user_attr("prune_reason", reason_key)
                if extra:
                    for k, v in extra.items():
                        try:
                            self.current_trial.set_user_attr(k, v)
                        except Exception:
                            pass
                self.study.tell(self.current_trial, state=optuna.trial.TrialState.PRUNED)
        except Exception as e:
            App.Console.PrintError(f"[Optuna] prune error ({reason_key}): {e}\n")
        finally:
            self.current_trial = None

    # def _append_best_trial_to_study(self):
    #     """Skapa ett syntetiskt 'best' trial sist i studyn för reproducerbarhet."""
    #     try:
    #         best = self._get_best_completed_trial()
    #         if best is None:
    #             App.Console.PrintMessage("[Worker] No best trial to append.\n")
    #             return

    #         # skapa nytt trial
    #         new_trial = self.study.ask()

    #         # sätt parametrar identiska med best.params
    #         for name, val in best.params.items():
    #             # OBS: ask() skapar trial med distributions; vi skriver direkt i trial.params
    #             new_trial.params[name] = val

    #         # beräkna objektiv-värdet (samma som best)
    #         score = float(best.value) if best.value is not None else 0.0

    #         # tell trial with value
    #         self.study.tell(new_trial, score)

    #         # --- ATTRIBUT: markera som final best ---
    #         # new_trial.set_user_attr("is_final_best", True)

    #         # sätt user_attrs för CAD-parametrar
    #         new_trial.set_user_attr("cad_params", best.params)

    #         App.Console.PrintMessage(
    #             f"[Worker] Appended synthetic best trial (score={score:.4f}).\n"
    #         )

    #     except Exception as e:
    #         App.Console.PrintError(f"[Worker] Error appending best trial: {e}\n")

    # -------------------------
    # Scoring helpers
    # -------------------------

    def _count_valid_clusters(self, metrics: dict) -> int:
        return sum(1 for m in metrics.values() if is_valid_cluster(m))

    def _score_of_measure(self, d: float, r: float) -> float:
        """Enkel per-slot score, samma vägningsidé som tidigare men utan sorteringsberoende."""
        r = max(0.0, r if r is not None else 0.0)
        d = 0.0 if d is None else float(d)
        r_log = math.log1p(r)
        return self.state.weight_density * d + self.state.weight_roundness * r_log

    def _scores_per_slot(self, metrics: dict) -> list | None:
        if not self._canonical_slots:
            valid = [m for m in metrics.values() if is_valid_cluster(m)]
            return [self._score_of_measure(m["density"], m["roundness"]) for m in valid] if valid else None

        score = []
        for slot in self._canonical_slots:
            m = metrics.get(slot)
            if m is None or not is_valid_cluster(m):
                return None  # saknad/ogiltig slot -> låt on_evaluated pruna
            score.append(self._score_of_measure(m.get("density"), m.get("roundness")))
        return score

    def _compute_and_update_state(self, metrics: dict) -> float:
        valid = [(k, m) for k, m in metrics.items() if is_valid_cluster(m)]

        # ... du har: valid = [(k, m) for k, m in metrics.items() if is_valid_cluster(m)]
        # Bygg globala delpoäng:
        density_global, roundness_global, equal_dist_global = aggregate_from_metrics_dict(
            metrics,  # använder bara de keys du redan skriver i evaluatorn
            plane_for_roundness=self._plane,  # XY/XZ/YZ
        )

        # Bas-mål från dina tre sliders
        base_term = self.state.weight_density * density_global + self.state.weight_roundness * roundness_global + self.state.weight_equal_distance * equal_dist_global

        with self.state.lock:
            self.state.hitscores = metrics

            if not valid:
                # Signalera till on_evaluated att vi ska PRUNA
                return None

            # if not valid:
            #     # OBS: -inf kan skapa problem i mismatch-handlern (multiplikation).
            #     # Om du vill vara snällare mot Optuna i mismatch: överväg -1e9 i stället.

            #     return float("-inf")

            # --- Samla grundlistor EN gång, oberoende av slot/fallback ---
            dens = [float(m["density"]) for _, m in valid]
            round_raw = [float(m["roundness"]) for _, m in valid]
            round_log = [math.log1p(r) for r in round_raw]

            # ---- 1) Bas-term ----
            use_slots = bool(self._canonical_slots)
            if use_slots:
                # Per-slot score (stabil identitet)
                # slot_scores = self._scores_per_slot(metrics)
                # Hård aggregering: min tvingar upp svagaste sloten
                # base_term = float(np.min(slot_scores))

                # Per-slot score (stabil identitet)
                slot_scores = self._scores_per_slot(metrics)  # kan vara None om slot saknas
                if slot_scores is None or len(slot_scores) == 0:
                    return None  # trigga prune uppströms
                # Hård aggregering: min tvingar upp svagaste sloten
                base_term = float(np.min(slot_scores))

                # Vill du ha mjukare: uncomment nedan
                # alpha = 4.0
                # base_term = -math.log(np.mean([math.exp(-alpha * s) for s in slot_scores]))
            else:
                # Fallback: din tidigare median-aggregation (utan beroende av sorteringsordning mellan trials)
                # Normalisering av roundness-logg
                r_min, r_max = min(round_log), max(round_log)

                def safe_norm(v, lo, hi):
                    return 0.0 if hi <= lo else (v - lo) / (hi - lo)

                dens_n = dens[:]  # du valde tidigare att använda rå densitet
                round_n = [safe_norm(r, r_min, r_max) for r in round_log]
                per_cluster = [self.state.weight_density * dn + self.state.weight_roundness * rn for dn, rn in zip(dens_n, round_n)]
                base_term = float(np.median(per_cluster))

            # --- 2) Normalizer (behöver dens/round_raw) ---
            self.normalizer.update({i: {"density": d, "roundness": r} for i, (d, r) in enumerate(zip(dens, round_raw))})

            # --- 3) Centroids/spreads för separation/overlap ---
            centroids = []
            spreads = []
            for _, m in valid:
                c = m.get("centroid", None)
                s = m.get("spread", None)
                if c is not None and isinstance(c, (tuple, list)) and len(c) >= 2:
                    cx, cy = float(c[0]), float(c[1])  # projicera till 2D
                    centroids.append((cx, cy))
                else:
                    centroids.append(None)
                try:
                    spreads.append(float(s) if s is not None else 0.0)
                except Exception:
                    spreads.append(0.0)

            sep_raw = None
            ov_raw = None
            margin = 0.0
            if all(c is not None for c in centroids) and len(centroids) >= 2:
                dists = []
                overlaps = []
                sp_median = float(np.median([s for s in spreads if np.isfinite(s)])) if any(np.isfinite(s) for s in spreads) else 0.0
                margin = 0.1 * sp_median

                for i in range(len(centroids)):
                    for j in range(i + 1, len(centroids)):
                        dx = centroids[i][0] - centroids[j][0]
                        dy = centroids[i][1] - centroids[j][1]
                        dij = float(math.hypot(dx, dy))
                        dists.append(dij)
                        rij = max(0.0, spreads[i] + spreads[j] + margin - dij)
                        overlaps.append(rij)

                sep_raw = float(np.median(dists)) if dists else 0.0
                ov_raw = float(np.sum(overlaps)) if overlaps else 0.0

                # Initiera skalor första gången
                if self._sep_scale is None:
                    self._sep_scale = max(sep_raw, 1e-6)
                if self._ov_scale is None:
                    n = len(centroids)
                    pairs = n * (n - 1) / 2
                    self._ov_scale = max(pairs * (margin if margin > 0 else 1.0), 1e-6)

            # --- 4) Normalisera sep/ov och vikta in i global score ---
            sep_n = 0.0 if (sep_raw is None or self._sep_scale is None) else max(0.0, min(1.0, sep_raw / self._sep_scale))
            ov_n = 0.0 if (ov_raw is None or self._ov_scale is None) else max(0.0, min(1.0, ov_raw / self._ov_scale))

            w_sep = getattr(self.state, "weight_separation", 0.5)
            w_ov = getattr(self.state, "weight_overlap", 1.0)
            w_dglob = getattr(self.state, "weight_density_global", 1.0)

            # Global densitets-term (du använder mean(d^2))
            d_global = float(np.mean([d**2 for d in dens])) if dens else 0.0

            global_score = base_term + w_dglob * d_global + w_sep * sep_n - w_ov * ov_n

            # uppdatera state/historik
            self.state.history.append((self.state.cad_params.copy(), metrics, global_score))
            self.state.global_score = global_score

        try:
            App.Console.PrintMessage(f"d_global={d_global:.3f}, base={base_term:.3f}, sep_n={sep_n:.3f}, ov_n={ov_n:.3f}" + (f", slots={len(self._canonical_slots)}" if self._canonical_slots else "") + "\n")
        except Exception:
            pass

        return global_score

    # -------------------------
    # Parameter suggestion
    # -------------------------

    def _suggest_params(self, trial) -> dict:
        params = {}
        for name in self.param_names:
            low, high = self.bounds[name]
            params[name] = trial.suggest_float(name, low, high)
        return params

    # -------------------------
    # Static helpers
    # -------------------------

    @staticmethod
    def _sanitize(s: str) -> str:
        """
        Tar bort otillåtna tecken, ersätter mellanslag med '-',
        komprimerar '---', och ser till att study-namnet är Optuna-säkert.
        """
        s = re.sub(r"[^A-Za-z0-9_\- ]+", "-", s)
        s = s.replace(" ", "-")
        s = re.sub(r"-{2,}", "-", s)
        return s.strip("-")

    def _make_study_name(self):
        """
        Skapar ett unikt och stabilt study-namn baserat på:
          - parameterlistan
          - det valda planet (XY/XZ/YZ)

        Exempel:
          param names = ["Comp M Radius (B)", "Angle"]
          plane = "XY"
          -> "XY-Comp-M-Radius-B_-Angle"
        """

        # 1. Sanera planet
        plane = getattr(self, "_plane", "XY")
        plane_s = self._sanitize(str(plane))

        # 2. Sanera param-namn
        sanitized = [self._sanitize(p) for p in sorted(self.param_names)]

        # 3. Kombinera
        return plane_s + "__" + "__".join(sanitized)

    @staticmethod
    def _make_study_name_old(param_names):
        allowed_pattern = re.compile(r"^[A-Za-z0-9_ ]+$")

        for name in param_names:
            if not allowed_pattern.match(name):
                App.Console.PrintError(f"Invalid parameter name: '{name}'.\n")
                return None

        names = tuple(sorted(param_names))
        return "_".join(names).replace(" ", "-")
