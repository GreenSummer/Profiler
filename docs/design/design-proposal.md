# PPA-Profiler Design Proposal

Scope confirmed with you: on-prem LLM only, tens of runs on a single RISC-V core project, design document only (no code yet).

---

## 1. The value thesis: why this tool deserves to exist

You said the tool must be useful to SoC designers or it fails. That is the right worry. Most internal "PPA dashboards" fail for one reason: they display what the tools already printed. A designer who wants area already has `report_area` open in a terminal. So the profiler must do the three things that **no single one of your source tools can do**:

**Thesis 1: Only the profiler can compute net performance.**
RTLA tells you achievable frequency. SPECint tells you cycles/IPC. Neither tells you the number the designer is actually judged on:

```
SPECint2006_score  ~=  SPECint2006_per_GHz  x  Fmax_GHz
```

Nearly every interesting microarchitecture change **trades IPC against frequency**: a deeper ROB, a bigger scheduler, or an extra bypass path raises IPC and lengthens the critical path. A change that gains 3% IPC but costs 150 MHz on a 3 GHz core is a **net performance loss**, and today nobody in your flow can see that in one place. Making this the headline number of the tool is the single highest-value decision in this document.

**Thesis 2: Only the profiler can do cross-domain attribution.**
Area, power, and timing all decompose over the *same RTL module hierarchy*, but they live in three different report formats. Joining them on hierarchy path answers the question designers actually ask: *"which module is simultaneously big, hot, and timing-critical?"* That module is where engineering effort pays back the most. This is the "hotspot matrix" view in section 4.

**Thesis 3: Only the profiler remembers.**
A single run is nearly worthless; PPA work is entirely comparative. Value comes from baseline-relative deltas, regression detection, and the accumulated record of "we tried a 64-entry ROB and it cost 4% area for 0.6% score." That institutional memory is also what makes the AI assistant progressively more useful (section 6.6).

Everything below serves these three theses. Anything that does not is a candidate to cut.

---

## 2. The metric model: what actually matters

Since you are new to PPA analysis, this section is the conceptual core. Metrics form a pyramid; designers work at the top, debug at the bottom.

### Tier 3: Figures of merit (the decision layer, ~8 numbers)

These are what go in a design review and what the scorecard shows.

| Metric | Formula | Why designers care |
|---|---|---|
| SPECint2006 score | `SPECint/GHz x Fmax` | Net delivered performance. The headline. |
| SPECint2006/GHz | geomean of 12 benchmark ratios at 1 GHz | Pure microarchitecture quality, frequency-independent. The standard RISC-V comparison metric. |
| Fmax | `1 / (T_target - WNS)` | Physical design quality; the frequency half of the trade. |
| Area efficiency | `score / mm^2` | Perf per unit silicon cost. Drives area budget arguments. |
| Power efficiency | `score / W`, or `mW/MHz` | Battery/thermal budget. `mW/MHz` is the classic embedded figure. |
| Energy per instruction (EPI) | `power / (IPC x freq)` | Workload-independent energy quality, in pJ/inst. |
| EDP / ED2P | `energy x delay`, `energy x delay^2` | Whether a change is a real win or just a voltage/frequency trade. |
| Area in kGE | `area_um2 / NAND2_area_um2` | Process-node-independent size; lets you compare against published cores. |

### Tier 2: Domain summaries (the triage layer)

- **Timing**: WNS and TNS per clock and per path group (reg2reg / in2reg / reg2out / clock-gating), number of violating endpoints (NVE), slack histogram, max logic depth.
- **Area**: total cell area, split into combinational / sequential / macro (SRAM) / clock-network / physical-only; instance count; utilization %.
- **Power**: total, split into internal / switching / leakage, and orthogonally into combinational / register / clock-network / memory; clock-gating efficiency; leakage share.
- **Performance**: per-benchmark score and IPC, geomean, plus cache miss rates (MPKI) and branch mispredict rate if your reports carry them.

