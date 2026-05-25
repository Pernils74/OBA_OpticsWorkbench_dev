# -*- coding: utf-8 -*-
# evaluation_service.py — REINTRODUCED CLEAN PIPELINE

from pydoc import doc

import FreeCAD as App
from PySide import QtCore
from .spreadsheet_utils import apply_cad_params
from oba_objects.oba_base import _trigger_ray_engine

import numpy as np
from collections import defaultdict
from oba_rayengine.oba_ray_analyser import aggregate_interaction_clusters

# ------------------------------------------------------------
# EVALUATION SERVICE
# ------------------------------------------------------------


class EvaluationService(QtCore.QObject):
    """
    Bridge mellan:
        CAD params → Ray engine → Cluster extraction → Optuna worker
    """

    evaluationReady = QtCore.Signal(dict)

    # -------------------------------------------------------
    # APPLY BEST PARAMS (UI BUTTON)
    # -------------------------------------------------------

    @QtCore.Slot(dict)
    def applyBest(self, params: dict):
        doc = App.ActiveDocument
        if not doc:
            App.Console.PrintError("[Eval] No active document\n")
            return
        try:
            apply_cad_params(params)
            # recompute_doc(doc, restore_view=False)
            App.Console.PrintMessage("[Eval] Applied best parameters.\n")

        except Exception as e:
            App.Console.PrintError(f"[Eval] applyBest failed: {e}\n")

    # -------------------------------------------------------
    # MAIN EVALUATION ENTRY
    # -------------------------------------------------------

    @QtCore.Slot(dict)
    def evaluate(self, payload):
        # print("🔥[evaluation_service] evaluate received in EvalService")
        # print(f"DEBUG: Payload: {payload}")

        doc = App.ActiveDocument
        if not doc:
            print("[evaluation_service] DEBUG: No active document in evaluate")
            self.evaluationReady.emit({"clusters": {}})
            return

        params = payload.get("params", {})

        # 1. APPLY PARAMS
        if params:
            print(f"[evaluation_service] DEBUG: Applying params: {params}")
            apply_cad_params(params)
            # ✅ Tvinga modelluppdatering
            doc.recompute()
            _trigger_ray_engine(reason="optuna_optimization", source=None, force=True)
            # print("[evaluation_service] DEBUG: Applied CAD parameters for evaluation.")

        # 2. NOTE:
        # Ray engine är reaktiv → ingen explicit recompute behövs
        # recompute_doc(doc, restore_view=False)

        # 3. COLLECT RAY CLUSTERS
        # print("[evaluation_service] DEBUG: Collecting clusters")

        # clusters = aggregate_interaction_clusters(plane=plane, mode="final", min_hits=1)
        clusters = aggregate_interaction_clusters(mode="final", min_hits=1)

        print(f"[evaluation_service] DEBUG: Collected {len(clusters)} clusters")

        # 4. RETURN TO WORKER
        self.evaluationReady.emit({"clusters": clusters})

        # -------------------------------------------------------
        # CLUSTER COLLECTION (CORE LOGIC)
        # -------------------------------------------------------

    # -------------------------------------------------------
    # PROJECTION HELPERS
    # -------------------------------------------------------

    def _project_points(self, points, plane):

        if plane == "XY":
            return points[:, [0, 1]]
        elif plane == "XZ":
            return points[:, [0, 2]]
        elif plane == "YZ":
            return points[:, [1, 2]]

        return points[:, [0, 1]]
