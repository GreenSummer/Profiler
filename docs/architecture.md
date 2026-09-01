# PPA-Profiler — Architecture & Design Document

> How the system is structured, how it is implemented, how data is stored,
> what tables exist in the database, and which technologies are used.
> Companion documents: [`design-proposal.md`](design/design-proposal.md) (original
> product proposal), [`v2-version-centric-analysis.md`](design/v2-version-centric-analysis.md),
> [`release-overview-board.md`](design/release-overview-board.md).

---

## 1. What it is

PPA-Profiler is a **RISC-V Power-Performance-Area analysis workbench**. It ingests the
text reports produced by EDA flows (RTLA area/timing/QoR, PrimePower, a SPECint
performance report) for a series of RTL versions, stores every parsed value with
**line-level provenance** back to the raw report text, and layers analysis on top:
figures of merit, rule-based diagnosis, version-series change-point detection,
cross-domain correlations, and a 6-panel release overview board backed by a
multi-model provenance series (full synthesis + four perf models).

Core design principles:

1. **Traceability** — every plotted number resolves to the exact lines of the
   original report (raw text stored verbatim in the DB + 1-based `src_line` on
   every parsed row).
2. **Version-centric** — the primary axis is the RTL version series
   (v0.1…v0.16), not individual runs; changes between versions are detected
   statistically, not eyeballed.
3. **Hybrid metrics storage** — typed tables for the four report domains
   (area/power/timing/perf), plus a tall `Metric` table that absorbs anything
   without a typed home (FOMs, summary scalars).
4. **Offline-first AI** — the assistant runs fully deterministic pattern answers
   when no on-prem LLM is reachable; when one is, it drives a read-only tool loop.

---

## 2. Tech stack

### Backend (`backend/`, Python ≥ 3.10)

| Concern | Technology | Notes |
|---|---|---|
| Web API | **FastAPI 0.115** + **Uvicorn** | ~25 JSON endpoints under `/api/*`; also serves the built frontend from `frontend/dist` |
| ORM / schema | **SQLModel 0.0.22** (SQLAlchemy under the hood) | all tables are `SQLModel, table=True` classes in `ppa/models.py` |
| Database | **SQLite in WAL mode** | single file `backend/data/ppa.db`; no external DB service; the demo DB is tracked in git on purpose |
| Validation / settings | **Pydantic v2** + **pydantic-settings** | `ppa/config.py`: every setting overridable via `PPA_*` env vars |
| Rule pack config | **PyYAML** | rule thresholds/packs loadable from YAML |
| CLI | **Typer** + **Rich** | `python -m ppa.cli demo` / `serve` / … |
| AI client | **httpx** | thin OpenAI-compatible wrapper (`ppa/ai/llm.py`) for **Ollama** (`http://localhost:11434/v1`, default model `qwen2.5:32b-instruct`) or **vLLM** — fully on-prem, no cloud calls |
| Tests | **pytest** + `fastapi.testclient` | hermetic: temp DBs, LLM probe monkeypatched off |

### Frontend (`frontend/`, TypeScript)

| Concern | Technology | Notes |
|---|---|---|
| Framework | **React 18** + **TypeScript 5.6** | strict typing of API payloads in `src/types.ts` |
| Build | **Vite 6** | `npm run build` = `tsc --noEmit && vite build` → `dist/`, served by FastAPI |
| Server state | **@tanstack/react-query 5** | one query per endpoint, keyed by run/version |
| Client state | **zustand 5** | single `useApp` store; state mirrored into the **URL hash** (`#view=…&run=…&drill=…&ov=…`) so any analysis state is shareable |
| Charts | **ECharts 5** via `echarts-for-react` | wrapped in `src/components/EChart.tsx` (dark theme, click-event plumbing) |
| Styling | **Tailwind CSS 4** | dark slate theme, shared primitives in `src/components/ui.tsx` (Card, Table, Delta, SevBadge, fmt…) |

### Sample data