### Tier 1: Raw detail (the debug layer)

Hierarchical per-module area and power rows, top-N timing paths with startpoint/endpoint/module ownership/logic depth, per-benchmark cycle and instruction counts. This is the drill-down target, not the landing page.

### The derived metrics designers ask for constantly

Ratios matter more than absolutes; these should be first-class computed columns, not something the user builds by hand:
- `power_density` = module power / module area (mW/mm^2) -> IR-drop and thermal risk
- `seq_area_ratio` = sequential / total area -> flop-heavy designs are power-hungry and hard to gate
- `clock_power_share` = clock-network power / total power -> gating and CTS opportunity
- `leakage_share` = leakage / total -> VT-mix (LVT/SVT/ULVT) over-aggressiveness
- `clock_gating_efficiency` = gated flop count / total flop count (or gated-cycle fraction)
- `area_ROI` = delta_score_% / delta_area_% -> **the single best "was it worth it" number**
- `power_ROI` = delta_score_% / delta_power_%

`area_ROI` and `power_ROI` deserve special emphasis: a change with ROI < ~0.3 is usually rejected on sight in a design review. Surfacing it automatically converts the tool from a viewer into a decision aid.

### The seven questions the tool must answer

Every view below is justified by one of these. This list is the acceptance test for usefulness:

1. Where does my design stand against target Fmax / area / power budgets right now?
2. What changed since the last run, and was it good or bad on net?
3. Which module should I work on next to get the most PPA return?
4. Is this microarchitecture option worth its cost? (config A vs B vs C)
5. Which configuration points are Pareto-optimal, so which should we tape out?
6. Why is this module big / hot / slow? (root cause drill-down)
7. What is abnormal or broken in this data that I have not noticed?

---

## 3. Data model (SQLite)

Right-sized for tens of runs: plain SQLite with WAL, no partitioning, no DuckDB, no Postgres, no auth. The schema below is the part worth getting right, because everything downstream depends on it and it is the expensive thing to change later.

### Identity and provenance

```
project        (id, name, process_node, nand2_area_um2, target_freq_mhz,
                area_budget_mm2, power_budget_mw)
design         (id, project_id, rtl_git_sha, rtl_branch, description, date)
config         (id, design_id, name, params_json)      -- ROB size, L1D KB, issue width...
corner         (id, name, process, voltage, temp, lib_set, rc_corner)
run            (id, design_id, config_id, corner_id, tool, tool_version,
                stage, started_at, status, workdir_path)
raw_report     (id, run_id, kind, file_path, sha256, bytes, parser_version,
                parse_status, parse_log)
```

Two non-obvious but critical fields:
- `parser_version` + `sha256` on every report: lets you re-parse everything when a tool upgrade changes format, and detect silently-edited reports.
- `stage` on `run` (`rtla_predict` / `synth` / `place` / `cts` / `route`): area and timing mean different things at different stages, and comparing across stages is a classic false-alarm source.

### Metrics: hybrid tall + typed

```
metric        (run_id, key, value, unit, scope_path NULL)   -- tall, flexible
area_row      (run_id, scope_path, parent_path, depth, total_area,
               comb_area, seq_area, macro_area, clock_area, inst_count)
power_row     (run_id, scope_path, parent_path, depth, internal, switching,
               leakage, total, category)
timing_path   (run_id, path_id, clock, path_group, slack, required, arrival,
               startpoint, endpoint, start_module, end_module,
               logic_depth, is_hold)
perf_row      (run_id, benchmark, cycles, instructions, ipc, score,
               ref_time, cache_mpki_json, branch_mispred_rate)
```

Rationale: the **tall `metric` table absorbs everything you have not thought of yet** (you said you do not know what matters yet, so schema flexibility is a requirement, not a nice-to-have), while the four typed tables give fast indexed hierarchy queries for the views that need them. Do not try to make everything tall; hierarchy joins on a tall table get painful.

### Analysis layer

