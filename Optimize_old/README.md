
Optimizer väljer params
↓
EvaluationService:
  - uppdaterar Spreadsheet A
  - recompute FreeCAD
  - kör optikbänk
  - RayHits → Spreadsheet B
↓
Optimizer:
  - läser Spreadsheet B
  - analyserar data
  - väljer nästa params



Spreadsheet (C/D) ──► Optimizer (bounds)
                        │
                        ▼
                nya värden
                        │
                        ▼
Spreadsheet (B) ──► FreeCAD recompute
                        │
                        ▼
                 RayHits sheet
                        │
                        ▼
                HitScores sheet
                        │
                        ▼
                    metrics
                        │
                        └─── tillbaka till Optimizer



1) Komponent-/ansvars‑träd

NewOptimizeDialogDock (UI, main thread)
├─ QSlider "Målfördelning (densitet ↔ rundhet)"
│   ├─ sliderPressed → (pausa worker)
│   └─ sliderReleased → (skicka vikter + resuma worker)
├─ QListWidget "Parametrar att optimera"
├─ QPushButton "Starta" / "Stäng"
├─ QLabel status + sheetstatus
├─ EvaluationService (main thread)
│   ├─ apply params → Spreadsheet (SPREADSHEET_NAME)
│   ├─ recompute_doc(doc)
│   ├─ RayHitsCluster().execute(...) → RESULT_SHEET_NAME
│   └─ read_density_roundness_metrics(doc) → dict{cluster_id: {density, roundness}}
└─ QThread (arbets-tråd)
    └─ OptimizationWorker (QObject, i QThread)
        ├─ QTimer _tick (driver huvudloopen)
        ├─ Optimizer (policy: ask() → nästa parametrar)
        ├─ requestEvaluate(payload) → EvaluationService
        ├─ on_evaluated(metrics) → uppdatera OptimizationState
        ├─ progress(info) → UI
        ├─ finished() → UI
        ├─ update_weights(density, roundness) ← UI
        ├─ pause_due_to_slider() / resume_after_slider() ← UI
        └─ state (OptimizationState: cad_params, hitscores, global_score, history, lock, unused_candidates)

2) Signal-/slot‑träd (”vem pratar med vem”)

UI (NewOptimizeDialogDock)
├─ weightsChanged(density, roundness) ───────────────▶ OptimizationWorker.update_weights()
├─ sliderPaused() ───────────────────────────────────▶ OptimizationWorker.pause_due_to_slider()
├─ sliderResumed() ──────────────────────────────────▶ OptimizationWorker.resume_after_slider()
├─ (Starta) startar QThread ─────────────────────────▶ OptimizationWorker.start()
└─ (Stoppa) (helst via signal) ──────────────────────▶ OptimizationWorker.stop()/shutdown()

OptimizationWorker (i QThread)
├─ QTimer _tick.timeout ─────────────────────────────▶ _step()
├─ requestEvaluate({"params": ...}) ────────────────▶ EvaluationService.evaluate(payload)
├─ on_evaluated(metrics) ◀─────────────────────────── EvaluationService.evaluationReady(metrics)
├─ progress(info) ───────────────────────────────────▶ UI (statusuppdatering)
└─ finished() ───────────────────────────────────────▶ UI (stäng/återställ)

EvaluationService (main thread)
└─ evaluationReady(metrics) ─────────────────────────▶ OptimizationWorker.on_evaluated(metrics)



3) Sekvensflöde (ASCII)

[Starta]
UI: _start_worker()
  ├─ skapar QThread + OptimizationWorker
  ├─ kopplar signaler (weightsChanged, sliderPaused/Resumed, requestEvaluate, evaluationReady, progress, finished)
  └─ thread.start() → OptimizationWorker.start() → _tick.start(0)

[Iteration]
OptimizationWorker._step()
  ├─ if _stop: finished()
  ├─ if _paused_by_slider: _tick.start(25); return
  ├─ if _waiting_for_eval: return
  ├─ params = Optimizer.ask(state)
  ├─ state.cad_params = params
  ├─ _waiting_for_eval = True
  └─ emit requestEvaluate({"params": params}) → EvaluationService.evaluate(payload)

[Evaluate (main thread)]
EvaluationService.evaluate(payload)
  ├─ apply params → Spreadsheet
  ├─ recompute_doc(doc)
  ├─ RayHitsCluster().execute(...)
  ├─ metrics = read_density_roundness_metrics(doc)
  └─ emit evaluationReady(metrics) → OptimizationWorker.on_evaluated(metrics)

[Resultat tillbaka]
OptimizationWorker.on_evaluated(metrics)
  ├─ _waiting_for_eval = False
  ├─ state.hitscores = metrics
  ├─ state.global_score = min(weighted density+roundness per cluster)
  ├─ state.history.append((cad_params, metrics, global_score))
  ├─ emit progress({type:"step", ...}) → UI
  └─ if not _stop: _tick.start(0) else finished()