`backend/ppa/sample_data.py` deterministically generates a realistic 16-version
demo series (`sample_runs/`, 80 run directories) with five planted engineering
events (bypass network, un-retimed MAC, clock-gating bug, LVT drift, BTAC resize).
All randomness is seeded with stable integer arithmetic (never Python's salted
`hash()`), so rebuilds are byte-identical.

---

## 3. System architecture

```
                 ┌────────────────────────────────────────────────────────┐
                 │  Report files on disk (sample_runs/ or your own)       │
                 │  rtla_area.rpt · rtla_timing.rpt · rtla_qor.rpt        │
                 │  primepower.rpt · specint.rpt · manifest.json          │
                 └──────────────────────┬─────────────────────────────────┘
                                        │  ppa.cli demo / ingest
                                        ▼
┌──────────────────────── INGEST PIPELINE (backend/ppa) ────────────────────────┐
│ ingest.py     manifest → Project/Design(version,model)/Config/Corner/Run      │
│ parsers/*     deterministic text parsers (one per report kind, versioned)     │
│ canonicalize  tool paths → canonical 'core_top/u_ex/…' scope paths            │
│ metrics.py    figures of merit (Fmax, SPECint score, score/mm², mW/MHz…)      │
│ rules.py      rule engine → Findings (timing/area/power/perf/xdom/DQ)         │
│ versioning.py change-point detection over the synth series → ChangeEvents     │
└──────────────────────────────────────┬────────────────────────────────────────┘
                                       ▼
                 ┌────────────────────────────────────────────┐
                 │  SQLite (WAL)  backend/data/ppa.db         │
                 │  identity · raw reports · typed rows ·     │
                 │  tall metrics · analysis · AI/workflow     │
                 └──────────────────────┬─────────────────────┘
                                        ▼
┌──────────────────────── API LAYER (main.py, FastAPI) ─────────────────────────┐
│ runs/scorecard/compare/design-space · area/power/timing/perf/hotspot          │
│ findings(+ack/feedback) · ingest-status · rules                               │
│ versions/change-points/correlations/search/trace        (v2 version series)   │
│ overview/version-drill/version-compare                  (v3 overview board)   │
│ ai/status · ai/chat                                     (assistant)           │
└──────────────────────────────────────┬────────────────────────────────────────┘
                                       ▼
┌──────────────────────── FRONTEND (React SPA) ─────────────────────────────────┐
│ api.ts (typed fetch) → react-query cache → 13 views                           │
│ zustand store (run, baseline, compare tray, version pair, drill, ov, trace)   │
│   ⇄ URL hash sync — every state shareable as a link                           │
│ TraceDrawer: any ⌖ src button → /api/trace → highlighted raw report lines     │
└───────────────────────────────────────────────────────────────────────────────┘
```

Backend module map:

| Module | Responsibility |
|---|---|
| `ppa/models.py` | the entire DB schema (SQLModel tables, see §5) |
| `ppa/db.py` | engine creation (`PRAGMA journal_mode=WAL`), `init_db`, session dependency |
| `ppa/parsers/base.py`, `common.py` | parser dataclasses (every row carries `src_line`), shared regex/number helpers |
| `ppa/parsers/rtla.py` | RTLA area report (hierarchy indent-based), timing report (8-line path blocks), QoR report |
| `ppa/parsers/primepower.py` | power hierarchy (internal/switching/leakage), clock-gating efficiency, categories |
| `ppa/parsers/specint.py` | per-benchmark IPC / ratio@1GHz / MPKI table, geomean ratio |
| `ppa/canonicalize.py` | tool-specific hierarchy paths → one canonical form (`u_ex.gen_alu[0].u_alu` → `u_ex/gen_alu_0/u_alu`), owner-module resolution |
| `ppa/ingest.py` | end-to-end: manifest → rows in DB; stores raw text + SHA-256 + parser version per report; applicable-report filtering per model |
| `ppa/metrics.py` | figures of merit, net-score decomposition (IPC vs Fmax trade), Pareto front |
| `ppa/rules.py` | rule engine (`RunFacts` context per run) → `Finding` rows; model-aware (perf-model runs never compare against the synth golden baseline) |
| `ppa/versioning.py` | version series, change-point detection (robust z-score, step/spike/trend/recovery classification, module attribution), correlations, signal search, trace-to-source, **overview board / drill-down / multi-compare** |
| `ppa/analysis.py` | per-run view queries: list_runs, scorecard, compare, area/power/timing/perf trees, hotspot, findings workflow |
| `ppa/main.py` | FastAPI app: all endpoints + static serving of `frontend/dist` |
| `ppa/ai/` | `llm.py` (OpenAI-compatible httpx client + probe), `tools.py` (read-only tool definitions), `context_pack.py` (DB → prompt context), `agent.py` (tool loop + deterministic offline patterns) |
| `ppa/sample_data.py` | deterministic demo generator (v3: 16 versions × 5 provenance series) |
| `ppa/cli.py` | Typer CLI: `demo` (generate + ingest), `serve` (uvicorn), etc. |

