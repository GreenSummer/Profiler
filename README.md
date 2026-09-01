# PPA-Profiler

A web-based Power/Performance/Area analysis workbench for RISC-V SoC designers. It ingests
RTL-Architect (RTLA) area/timing reports, PrimePower vectorless power reports, and SPECint 2006
performance reports into SQLite, computes cross-domain figures of merit, diagnoses abnormal
results with a deterministic rule engine, and offers an AI assistant that explains the data —
without ever inventing a number.

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

## Quickstart

```bash
# 1. Backend
cd backend
python3 -m venv ../.venv
../.venv/bin/pip install -r requirements.txt

# 2. Demo data: 12-run config sweep (ROB sizes, issue width, caches, VT mix...)
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

The demo sweep deliberately contains the interesting cases: `rob192` (IPC +8.7% but net score
−0.9% — frequency loss dominates), `leaky` (aggressive VT mix → high leakage share), `nocg`
(clock gating disabled → low gating efficiency), `rob128` (on the Pareto frontier).

During frontend development you can instead run `npm run dev` (Vite on :5173, proxying `/api`
to :8000).

## The 11 views

| # | View | Answers |
|---|------|---------|
| V1 | Runs | What runs exist, how do they rank, what changed per column vs baseline? |
| V2 | Scorecard | Budgets, KPIs with deltas, the four domains on one page |
| V3 | Compare | Config diff → net-score decomposition → area/power delta waterfalls |
| V4 | Design Space | Pareto frontier (score vs area/power), parallel coordinates over configs |
| V5 | Area Explorer | Treemap drill-down, comb/seq/macro/buf splits, Δ-vs-baseline coloring |
| V6 | Power Explorer | Internal/switching/leakage by module, clock share, CG efficiency, density |
| V7 | Timing Explorer | Slack histogram, critical-module leaderboard, worst paths, logic depth |
| V8 | Performance Explorer | Per-benchmark IPC and SPECratio@1GHz vs baseline, MPKI, mispredicts |
| V9 | Hotspot Matrix | Area share × power share × timing criticality bubble chart (cross-tool) |
| V10 | Diagnosis | Rule findings with evidence, ack/fix workflow, feedback, "ask AI" |
| V11 | Ingest & Admin | Parse status per report (SHA-256 + parser version), rule pack, CLI help |

Selection context is global (run, baseline, comparison tray) and mirrored into the URL hash, so
any analysis state is shareable.

## AI assistant

- **On-prem only**: talks to any OpenAI-compatible endpoint — Ollama and vLLM by default
  (`PPA_AI_BASE_URL`, `PPA_AI_MODEL`).
- **Trust contract**: the model never computes. It selects typed, read-only tools
  (`get_context_pack`, `compare_runs`, ...); every number in an answer comes verbatim from
  deterministic Python output, and every claim carries a citation chip (`run · source`).
- **Text-to-SQL is deliberately rejected**: hierarchy tables roll children into parents, so
  LLM-written SQL double-counts area and power silently. The typed tool layer makes that bug
  structurally impossible.
- **Deterministic fallback**: if no LLM is reachable — or the installed model is below the
  tool-calling size threshold (`PPA_AI_MIN_MODEL_B`, default 4B) — a built-in analyst answers
  common question shapes (overview / compare / findings) from context packs, instantly, with
  citations and view proposals. The badge in the top bar always tells you which mode you're in.
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
my_sweep/
  manifest.json          # [{"label": "run_a", "params": {...}, "corner": "tt_0p80v_25c",
                         #   "stage": "rtla_predict", "order": 0}, ...]
  run_a/
    rtla_area.rpt        # RTLA hierarchical area report
    rtla_timing.rpt      # RTLA timing report (groups, histogram, paths)
    rtla_qor.rpt         # RTLA QoR summary
    primepower.rpt       # PrimePower hierarchical vectorless power
    specint.rpt          # SPECint2006 per-benchmark results
```

```bash
../.venv/bin/python -m ppa.cli ingest my_sweep --project my-project
../.venv/bin/python -m ppa.cli check-format my_sweep/run_a/rtla_area.rpt   # parser dry-run
```

Path canonicalization is the hard part and is handled: RTLA prints `/`-separated indented
hierarchies, PrimePower prints `.`-separated paths with bracketed generate blocks
(`gen_alu[0]`); both map to one canonical form (`core_top/u_ex/gen_alu_0/u_alu`) so area,
power, and timing join per module. A data-quality rule (`DQ_*`) fires when paths don't match.

Parsers are versioned per report kind; every raw report is content-hashed (SHA-256) at ingest,
so provenance is auditable from V11.

## Diagnosis rules

`backend/ppa/rules_pack.yaml` — 19 rules in 6 categories (timing, area, power, performance,
cross-domain, data quality). Thresholds are data, not code: designers tune the YAML and
re-ingest. Severity escalation and title templates are in the same file. 👍/👎 feedback on
findings is persisted to guide future threshold tuning.

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

Covers canonicalization, all parsers, figures of merit, decomposition, Pareto, end-to-end
ingest + rule firing (the intentional anomalies must be caught, the cross-tool join must be
clean), and the API including the AI offline fallback (hermetic — no LLM required).

## Repository layout

```
backend/ppa/        FastAPI app, parsers, canonicalize, metrics, ingest, rules,
                    analysis views, AI layer (context packs, tools, agent, llm)
backend/tests/      pytest suite
frontend/src/       views/ (V1-V11), ai/ (ChatPanel, badge), store, api client
sample_runs/        synthetic 12-run sweep + manifest.json (parser fixtures & demo)
```

## Known limitations

- Vectorless power is good for relative comparison, not signoff — the UI says so where it matters.
- The synthetic sweep models one core at one corner; multi-corner support is future work.
- Metric names align with METRICS2.1 concepts but full export compatibility is untested.
