# optimize_worker.py
# -*- coding: utf-8 -*-

import os
import sys

from PySide import QtCore

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
LIBDIR = os.path.join(BASE_DIR, "vendor_optuna")

if LIBDIR not in sys.path:
    sys.path.insert(0, LIBDIR)

import optuna

DB_PATH = f"sqlite:///{os.path.join(BASE_DIR, 'optimization.db')}"


class OptimizationWorker(QtCore.QObject):
    requestEvaluate = QtCore.Signal(dict)
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

        # ✅ behåll alla för metadata
        self.all_metrics = config["metrics"]
        # ✅ endast aktiva används i optimering
        # self.metrics = config["metrics"]
        self.metrics = [m for m in config["metrics"] if m.get("active", True)]
        print("ALL METRICS:", [m["name"] for m in self.all_metrics])
        print("ACTIVE METRICS:", [m["name"] for m in self.metrics])

        self._baseline = config.get("baseline", None)

        directions = [m["direction"] for m in self.metrics]

        # study_name = self._make_study_name()
        study_name = config["study_name"]

        new_study = config.get("new_study", False)

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
                directions=directions,
                sampler=optuna.samplers.NSGAIISampler(),
            )

            # ✅ ENQUEUE BASELINE
            initial_params = config.get("initial_params")
            print("[worker] enqueue baseline:", initial_params)
            self.study.enqueue_trial(initial_params)

            self.study.set_user_attr("metric_names", [m["name"] for m in self.metrics])  # spar metric_names en gång för plotten
            self.study.set_user_attr("all_metrics", [m["name"] for m in self.all_metrics])  # används inte just nu
            self.study.set_user_attr("active_metrics", [m["name"] for m in self.metrics])  # används inte just nu

            self.study.set_user_attr("metric_config", self.metrics)
            self.study.set_user_attr("param_names", self.param_names)

        else:
            print("[worker] RESUME study")
            self.study = optuna.create_study(
                study_name=study_name,
                storage=DB_PATH,
                load_if_exists=True,
                directions=directions,
                sampler=optuna.samplers.NSGAIISampler(),
            )

        print("[worker] start", config["n_trials"])

        for _ in range(config["n_trials"]):
            if self._stop:
                break
            trial = self.study.ask()
            try:
                params = self._suggest(trial)
                self._last_results = None
                self._waiting = True
                self.requestEvaluate.emit(params)
                while self._waiting and not self._stop:
                    QtCore.QThread.msleep(10)

                if self._stop:
                    print("[worker] stopped")
                    break

                if self._last_results is None:
                    raise RuntimeError("No evaluation result received")

                results = self._last_results
                # print("[worker] RESULTS:", results)
                # ✅ SPARA DEBUG DATA ALLTID (bra för UI)
                trial.set_user_attr("params", params)
                trial.set_user_attr("metrics", results)

                # ✅ PRUNING
                if results.get("_pruned"):
                    print(f"[PRUNE] trial={trial.number} params={params}")
                    self.study.tell(trial, state=optuna.trial.TrialState.PRUNED)
                    continue

                # ✅ NORMAL CASE
                values = tuple(results.get(m["name"], 0.0) for m in self.metrics)
                # values = tuple(results[m["name"]] for m in self.metrics)

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
                self.study.tell(
                    trial,
                    state=optuna.trial.TrialState.FAIL,
                )
            except RuntimeError as e:
                print(f"[worker] runtime error: {e}")
                trial.set_user_attr("status", "runtime_error")
                trial.set_user_attr("message", str(e))
                self.study.tell(
                    trial,
                    state=optuna.trial.TrialState.FAIL,
                )
            except Exception as e:
                print(f"[worker] hard fail: {e}")
                self.study.tell(
                    trial,
                    state=optuna.trial.TrialState.FAIL,
                )
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

    def _suggest(self, trial):
        params = {}
        for name in self.param_names:
            lo, hi = self.bounds[name]
            params[name] = trial.suggest_float(
                name,
                lo,
                hi,
            )
        return params

    @QtCore.Slot(object)
    def on_evaluated(self, results):
        if self._stop:
            return

        self._last_results = results
        self._waiting = False