---

## 4. How data gets in: the ingest pipeline

1. **Manifest-driven.** `sample_runs/manifest.json` lists run directories with
   `label`, `version`, `model`, `stage`, `order`, `change_note`, `sha`, `params`.
   `ingest_directory()` walks it in `order` and creates one `Design` per
   `(version, model)` pair.
2. **Parse.** For each run directory, every applicable report is parsed by its
   dedicated parser (parsers are versioned; `parser_version` is stored per
   report). Perf-model runs (`gem5/slice/zebu/fogs`) only carry `specint.rpt`;
   missing synth reports there are expected, not a data-quality error.
3. **Raw preservation.** The full report text is stored verbatim in
   `RawReport.content` with `sha256`, byte size, parse status and warnings —
   the report files are no longer needed on disk after ingest.
4. **Canonicalize.** Hierarchy paths from different tools (dots, backslashes,
   `gen_` blocks, array indices) are normalized to one canonical slash form;
   the original spelling is kept in `ScopeAlias` so any tool path can be joined.
5. **Typed rows + tall metrics.** Area/power/timing/perf rows go to their typed
   tables (each with `src_line`); derived and summary values (FOMs, WNS/TNS/NVE,
   clock-gating efficiency, leakage share…) go to the tall `Metric` table as
   `key`/`value`/`unit`/`scope_path`.
6. **Analysis at ingest.** Figures of merit are computed (`metrics.py`), the
   rule engine fires (`rules.py` → `Finding`s), and change-point detection runs
   over the synth series (`versioning.py` → `ChangeEvent`s, idempotent).

Schema changes require a **full DB rebuild** (`rm backend/data/ppa.db* && ppa.cli demo`);
there is no migration path — the demo DB is disposable and regenerable.

---

## 5. Database design

Single SQLite file in **WAL mode** (`-wal`/`-shm` sidecars are gitignored; the
main file is checkpointed before commits). 19 tables in four groups:

### 5.1 Identity & provenance

| Table | Key columns | Purpose |
|---|---|---|
| **Project** | `name`, `process_node` (N7), `nand2_area_um2`, `target_freq_mhz`, `area_budget_mm2` (2.0), `power_budget_mw`, `settings_json` (incl. `target_geomean` 1.45) | top-level container; budgets/targets drive mark lines and rules |
| **Design** | `project_id`, `version` ("v0.5"), **`model`** (`synth` \| `gem5` \| `slice` \| `zebu` \| `fogs`), `rtl_git_sha`, `rtl_branch`, `change_note`, `date` | one row per (RTL version, provenance series) — the v3 multi-model extension |
| **Config** | `design_id`, `name`, `params_json` | parameter set of a run (JSON) |
| **Corner** | `name`, `process`/`voltage`/`temp`, `lib_set`, `rc_corner` | PVT corner |
| **Run** | `design_id`, `config_id`, `corner_id`, `label`, `tool`, `tool_version`, `stage` (`synth` for full synth, `sim` for perf models), `status` | the unit of analysis; 80 in the demo (16 × 5) |
| **RawReport** | `run_id`, `kind`, `file_path`, `sha256`, `bytes`, **`content`** (full text), `parser_version`, `parse_status`, `parse_log` | verbatim report storage → the trace/search backbone |

