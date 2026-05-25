from PySide import QtCore
from .optuna_optimizer import Optimizer


class OptimizationWorker(QtCore.QObject):
    requestEvaluate = QtCore.Signal(dict)
    progress = QtCore.Signal(dict)
    finished = QtCore.Signal()

    def __init__(self, state, param_names, bounds):
        super().__init__()
        self.state = state
        self.optimizer = Optimizer(param_names, bounds)

        self._paused_by_slider = False
        self._stop = False
        self._waiting = False
        self._last_metrics = None

        self._tick = QtCore.QTimer(self)
        self._tick.setSingleShot(True)
        self._tick.timeout.connect(self._step)

    @QtCore.Slot()
    def start(self):
        self._stop = False
        self._waiting = False
        self._tick.start(0)

    @QtCore.Slot()
    def stop(self):
        self._stop = True
        # Om vi väntar på eval-resultat, låt on_evaluated få avsluta
        if self._waiting is False:
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
        # starta om loopen snabbt efter resume
        if not self._waiting and not self._stop:
            self._tick.start(0)

    @QtCore.Slot(float, float)
    def update_weights(self, density, roundness):
        with self.state.lock:
            self.state.weight_density = density
            self.state.weight_roundness = roundness
        self.progress.emit(
            {
                "type": "weights",
                "weights": {"density": density, "roundness": roundness},
            }
        )

    @QtCore.Slot(dict)
    def on_evaluated(self, metrics: dict):
        if self._stop:
            self.finished.emit()
            return

        self._waiting = False

        with self.state.lock:
            self.state.hitscores = metrics
            if metrics:
                self.state.global_score = min(self.state.weight_density * m.get("density", 0.0) + self.state.weight_roundness * m.get("roundness", 0.0) for m in metrics.values())
            else:
                self.state.global_score = float("-inf")

            self.state.history.append((self.state.cad_params.copy(), metrics, self.state.global_score))

        self.progress.emit(
            {
                "type": "step",
                "params": self.state.cad_params.copy(),
                "metrics": metrics,
                "score": self.state.global_score,
            }
        )

        if not self._stop:
            self._tick.start(0)
        else:
            self.finished.emit()

    def _step(self):
        if self._stop:
            self.finished.emit()
            return

        if self._waiting:
            return

        # 🔧 respektera paus: schemalägg nästa tick och gör inget mer
        if self._paused_by_slider:
            self._tick.start(25)  # liten delay så vi inte spinner
            return

        # --- välj nästa CAD-parametrar ---
        with self.state.lock:
            params = self.optimizer.ask(self.state)
            self.state.cad_params = params.copy()

        self._waiting = True
        self.requestEvaluate.emit({"params": params})
