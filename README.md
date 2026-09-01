# PPA-Profiler

A web-based Power/Performance/Area analysis workbench for RISC-V SoC designers. It ingests
RTL-Architect (RTLA) area/timing reports, PrimePower vectorless power reports, and SPECint 2006
performance reports into SQLite, computes cross-domain figures of merit, diagnoses abnormal
results with a deterministic rule engine, and offers an AI assistant that explains the data —
without ever inventing a number. v2 adds the version axis: statistical change-point detection
across an RTL version series, perf×PPA correlations, signal search, and plot-to-raw-data
tracing.

## Why it exists

Three things spreadsheets and generic BI tools cannot do:

1. **Net performance attribution** — SPECint score = SPECint/GHz × Fmax. The profiler decomposes
   every change into an IPC (microarchitecture) part and a frequency (physical) part, so an IPC
   gain that costs frequency is caught as the net loss it is.
2. **Cross-tool attribution on hierarchy paths** — power paths from PrimePower are joined to
   area paths from RTLA and to critical timing paths through one canonical module hierarchy.
   "Which module is expensive everywhere?" is one view, not a week of Excel.
3. **Memory** — baselines, deltas vs baseline, Pareto frontiers, and budget overruns are
   persistent, so the analysis context survives between sessions.
4. **The accumulation story** — a single-config RTL series (v0.1..v0.16, one change note per
   week) is where regressions actually happen. Robust change-point detection (median + k·MAD
   over version-to-version deltas) separates real events from ±0.5% noise, attributes each jump
   to a module, and traces every plotted number back to the exact raw report line.

## Quickstart

```bash
# 1. Backend
cd backend
python3 -m venv ../.venv
../.venv/bin/pip install -r requirements.txt

# 2. Demo data: 16-version RTL series (v0.1..v0.16, single config) x 5 provenance
#    series (full synth + gem5/slice/zebu/fogs perf models = 80 runs),
#    generates sample_runs/ and ingests into backend/data/ppa.db
../.venv/bin/python -m ppa.cli demo

# 3. Frontend
cd ../frontend
npm install
npm run build        # tsc + vite -> dist/

# 4. Serve API + UI at http://localhost:8000
cd ../backend
../.venv/bin/python -m ppa.cli serve
```

The demo series deliberately contains the interesting cases: **v0.5** (bypass network → area
+8%, attributed to `u_ex`), **v0.7** (MAC instruction, un-retimed → WNS −120 ps cliff and score
spike, recovered at v0.8), **v0.9** (clock-gating insertion disabled by a script bug → gating
efficiency −23 points, power +10%), **v0.11–v0.13** (LVT scope creep → leakage share ×2 as a
3-version trend), and **v0.14** (BTAC 512→2k, the "good trade": +2.9% score for +1.9% area).

During frontend development you can instead run `npm run dev` (Vite on :5173, proxying `/api`
to :8000).

## The 13 views

| # | View | Answers |
|---|------|---------|
| V1 | Version Timeline | How do area/power/WNS/score evolve across versions? Which transitions are statistically real change points, and what RTL change caused each? |
| V2 | Runs | What runs exist, how do they rank, what changed per column vs baseline? Below the table: the **Release Overview Board** (6-panel PPA dashboard) plus per-version drill-down and multi-version compare |
| V3 | Scorecard | Budgets, KPIs with deltas, the four domains on one page |
| V4 | Compare | Config diff → net-score decomposition → area/power delta waterfalls; adjacent versions get the change-note header + detected-changes panel |
| V5 | Design Space | Pareto frontier (score vs area/power), parallel coordinates over configs |
| V6 | Correlations | Which perf metrics track which PPA costs across versions? (perf×PPA heatmap, scatter + fit line, per-module table) |
| V7 | Area Explorer | Treemap drill-down, comb/seq/macro/buf splits, Δ-vs-baseline coloring |
| V8 | Power Explorer | Internal/switching/leakage by module, clock share, CG efficiency, density |
| V9 | Timing Explorer | Slack histogram, critical-module leaderboard, worst paths, logic depth, signal-name filter |
| V10 | Performance Explorer | Per-benchmark IPC and SPECratio@1GHz vs baseline, MPKI, mispredicts |
| V11 | Hotspot Matrix | Area share × power share × timing criticality bubble chart (cross-tool) |
| V12 | Diagnosis | Rule findings with evidence, ack/fix workflow, feedback, "ask AI" — including `version_change` findings from the change-point detector |
| V13 | Ingest & Admin | Parse status per report (SHA-256 + parser version), rule pack, CLI help |