### 5.2 Metrics (hybrid: typed rows + tall table)

| Table | Grain | Key columns |
|---|---|---|
| **Metric** (tall) | run × key × scope | `key` ("fom.area_mm2", "timing.wns_ns", "power.clock_gating_eff"…), `value`, `unit`, `scope_path?` — absorbs anything untyped |
| **AreaRow** | run × hierarchy node | `scope_path`, `parent_path`, `depth`, `total_area`, `comb_area`, `seq_area`, `macro_area`, `clock_area`, `buf_inv_area`, `inst_count`, `src_line`. Depth convention: `core_top`/`Total`/`die_total` = depth 1, `core_top/u_*` modules = depth 2 (the "module" grain used by waterfalls/hotspots/correlations), leaves deeper. `die_total` models the core at 62 % site utilization (board panel proxy) |
| **PowerRow** | run × hierarchy node | `internal`/`switching`/`leakage`/`total` (mW), `depth`, `src_line` |
| **TimingPath** | run × path | `path_id`, `clock`, `slack_ns`, `required_ns`, `arrival_ns`, `startpoint`, `endpoint`, `start_module`, `end_module`, `logic_depth`, `is_hold`, `src_line` |
| **PerfRow** | run × benchmark | `benchmark` ("400.perlbench"…), `ipc`, `ratio_1ghz`, `ref_ipc`, `cycles_m`, `inst_m`, `l1d_mpki`, `l2_mpki`, `br_mispred_pct`, `src_line` |
| **ScopeAlias** | run × tool path | `tool_path` → `canonical_path` (cross-tool join) |

**Why hybrid:** typed tables give fast, indexed, structured queries for the four
known domains; the tall `Metric` table means a new parser-discovered quantity
never requires a schema change — it just becomes a new key.

### 5.3 Analysis layer

| Table | Purpose |
|---|---|
| **ChangeEvent** | persisted change point: `from_run_id`/`to_run_id`, `metric_key`, `scope_path` (module attribution), `delta_pct`, `magnitude` (robust z = delta / MAD scale), `method` (`step` \| `spike` \| `recovery` \| `trend`), `severity`, `note` |
| **Baseline** | project's golden/user baselines (`run_id`, `label`, `is_golden`) |
| **Finding** | rule-engine output: `rule_id` (e.g. `TIM_WNS_NEG`, `AREA_MOD_GROWTH`, `XDOM_NET_SCORE_DOWN`, `VC_CHANGE_POINT`, `DQ_*`), `severity`, `category`, `scope_path`, `title`, `evidence_json`, workflow `status` (`open`→`acknowledged`/`fixed`/`wont_fix`), optional `ai_explanation`/`ai_proposal` |
| **RuleFeedback** | 👍/👎 per finding (`verdict`, `comment`, `author`) |
| **Annotation** | free-text notes anchored to run + scope |

### 5.4 AI / workflow

| Table | Purpose |
|---|---|
| **ChatSession** | assistant session (`title`, `context_json`) |
| **ChatMessage** | `role`, `content`, `tool_trace` (JSON list of tool calls), `citations` (JSON list), `offline` flag |

Relationships (FK graph): `Project 1─* Design 1─* Run`, `Run *─1 Config`,
`Run *─1 Corner`, `Run 1─* {RawReport, Metric, AreaRow, PowerRow, TimingPath,
PerfRow, ScopeAlias, Finding, Annotation}`, `Project 1─* {ChangeEvent,
Baseline}`, `ChatSession 1─* ChatMessage`, `Finding 1─* RuleFeedback`.

---

## 6. Analysis engine (how it is implemented)

### 6.1 Figures of merit (`metrics.py`)
Computed per run from parsed rows: `fmax_mhz` (from WNS vs target period, or a
fixed clock), `specint_per_ghz` (geomean ratio), **`specint_score` =
SPECint/GHz × Fmax** (the net number a frequency/IPC trade is judged on),
`area_mm2` (core total), `total_power_mw`, `mw_per_mhz`, `epi_pj`,
`area_eff_score_per_mm2`, `leakage_share`, `clock_gating_eff`. Also: net-score
decomposition (IPC vs Fmax contributions, verdict loss/win) and Pareto front
identification for the design-space view.

