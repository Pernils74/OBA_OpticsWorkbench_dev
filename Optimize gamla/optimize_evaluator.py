# -*- coding: utf-8 -*-
# evaluation_service.py — STÄDAD, parser-baserad, kompatibel med nya metrics

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

from .spreadsheet_utils import (
    apply_cad_params,
    remove_spreadsheets_by_name,
)
from .cad_refresh import (
    recompute_doc,
    remember_active_subwindow,
    restore_active_subwindow,
)

# Läs råa RayHits och bygg grupp-statistik
from __sparas__.oba_rayhits.sa_rayhits_parser import get_tree_and_stats_for_sheet

# Samma mått som används i optimeringen
from .optimize_evaluator_metrics import roundness_score_from_cov, density_score

from .optimize_config import (
    SPREADSHEET_NAME,
    SOURCE_SHEET_NAME,  # t.ex. "RayHits"
    RESULT_SHEET_NAME,  # ej längre använd här
)


class EvaluationService(QtCore.QObject):
    evaluationReady = QtCore.Signal(dict)

    # -------------------------------------------------------
    # Publika slots
    # -------------------------------------------------------
    @QtCore.Slot(dict)
    def applyBest(self, params: dict):
        doc = App.ActiveDocument
        if not doc:
            App.Console.PrintError("[Eval] No active document.\n")
            return
        try:
            apply_cad_params(params)
            recompute_doc(doc, restore_view=False)
            App.Console.PrintMessage("[Eval] Applied best Optuna parameters.\n")
        except Exception as e:
            App.Console.PrintError(f"[Eval] Failed apply best params: {e}\n")

    @QtCore.Slot(dict)
    def evaluate(self, payload: dict):
        """
        Körs i main thread.
        payload = {"params": {...}, "plane": "XY"|"XZ"|"YZ", "mode": "probe"|None}
        """
        doc = App.ActiveDocument
        if not doc:
            self.evaluationReady.emit({})
            return

        params = payload.get("params", {})
        plane = (payload.get("plane") or "XY").upper()

        # 1) Sätt CAD-parametrar (om några) + recompute + exportera RayHits
        try:
            if params:
                apply_cad_params(params)

            prev_subwin = remember_active_subwindow()
            recompute_doc(doc, restore_view=False)

            # Städa gamla RayHits-blad (för att slippa RayHits001, 002, ...)
            remove_spreadsheets_by_name(doc, SOURCE_SHEET_NAME)

            # Generera nytt RayHits-blad via OpticsWorkbench
            import sa_OpticsWorkbench as OW

            OW.Hits2CSV()

            # Återställ vy
            restore_active_subwindow(prev_subwin)

        except Exception as e:
            App.Console.PrintError(f"[Eval] recompute/Hits2CSV error: {e}\n")
            self.evaluationReady.emit({"metrics": {}})
            return

        # 2) Läs RayHits → (tree, stats) via parsern
        try:
            # SOURCE_SHEET_NAME är prefix (parsern klarar 'börjar med')
            _tree, stats = get_tree_and_stats_for_sheet(SOURCE_SHEET_NAME, doc=doc, compute_weighted_3d=False)
        except Exception as e:
            App.Console.PrintError(f"[Eval] parser error: {e}\n")
            self.evaluationReady.emit({"metrics": {}})
            return

        # 3) Konvertera stats → metrics (format som workern/metrics väntar sig)
        metrics = self._stats_to_metrics(stats, plane)

        # 4) Returnera till worker
        self.evaluationReady.emit({"metrics": metrics})

    # -------------------------------------------------------
    # Intern: konvertera stats → metrics
    # -------------------------------------------------------
    def _stats_to_metrics(self, stats: dict, plane: str) -> dict:
        """
        stats: dict[group_id(tuple)] -> stat-dict, från sa_rayhits_parser.build_group_stats
        plane: "XY"|"XZ"|"YZ" — används för 'roundness' (kovarians i valt plan)

        RETURNERAR:
          metrics: dict[str -> dict] där nyckeln är "clusterId:bounce" (numerisk:numerisk)
                   och värdet innehåller fält som worker + optimize_metrics använder.
        """

        # 1) Stabil sortering för deterministisk id-tilldelning
        def sort_key(item):
            (absorber, ray, bounce, prev), stat = item
            fi = stat.get("first_index", 10**9)
            prev_s = "" if prev is None else str(prev)
            return (str(absorber), str(ray), int(bounce or 0), prev_s, int(fi))

        items = sorted(stats.items(), key=sort_key)

        # 2) Tilldela ett heltals cluster_id per (absorber, ray, prev)
        id_map = {}
        next_id = 0

        def get_cluster_id(group_id):
            absorber, ray, _bounce, prev = group_id
            key = (str(absorber), str(ray), str(prev))
            nonlocal next_id
            if key not in id_map:
                id_map[key] = next_id
                next_id += 1
            return id_map[key]

        plane = plane.upper()
        if plane not in ("XY", "XZ", "YZ"):
            plane = "XY"

        metrics = {}

        for group_id, stat in items:
            absorber, ray, bounce, prev = group_id
            bounce_i = int(bounce or 0)
            cid = get_cluster_id(group_id)  # numeriskt och stabilt
            key = f"{cid}:{bounce_i}"  # worker förväntar "int:int"

            # Centralt innehåll från stats
            count = int(stat.get("count", 0) or 0)
            spread = stat.get("spread", {}) or {}
            radius3d = float(spread.get("3D", {}).get("radius", 0.0) or 0.0)

            # Rundhet (λ_min/λ_max) i valt plan
            cov_plane = spread.get(plane, {}).get("cov")
            roundness = roundness_score_from_cov(cov_plane) if cov_plane is not None else 0.0

            # Densitet – använd samma definition som i optimeringen (positiv och i [0,1])
            density = density_score(count, radius3d)

            # Centroider (hela dicten så aggregate kan plocka "3D")
            centroid = stat.get("centroid", {})

            metrics[key] = {
                "density": float(density),  # > 0 om klustret har vettig densitet
                "roundness": float(roundness),  # 0..1
                "count": count,
                "centroid": centroid,
                "spread": spread,  # inkluderar cov/radius/std för XY/XZ/YZ/3D
            }

        return metrics
