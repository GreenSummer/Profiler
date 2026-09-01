---
kind: business_term
name: Business Glossary
category: business_term
scope:
    - '**'
---

### PPA
- Definition：Power, Performance, Area — the three axes of silicon design evaluation that the profiler measures, compares, and optimizes across runs.
- Aliases：power-performance-area

### RTLA
- Definition：RTL-Architect, the EDA tool whose `.rpt` outputs (area hierarchy, timing path groups, QoR metrics) are parsed and ingested into the profiler alongside PrimePower and SPECint results.
- Aliases：RTL-Architect

### PrimePower
- Definition：Synopsys vectorless power measurement tool; its hierarchical power reports (internal/switching/leakage/total per module) are parsed and cross-joined with RTLA area data via canonicalized paths.

### SPECint2006
- Definition：The SPEC CPU 2006 integer benchmark suite used to measure performance; the profiler parses per-benchmark IPC, cycles, instructions, cache miss rates, and branch-misprediction percentages, then normalizes to a 1 GHz ratio for comparison.
- Aliases：SPECint、SPECint2k6

### OpenROAD METRICS2.1
- Definition：An IEEE DATC RDF de facto standard metric format emitted by the open-source ORFS/OpenLane flow (Yosys+OpenROAD+OpenSTA). The profiler adopts it as a reference for metric naming/semantics and plans an importer so runs from fully open flows can be profiled alongside RTLA/PrimePower.
- Aliases：METRICS2.1、ORFS metrics

### context pack
- Definition：A curated snapshot of DDL, examples, and run metadata fed to the LLM so it reasons over verified PPA numbers instead of generating free-form SQL or Python. Replaces text-to-SQL approaches because hierarchical tables double-count when summed naively.

### offline analyst
- Definition：Deterministic fallback mode of the AI assistant that answers questions from context packs with full citations when no local LLM endpoint is reachable; preserves the UX without requiring Ollama/vLLM.

### net score
- Definition：Composite trade-off metric that combines IPC gain against frequency loss (and other PPA axes) to decide whether a change is beneficial overall; used by the rule engine to flag cases like 'IPC +8.7% but net score −0.9%'.

### Pareto frontier
- Definition：Set of non-dominated runs plotted in multi-dimensional PPA space; a run off the frontier is dominated by another run that is better on at least one axis and not worse on others.

### canonical path
- Definition：Normalized RTL hierarchy path used to join area, power, timing, and perf data across tools (e.g. mapping PrimePower's `u_ex.gen_alu[0].u_alu` onto RTLA's spelling) so cross-tool attribution is possible.
