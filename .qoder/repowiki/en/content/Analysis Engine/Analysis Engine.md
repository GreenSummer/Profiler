# Analysis Engine

<cite>
**Referenced Files in This Document**
- [analysis.py](file://backend/ppa/analysis.py)
- [rules.py](file://backend/ppa/rules.py)
- [metrics.py](file://backend/ppa/metrics.py)
- [models.py](file://backend/ppa/models.py)
- [main.py](file://backend/ppa/main.py)
- [config.py](file://backend/ppa/config.py)
- [rules_pack.yaml](file://backend/ppa/rules_pack.yaml)
- [Scorecard.tsx](file://frontend/src/views/Scorecard.tsx)
- [Compare.tsx](file://frontend/src/views/Compare.tsx)
- [api.ts](file://frontend/src/api.ts)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)
10. [Appendices](#appendices)

## Introduction
This document explains PPA-Profiler’s analysis engine: the query layer that serves each frontend view, the rule-based diagnostic engine that detects issues across area, power, timing, and performance domains, and the metrics system that computes figures of merit, deltas, and Pareto fronts for design space exploration. It also covers hotspot analysis algorithms, baseline comparisons, performance considerations, and extensibility points for adding new capabilities.

## Project Structure
The backend exposes a FastAPI application with one endpoint per view (V1–V11). Each endpoint delegates to a dedicated function in the analysis layer. The analysis layer reads from SQLModel models and uses a pure-Python metrics module for all derived calculations. A YAML-driven rule pack defines thresholds and titles; evaluators in rules.py implement deterministic checks and produce findings.

```mermaid
graph TB
FE["Frontend Views<br/>Scorecard, Compare, Design Space"] --> API["FastAPI Endpoints<br/>/api/*"]
API --> AL["Analysis Layer<br/>analysis.py"]
AL --> DB["SQLModel Models<br/>models.py"]
AL --> MET["Metrics Engine<br/>metrics.py"]
AL --> RUL["Rule Engine<br/>rules.py + rules_pack.yaml"]
```

**Diagram sources**
- [main.py:38-105](file://backend/ppa/main.py#L38-L105)
- [analysis.py:1-439](file://backend/ppa/analysis.py#L1-L439)
- [metrics.py:1-258](file://backend/ppa/metrics.py#L1-L258)
- [rules.py:1-361](file://backend/ppa/rules.py#L1-L361)
- [models.py:1-217](file://backend/ppa/models.py#L1-L217)

**Section sources**
- [main.py:1-206](file://backend/ppa/main.py#L1-L206)
- [analysis.py:1-439](file://backend/ppa/analysis.py#L1-L439)
- [metrics.py:1-258](file://backend/ppa/metrics.py#L1-L258)
- [rules.py:1-361](file://backend/ppa/rules.py#L1-L361)
- [models.py:1-217](file://backend/ppa/models.py#L1-L217)

## Core Components
- Query/analysis layer: One function per view (list_runs, scorecard, compare, design_space, area_explorer, power_explorer, timing_explorer, perf_explorer, hotspot, findings, ingest_status). These functions assemble data for frontend visualization and are the deterministic data source for AI tools.
- Rule-based diagnostic engine: Loads rules from YAML, evaluates them against precomputed facts per run, and persists findings with severity, category, scope, and evidence.
- Metrics engine: Computes domain summaries, figures of merit, deltas, ROI, net-score decomposition, and Pareto fronts. All arithmetic is centralized here.
- Data models: Typed tables for runs, configs, corners, metrics, area/power/perf rows, timing paths, baselines, findings, and annotations.

**Section sources**
- [analysis.py:16-439](file://backend/ppa/analysis.py#L16-L439)
- [rules.py:24-361](file://backend/ppa/rules.py#L24-L361)
- [metrics.py:13-258](file://backend/ppa/metrics.py#L13-L258)
- [models.py:17-217](file://backend/ppa/models.py#L17-L217)

## Architecture Overview
The API endpoints map directly to analysis functions. Each analysis function queries typed rows and metrics, optionally compares against a baseline, and returns structured payloads consumed by the frontend views.

```mermaid
sequenceDiagram
participant FE as "Frontend"
participant API as "FastAPI"
participant AL as "analysis.py"
participant DB as "SQLModel"
participant MET as "metrics.py"
participant RUL as "rules.py"
FE->>API : GET /api/scorecard/{run_id}
API->>AL : scorecard(session, run_id)
AL->>DB : Load Run, Config, Corner, Metrics
AL->>RUL : baseline_run() via RunFacts
AL->>MET : delta(), compare_fom(), net_score_decomposition()
AL-->>API : Scorecard payload
API-->>FE : JSON response
```

**Diagram sources**
- [main.py:45-50](file://backend/ppa/main.py#L45-L50)
- [analysis.py:69-125](file://backend/ppa/analysis.py#L69-L125)
- [metrics.py:142-187](file://backend/ppa/metrics.py#L142-L187)
- [rules.py:34-72](file://backend/ppa/rules.py#L34-L72)

## Detailed Component Analysis

### Query Layer: View Functions
Each view has a dedicated function returning a normalized payload:
- list_runs: Lists runs with FOMs, timing summary, and open finding counts.
- scorecard: Aggregates FOMs, budgets, domain summaries, deltas vs baseline, and top findings.
- compare: Compares multiple runs, computing FOM deltas, config diffs, area/power waterfalls, and net-score decomposition.
- design_space: Collects points (x,y) and marks Pareto-optimal indices.
- area_explorer/power_explorer/timing_explorer/perf_explorer/hotspot: Provide hierarchical breakdowns, histograms, leaderboards, and multi-metric rankings.
- findings: Filters and sorts findings by severity/category/status.
- ingest_status: Reports raw report parsing status.

```mermaid
flowchart TD
Start(["API Request"]) --> Route{"Endpoint"}
Route --> |/api/runs| V1["list_runs"]
Route --> |/api/scorecard| V2["scorecard"]
Route --> |/api/compare| V3["compare"]
Route --> |/api/design-space| V4["design_space"]
Route --> |/api/area| V5["area_explorer"]
Route --> |/api/power| V6["power_explorer"]
Route --> |/api/timing| V7["timing_explorer"]
Route --> |/api/perf| V8["perf_explorer"]
Route --> |/api/hotspot| V9["hotspot"]
Route --> |/api/findings| V10["findings"]
Route --> |/api/ingest-status| V11["ingest_status"]
V1 --> End(["JSON Response"])
V2 --> End
V3 --> End
V4 --> End
V5 --> End
V6 --> End
V7 --> End
V8 --> End
V9 --> End
V10 --> End
V11 --> End
```

**Diagram sources**
- [main.py:38-105](file://backend/ppa/main.py#L38-L105)
- [analysis.py:46-439](file://backend/ppa/analysis.py#L46-L439)

**Section sources**
- [analysis.py:46-439](file://backend/ppa/analysis.py#L46-L439)
- [main.py:38-105](file://backend/ppa/main.py#L38-L105)

### Rule-Based Diagnostic Engine
- Rules are defined in YAML with id, category, severity, title template, and params.
- Evaluators read from RunFacts (precomputed per run): metrics, area/power/perf rows, timing paths, reports, project, config, and baseline context.
- Evaluator outputs are tuples of (severity_override, scope, evidence), which are rendered into Finding records with category and evidence JSON.
- run_rule_engine clears old findings for affected runs, re-evaluates all rules, and persists new findings.

```mermaid
classDiagram
class RunFacts {
+int run_id
+Run run
+dict metrics
+list area
+list power
+list perf
+list paths
+list reports
+Project project
+string config_name
+dict config_params
+int baseline_run_id
+dict baseline_metrics
+dict baseline_area
+dict baseline_perf
+area_at_depth(depth) list
+power_by_path() dict
}
class RuleEvaluator {
<<function>>
+__call__(facts, params) list
}
class Finding {
+int id
+int run_id
+string rule_id
+string severity
+string category
+string scope_path
+string title
+dict evidence_json
+string status
}
RunFacts --> Finding : "produces evidence"
RuleEvaluator --> RunFacts : "reads"
RuleEvaluator --> Finding : "creates"
```

**Diagram sources**
- [rules.py:24-79](file://backend/ppa/rules.py#L24-L79)
- [rules.py:84-310](file://backend/ppa/rules.py#L84-L310)
- [models.py:168-180](file://backend/ppa/models.py#L168-L180)

**Section sources**
- [rules.py:19-361](file://backend/ppa/rules.py#L19-L361)
- [rules_pack.yaml:1-119](file://backend/ppa/rules_pack.yaml#L1-L119)
- [models.py:168-180](file://backend/ppa/models.py#L168-L180)

### Metrics Calculation System
- Domain summaries: AreaSummary, PowerSummary, TimingSummary, PerfSummary provide computed properties (e.g., fmax_mhz, leakage_share, geomean_ratio_1ghz).
- Figures of merit: Combine timing-derived or fixed frequency with performance to compute specint_score, efficiencies, energy metrics (EPI, EDP, ED2P).
- Comparison utilities: delta, roi, compare_fom, net_score_decomposition enable baseline comparisons and attribution of score changes to IPC vs frequency.
- Pareto front: Identifies non-dominated points for design space exploration with configurable objective directions.

```mermaid
flowchart TD
A["Inputs: Timing/Area/Power/Perf"] --> B["Summarize Domains"]
B --> C["Compute FOMs"]
C --> D["Deltas & ROI"]
D --> E["Net-Score Decomposition"]
E --> F["Pareto Front"]
```

**Diagram sources**
- [metrics.py:13-137](file://backend/ppa/metrics.py#L13-L137)
- [metrics.py:142-187](file://backend/ppa/metrics.py#L142-L187)
- [metrics.py:239-258](file://backend/ppa/metrics.py#L239-L258)

**Section sources**
- [metrics.py:13-258](file://backend/ppa/metrics.py#L13-L258)

### Hotspot Analysis Algorithm
Hotspot ranks modules by combining area share, power share, and criticality (from timing path density). It also computes deltas vs baseline when available.

```mermaid
flowchart TD
S["Start"] --> L1["Load area/power paths"]
L1 --> L2["Count critical modules from top timing paths"]
L2 --> L3["Compute total area/power at min depth"]
L3 --> L4["For each level-2 module:<br/>area_share, power_share, power_density, criticality"]
L4 --> L5["Baseline deltas if baseline exists"]
L5 --> L6["Sort by combined score"]
L6 --> E["Return ranked rows"]
```

**Diagram sources**
- [analysis.py:361-398](file://backend/ppa/analysis.py#L361-L398)

**Section sources**
- [analysis.py:361-398](file://backend/ppa/analysis.py#L361-L398)

### Pareto Front Identification
The Pareto algorithm identifies non-dominated points given objective directions (minimize x, maximize y by default). Used by design_space to mark optimal trade-offs.

```mermaid
flowchart TD
P0["Points (x,y)"] --> P1["For each i,j pair"]
P1 --> P2{"q dominates p?"}
P2 --> |Yes| P3["Mark i dominated"]
P2 --> |No| P4["Keep i"]
P3 --> P5["Collect non-dominated indices"]
P4 --> P5
P5 --> P6["Return set of indices"]
```

**Diagram sources**
- [metrics.py:239-258](file://backend/ppa/metrics.py#L239-L258)

**Section sources**
- [metrics.py:239-258](file://backend/ppa/metrics.py#L239-L258)

### Delta Calculations and Baseline Comparisons
- Per-FOM deltas include absolute and percentage differences.
- ROI measures score gain per cost gain (area or power).
- Net-score decomposition attributes score change to IPC and frequency components plus cross term.
- Waterfalls show module-level deltas for area and power between baseline and current runs.

```mermaid
sequenceDiagram
participant A as "analysis.compare"
participant M as "metrics"
A->>M : compare_fom(base_fom, cur_fom)
M-->>A : {metric : delta, area_roi, power_roi}
A->>M : net_score_decomposition(base_fom, cur_fom)
M-->>A : {ipc_pct, freq_pct, cross_pct, net_pct, verdict}
A->>A : _delta_waterfall(area/power)
A-->>Client : comparisons with waterfalls
```

**Diagram sources**
- [analysis.py:139-199](file://backend/ppa/analysis.py#L139-L199)
- [metrics.py:142-187](file://backend/ppa/metrics.py#L142-L187)

**Section sources**
- [analysis.py:139-199](file://backend/ppa/analysis.py#L139-L199)
- [metrics.py:142-187](file://backend/ppa/metrics.py#L142-L187)

### Examples of Rule Definitions and Custom Rules
- Rule definitions live in rules_pack.yaml with id, category, severity, title template, and params.
- To add a new rule:
  - Add an entry in rules_pack.yaml.
  - Implement a matching evaluator in rules.py and register it in EVALUATORS.
  - The evaluator reads from RunFacts and returns hits with severity override, scope, and evidence.

Examples present in the repository include timing (WNS negative, NVE high, module dominance, deep logic), area (budget exceed, sequential ratio, growth), power (leakage share, clock share, gating efficiency, density, budget), performance (bench regressions, isolated outlier), cross-domain (net score down, ROI low), and data quality (missing reports, parse warnings).

**Section sources**
- [rules_pack.yaml:1-119](file://backend/ppa/rules_pack.yaml#L1-L119)
- [rules.py:290-310](file://backend/ppa/rules.py#L290-L310)

### Finding Classification by Severity and Category
- Severity levels: critical, high, medium, low, info.
- Categories: timing, area, power, performance, cross_domain, data_quality.
- Findings can be filtered by run_id, severity, category, and status. Sorting prioritizes severity then category.

**Section sources**
- [models.py:168-180](file://backend/ppa/models.py#L168-L180)
- [analysis.py:403-423](file://backend/ppa/analysis.py#L403-L423)

### Frontend Integration
- Frontend views call backend APIs using typed helpers and render KPIs, deltas, charts, and tables.
- Scorecard displays FOMs, budgets, domain summaries, and top findings.
- Compare shows deltas, ROI, net-score decomposition, and waterfalls.

**Section sources**
- [Scorecard.tsx:1-124](file://frontend/src/views/Scorecard.tsx#L1-L124)
- [Compare.tsx:1-148](file://frontend/src/views/Compare.tsx#L1-L148)
- [api.ts:1-49](file://frontend/src/api.ts#L1-L49)

## Dependency Analysis
- main.py mounts FastAPI endpoints that delegate to analysis.py functions.
- analysis.py depends on models.py for typed data access and metrics.py for computations.
- rules.py depends on models.py and loads rules_pack.yaml; it produces findings persisted via models.
- Frontend api.ts calls backend endpoints and consumes typed responses.

```mermaid
graph LR
main["main.py"] --> analysis["analysis.py"]
analysis --> models["models.py"]
analysis --> metrics["metrics.py"]
rules["rules.py"] --> models
rules --> yaml["rules_pack.yaml"]
frontend["frontend/api.ts"] --> main
```

**Diagram sources**
- [main.py:12-17](file://backend/ppa/main.py#L12-L17)
- [analysis.py:8-13](file://backend/ppa/analysis.py#L8-L13)
- [rules.py:11-16](file://backend/ppa/rules.py#L11-L16)
- [api.ts:23-48](file://frontend/src/api.ts#L23-L48)

**Section sources**
- [main.py:12-17](file://backend/ppa/main.py#L12-L17)
- [analysis.py:8-13](file://backend/ppa/analysis.py#L8-L13)
- [rules.py:11-16](file://backend/ppa/rules.py#L11-L16)
- [api.ts:23-48](file://frontend/src/api.ts#L23-L48)

## Performance Considerations
- Deterministic computation boundary: All derived metrics and comparisons are performed in Python within metrics.py, ensuring reproducibility and avoiding ad-hoc calculations elsewhere.
- Baseline caching: RunFacts preloads baseline metrics, area, and perf once per run evaluation to avoid repeated queries.
- Query patterns: Analysis functions fetch only necessary rows and build dictionaries keyed by scope_path/benchmark for O(1) lookups during comparisons and waterfall computations.
- Pareto complexity: The Pareto front algorithm is O(n^2); for large design spaces, consider sampling or incremental updates.
- Extensibility without breaking ingestion: Rule evaluators are wrapped in try/except so a broken rule does not halt ingestion.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
- Missing baseline: If no baseline is configured for a project, baseline-related fields will be empty; ensure a Baseline row links a project to a reference run.
- Empty results: Ensure runs have associated metrics and rows; check ingest status to confirm parsers succeeded.
- Rule errors: Broken evaluators are caught; verify rule IDs match registered evaluators and parameters exist in YAML.
- Findings not updating: Re-run the rule engine after data changes; old findings for affected runs are cleared before recomputation.

**Section sources**
- [rules.py:313-352](file://backend/ppa/rules.py#L313-L352)
- [analysis.py:428-439](file://backend/ppa/analysis.py#L428-L439)

## Conclusion
PPA-Profiler’s analysis engine centralizes data retrieval, metric computation, and diagnostics behind a clean API surface. The rule-based engine enables maintainable, parameterized diagnosis across domains, while the metrics engine provides robust comparisons, ROI, and design space insights. The architecture supports extensibility through YAML-driven rules and modular evaluators, and integrates seamlessly with the frontend for interactive exploration.

[No sources needed since this section summarizes without analyzing specific files]

## Appendices

### API Surface Summary
- Runs: GET /api/runs
- Scorecard: GET /api/scorecard/{run_id}
- Compare: GET /api/compare?run_ids=...
- Design Space: GET /api/design-space?x=&y=
- Area/Power/Timing/Perf/Hotspot: GET /api/{view}/{run_id}
- Findings: GET /api/findings?run_id=&severity=&category=&status=
- Ingest Status: GET /api/ingest-status
- Rules: GET /api/rules

**Section sources**
- [main.py:38-162](file://backend/ppa/main.py#L38-L162)

### Configuration
- Database path, sample directory, AI settings, and frontend dist are configurable via environment variables prefixed with PPA_.

**Section sources**
- [config.py:12-30](file://backend/ppa/config.py#L12-L30)