### 6.2 Rule engine (`rules.py`)
Each run builds a `RunFacts` context (metrics, trees, baseline context, **model**).
Rules fire Findings with structured `evidence_json`: timing (WNS negative, NVE
high, deep logic, module dominates), area (module growth, over budget, seq
ratio), power (density, clock-gating low), performance (benchmark regression,
isolated outlier — **synth runs only**), cross-domain (ROI low, net score down),
data quality (parse warnings, missing reports — model-aware), and
`VC_CHANGE_POINT` findings promoted from high/medium ChangeEvents.
Perf-model runs are a *reference series*: they never compare against the synth
golden baseline (cross-provenance deltas would just measure model bias).

### 6.3 Version series & change points (`versioning.py`)
- `version_series(model="synth")`: ordered versions with headline metrics, sha,
  change note; the perf-model series are selectable via the `model` parameter.
- Change-point detection: version-to-version deltas per metric, robust z-score
  (median + k·MAD), classified **step** (persists), **spike**+**recovery**
  (reverts next version), or **trend** (multi-version drift); attributed to the
  biggest contributing module via a depth-2 delta waterfall, or to the owner of
  a new worst path. Idempotent — re-running replaces, never duplicates.
- Correlations: Pearson r between perf metrics and PPA costs across versions,
  plus per-module area/power vs score.
- Signal search: a **signal** is a timing-report startpoint/endpoint name (the
  only signal-level source in these report formats); search returns slack
  history across versions plus raw-text hits (file + line).
- Trace-to-source: `(run, kind, scope_path | path_id | benchmark | line)` →
  the exact report lines (highlighted), sha256 and parser version.

### 6.4 Release overview board (v3)
`overview_board()` assembles one payload for the 6-panel dashboard: geomean per
provenance series vs target, perf-per-area vs target efficiency (1.45 / 2 mm²),
per-benchmark ratio and IPC matrices (12 benchmarks × 4 perf models × 16
versions), stacked area breakdown (Frontend=`u_ifu`, Backend=`u_ex`,
Memblock=`u_lsu`, L2 top=`u_l2`, Other), timing closure series (WNS/TNS/NVE),
and board metrics (max logic levels, gated %, core-vs-die, comb share,
utilization proxy; congestion overflow is a documented placeholder — no
synth-stage source). `version_drill(v)` adds per-version module/signal
drill-down; `version_compare_multi(vs)` builds module/IPC/signal matrices with
deltas vs the earliest selected version.

**Multi-model semantics** (planted in the sample generator, deterministic):
zebu = emulation truth; gem5 = zebu × ~1.02 (optimistic bias); slice = zebu ±1 %;
fogs = zebu ±2 %. All share the same planted IPC events, so model gaps are
visible but trends agree.

### 6.5 AI assistant (`ppa/ai/`)

The assistant is built around a **trust contract**, enforced structurally in
code rather than by prompting alone:

1. the model can only *select tools*, never compute — every number in an answer
   comes verbatim from deterministic Python output;
2. citations travel with each tool call and are returned alongside the answer;
3. refusal ("I don't have that data") is preferred over guessing.

**LLM client (`llm.py`).** A thin OpenAI-compatible `httpx` wrapper
(`/chat/completions`, non-streaming) pointed at an on-prem endpoint — Ollama by
default (`http://localhost:11434/v1`, model `qwen2.5:32b-instruct`), vLLM or
any compatible server via `PPA_AI_BASE_URL` / `PPA_AI_MODEL`. `probe()` checks
reachability and resolves the configured model against the installed ones; the
result is exposed at `GET /api/ai/status`. No cloud calls exist in the codebase.