The top bar carries a **global search** (modules, timing signals with per-version slack history,
raw report text with file + line). Clicking navigates: module → Area view, signal → Timing view
filtered, text hit → trace drawer. Every plotted row/path in the explorers and Compare has a
**⌖ source** button that opens the raw-data trace drawer showing the exact report lines behind
the value (highlighted via stored line provenance).

Selection context is global (run, baseline, comparison tray, version pair, search query, trace
target) and mirrored into the URL hash, so any analysis state is shareable.

## Version-centric workflow

1. **Series** — one Design row per version (`version`, `sha`, `date`, `change_note` in the
   manifest); the Version Timeline plots headline metrics across v0.1..v0.16 with detected
   change points marked and the change note on hover.
2. **Detection** — `versioning.py` computes version-to-version deltas per metric and flags
   outliers with a robust z-score (median + k·MAD). Each event is classified as **step**
   (persistent), **spike** + **recovery** (reverted), or **trend** (multi-version drift), and
   attributed to the biggest contributing module (depth-2 waterfall delta) or the owner of the
   new worst timing path. High/medium events also surface in Diagnosis as `version_change`
   findings with the full Finding workflow.
3. **Correlation** — Pearson r between perf (score, SPECint/GHz, Fmax) and PPA (area, power,
   WNS, leakage share, CG efficiency) across versions, plus per-module area/power vs score
   ("which module's power tracks the score?").
4. **Trace** — every parsed row stores its source line (`src_line`) and every raw report is
   stored verbatim in the DB (`RawReport.content`), so any plotted value traces back to the
   exact report lines — no report files needed on disk after ingest.
5. **Signals** — a signal is a timing-report startpoint/endpoint name (the only signal-level
   source in RTLA/PrimePower/SPECint reports). Search a name to get its slack history across
   versions, plus raw-text matches with file + line.

## Release Overview Board

The Runs page renders, below the runs table, a 6-panel release dashboard backed by the
multi-model version series, plus per-version drill-down and multi-version comparison:

1. **Geomean trend & performance per area** — geomean SPECratio@1GHz per provenance series
   vs the project target (`target_geomean`), and synth score/mm² vs the target efficiency
   (target geomean ÷ area budget).
2. **Benchmark performance trend** — per-benchmark SPECratio across releases with a 12-suite
   chip selector; gem5 dashed vs zebu solid, slice/fogs toggleable, plus a per-release delta
   table (Δ vs previous, gem5-vs-zebu model gap).
3. **Bring-up IPC trends** — same selector, IPC on the y-axis across the perf models.
4. **Area breakdown** — stacked Frontend/Backend/Memblock/L2 top/Other shares per release
   with the area-budget mark line (Frontend = `u_ifu`, Backend = `u_ex`, Memblock = `u_lsu`,
   L2 top = `u_l2`, Other = `u_csr` + `u_clk`).
5. **Timing closure** — WNS/TNS lines with NVE violating-endpoint bars per release.
6. **PPA board** — six synthesis-health tiles: utilization proxy, core vs die area, max
   logic levels, gated-register %, congestion overflow (placeholder), comb vs non-comb share.

**Provenance series** — every version has five runs keyed by `Design.model`: `synth` (full
RTL synthesis, the only series driving change-point detection, rules baselines and PPA
panels), and the perf models `gem5`, `slice`, `zebu` (emulation truth) and `fogs` — each a
`specint.rpt` carrying per-benchmark IPC + ratio. Model runs have `stage = sim`; the rule
engine never compares them against the synth baseline (their systematic bias is the point:
gem5 carries a +2% optimism, slice ±1%, fogs ±2% noise around zebu).

