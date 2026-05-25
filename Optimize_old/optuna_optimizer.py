# optimizer.py


import sys
import os


BASE = os.path.dirname(os.path.dirname(__file__))  # .../Oba/
LIBDIR = os.path.join(BASE, "vendor_optuna")

if LIBDIR not in sys.path:
    sys.path.insert(0, LIBDIR)

import optuna

from PySide import QtCore


class OptimizationWorker(QtCore.QObject):
    def __init__(self, state, param_names, bounds):
        super().__init__()

        self.state = state

        self.param_names = param_names
        self.bounds = bounds

        # 🔑 Optuna-studie med SQLite-storage
        self.study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(
                multivariate=True,
                group=True,
            ),
            storage="sqlite:///optimization.db",
            study_name="optics_optimization",
            load_if_exists=True,
        )

        self.current_trial = None  # håller pågående trial

        self.normalizer = MetricNormalizer()

        self._paused_by_slider = False
        self._stop = False
        self._waiting_for_eval = False
        self._last_metrics = None

        self._tick = QtCore.QTimer(self)
        self._tick.setSingleShot(True)
        self._tick.timeout.connect(self._step)
