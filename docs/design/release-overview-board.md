# PPA-Profiler: Release Overview Board + Version Drill-Down/Compare

Adds the 6-panel PPA release dashboard **inside the Runs page, below the runs table**, backed by a multi-model version series (gem5 / slice / zebu / fogs perf models + full synthesis), plus per-version module- and signal-level drill-down with multi-version comparison. Per the confirmed choices: SPECint2006 12-suite, board metrics derived from existing tables, multi-version compare.

## Data model (multi-model series)

### B1. Schema — `backend/ppa/models.py`
- `Design` gains `model: str = "synth"` — provenance series: `synth` (full RTL synthesis), `gem5`, `slice`, `zebu`, `fogs`.
- `Project` defaults: `area_budget_mm2 = 2.0` (column already exists); `settings_json` gains `target_geomean: 1.45` (target line for panel 1; target efficiency = 1.45 / 2.0 score/mm2).

### B2. Sample data v3 — `backend/ppa/sample_data.py` + `backend/ppa/ingest.py`
- `VERSIONS` unchanged (v0.1..v0.16, same shas/notes). For each version generate 5 runs:
  - `model=synth`: existing 5 reports (unchanged formats — parsers untouched).
  - `model=gem5|slice|zebu|fogs`: one `specint.rpt` each (existing format, parser unchanged), carrying per-benchmark IPC + ratio@1GHz.
- Perf-model series semantics (deterministic, seeded per model+version): zebu = truth (current IPC model); gem5 = zebu * ~1.02 optimistic tilt; slice = zebu ±1%; fogs = zebu ±2%. All share the planted IPC events (v0.14 BTAC +2.4% IPC; MAC at v0.7 leaves IPC flat), so model gaps are visible but trends agree.
- Manifest entries gain `"model"`; `ingest_directory` creates one `Design` per (version, model) and sets `Run.stage` = `"synth"` for synth, `"sim"` for perf models.
- 80 runs total; demo DB rebuild required (`rm backend/data/ppa.db* && ppa.cli demo`).

### B3. Analysis — `backend/ppa/versioning.py`, `backend/ppa/analysis.py`
- `version_series(session, project_id=None, model="synth")` — filters `Design.model`; change-point detection stays synth-only (unchanged behavior). `list_runs` exposes `model` per run.
- New `overview_board(session)` returning one payload:
  - `geomean`: per model (incl. synth) geomean ratio across 16 versions + `target` scalar.
  - `perf_per_area`: synth `specint_score / area_mm2` per version + `target_eff = target_geomean / 2.0`.
  - `benchmarks`: `{benchmark: {model: [ratio per version]}}` (12 benchmarks x 4 perf models).
  - `ipc`: same shape keyed by IPC (bring-up trends).
  - `area_breakdown`: per version, stacked shares of the 4 categories + other: Frontend=`core_top/u_ifu`, Backend=`core_top/u_ex`, Memblock=`core_top/u_lsu`, L2 top=`core_top/u_l2`, other=`u_csr`+`u_clk` (stack sums to total).
  - `timing`: per version WNS, TNS, NVE (from metrics table).
  - `board`: per version: `max_logic_levels` (max `TimingPath.logic_depth`), `gated_pct` (`power.clock_gating_eff` from primepower), `core_vs_total` (core_top vs new `die_total` area row), `comb_share` (comb vs seq+macro+clock+buf of top row), `util_proxy` (core/die ratio — true site utilization has no synth source), `congestion_overflow: null` (no source at synth stage; placeholder).
- New `version_drill(session, version)`: change note + detected events at that version, depth-1 module table (area/power + delta vs previous synth version), top-10 worst signals with `path_id` (trace-ready).
- New `version_compare_multi(session, versions: list[str])`: per-module area/power matrix across selected versions with deltas vs the first selected; per-benchmark IPC deltas (synth-adjacent perf model = zebu); signal slack matrix for signals present across the selected versions.