```
scope_alias   (run_id, tool_path, canonical_path)  -- name-mismatch bridge
baseline      (project_id, run_id, label, is_golden)
finding       (id, run_id, rule_id, severity, category, scope_path,
               title, evidence_json, status, ai_explanation, ai_proposal)
annotation    (id, run_id, scope_path, author, body, created_at)
chat_session  (id, context_json, created_at) / chat_message (...)
rule_feedback (finding_id, verdict, comment, author)
```

`scope_alias` is the unglamorous table that decides whether this project works. See risk R1.

### The mandatory normalization step

Cross-tool joins only work if hierarchy paths are canonicalized. RTLA, PrimePower, and your RTL will disagree on separators (`/` vs `.`), on generate-block naming (`u_core/gen_way[0].u_tag` vs `u_core/gen_way_0_/u_tag`), and on whether the top level is included. Build one `canonicalize_path()` function, apply it at ingest, store both the original and canonical form, and **report unmatched paths as a data-quality finding** rather than silently dropping them. Silent drops in a PPA tool destroy trust permanently.

---

## 4. What to display: the views

Eleven views, ordered by build priority. Each maps to questions from section 2.

### V1. Run Explorer (Q1, Q2) - the landing page
Sortable/filterable table of all runs: date, config, corner, stage, RTL sha, and the eight Tier-3 figures of merit as columns. Row actions: set as baseline, add to comparison, open scorecard. Status dot per run for data-quality issues.
Interaction: multi-select rows -> "Compare" (feeds V3) or "Explore" (feeds V4).

### V2. PPA Scorecard (Q1) - single run health
KPI cards for the eight figures of merit, each showing absolute value, delta vs baseline (colored), and progress against project budget/target. Below: three compact domain panels (timing / area / power) with Tier-2 summaries, plus the performance geomean. Right rail: top 5 open findings from the diagnosis engine.
This is the view a designer checks every morning and the one you screenshot into a design review.

### V3. Compare / Delta (Q2, Q4) - the workhorse
Select 2..N runs. Contains:
- **Config diff** and RTL sha diff at the top: *what changed* before *what it cost*.
- **Figure-of-merit delta table** with `area_ROI` / `power_ROI` computed.
- **Net performance decomposition**: a small waterfall showing `IPC contribution` and `Fmax contribution` summing to net score delta. This is thesis 1 made visible and will likely be the most-used chart in the tool.
- **Area delta waterfall by module**, sorted by contribution, so a +3% total area is immediately attributed to the modules responsible.
- Same waterfall for power.
- **Timing delta**: WNS/TNS per path group, plus whether critical-path ownership moved to a different module.

### V4. Design Space Explorer (Q5)
**Parallel coordinates** plot (one axis per metric, one polyline per run) with brushing on each axis - the standard multi-objective DSE visualization and ideal for spotting "no config is good on all four axes." Plus a **2D scatter with computed Pareto frontier** (default axes: score vs power, score vs area), non-dominated points highlighted, dominated points dimmed. Click/lasso a point set -> push to V3.
At tens of configs this is readable without any clustering or sampling.

### V5. Area Explorer (Q3, Q6)
**Treemap** (or sunburst/icicle) of the module hierarchy sized by area, colored by either comb/seq/macro/clock composition or by delta-vs-baseline. Click to drill down, breadcrumb to go back. Side table: top-N modules by area, by area growth, and by `seq_area_ratio`. Toggle to switch size encoding to instance count, which exposes "many tiny cells" vs "few big macros."

### V6. Power Explorer (Q3, Q6)
Same treemap idiom on power (consistency of idiom matters for learnability). Stacked bars for internal/switching/leakage by top-level module. Dedicated panels for clock-network power and clock-gating efficiency, since those are the two most actionable power findings in practice. Sortable `power_density` column to flag thermal/IR hotspots.