**Drill-down & compare** — clicking a version (chart category axis or the release strip)
opens the drill-down: change note, detected change events, the module table with area/power
deltas vs the previous release (rows link to the Area/Power explorers and the ⌖ trace
drawer), and the worst signals with trace-ready path ids. Checking versions (cap 4) builds
the multi-version compare: module area/power matrices with deltas vs the earliest selected
release, per-benchmark IPC deltas (zebu), and the slack matrix of signals present in every
selected version; "Open in Compare view" hands the runs to the existing Compare tray.

Derived-metric caveats: **utilization** is rendered as a core/die area-ratio proxy (the
demo area report carries a `die_total` row = core ÷ 0.62 utilization; true site utilization
has no synthesis-stage source), and **congestion overflow** has no source at the synth stage
and renders as an annotated placeholder.

## AI assistant

- **On-prem only**: talks to any OpenAI-compatible endpoint — Ollama and vLLM by default
  (`PPA_AI_BASE_URL`, `PPA_AI_MODEL`).
- **Trust contract**: the model never computes. It selects typed, read-only tools (14:
  `get_context_pack`, `compare_runs`, `get_version_series`, `get_change_points`,
  `get_correlations`, `search_signals`, `trace_to_source`, ...); every number in an answer
  comes verbatim from deterministic Python output, and every claim carries a citation chip
  (`run · source`).
- **Text-to-SQL is deliberately rejected**: hierarchy tables roll children into parents, so
  LLM-written SQL double-counts area and power silently. The typed tool layer makes that bug
  structurally impossible.