**Tool layer (`tools.py`).** 14 read-only tools, each a Pydantic-validated
function over the analysis/versioning layer with row limits (`_clip`):
`list_runs`, `get_context_pack`, `compare_runs`, `breakdown` (area/power tree),
`timing_paths`, `perf_scores`, `pareto`, `get_findings`, `get_version_series`,
`get_change_points`, `get_correlations`, `search_signals`, `trace_to_source`,
and `propose_view` (returns a `view_proposal` the UI turns into a one-click
navigation jump). `execute_tool()` returns `(result_json, citations)` — every
citation names the run label and source ("context pack", "rule engine", …).
The model never generates SQL and never does arithmetic.

**What the context is (`context_pack.py`).** Context packs are compact,
LLM-friendly digests precomputed by deterministic Python — the model's window
into the DB, sized for small local models:

- `build_run_pack(run_id)` — one run: identity (label, stage, corner, config,
  version + change note + RTL sha), all **figures of merit**, FOM deltas vs
  baseline (cur/base/pct), **domain summaries and budgets** (from the
  scorecard), top-10 **modules by area/power share + criticality** (hotspot),
  5 **worst timing paths** (slack, module, depth), **per-benchmark IPC with
  deltas**, top-10 **open findings**, and an embedded `version_context`:
  the 16-version headline series (score/area/power/WNS + change notes), the
  8 strongest **change points** (magnitude-sorted, with attribution) and the
  6 strongest **perf×PPA correlations** — so even a single tool call can
  answer version-axis questions.
- `build_comparison_pack(run_ids)` — config diff, net-score **decomposition**
  (IPC vs frequency), key FOM deltas (score, area, power, ROIs), top-5 area
  and power **waterfall** contributors per pair, plus a `version_pair` block
  (from/to version, change note, detected change events between the two runs)
  and the run packs of both sides.
- **UI context** — the frontend sends `run_context` (`{view, run_id}`) with
  every chat request; the agent injects it as a second system message
  ("user is looking at this", truncated to 2 KB) so answers are grounded in
  what's on screen.

**Agent loop (`agent.py`).** `chat()` first probes the endpoint. If
unreachable — or the resolved model is below `ai_min_model_b` (4B, parsed from
names like `qwen3:0.6b`) — it answers via the offline analyst immediately
instead of burning minutes on failing rounds. Otherwise it runs a bounded tool
loop (`ai_max_tool_rounds` = 6) with graduated guardrails:

- the first round uses `tool_choice="required"` — small models otherwise
  narrate from memory instead of fetching data;
- models under 8B get a **compact tool set** (`get_context_pack` + `list_runs`)
  since mid-size local models handle few tools better than many, and the run
  pack already embeds findings, paths and per-benchmark data;
