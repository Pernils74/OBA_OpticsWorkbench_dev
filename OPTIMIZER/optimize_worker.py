# optimize_worker.py
# -*- coding: utf-8 -*-

import os
import sys

from oba_rayengine.oba_ray_core import OBARayManager

from PySide import QtCore

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
LIBDIR = os.path.join(BASE_DIR, "vendor_optuna")

if LIBDIR not in sys.path:
    sys.path.insert(0, LIBDIR)

import optuna
from optuna.samplers import TPESampler, RandomSampler, CmaEsSampler, NSGAIISampler

# DB_PATH = f"sqlite:///{os.path.join(BASE_DIR, 'optimization.db')}"


def get_db_path():
    import FreeCAD as App
    import os

    doc = App.ActiveDocument

    if doc and doc.FileName:
        base = os.path.splitext(doc.FileName)[0]
    else:
        # fallback om dokument ej sparat
        base = os.path.join(os.getcwd(), "unsaved_document")

    return f"sqlite:///{base}_optuna.db"


DB_PATH = get_db_path()


class OptimizationWorker(QtCore.QObject):
    requestEvaluate = QtCore.Signal(dict, dict)
    progress = QtCore.Signal(dict)
    finished = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self._stop = False

        self._waiting = False
        self._last_results = None

    def request_stop(self):
        print("[worker] stop requested")

        self._stop = True
        self._waiting = False

    @QtCore.Slot(dict)
    def start(self, config):
        self._stop = False
        self._waiting = False
        self._last_results = None

        self.param_names = config["params"]
        self.bounds = config["bounds"]
        self.unselected_params = config.get("unselected_params", {})  # Parametrar som INTE optimeras

        self.start_cad_params = config.get("start_cad_params")  # Spara undan cad_params vid start

        if self.start_cad_params is None:
            self.start_cad_params = {}

            if isinstance(self.unselected_params, dict):
                self.start_cad_params.update(self.unselected_params)

            # initial_params används endast som fallback
            initial_params = config.get("initial_params", {})

            if isinstance(initial_params, dict):
                self.start_cad_params.update(initial_params)

        # --------------------------------------------------
        # METRICS
        # --------------------------------------------------

        self.all_metrics = config["metrics"]
        self.metrics = [m for m in config["metrics"] if m.get("active", True)]
        print("ALL METRICS:", [m["name"] for m in self.all_metrics])
        print("ACTIVE METRICS:", [m["name"] for m in self.metrics])
        print("[worker] start CAD params:", self.start_cad_params)

        study_name = config["study_name"]
        new_study = config.get("new_study", False)

        multi = config.get("multi_objective", False)

        # --------------------------------------------------
        # SAMPLER
        # --------------------------------------------------
        sampler = self._create_sampler(config)
        print(f"[worker] sampler=" f"{sampler.__class__.__name__} " f"multi={multi}")
        # --------------------------------------------------
        # DIRECTIONS
        # --------------------------------------------------
        if len(self.metrics) == 1:
            direction = self.metrics[0]["direction"]
            directions = None
        else:
            direction = None
            directions = [m["direction"] for m in self.metrics]
        # --------------------------------------------------
        # STUDY
        # --------------------------------------------------
        if new_study:
            print("[worker] NEW study")
            try:
                optuna.delete_study(
                    study_name=study_name,
                    storage=DB_PATH,
                )
            except Exception:
                pass

            self.study = optuna.create_study(
                study_name=study_name,
                storage=DB_PATH,
                load_if_exists=False,
                sampler=sampler,
                direction=direction,
                directions=directions,
            )

            initial_params = config.get("initial_params")
            print("[worker] enqueue initial trial:", initial_params)
            if initial_params:
                self.study.enqueue_trial(initial_params)
            self.study.set_user_attr("metric_names", [m["name"] for m in self.metrics])
            self.study.set_user_attr("all_metrics", [m["name"] for m in self.all_metrics])
            self.study.set_user_attr("active_metrics", [m["name"] for m in self.metrics])
            self.study.set_user_attr("metric_config", self.metrics)
            self.study.set_user_attr("param_names", self.param_names)
            self.study.set_user_attr("sampler", config.get("sampler"))

        else:
            print("[worker] RESUME study")
            self.study = optuna.create_study(
                study_name=study_name,
                storage=DB_PATH,
                load_if_exists=True,
                sampler=sampler,
                direction=direction,
                directions=directions,
            )

        # --------------------------------------------------
        # MAIN LOOP
        # --------------------------------------------------
        n_trials = config["n_trials"]
        if n_trials < 0:
            print("[worker] 🚀 running infinite trials")
            iterator = iter(int, 1)
        else:
            print(f"[worker] 🚀 running " f"({n_trials}) trials")
            iterator = range(n_trials)
        for _ in iterator:
            if self._stop:
                break
            trial = self.study.ask()
            self.current_trial_id = trial.number
            try:
                params = self._suggest(trial)  # SUGGEST PARAMS
                self._last_results = None
                self._waiting = True
                # --------------------------------------------------
                # EVALUATE
                # --------------------------------------------------
                self.requestEvaluate.emit(params, self.unselected_params)
                while self._waiting and not self._stop:
                    QtCore.QThread.msleep(10)
                if self._stop:
                    print("[worker] stopped")
                    break
                if self._last_results is None:
                    raise RuntimeError("No evaluation result received")

                payload = self._last_results
                # --------------------------------------------------
                # PRUNED
                # --------------------------------------------------
                if payload.get("_pruned"):
                    print(f"[PRUNE] " f"trial={trial.number} " f"params={params}")
                    self.study.tell(trial, state=optuna.trial.TrialState.PRUNED)
                    continue
                # --------------------------------------------------
                # RESULTS
                # --------------------------------------------------
                results = payload.get("results", {})
                debug_info = payload.get("debug", {})
                # --------------------------------------------------
                # STORE USER ATTRS
                # --------------------------------------------------
                trial.set_user_attr("params", params)
                trial.set_user_attr("metrics", results)
                trial.set_user_attr("debug", debug_info)
                trial.set_user_attr("unselected_params", self.unselected_params)
                # --------------------------------------------------
                # VALUES
                #
                # EvaluationService har redan gjort eventuell
                # recheck och medelvärdesberäkning.
                # Här ska vi därför INTE räkna om något.
                # --------------------------------------------------
                values = []
                for m in self.metrics:
                    v = results.get(m["name"], 0.0)
                    v = float(v)
                    # Optuna får alltid maximize internt.
                    # if m["direction"] == "minimize":
                    #     v = -v
                    values.append(v)
                values = tuple(values)
                # --------------------------------------------------
                # TELL
                # --------------------------------------------------
                self.study.tell(trial, values)
                # print(f"[worker] " f"trial={trial.number} " f"values={values}")
                if trial.number % 10 == 0:
                    self.progress.emit({"trial": trial.number, "values": values})
            except KeyError as e:
                print(f"[worker] missing metric: {e}")
                self.study.tell(trial, state=optuna.trial.TrialState.FAIL)
            except RuntimeError as e:
                print(f"[worker] runtime error: {e}")
                trial.set_user_attr("status", "runtime_error")
                trial.set_user_attr("message", str(e))
                self.study.tell(trial, state=optuna.trial.TrialState.FAIL)
            except Exception as e:
                print(f"[worker] hard fail: {e}")
                self.study.tell(trial, state=optuna.trial.TrialState.FAIL)
        # --------------------------------------------------
        # BEST TRIALS
        # --------------------------------------------------
        best_trials_data = [
            {
                "trial": t.number,
                "params": t.params,
                "values": t.values,
                "metrics": t.user_attrs.get(
                    "metrics",
                    {},
                ),
            }
            for t in self.study.best_trials
        ]
        self.finished.emit(best_trials_data)

    # start_old används inte utan bara med som historia
    def start_old(self, config):
        self._stop = False
        self._waiting = False
        self._last_results = None

        self.param_names = config["params"]
        self.bounds = config["bounds"]
        self.unselected_params = config.get("unselected_params", [])

        # ✅ metadata
        self.all_metrics = config["metrics"]
        self.metrics = [m for m in config["metrics"] if m.get("active", True)]

        print("ALL METRICS:", [m["name"] for m in self.all_metrics])
        print("ACTIVE METRICS:", [m["name"] for m in self.metrics])

        study_name = config["study_name"]
        new_study = config.get("new_study", False)

        multi = config.get("multi_objective", False)

        # ✅ skapa sampler korrekt
        sampler = self._create_sampler(config)

        print(f"[worker] sampler={sampler.__class__.__name__} multi={multi}")

        # ✅ directions vs direction (Optuna korrekt hantering)
        if len(self.metrics) == 1:
            direction = self.metrics[0]["direction"]
            directions = None
        else:
            direction = None
            directions = [m["direction"] for m in self.metrics]

        # ✅ skapa / ladda study
        if new_study:
            print("[worker] NEW study")

            try:
                optuna.delete_study(
                    study_name=study_name,
                    storage=DB_PATH,
                )
            except Exception:
                pass

            self.study = optuna.create_study(
                study_name=study_name,
                storage=DB_PATH,
                load_if_exists=False,
                sampler=sampler,
                direction=direction,
                directions=directions,
            )

            initial_params = config.get("initial_params")
            print("[worker] enqueue initial trial:", initial_params)

            if initial_params:
                self.study.enqueue_trial(initial_params)

            self.study.set_user_attr("metric_names", [m["name"] for m in self.metrics])
            self.study.set_user_attr("all_metrics", [m["name"] for m in self.all_metrics])
            self.study.set_user_attr("active_metrics", [m["name"] for m in self.metrics])
            self.study.set_user_attr("metric_config", self.metrics)
            self.study.set_user_attr("param_names", self.param_names)
            self.study.set_user_attr("sampler", config.get("sampler"))

        else:
            print("[worker] RESUME study")
            storage = optuna.storages.RDBStorage(
                url=DB_PATH,
                engine_kwargs={
                    "connect_args": {
                        "timeout": 60,
                    }
                },
            )

            self.study = optuna.create_study(
                study_name=study_name,
                storage=storage,
                # storage=DB_PATH,
                load_if_exists=True,
                sampler=sampler,
                direction=direction,
                directions=directions,
            )

        print("[worker] start", config["n_trials"])
        # ✅ MAIN LOOP
        n_trials = config["n_trials"]
        if n_trials < 0:
            print("[worker] 🚀  running infinite trials")
            iterator = iter(int, 1)  # endless generator
        else:
            print(f"[worker] 🚀  running ({n_trials}) trials")
            iterator = range(n_trials)

        for _ in iterator:  # range(config["n_trials"]):
            if self._stop:
                break
            trial = self.study.ask()
            self.current_trial_id = trial.number
            try:
                # Local step-limited parameter suggestion (damped search).
                params = self._suggest(trial)
                self._last_results = None
                self._waiting = True
                self.requestEvaluate.emit(params, self.unselected_params)
                while self._waiting and not self._stop:
                    QtCore.QThread.msleep(10)

                if self._stop:
                    print("[worker] stopped")
                    break

                if self._last_results is None:
                    raise RuntimeError("No evaluation result received")

                payload = self._last_results

                # ✅ pruning
                if payload.get("_pruned"):
                    print(f"[PRUNE] trial={trial.number} params={params}")
                    self.study.tell(trial, state=optuna.trial.TrialState.PRUNED)
                    continue

                results = payload.get("results", {})
                debug_info = payload.get("debug", {})
                # ✅ debug storage

                trial.set_user_attr("params", params)
                trial.set_user_attr("metrics", results)
                trial.set_user_attr("debug", debug_info)
                trial.set_user_attr("unselected_params", self.unselected_params)

                # ✅ values (robust + direction handling)
                values = []
                for m in self.metrics:
                    v = results.get(m["name"], 0.0)
                    # normalize internally if minimize
                    if m["direction"] == "minimize":
                        v = -v

                    values.append(v)

                values = tuple(values)
                self.study.tell(trial, values)
                if trial.number % 10 == 0:
                    self.progress.emit(
                        {
                            "trial": trial.number,
                            "values": values,
                        }
                    )

            except KeyError as e:
                print(f"[worker] missing metric: {e}")
                self.study.tell(trial, state=optuna.trial.TrialState.FAIL)

            except RuntimeError as e:
                print(f"[worker] runtime error: {e}")
                trial.set_user_attr("status", "runtime_error")
                trial.set_user_attr("message", str(e))
                self.study.tell(trial, state=optuna.trial.TrialState.FAIL)

            except Exception as e:
                print(f"[worker] hard fail: {e}")
                self.study.tell(trial, state=optuna.trial.TrialState.FAIL)

        # ✅ best trials
        best_trials_data = [
            {
                "trial": t.number,
                "params": t.params,
                "values": t.values,
                "metrics": t.user_attrs.get("metrics", {}),
            }
            for t in self.study.best_trials
        ]

        self.finished.emit(best_trials_data)

    def _suggest_utan_dämpning(self, trial):
        params = {}
        for name in self.param_names:
            lo, hi = self.bounds[name]
            params[name] = trial.suggest_float(
                name,
                lo,
                hi,
            )

        return params

    def _suggest_trust_regions(self, trial):
        params = {}
        step_ratio = 0.15  # 🔧 15% av range

        for name in self.param_names:
            lo, hi = self.bounds[name]
            prev = None
            if hasattr(self, "_last_params"):
                prev = self._last_params.get(name)
            span = (hi - lo) * step_ratio
            if prev is None:
                lo2, hi2 = lo, hi
            else:
                lo2 = max(lo, prev - span)
                hi2 = min(hi, prev + span)
            v = trial.suggest_float(name, lo2, hi2)
            params[name] = v
        self._last_params = params.copy()
        return params

    # Constrain Optuna's search to a trust region around the
    # current best solution. This reduces large CAD geometry
    # jumps while still allowing gradual exploration.
    def _suggest(self, trial):
        params = {}

        step_ratio = 0.15  # ±15% av hela parameterns range

        best_params = None

        # Hämta bästa trial hittills
        complete = [t for t in self.study.trials if t.state == optuna.trial.TrialState.COMPLETE]

        if complete:
            if len(self.metrics) == 1:
                best_trial = self.study.best_trial
            else:
                # Multi-objective: använd första Pareto-lösningen
                best_trial = self.study.best_trials[0]

            best_params = best_trial.params

        for name in self.param_names:
            lo, hi = self.bounds[name]

            if best_params and name in best_params:
                prev = best_params[name]
            else:
                prev = None

            span = (hi - lo) * step_ratio

            if prev is None:
                lo2, hi2 = lo, hi
            else:
                lo2 = max(lo, prev - span)
                hi2 = min(hi, prev + span)

            params[name] = trial.suggest_float(name, lo2, hi2)

        return params

    def _create_sampler(self, config):
        name = config.get("sampler", "TPESampler")
        constant_liar = config.get("constant_liar", False)
        multi = config.get("multi_objective", False)

        # ✅ multi-objective kräver NSGA-II
        if multi and name != "NSGAIISampler":
            print("[WARN] Switching to NSGAIISampler (multi-objective)")
            return NSGAIISampler()

        if name == "TPESampler":
            return TPESampler(
                constant_liar=constant_liar,
                multivariate=True,
                n_startup_trials=20,
                seed=42,
            )

        elif name == "RandomSampler":
            return RandomSampler()

        elif name == "CmaEsSampler":
            return CmaEsSampler()

        elif name == "NSGAIISampler":
            return NSGAIISampler()

        return TPESampler(seed=42)

    @QtCore.Slot(object)
    def on_evaluated(self, results):
        if self._stop:
            return

        self._last_results = results
        self._waiting = False