### V7. Timing Explorer (Q6)
- **Slack histogram / S-curve** of endpoint slack: shape tells you instantly whether you have one broken path or a systemic wall.
- Path-group summary table (WNS/TNS/NVE per clock x group).
- Top-N path table, expandable to the path detail (startpoint -> endpoint, logic depth, owning module).
- **Critical-module leaderboard**: which module owns the most of the top-100 paths, tracked across runs. A module that stays #1 across five runs is a structural problem, not a P&R problem, and that distinction is expensive to learn manually.

### V8. Performance Explorer (Q6)
Per-benchmark bars (score and IPC) normalized to baseline, with the geomean marked. Benchmark outliers are diagnostic: `429.mcf` and `471.omnetpp` are memory/pointer-chasing bound, `456.hmmer` is compute bound, `403.gcc` is branch/I-cache bound. A regression isolated to mcf points at the memory subsystem, not the core. Show MPKI and branch mispredict rate alongside when available. A frequency-assumption selector converts IPC to score live.

### V9. Cross-Domain Hotspot Matrix (Q3) - thesis 2
Per module, one row: `area %`, `power %`, `criticality` (share of top paths owned), `power_density`, and delta-vs-baseline for each. Rendered as a heatmap and as a bubble chart (x = area share, y = power share, size = criticality). The top-right-large bubbles are your work queue. As far as I know no commercial tool gives you this joined view, which is why it is worth building.

### V10. Diagnosis Center (Q7)
Findings list with severity, category, scope, evidence, AI explanation, and proposal. Filter by severity/category/status. Workflow: open -> acknowledged -> fixed / wont-fix (with reason). See section 5.

### V11. Ingest & Admin
Point at a run directory, show per-report parse status with the parse log, edit run metadata (config params, corner, stage), define project budgets/targets, and edit the diagnosis rule pack. Unsexy, but if ingestion is not self-service the tool dies when you stop personally feeding it.

### Cross-cutting: AI chat side panel
Always available, context-aware of the current view and selection (section 6).

---

## 5. Configuration items (your requirement 1)

The "select/configure and show as configured" requirement is best served by a three-layer model rather than a pile of dropdowns.

### Layer 1: Global selection context (persistent top bar, applies everywhere)
- Project, design/RTL revision, config(s), corner (PVT), stage
- **Baseline run** - the reference for every delta in the app
- Comparison set (the runs currently "in the tray")

### Layer 2: Per-view config panel
- **Metric selection**: which columns/series, with show/hide/reorder/pin
- **Units**: um^2 / mm^2 / kGE; mW / W; ps / ns
- **Normalization mode**: absolute | delta vs baseline | % delta | per-GHz | per-mm^2 | per-W. One control, enormous leverage - it turns every table into four different tables.
- **Hierarchy depth** (1..N) and module path filter (glob/regex), include/exclude macros, top-N cutoff
- **Frequency assumption**: `use timing-derived Fmax` | `fixed N GHz`. Required to convert IPC to score; must be explicit and visible, never hidden, because it silently changes the headline number.
- **Timing**: clock, path group, setup/hold, slack threshold
- **Power**: scenario/mode (active/idle), category split, toggle-rate assumption
- **Performance**: benchmark subset, geomean vs custom weights, IPC vs score
- **Chart**: axes, color/size encoding, log scale, Pareto on/off, group-by, stack vs group

### Layer 3: Project settings (admin)
- Targets and budgets (Fmax target, area budget, power budget) - these drive all red/yellow/green
- Regression thresholds (e.g. area > +2%, power > +1%, WNS worse than -50 ps, score < -0.5%)
- Diagnosis rule pack enable/disable and threshold overrides
- NAND2 gate area for kGE, reference machine for SPEC ratios
- AI: model endpoint, model name, temperature, privacy mode

### Making configuration usable, not just present
- **All state encoded in the URL** so a designer can paste a link in Slack and a colleague sees exactly the same chart. This is the cheapest collaboration feature in existence and disproportionately drives adoption.
- **Saved views**: name and reuse a full configuration; pin favorites to the home page.
- **Export**: CSV/XLSX for tables, PNG/SVG for charts, and a one-click PDF "PPA review packet" of the scorecard plus findings.