[Slider-drag]
UI: sliderPressed
  └─ emit sliderPaused() → OptimizationWorker.pause_due_to_slider()
       └─ _paused_by_slider = True → _step() bara skjuter upp tick (ingen evaluate)

UI: sliderReleased
  ├─ _emit_weights() → emit weightsChanged(d,r) → OptimizationWorker.update_weights()
  │    └─ uppdaterar state.weight_density/roundness + emit progress({type:"weights"})
  └─ emit sliderResumed() → OptimizationWorker.resume_after_slider()
       └─ _paused_by_slider = False → nästa _step() fortsätter

[Stoppa]
UI: Stoppa
  └─ (helst via signal) → OptimizationWorker.stop()
       ├─ _stop = True
       ├─ om inte _waiting_for_eval: emit finished()
       └─ annars avslutas vid nästa on_evaluated/step




4) Dataflöde i state (kort)

OptimizationState
├─ cad_params (senast skickade parametrar till CAD)
├─ hitscores (metrics från RESULT_SHEET_NAME)
├─ global_score (min viktad sum(density, roundness) över kluster)
├─ history: list of (cad_params, metrics, global_score)
├─ weight_density, weight_roundness (från UI)
├─ lock (för trådskydd)
└─ unused_candidates (LHS-kö, om finns)





ui_dialog.py

Skapar dock (UI) och knappar.
Slider:

sliderPressed → sliderPaused.emit() → Worker pausar.
sliderReleased → _emit_weights() + sliderResumed.emit() → Worker resumar.


Startar QThread + skapar OptimizationWorker, kopplar signaler, startar loop.

worker.py

QTimer‑driven huvudloop (_step).
Paus/resume via _paused_by_slider.
Be om nästa parametrar (optimizer.ask), emit requestEvaluate.
Ta emot evaluationReady, uppdatera state, emit progress, fortsätt så länge inte stoppad.

evaluation_service.py

Tar emot requestEvaluate.
Sätter Spreadsheet‑värden, kör recompute_doc, RayHitsCluster, läser metrics.
Emit evaluationReady(metrics).

optimizer.py

Genererar kandidatparametrar:

Först från state.unused_candidates (om någon).
Annars random inom bounds.

Översikt – komponenternas roller
NewOptimizeDialogDock (UI & styrning)

Visar listan med parametrar och en slider för viktning (densitet ↔ rundhet).
Startar/stannar optimeringen.
Håller state för UI och kopplar signaler mellan UI och worker.
Skickar vikter weightsChanged(density, roundness) till worker.
Skickar paus/resume när användaren drar i sliden (sliderPaused/sliderResumed).

OptimizationWorker (bakgrundslogik i egen QThread)

Kör huvudloopen för optimeringen via en QTimer (_tick), inte via en tight while-loop—det är bra för Qt:s eventloop.
Ber om utvärdering via requestEvaluate({"params": {...}}) till EvaluationService.
Mottar utvärderingsresultat via on_evaluated(metrics) och uppdaterar OptimizationState, räknar global score, och emitterar progress.
Respekterar paus: om _paused_by_slider = True så skjuter den fram nästa tick och gör inget (ingen ny evaluate) → UI blir mjuk när du drar sliden.

EvaluationService (utvärdering i huvudtråden)

Körs i main thread.
Applicerar CAD-parametrar på kalkylbladet (SPREADSHEET_NAME).
Kör recompute (recompute_doc(doc)).
Kör raytrace + klustring (RayHitsCluster().execute(...)) och läser metrics från RESULT_SHEET_NAME.
Skickar tillbaka metrics via evaluationReady(metrics) till worker.

Optimizer (policy för nästa kandidat)

Tar paramnamn och bounds.
Returnerar nästa kandidatlösning:

Först via LHS (om state.unused_candidates inte är tom), annars





NewOptimize/
├─ __init__.py
├─ ui_dialog.py             # Dock-widget (Qt GUI) 
├─ worker.py                # OptimizationWorker (QObject i QThread)
├─ optimizer.py             # BO/RBF‑logik, LHS, acquisition, nästa punkt
├─ objective.py             # Mål/kostnadsfunktion, aggregation av metrics
├─ spreadsheet_utils.py     # Läs/skriv param-gränser, alias, värden
├─ params_model.py          # Datamodell för parametrar (bounds, enhet, alias)
├─ logging_utils.py         # CSV/JSON‑loggning, tidstämpel, progress
├─ recompute_bridge.py      # Signaler/bridge för doc.recompute och mätdata
├─ commands.py              # FreeCAD‑kommandon (NewOptimizeDialogCmd m.fl.)
├─ config.py                # Konstanter, defaultvärden, env‑switchar
├─ tests/                   # (valfritt) enhetstester för rena moduler
└─ README.md                # kort översikt (hur kör man, vad gör vad)






Principer:

GUI (ui_dialog.py) ska vara tunn – bara widgets, knappar, signaler.
Worker (worker.py) kör loopen i bakgrundstråd och pratar med GUI via signals/slots.
FreeCAD‑doc/Spreadsheet‑ändringar sker i huvudtråd via en bridge (recompute_bridge) eller i dockan.
Optimeringslogiken (BO/RBF, LHS, acquisition) separeras in i optimizer.py så den går att testa utan FreeCAD.
Mål/metrics separeras in i objective.py (aggregering densitet↔rundhet).
Paramhantering (bounds, alias) centraliseras i params_model.py + spreadsheet_utils.py.
Loggning separeras så du kan slå av/på, byta format, buffra.



Vad som bör ligga i varje fil
ui_dialog.py  (GUI‑dockan)

Skapa NewOptimizeDialogDock.
Widgets: lista över parametrar, slider för densitet/rundhet, spinboxar för init/max, CSV‑val.
Start/Stop‑knapp (toggle).
Koppla weightsChanged från slider till worker.
Hantera worker‑signaler: progress, finished, error, requestApplyParams.
Metoder: selections(), current_weights(), _apply_params() (huvudtråd), _start_worker(), _request_stop().


Den kod jag gav dig tidigare passar här, men flytta ut OptimizationWorker till worker.py.


worker.py  (QThread‑worker, ingen GUI/FreeCAD‑touch)


class OptimizationWorker(QtCore.QObject):

start() – kör init‑sampling + BO/RBF‑loop utan att direkt röra FreeCAD.
update_weights(density, roundness) – trådsäker uppdatering av vikter.
stop() – cooperativt stopp.
Emitta: requestApplyParams(params_dict) till huvudtråden för dokumentändringar.
Emitta: progress(iter, info), finished(), error(msg).



Använd optimizer.py för att:

Generera LHS‑punkter (lhs(n, bounds)).
Uppdatera surrogat (RBF).
Välja nästa provpunkt (next_point(model, weights)).




optimizer.py  (ren algoritm – ingen GUI, ingen FreeCAD)

Funktioner/klasser:

lhs(n, bounds) – generera initiala punkter.
build_rbf(x, y, ...) – träna surrogatet (om du använder RBF).
acquisition(model, weights, ...) – t.ex. Expected Improvement/UC, anpassad mot dina metrics.
next_point(model, bounds, weights) – välj nästa punkt.
update_model(model, x_new, y_new) – uppdatera efter varje mätning.




Håll detta rent (bara numpy/scipy). Lätt att enhetstesta.


objective.py  (metrics och aggregering)

Funktioner:

compute_metrics(rows_or_geometry) -> {"density": ..., "roundness": ...}
aggregate(metrics, weights, agg="max"|"weighted_sum") -> float
normalize_metrics(metrics, ranges) – om du behöver skala.


Beskriv tydligt hur densitet/rundhet definieras och mäts.


spreadsheet_utils.py  (FreeCAD Spreadsheet I/O)

read_param_bounds(ss) -> [(name, row, (lo,hi), unit, base_val)]
read_current_params(ss) -> {name: value}
apply_params(ss, params_dict) – sätt celler/alias.
Hjälpmetoder för alias vs cellreferens (A1, B2…).


Används i dockans _apply_params() (huvudtråd).


params_model.py  (datamodell, typing)

Param = NamedTuple/Dataclass(name, lo, hi, unit, base, alias)
ParamSet – samling med validering, klampning inom bounds, konverteringar (enhet → modellvärde).
Hjälper optimizer.py att få bounds i rätt format.


logging_utils.py  (loggning till CSV/JSON)

append_csv(path, dict_row) – robust skrivning med header auto‑skapad.
append_jsonl(path, dict_row) – en rad per iteration.
ProgressLogger – klass med log_iteration(i, params, metrics, weights, timestamp).


Om du loggar i huvudtråd får du “sanna” värden efter recompute. Om du loggar i worker, logga bara algoritmisk progress (inte doc).


recompute_bridge.py  (synk/kvittens mellan worker ↔ dokument)

Signal/Slot‑mönster:

apply_params(params) → huvudtråd sätter i Spreadsheet + doc.recompute().
(valfritt) applied(params, metrics) – kvittens tillbaka till worker.


Kan erbjuda en liten RequestQueue om du vill batcha uppdateringar.


Du kan också hålla detta i dockan om du vill vara minimalistisk; en separat fil gör det tydligare.


commands.py  (FreeCAD‑kommandon)

NewOptimizeDialogCmd() – skapa/visa dockan.
(Valfritt) Andra kommandon för att starta med presets, öppna loggar etc.


Flytta ditt nuvarande NewOptimizeDialogCmd() hit och låt ui_dialog bara definiera klassen.


config.py

Defaults: DEFAULT_INIT_SAMPLES = 10, DEFAULT_MAX_ITERS = 20, slider default 80/20.
Feature‑flaggor: USE_JSON_LOG = False, RBF_EPS = 1.0.
Paths (om du vill ha fallback).


tests/

test_optimizer.py – nästa punkt, RBF‑uppdatering.
test_objective.py – aggregationen för vikter.
test_logging_utils.py – CSV/JSONl.
(FreeCAD‑beroende tester kan vara svårare; håll rena moduler testbara utan FreeCAD.)