- **Deterministic fallback**: if no LLM is reachable — or the installed model is below the
  tool-calling size threshold (`PPA_AI_MIN_MODEL_B`, default 4B) — a built-in analyst answers
  common question shapes (overview / compare / findings / "what changed in v0.5" / "why did
  power jump" / "how does power correlate with score" / "show signals matching …") from
  context packs and the version engine, instantly, with citations and view proposals. The
  badge in the top bar always tells you which mode you're in.
- **View proposals**: answers can end with a one-click "open this view" button that navigates
  the UI to the data being discussed.

## Open-source decisions

Adopted (all MIT/Apache/BSD-class): FastAPI + uvicorn, SQLModel/SQLAlchemy + SQLite (WAL),
Pydantic v2 + pydantic-settings, httpx (thin OpenAI-compatible client — no LLM framework),
Typer + rich, PyYAML (rule pack), React 18 + TypeScript + Vite, Apache ECharts (treemap,
parallel coordinates, waterfall, scatter, histogram in one library), TanStack Query/Table,
Zustand, Tailwind CSS v4, Ollama/vLLM as the model server.

Standard adopted: **OpenROAD METRICS2.1** as the metric naming/semantics reference for future
flow interoperability.

Evaluated and rejected:

| Candidate | Reason |
|---|---|
| Vanna | Its core idea (curated context) is adapted into context packs; the library itself generates SQL — double-counting hazard on hierarchical tables |
| Chat2DB | License drift; general SQL chat client, not embeddable domain logic |
| pandas-ai | Data lives in SQLite, not pandas; possible future ad-hoc layer |
| Superset / Metabase / Grafana | Generic BI cannot express net-score decomposition, Pareto frontiers, ROI, or cross-tool joins — that's the product |
| LiteLLM | One endpoint needed; ~100 lines of owned httpx beat a framework dependency |
| LangChain / LlamaIndex | The trust contract needs a small, controlled tool loop, not an agent framework |
| sqlite-vec | At tens-of-runs scale, precomputed digests + FTS5 suffice |

Principles: thin over thick, domain semantics are the moat, permissive and boring dependencies.

## Ingesting your own reports

A run directory holds the five reports; the root holds a `manifest.json`:

```
my_series/
  manifest.json          # [{"label": "v0.1", "version": "v0.1", "sha": "8f2c1ad",
                         #   "date": "2026-05-04", "change_note": "initial bring-up",
                         #   "params": {...}, "corner": "tt_0p80v_25c",
                         #   "stage": "synth", "order": 0}, ...]
  v0.1/
    rtla_area.rpt        # RTLA hierarchical area report
    rtla_timing.rpt      # RTLA timing report (groups, histogram, paths)
    rtla_qor.rpt         # RTLA QoR summary
    primepower.rpt       # PrimePower hierarchical vectorless power
    specint.rpt          # SPECint2006 per-benchmark results
```

```bash
../.venv/bin/python -m ppa.cli ingest my_series --project my-project
../.venv/bin/python -m ppa.cli check-format my_series/v0.1/rtla_area.rpt   # parser dry-run
```

Path canonicalization is the hard part and is handled: RTLA prints `/`-separated indented
hierarchies, PrimePower prints `.`-separated paths with bracketed generate blocks
(`gen_alu[0]`); both map to one canonical form (`core_top/u_ex/gen_alu_0/u_alu`) so area,
power, and timing join per module. A data-quality rule (`DQ_*`) fires when paths don't match.

Parsers are versioned per report kind; every raw report is content-hashed (SHA-256) at ingest
and stored verbatim in the DB, so provenance is auditable from V13 and the trace drawer /
search work without the original files on disk.

## Diagnosis rules

`backend/ppa/rules_pack.yaml` — 19 rules in 6 categories (timing, area, power, performance,
cross-domain, data quality). Thresholds are data, not code: designers tune the YAML and
re-ingest. Severity escalation and title templates are in the same file. 👍/👎 feedback on
findings is persisted to guide future threshold tuning. On top of the pack, the change-point
detector emits `version_change` findings (`VC_CHANGE_POINT`) for high/medium events — same
Finding workflow (ack / fix / feedback) as the YAML rules.

## Configuration

All settings are environment-overridable with the `PPA_` prefix
(`backend/ppa/config.py`):

| Variable | Default | Meaning |
|---|---|---|
| `PPA_DB_PATH` | `backend/data/ppa.db` | SQLite database |
| `PPA_AI_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible endpoint |
| `PPA_AI_MODEL` | `qwen2.5:32b-instruct` | Model name |
| `PPA_AI_MIN_MODEL_B` | `4.0` | Below this size the agent stays deterministic |
| `PPA_AI_MAX_TOOL_ROUNDS` | `6` | Tool-loop round budget |
| `PPA_FRONTEND_DIST` | `frontend/dist` | Built SPA served by the backend |

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest tests/ -q
```

Covers canonicalization, all parsers (with line provenance, incl. the `die_total`
utilization row), figures of merit, decomposition, Pareto, end-to-end ingest + rule firing
on the 80-run multi-model series (all 5 planted events caught, zero false alarms on noise
transitions, perf-model runs isolated from synth baselines), version series, change-point
detection and classification (step/spike/recovery/trend + module attribution), correlations,
the release overview board payload (shapes, model ordering, area stacks, board metrics),
per-version drill-down and multi-version compare, signal search (slack history per version),
trace-to-source (area/power/timing/perf + raw-text line mode), the API including the version
and overview/drill/compare endpoints, and the AI offline analyst patterns (hermetic —
no LLM required).

## Repository layout

```
backend/ppa/        FastAPI app, parsers, canonicalize, metrics, ingest, rules,
                    analysis views, versioning (series, change points,
                    correlations, signal search, trace), AI layer (context
                    packs, tools, agent, llm)
backend/tests/      pytest suite
frontend/src/       views/ (13 views), components/ (trace drawer, search),
                    ai/ (ChatPanel, badge), store, api client
sample_runs/        synthetic 16-version series + manifest.json (fixtures & demo)
```

## Known limitations

- Vectorless power is good for relative comparison, not signoff — the UI says so where it matters.
- "Signal" means timing-report startpoint/endpoint names plus names in raw report text; RTL
  signal-level power attribution is not in these report formats and is future work.
- The synthetic series models one core at one corner; multi-corner support is future work.
- Metric names align with METRICS2.1 concepts but full export compatibility is untested.