---

## 6. AI design (your requirements 2 and 3)

### 6.1 Three distinct AI capabilities

Conflating these is the usual mistake; they have different reliability requirements and should be built separately:

| Capability | Nature | Reliability need |
|---|---|---|
| A. Diagnosis (req 3) | Deterministic rules + LLM narration | Very high - must not cry wolf |
| B. Chat over data (req 2) | Retrieval + tool calls + LLM synthesis | High on numbers, medium on prose |
| C. Natural language to view | Intent -> UI state | Low risk; wrong chart is harmless |

### 6.2 The architectural decision: precomputed context packs, not text-to-SQL

Given your two constraints - **on-prem models only** and **tens of runs** - I recommend explicitly **against** free-form natural-language-to-SQL, which is the default choice most teams reach for. Reasons:

1. A locally-servable model (roughly 7B-70B) writes materially worse SQL than a frontier model, and a wrong-but-plausible number in a PPA tool is worse than no answer at all. It will get someone to make a bad tapeout decision.
2. At your scale, you do not need SQL generation. **The entire analytically-relevant dataset fits in the context window.** Tens of runs x eight figures of merit x top-30 modules x top-20 timing paths is on the order of 10-30k tokens.

So: at ingest time, precompute a compact, LLM-friendly **PPA Context Pack** per run and per comparison - a structured JSON/Markdown digest of figures of merit, top-N area/power modules, top-N critical paths, per-benchmark scores, and open findings. The assistant reads facts already computed by deterministic Python, never by generated SQL. This is more reliable, much faster, far easier to debug, and it eliminates the entire SQL-injection and runaway-query surface.

Retrieval is then only needed for things too big for context, handled by a small tool layer:

```
list_runs()                          get_context_pack(run_ids)
compare_runs(run_ids)                area_breakdown(run_id, path, depth)
power_breakdown(run_id, path, depth) timing_paths(run_id, filters, top_n)
perf_scores(run_id, benchmarks)      pareto(metric_x, metric_y)
get_findings(filters)                search_reports(query)   # RAG, raw .rpt text
propose_view(view, config)           # capability C
```

All read-only, typed (Pydantic), with row limits. Local models handle a compact tool set like this reliably; keep it under ~12 tools and do not let it sprawl.

### 6.3 The trust contract (non-negotiable)

An AI feature in EDA gets exactly one chance. If it hallucinates a number once in front of a senior designer it is dead forever. Therefore:

1. **The LLM never computes or invents a number.** All arithmetic happens in Python; the model only selects, explains, and proposes. If you take one rule from this document, take this one.
2. **Every claim carries a citation** back to `run_id` + report file + line range, rendered as a clickable link to the raw report text.
3. **Refuse rather than guess**: if no tool returns supporting data, the answer is "I do not have that data," and the UI makes that state visually distinct.
4. **Full auditability**: log every prompt, tool call, and response.
5. **Answers are rendered as real tables and charts**, not prose containing digits - it is both more useful and structurally harder to hallucinate.

### 6.4 Diagnosis: rules first, LLM second (requirement 3)

The pipeline: `ingest -> rule engine -> findings with evidence -> LLM enrichment -> designer feedback`.

The rule engine is deterministic and defined in YAML so designers can add their own rules without touching code:

```yaml
- id: PWR_CLOCK_SHARE
  category: power
  when: "clock_power / total_power > 0.30"
  severity: high
  title: "Clock network consumes {clock_power_share:.0%} of total power"
  evidence: [power_row.clock_area_modules, clock_gating_efficiency]
```

Starter rule pack, grouped:

**Timing**: WNS < 0 (severity scaled by magnitude); NVE above threshold; one module owning > 30% of top-100 paths; logic depth > 25; hold violations post-CTS; critical path crossing a module boundary repeatedly (suggests bad partitioning).