### B4. API — `backend/ppa/main.py`
- `GET /api/overview` — full board payload (small: 16 versions x 5 models).
- `GET /api/version-drill?version=v0.5`.
- `GET /api/version-compare?versions=v0.3,v0.5,v0.8`.
- Existing endpoints untouched (timeline/change-points/correlations/search/trace keep working on the synth series).

## Frontend

### F1. State + client — `frontend/src/types.ts`, `api.ts`, `store.ts`
- Types: `OverviewData`, `VersionDrill`, `VersionCompare`; api fns `overview()`, `versionDrill(v)`, `versionCompare(vs)`.
- Store: `drillVersion: string | null`, `overviewVersions: string[]` (multi-select, cap 4), URL params `drill`, `ov`.

### F2. OverviewBoard panels 1-3 — new `frontend/src/views/OverviewBoard.tsx` (rendered by `RunExplorer.tsx` below the table + compare bar)
- P1 left: geomean lines per model (gem5 dashed, zebu solid, slice/fogs/synth own styles, target dotted markLine); right: perf/area (score/mm2) line with target-efficiency markLine.
- P2: benchmark chip selector (12) -> ratio trend chart (gem5 dashed + zebu solid per spec; slice/fogs toggleable) + per-release delta detail table for the selected benchmark.
- P3: bring-up IPC trends, same 12-selector, IPC on y-axis across the 4 perf models.

### F3. OverviewBoard panels 4-6
- P4: cumulative stacked bar of the 4 area categories (+ other) across release tags; red dashed markLine at 2.0 mm2 (from `area_budget_mm2`).
- P5: WNS + TNS lines with NVE bars on secondary axis (timing-closure progress).
- P6: 6-subplot grid: utilization proxy, core vs total area, max logic levels, gated registers %, congestion overflow % (placeholder tile annotated "requires place/route data"), comb vs non-comb distribution.

### F4. Drill-down + multi-version compare
- Clicking a version label (in P4/P5 x-axis or a version strip) sets `drillVersion` and opens the drill-down panel: change note, detected events, module table (area/power + delta, rows link to Area/Power explorers and trace drawer via existing `openTrace`), worst-signal table (links to Timing view / trace drawer).
- Per-version checkboxes build `overviewVersions`; compare panel shows module matrix with deltas vs earliest selected, per-benchmark IPC delta table, signal slack matrix; "Open in Compare view" populates the existing `compareIds` tray and navigates.

## Tests & verification
- New tests: overview payload shape (16 points/model, geomean ordering gem5 > zebu > fogs/slice within tolerance), area stacks sum to total area, board metrics present with congestion null; multi-model series isolation (`version_series(model="synth")` == 16, change points unaffected); version-drill content at v0.5/v0.7; multi-compare across 3 versions (first-version deltas zero, mac signals only v0.7+); API tests for the 3 new endpoints.
- E2E: rebuild demo DB (80 runs), browser-verify all 6 panels + drill-down + 3-way compare; existing 13 tests must keep passing (they target the synth series via tmp DBs).
- README: document the Runs-page board, the model series definition (gem5/slice/zebu/fogs/full/target), and derived-metric caveats (utilization proxy, congestion placeholder).

## Assumptions
- "slice" appears twice in the spec — treated as one series; "full" = the full synthesis series (existing v0.1..v0.16 synth runs); "target" = project-level target geomean (1.45) and the 2 mm2 constraint.
- Board metrics per the "derive from existing" decision: utilization rendered as core/die area ratio proxy (add a `die_total` top row to the sample area report, total = core / 0.62 utilization), congestion overflow has no synth-stage source and renders as an annotated placeholder.
- Panel 2/3 styling per spec: gem5 dashed, zebu solid; slice/fogs toggleable additions.
- Report formats and parsers stay unchanged (perf models emit the existing specint.rpt format); schema addition (`Design.model`) requires a demo DB rebuild.