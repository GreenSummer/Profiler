# PPA-Profiler v2: Version-Centric PPA Analysis with AI

Replaces the 12-config sweep demo with a 16-version RTL series (one config, stage=synth) and adds the four missing capabilities: version-axis analysis, statistical change-point/outlier detection, perf-PPA correlation, and plot-to-raw-data tracing with signal search. Parsers and report formats are unchanged; all existing views keep working on any run set.

## Backend

### B1. Schema evolution — `backend/ppa/models.py`
- `Design` gains `version: str` ("v0.4") and `change_note: str` ("added bypass network"); one Design row per version; `Run.stage` now "synth".
- `RawReport` gains `content: str` (full report text stored in DB — enables trace and search without files on disk).
- Typed rows gain source provenance: `AreaRow`, `PowerRow`, `TimingPath`, `PerfRow` each gain `src_line: int` (1-based line in the source report).
- New `ChangeEvent` table: `(id, project_id, from_run_id, to_run_id, metric_key, scope_path?, delta_pct, magnitude, method: step|spike|trend, severity, note)` — persisted output of the detector.

### B2. Parser line provenance — `backend/ppa/parsers/{rtla,primepower,specint}.py`
- Each parsed record carries the line number where its text block starts; `ingest.py` stores it in `src_line` and stores report text in `RawReport.content`. Report file formats unchanged.

### B3. Sample data v2 — `backend/ppa/sample_data.py` (rewrite)
- 16 versions v0.1..v0.16: weekly dates, distinct git shas, change_note each; single config; deterministic ±0.5% noise on all metrics.
- Planted events (each with a plausible note):
  - v0.5: total area +8%, u_ex +42% ("added full bypass network")
  - v0.7: WNS −80ps cliff, critical path moves to u_mul, logic depth grows ("added MAC instruction")
  - v0.9: power +10%, clock-gating efficiency collapses to ~55% ("CG insertion disabled by script bug")
  - v0.12: leakage share climbs ~2x over 3 versions ("VT mix shifted to LVT in synth script")
  - v0.14: IPC +3%, area +1.5% — the "good trade" the net-score view should bless ("BTAC entries 512→2k")
- `manifest.json` v2 entries carry `version`, `sha`, `date`, `change_note`.

### B4. Version analysis engine — new `backend/ppa/versioning.py`
- `version_series(project_id)`: ordered versions with FOMs + change notes.
- `detect_change_points(series, metric_key)`: robust step detection — version-to-version deltas vs median + k·MAD (k configurable in `Settings`); classify step/spike/trend; module attribution via depth-2 waterfall deltas between the two runs; persists `ChangeEvent`.
- `correlations(series)`: Pearson r between perf (score, IPC, Fmax) and PPA (area, power, WNS, leakage share) across versions, plus top module-level correlations (module power/area vs score). Pure Python, no new deps.
- `signal_search(query)`: substring match over timing startpoint/endpoint across all runs (returns slack per version — a signal history) + raw report text scan (returns file + line).
- `trace_to_source(run_id, kind, scope_path | path_id)`: exact raw report lines backing a plotted value, via `src_line` + `RawReport.content`.

### B5. API — `backend/ppa/main.py`
- `GET /api/versions` — series + FOMs + change notes
- `GET /api/change-points` — all detected ChangeEvents
- `GET /api/correlations` — perf×PPA matrix + module correlations
- `GET /api/search?q=` — signals, modules, report-text hits (file + line)
- `GET /api/trace` — raw lines for a value
- `ppa.cli demo` regenerates the fresh v2 DB (tracked `backend/data/ppa.db` is re-committed).

### B6. Findings integration — `backend/ppa/rules.py`, `rules_pack.yaml`
- Change points above severity thresholds surface in the Diagnosis view under new category `version_change` (reuse the Finding workflow: ack/fix/feedback).

### B7. AI layer — `backend/ppa/ai/{tools,context_pack,agent}.py`
- New tools: `get_version_series`, `get_change_points`, `get_correlations`, `search_signals`, `trace_to_source` (total ~14 tools; compact small-model set stays `{get_context_pack, list_runs}`).
- Context pack v2 embeds version-series summary + top change points + headline correlations, so the compact path still answers version questions.
- Offline analyst patterns: "what changed in/after v0.5", "why did area/power/WNS jump", "show signals matching …", "how does power correlate with score".

## Frontend

### F1. Version Timeline (new Overview landing view)
- ECharts multi-line chart (area / power / WNS / score) across versions; change points as marked points with vertical markers; hover shows change note; click a version pair → Compare. Event table below: metric, delta, severity, attribution, note.

### F2. Global search (top bar, debounced)
- Grouped results: modules, timing signals (slack history per version), report-text matches with file + line. Click navigates: module → explorer, signal → timing view filtered, text match → trace drawer.

### F3. Correlations view
- Perf×PPA heatmap, scatter + fit line for a chosen pair across versions, module-correlation table ("which module's power tracks score").

### F4. Raw-data trace drawer
- "⌖ source" affordance on rows/paths in Area/Power/Timing explorers and Compare waterfalls → drawer showing the exact report lines (highlighted via src_line).

### F5. Compare view: version mode
- When runs are adjacent versions: change-note header + module attribution + trace links.

### F6. Store / URL state — `frontend/src/store.ts`, `api.ts`, `types.ts`
- Add version-pair selection, search query, trace drawer state to URL-synced store.

## Tests & verification — `backend/tests/`
- New: version series (16 versions, FOM sanity), change-point detection catches all 5 planted events with no false alarms on noise, correlation signs match planted relations, signal search finds planted signals with correct run/line, trace returns exact lines, API tests for all 5 new endpoints, offline-analyst version patterns.
- E2E: rebuild demo, all views against v2 data, README updated (new views, version workflow, signal definition).

## Assumptions
- "Signal" = timing report startpoint/endpoint names + names in raw report text (only signal-level source in RTLA/PrimePower/SPECint reports).
- Fresh demo DB replaces the config sweep; schema additions require re-ingest (`ppa.cli demo`).
- No new Python/JS dependencies; all statistics in pure Python, charts in existing ECharts.