**Area**: module area growth > 5% vs baseline; utilization > 75% (congestion risk); `seq_area_ratio` > 0.5; a module far larger than its siblings; total area over budget.

**Power**: `leakage_share` > 25% (VT mix too aggressive); `clock_power_share` > 30%; clock-gating efficiency < 70%; `power_density` above a per-project threshold (IR/thermal risk); register power exceeding combinational power.

**Performance**: any benchmark regressing > 1%; geomean regression; an isolated single-benchmark outlier (with the interpretation hint from V8); IPC gain accompanied by an Fmax loss that makes **net score negative** - the flagship cross-domain rule.

**Cross-domain ROI**: `area_ROI` < 0.3; `power_ROI` < 0.3; EDP worse despite a score improvement.

**Data quality** (do not skip these - they are the cheapest to implement and prevent the most wasted debug time): mismatched RTL sha between the area/power/perf runs being compared; mismatched corner or stage; unparsed report sections; hierarchy paths that failed to match across tools; zero or absurd values; a report older than the RTL commit it claims to describe.

The LLM then enriches each finding with a plain-language explanation, ranked root-cause hypotheses, and concrete proposals annotated with expected impact / effort / risk. Because a rule already established that the finding is real and supplied the evidence, the model is doing language work rather than analysis, which is exactly what a local model is good at.

### 6.5 Chat behavior (requirement 2)

- The chat panel is **selection-aware**: it receives the current view, filters, and selected runs, so "why is this worse?" resolves without the user restating context.
- "Explain this" buttons on every chart and finding, which prefill a grounded question.
- Answers may embed tables and charts, and may return a **view proposal** the user can apply with one click (capability C): *"show me L2 power for config A vs B"* reconfigures V6 rather than describing it in words.
- Sessions are saved and attached to runs, so the reasoning behind a decision is recoverable months later.

### 6.6 The feedback loop that makes it improve

Every finding gets a thumbs up/down plus an optional reason ("not applicable, that path is a false path"). Store it in `rule_feedback`. This gives you three things: rule threshold tuning grounded in real verdicts, few-shot examples that make explanations match your team's idiom, and a growing RAG corpus of past findings and their resolutions. After a few months the assistant can answer "have we tried this before?" - which is the point at which designers start using it voluntarily rather than because you asked them to.

### 6.7 On-prem AI stack

- **Serving**: Ollama for simplicity at your scale (vLLM only if you later need concurrency).
- **Model**: a Qwen-class 32B instruct model is the sweet spot for reliable tool calling on a single workstation GPU; a 70B-class model if you have the VRAM. Prefer the strongest tool-calling model you can serve over the largest one.
- **Abstraction**: LiteLLM, so the model is a config value and you can move to vLLM or a cloud endpoint later without touching application code.
- **Embeddings + RAG**: `bge-m3` or `nomic-embed-text` with `sqlite-vec`, keeping the single-file SQLite story intact for raw report text and the knowledge base.
- **Orchestration**: a plain Python tool-calling loop. Deliberately avoid LangChain-style frameworks here; with about a dozen typed tools the framework costs more in debugging opacity than it saves.

---

## 7. Technology stack (all open source)

**Backend**: Python 3.11+, FastAPI, SQLModel/SQLAlchemy, Pydantic v2, SQLite (WAL mode), Polars for report parsing and aggregation, Typer for the ingest CLI.

**Frontend**: React + TypeScript + Vite; **Apache ECharts** for charts (chosen specifically because it covers treemap, sunburst, parallel coordinates, waterfall, heatmap, and histogram in one library - these are exactly the idioms PPA needs, and mixing chart libraries costs consistency); **TanStack Table** for grouped/pinnable/virtualized tables; TanStack Query for data fetching; Zustand for selection state; shadcn/ui + Tailwind for UI.

**AI**: LiteLLM + Ollama + sqlite-vec, as above.