- a content-only reply is accepted **only after** at least one tool call;
  otherwise the agent nudges up to twice ("call get_context_pack now — do not
  answer from memory");
- tool errors are fed back to the model as `{"error": …}` results;
- at loop exhaustion it forces a final answer ("use only the tool results
  above"); if the model never called a tool, it falls back to the offline
  analyst (`reason="no_tools"`).

The system prompt encodes the trust rules plus domain knowledge (score =
SPECint/GHz × Fmax, WNS/TNS/NVE definitions, area/power splits, change-point
method taxonomy, ROI heuristics, vectorless-power caveat).

**Offline deterministic analyst.** `offline_answer()` is a pattern matcher over
the question text that assembles cited answers directly from the DB: version
questions ("what changed in/after vX", trends, "why did the power jump" →
metric-word detection + change-point listing), correlation questions,
signal-search questions (regex-extracts the query term), run comparisons
(config diff + decomposition), findings questions, and a default run overview
from the context pack. Each pattern returns markdown content, citations, a
`view_proposal`, and a mode note explaining why the deterministic path was
taken (offline / small_model / no_tools) — so the assistant always answers,
flagged `offline: true`.

**API + persistence + UI.** `POST /api/ai/chat` takes `{messages,
run_context}` and returns `{content, citations, tool_trace, offline,
view_proposal}`; sessions and messages persist in `ChatSession` /
`ChatMessage` (including the tool trace and citations as JSON). The frontend
`ChatPanel` renders the answer, turns `view_proposal` into a navigation button
(driven by the same zustand store/URL-hash mechanism as everything else) and
shows citations and the offline-mode note.

---

## 7. API surface (`main.py`)

| Group | Endpoints |
|---|---|
| Runs & views | `GET /api/runs` · `GET /api/scorecard/{run_id}` · `GET /api/compare?run_ids=` · `GET /api/design-space` |
| Domain explorers | `GET /api/area/{run_id}` · `/api/power/{run_id}` · `/api/timing/{run_id}` · `/api/perf/{run_id}` · `/api/hotspot/{run_id}` |
| Diagnosis | `GET /api/findings` · `PATCH /api/findings/{id}` (status workflow) · `POST /api/findings/{id}/feedback` · `GET /api/rules` · `GET /api/ingest-status` |
| Version series (v2) | `GET /api/versions` · `/api/change-points` · `/api/correlations` · `/api/search?q=` · `/api/trace?run_id&kind&…` |
| Overview board (v3) | `GET /api/overview` · `/api/version-drill?version=` · `/api/version-compare?versions=a,b,c` (400 if < 2) |
| AI | `GET /api/ai/status` · `POST /api/ai/chat` |

All responses are plain JSON dicts (no response-model serialization overhead);
the frontend keeps matching TypeScript interfaces in `src/types.ts`.

---

## 8. Frontend architecture

- **One SPA, 13 views** (`src/views/`), switched by the zustand `view` state and
  mirrored to the URL hash — no router library, no history API needed.
- **Data flow:** `api.ts` (typed `fetch` wrappers) → react-query (caching per
  endpoint key) → views. Mutations (finding status, feedback) invalidate the
  affected query keys.
- **Global store** (`store.ts`): `runId`, `baselineRunId`, `compareIds` (tray),
  `versionPair`, `searchQuery`, `trace` target, `drillVersion`,
  `overviewVersions` (cap 4) — each with URL-hash sync, so every analysis state
  is a shareable link.
- **Views:** Version Timeline, Runs (+ Release Overview Board below the table:
  6 panels, drill-down, multi-version compare), Scorecard, Compare, Design
  Space, Correlations, Area/Power/Timing/Performance explorers, Hotspot Matrix,
  Diagnosis, Ingest & Admin.
- **Trace affordance:** every plotted row/path/value carries a **⌖ src** button
  (`SourceBtn`) that opens the `TraceDrawer` → `/api/trace` → the raw report
  lines with the exact provenance highlighted.
- **Global search** in the top bar: modules → Area view, signals → Timing view
  (filtered), raw-text hits → trace drawer.

---

## 9. Testing & operations

- **Backend tests** (`backend/tests/test_backend.py`, 16 tests, hermetic):
  canonicalization, all parsers (incl. the `die_total` utilization row), FOMs,
  decomposition, Pareto, ingest + rule firing on the 80-run multi-model DB (all
  5 planted events caught, zero false alarms), version series isolation per
  model, change-point classification, correlations, overview/drill/compare
  payloads, signal search, trace-to-source, API coverage, offline AI patterns.
  Each run uses a fresh temp DB built by the deterministic generator.
- **Frontend:** `tsc --noEmit` as part of the build; E2E verified in-browser.
- **Demo lifecycle:** `ppa.cli demo` regenerates `sample_runs/` and rebuilds
  `backend/data/ppa.db` from scratch (required after any schema change);
  `ppa.cli serve` runs API + UI on `:8000`.

---

## 10. Known limitations / derived-metric caveats

- **Utilization** on the board is a core/die area-ratio *proxy* (`die_total` =
  core ÷ 0.62 in the sample data); true site utilization has no synthesis-stage
  source.
- **Congestion overflow** has no source at the synth stage → rendered as an
  annotated placeholder tile.
- Perf-model runs carry only `specint.rpt`; area/power/timing panels are
  synth-series-only by design.
- "Signal" coverage is limited to timing-report startpoint/endpoint names —
  the only signal-level information present in these report formats.
- SQLite + single-node FastAPI is a deliberate scale choice: the workload is
  one engineer's release history (tens–hundreds of runs), not a multi-user farm.
