"""Typed, read-only tool layer for the AI assistant (plan section 6.2).
Every tool is a Pydantic-validated function over the analysis layer with
row limits. All arithmetic is done in Python, never by the model."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field
from sqlmodel import Session

from .. import analysis
from .. import versioning
from ..models import Run
from .context_pack import build_comparison_pack, build_run_pack


class ListRunsIn(BaseModel):
    """List all ingested runs with headline figures of merit."""

    op: Literal["list_runs"] = "list_runs"


class GetContextPackIn(BaseModel):
    """Full precomputed PPA digest for one run (or two for a comparison)."""

    op: Literal["get_context_pack"] = "get_context_pack"
    run_ids: list[int] = Field(description="one or two run ids", max_length=2)


class CompareRunsIn(BaseModel):
    """Deterministic comparison: config diff, FOM deltas, IPC/freq decomposition."""

    op: Literal["compare_runs"] = "compare_runs"
    run_ids: list[int] = Field(min_length=2, max_length=4)


class BreakdownIn(BaseModel):
    """Hierarchical area or power breakdown for one run."""

    op: Literal["breakdown"] = "breakdown"
    kind: Literal["area", "power"]
    run_id: int
    depth: int = Field(default=2, description="hierarchy depth to report", le=4)


class TimingPathsIn(BaseModel):
    """Worst timing paths, optionally filtered by module substring."""

    op: Literal["timing_paths"] = "timing_paths"
    run_id: int
    module_contains: str = ""
    top_n: int = Field(default=10, le=50)


class PerfScoresIn(BaseModel):
    """Per-benchmark IPC/ratios with deltas vs the project baseline."""

    op: Literal["perf_scores"] = "perf_scores"
    run_id: int


class ParetoIn(BaseModel):
    """Pareto frontier over two figures of merit across all runs."""

    op: Literal["pareto"] = "pareto"
    x: Literal["total_power_mw", "area_mm2", "fmax_mhz"] = "total_power_mw"
    y: Literal["specint_score", "specint_per_ghz"] = "specint_score"


class GetFindingsIn(BaseModel):
    """Diagnosis findings from the deterministic rule engine."""

    op: Literal["get_findings"] = "get_findings"
    run_id: int | None = None
    severity: Literal["critical", "high", "medium", "low", "info"] | None = None
    category: Literal["timing", "area", "power", "performance", "cross_domain",
                      "data_quality", "version_change"] | None = None


class GetVersionSeriesIn(BaseModel):
    """Ordered RTL version series with headline PPA metrics and change notes."""

    op: Literal["get_version_series"] = "get_version_series"
    metrics: list[str] = Field(
        default_factory=list, max_length=6,
        description="optional display keys to keep, e.g. ['area_mm2','total_power_mw']")


class GetChangePointsIn(BaseModel):
    """Detected version-to-version change points (step/spike/recovery/trend)."""

    op: Literal["get_change_points"] = "get_change_points"
    metric: str | None = Field(default=None,
                                description="filter by display key, e.g. area_mm2")
    severity: Literal["high", "medium", "low"] | None = None


class GetCorrelationsIn(BaseModel):
    """Pearson correlations between performance and PPA metrics across versions."""

    op: Literal["get_correlations"] = "get_correlations"


class SearchSignalsIn(BaseModel):
    """Substring search over timing signals (slack history) and raw report text."""

    op: Literal["search_signals"] = "search_signals"
    query: str = Field(min_length=2, max_length=64,
                       description="substring of a signal or module name, e.g. 'mac'")


class TraceToSourceIn(BaseModel):
    """The exact raw report lines backing one plotted value."""

    op: Literal["trace_to_source"] = "trace_to_source"
    run_id: int
    kind: Literal["area", "power", "timing", "perf"]
    scope_path: str | None = Field(default=None,
                                   description="required for area/power")
    path_id: int | None = Field(default=None, description="required for timing")
    benchmark: str | None = Field(default=None, description="required for perf")


class ProposeViewIn(BaseModel):
    """Ask the UI to navigate to a view with a configuration."""

    op: Literal["propose_view"] = "propose_view"
    view: Literal["run-explorer", "scorecard", "compare", "design-space",
                  "area", "power", "timing", "performance", "hotspot",
                  "findings", "ingest", "timeline", "correlations"]
    run_id: int | None = None
    run_ids: list[int] = Field(default_factory=list, max_length=4)


TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "list_runs", "description": "List all runs with headline PPA figures of merit.",
            "parameters": ListRunsIn.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_context_pack",
            "description": "Full precomputed PPA digest for one run, or a two-run comparison digest.",
            "parameters": GetContextPackIn.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_runs",
            "description": "Deterministic run comparison: config diff, FOM deltas, IPC vs frequency decomposition, area/power waterfalls.",
            "parameters": CompareRunsIn.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "breakdown",
            "description": "Hierarchical area or power breakdown (per module, with shares).",
            "parameters": BreakdownIn.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "timing_paths",
            "description": "Worst setup timing paths with owning module and logic depth.",
            "parameters": TimingPathsIn.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "perf_scores",
            "description": "Per-benchmark SPECint IPC and ratio with baseline deltas.",
            "parameters": PerfScoresIn.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pareto",
            "description": "Pareto frontier across runs for two chosen metrics.",
            "parameters": ParetoIn.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_findings",
            "description": "Abnormalities and rule-engine findings, optionally filtered.",
            "parameters": GetFindingsIn.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_version_series",
            "description": "Ordered RTL version series: headline PPA metrics, git sha and change note per version.",
            "parameters": GetVersionSeriesIn.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_change_points",
            "description": "Statistically detected version-to-version change points (step/spike/recovery/trend) with module attribution and change notes.",
            "parameters": GetChangePointsIn.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_correlations",
            "description": "Pearson r between performance (score, IPC, Fmax) and PPA (area, power, WNS, leakage) across versions, plus per-module correlations.",
            "parameters": GetCorrelationsIn.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_signals",
            "description": "Search timing signals by name substring (returns slack history per version) and raw report text (file + line).",
            "parameters": SearchSignalsIn.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trace_to_source",
            "description": "Trace one plotted value back to the exact raw report lines it came from (area/power/timing/perf).",
            "parameters": TraceToSourceIn.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_view",
            "description": "Navigate the user's UI to a specific PPA-Profiler view.",
            "parameters": ProposeViewIn.model_json_schema(),
        },
    },
]


def _clip(obj, max_bytes: int = 24000) -> str:
    s = json.dumps(obj, default=str)
    return s if len(s) <= max_bytes else s[:max_bytes] + "...(clipped)"


def execute_tool(session: Session, name: str, arguments: dict) -> tuple[str, list[dict]]:
    """Run one tool. Returns (result_json, citations). Citations reference the
    run/report the data came from so answers stay verifiable (plan 6.3)."""
    citations: list[dict] = []

    def cite(run_id: int, what: str):
        run = session.get(Run, run_id) if run_id else None
        citations.append({"run_id": run_id, "run_label": run.label if run else str(run_id),
                          "source": what})

    if name == "list_runs":
        runs = analysis.list_runs(session)
        return _clip([{"run_id": r["run_id"], "label": r["label"], "fom": r["fom"],
                       "open_findings": r["open_findings"]} for r in runs]), citations

    if name == "get_context_pack":
        args = GetContextPackIn(**arguments)
        if len(args.run_ids) == 1:
            pack = build_run_pack(session, args.run_ids[0])
            cite(args.run_ids[0], "context pack")
        else:
            pack = build_comparison_pack(session, args.run_ids)
            for rid in args.run_ids:
                cite(rid, "context pack")
        return _clip(pack), citations

    if name == "compare_runs":
        args = CompareRunsIn(**arguments)
        data = analysis.compare(session, args.run_ids)
        for rid in args.run_ids:
            cite(rid, "comparison")
        return _clip(data), citations

    if name == "breakdown":
        args = BreakdownIn(**arguments)
        if args.kind == "area":
            data = analysis.area_explorer(session, args.run_id)
            rows = [r for r in data["rows"] if r["depth"] == args.depth][:30]
            out = {"total_um2": data["total_um2"],
                   "rows": [{"module": r["scope_path"], "area_um2": round(r["total_area"], 1),
                             "share": round(r["share"], 4),
                             "seq_ratio": round(r["seq_ratio"], 3)} for r in rows]}
        else:
            data = analysis.power_explorer(session, args.run_id)
            rows = [r for r in data["rows"] if r["depth"] == args.depth][:30]
            out = {"total_mw": data["total_mw"],
                   "clock_gating_eff": data["clock_gating_eff"],
                   "rows": [{"module": r["scope_path"], "total_mw": round(r["total"], 3),
                             "share": round(r["share"], 4),
                             "leak_share": round(r["leak_share"], 3)} for r in rows]}
        cite(args.run_id, f"{args.kind} breakdown")
        return _clip(out), citations

    if name == "timing_paths":
        args = TimingPathsIn(**arguments)
        data = analysis.timing_explorer(session, args.run_id)
        paths = data["paths"]
        if args.module_contains:
            paths = [p for p in paths if args.module_contains.lower() in p["module"].lower()]
        cite(args.run_id, "timing report")
        return _clip({"wns_ns": data["wns_ns"], "nve": data["nve"],
                      "paths": paths[:args.top_n]}), citations

    if name == "perf_scores":
        args = PerfScoresIn(**arguments)
        data = analysis.perf_explorer(session, args.run_id)
        cite(args.run_id, "SPECint report")
        return _clip(data), citations

    if name == "pareto":
        args = ParetoIn(**arguments)
        data = analysis.design_space(session, args.x, args.y)
        front = [p for p in data["points"] if p["pareto"]]
        cite(0, "all runs")
        return _clip({"x": args.x, "y": args.y,
                      "pareto_optimal": [{"label": p["label"], "x": round(p["x"], 4),
                                          "y": round(p["y"], 4)} for p in front],
                      "n_runs": len(data["points"])}), citations

    if name == "get_findings":
        args = GetFindingsIn(**arguments)
        data = analysis.findings(session, run_id=args.run_id,
                                 severity=args.severity, category=args.category)
        for f in data[:20]:
            cite(f["run_id"], f"rule {f['rule_id']}")
        return _clip(data[:30]), citations

    if name == "get_version_series":
        args = GetVersionSeriesIn(**arguments)
        data = versioning.version_series(session)
        series = data["series"]
        if args.metrics:
            series = [{**s, "metrics": {k: s["metrics"].get(k) for k in args.metrics}}
                      for s in series]
        else:
            series = [{**s, "metrics": {k: v for k, v in s["metrics"].items()
                                        if k in ("specint_score", "area_mm2",
                                                 "total_power_mw", "wns_ns")}}
                      for s in series]
        if series:
            cite(series[0]["run_id"], "version series")
            cite(series[-1]["run_id"], "version series")
        return _clip({"n_versions": len(series), "series": series}), citations

    if name == "get_change_points":
        args = GetChangePointsIn(**arguments)
        data = versioning.change_points(session)
        if args.metric:
            data = [e for e in data if e["metric_key"] == args.metric]
        if args.severity:
            data = [e for e in data if e["severity"] == args.severity]
        for e in data[:20]:
            cite(e["to_run_id"], f"change point {e['metric_key']}")
        return _clip({"n_events": len(data), "events": data}), citations

    if name == "get_correlations":
        data = versioning.correlations(session)
        cite(0, "version series")
        return _clip(data), citations

    if name == "search_signals":
        args = SearchSignalsIn(**arguments)
        data = versioning.signal_search(session, args.query)
        cited: set[int] = set()
        for sig in data["signals"][:5]:
            if sig["history"] and sig["history"][0]["run_id"] not in cited:
                cited.add(sig["history"][0]["run_id"])
                cite(sig["history"][0]["run_id"], "signal search")
        return _clip(data), citations

    if name == "trace_to_source":
        args = TraceToSourceIn(**arguments)
        data = versioning.trace_to_source(
            session, args.run_id, args.kind, scope_path=args.scope_path,
            path_id=args.path_id, benchmark=args.benchmark)
        cite(args.run_id, "raw report trace")
        return _clip(data), citations

    if name == "propose_view":
        args = ProposeViewIn(**arguments)
        return json.dumps({"view_proposal": {"view": args.view,
                                             "run_id": args.run_id,
                                             "run_ids": args.run_ids}}), citations

    return json.dumps({"error": f"unknown tool {name}"}), citations