**Notable rejects**, so the reasoning is on record: Superset/Metabase/Grafana give you charts fast but cannot express hierarchy-aware cross-domain joins, Pareto frontiers, or an embedded AI workflow - you would spend more time fighting them than a custom React app costs. Postgres and DuckDB are unnecessary at tens of runs; keep the migration path in mind but do not pay for it now.

---

## 8. Roadmap

Each phase is independently useful. Phase 1 alone should already beat reading .rpt files by hand.

**Phase 1 - Foundation.** Parsers for RTLA area/timing/qor, PrimePower, SPECint, with golden-file tests. SQLite schema. Path canonicalization. Ingest CLI. V1 Run Explorer, V2 Scorecard, and basic V5/V6/V7 tables.

**Phase 2 - Comparison.** V3 Compare/Delta including the net-performance waterfall and area delta waterfall, V8 Performance Explorer, baseline management, URL state, saved views. *This is where the tool starts changing behavior.*

**Phase 3 - Insight.** V4 Design Space Explorer with Pareto, V9 Hotspot Matrix, treemap drill-downs, annotations.

**Phase 4 - Diagnosis.** Rule engine, YAML rule pack, V10 Diagnosis Center with the findings workflow. Deliberately **before** the AI chat, because it is deterministic, it is where most of the practical value lives, and it produces the structured findings the AI later narrates.

**Phase 5 - AI.** Context packs, tool layer, chat panel with citations, LLM enrichment of findings, NL-to-view, feedback loop.

**Phase 6 - Automation.** Auto-ingest from your regression flow, regression alerts, PDF review packets, knowledge base RAG.

---

## 9. Risks, honestly stated

**R1 - Hierarchy name mismatch (highest risk).** If RTLA and PrimePower disagree on instance path spelling, thesis 2 collapses and V9 is empty. Mitigation: build `canonicalize_path()` and the `scope_alias` table in phase 1, and surface the unmatched-path rate as a first-class data-quality metric. **I would want to see one real RTLA area report and one real PrimePower report side by side before writing any other code**, because this single question determines whether the cross-domain design is feasible as specified.

**R2 - Parser fragility.** EDA report formats shift between tool versions. Mitigation: always retain raw reports, version the parsers, and keep a golden-file fixture suite so a tool upgrade produces a clear test failure rather than silently corrupted data.

**R3 - Vectorless power accuracy.** Vectorless PrimePower estimates depend on assumed toggle rates and can diverge substantially from vector-based results. The tool must display the toggle-rate assumption next to every power number and avoid implying more precision than exists. Treat vectorless power as good for *relative* comparison, weak for absolute budgeting - and say so in the UI.

**R4 - SPEC methodology comparability.** Full SPECint2006 on RTL simulation is generally infeasible, so your numbers likely come from a performance model, FPGA, or SimPoint-sampled traces. Runs produced by different methods are not comparable. Mitigation: record the method as run metadata and refuse (or loudly warn on) cross-method comparisons.

**R5 - AI trust.** Covered by the section 6.3 contract. The failure mode is social, not technical, and it is irreversible.

**R6 - Adoption.** A tool nobody opens has failed regardless of quality. The mitigations are cheap and should not be deferred: shareable URLs, one-click export into review slides, and auto-ingest so data appears without anyone doing work.

---

## 10. What I need from you next

1. **One real sample of each report** - RTLA area, RTLA timing, RTLA qor, PrimePower, SPECint. Everything in phase 1 depends on their actual text format, and R1 in particular cannot be resolved by reasoning alone.
2. **Your config parameter space** - which RISC-V knobs you sweep (ROB, issue width, cache sizes, predictor sizes, VLEN...), which determines the `config.params_json` shape and the V4 axes.
3. **Targets and budgets** - Fmax target, area budget, power budget, process node, and NAND2 area, so the scorecard can show red/yellow/green rather than context-free numbers.
4. **How SPEC numbers are produced** (per R4).
5. **Confirmation of the section 1 theses** - particularly whether "net score = IPC x Fmax" matches how your team reasons. If it does not, the priority order of the views should change, and I would rather find that out now than in phase 3.
