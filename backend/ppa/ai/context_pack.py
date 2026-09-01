"""Precomputed PPA Context Packs (plan section 6.2): compact, LLM-friendly
digests built by deterministic Python. The assistant reads facts from these
packs and tools — it never generates SQL and never does arithmetic.

v2: every run pack embeds the version-series context (headline series, top
change points, headline correlations), so even the compact single-tool path
can answer version questions.
"""
from __future__ import annotations

from sqlmodel import Session

from .. import analysis
from .. import versioning
from ..models import Design, Run

# headline columns kept in the embedded series (bytes matter: packs are the
# context window of small local models)
_SERIES_KEYS = ("specint_score", "area_mm2", "total_power_mw", "wns_ns")


def _version_context(session: Session) -> dict:
    """Compact version-axis digest embedded in every run pack."""
    data = versioning.version_series(session)
    series = data["series"]
    if not series:
        return {}
    out = {
        "n_versions": len(series),
        "series": [
            {
                "version": s["version"], "date": s["date"],
                "change_note": s["change_note"],
                **{k: (round(v, 4) if v is not None else None)
                   for k, v in s["metrics"].items() if k in _SERIES_KEYS},
            }
            for s in series
        ],
    }
    events = versioning.change_points(session)
    top = sorted(events, key=lambda e: -abs(e["magnitude"]))[:8]
    out["top_change_points"] = [
        {"from_version": e["from_version"], "to_version": e["to_version"],
         "metric": e["metric_key"], "change_pct": round(e["delta_pct"], 4),
         "method": e["method"], "severity": e["severity"],
         "module": e["scope_path"], "note": e["note"]}
        for e in top
    ]
    corr = versioning.correlations(session)
    headline = sorted(corr["pairs"], key=lambda p: -abs(p["r"]))[:6]
    out["headline_correlations"] = [
        {"perf": p["perf"], "ppa": p["ppa"], "r": p["r"], "n": p["n"]}
        for p in headline
    ]
    return out


def build_run_pack(session: Session, run_id: int) -> dict:
    """Compact digest of a single run: FOM, domain summaries, top modules,
    top paths, per-benchmark scores, open findings, version context."""
    sc = analysis.scorecard(session, run_id)
    if not sc:
        return {}
    hs = analysis.hotspot(session, run_id)
    tm = analysis.timing_explorer(session, run_id)
    pf = analysis.perf_explorer(session, run_id)
    runs = {r["run_id"]: r for r in analysis.list_runs(session)}
    run = runs.get(run_id, {})
    run_row = session.get(Run, run_id)
    design = session.get(Design, run_row.design_id) if run_row else None
    pack = {
        "run": {"id": run_id, "label": run.get("label"),
                "stage": run.get("stage"), "corner": run.get("corner"),
                "config": run.get("config", {})},
        "figures_of_merit": {k: round(v, 4) for k, v in sc["fom"].items()
                             if isinstance(v, (int, float))},
        "fom_delta_vs_baseline": {
            k: {"cur": round(v["current"], 4), "base": round(v["baseline"], 4),
                "pct": round(v["pct"], 2) if v["pct"] is not None else None}
            for k, v in sc.get("fom_delta_vs_baseline", {}).items()},
        "domain_summaries": sc["domains"],
        "budgets": sc["budgets"],
        "top_modules_by_area_power": [
            {"module": r["module"], "area_share": round(r["area_share"], 3),
             "power_share": round(r["power_share"], 3),
             "criticality": round(r["criticality"], 3)}
            for r in hs["rows"][:10]
        ],
        "worst_timing_paths": [
            {"slack_ns": round(p["slack_ns"], 3), "module": p["module"],
             "depth": p["logic_depth"]} for p in tm["paths"][:5]
        ],
        "per_benchmark": [
            {"benchmark": r["benchmark"], "ipc": r["ipc"],
             "delta_pct": round(r["ipc_delta_pct"], 2) if r["ipc_delta_pct"] is not None else None}
            for r in pf["rows"]
        ],
        "open_findings": [
            {"severity": f["severity"], "category": f["category"],
             "title": f["title"]} for f in sc["findings"][:10]
        ],
    }
    if design and design.version:
        pack["run"]["version"] = design.version
        pack["run"]["change_note"] = design.change_note
        pack["run"]["rtl_sha"] = design.rtl_git_sha
    vc = _version_context(session)
    if vc:
        pack["version_context"] = vc
    return pack


def build_comparison_pack(session: Session, run_ids: list[int]) -> dict:
    """Digest of a comparison: config diff + FOM deltas + decomposition;
    for adjacent versions, the change note and detected change events."""
    cmp_data = analysis.compare(session, run_ids)
    packs = [build_run_pack(session, rid) for rid in run_ids[:2]]
    compact = {
        "runs": cmp_data.get("runs", []),
        "comparisons": [],
    }
    # version pair info: from/to version labels + change events between them
    version_pair = {}
    if len(run_ids) >= 2:
        rows = [(rid, session.get(Run, rid)) for rid in run_ids[:2]]
        designs = [(rid, session.get(Design, r.design_id) if r else None)
                   for rid, r in rows]
        if all(d and d.version for _, d in designs):
            version_pair = {
                "from_version": designs[0][1].version,
                "to_version": designs[1][1].version,
                "change_note": designs[1][1].change_note,
                "change_events": [
                    {"metric": e["metric_key"], "change_pct": round(e["delta_pct"], 4),
                     "severity": e["severity"], "method": e["method"],
                     "module": e["scope_path"]}
                    for e in versioning.change_points(session)
                    if e["from_run_id"] == run_ids[0] and e["to_run_id"] == run_ids[1]
                ],
            }
    for c in cmp_data.get("comparisons", []):
        compact["comparisons"].append({
            "base": c["base_label"], "current": c["label"],
            "config_diff": c["config_diff"],
            "decomposition": c["decomposition"],
            "key_deltas": {
                k: {"cur": round(v["current"], 4), "base": round(v["baseline"], 4),
                    "pct": round(v["pct"], 2) if v["pct"] is not None else None}
                for k, v in c["fom_delta"].items()
                if k in ("specint_score", "specint_per_ghz", "fmax_mhz", "area_mm2",
                         "total_power_mw", "area_roi", "power_roi")
                and isinstance(v, dict)
            },
            "area_waterfall_top": c["area_waterfall"][:5],
            "power_waterfall_top": c["power_waterfall"][:5],
        })
    if version_pair:
        compact["version_pair"] = version_pair
    compact["packs"] = [p for p in packs if p]
    return compact
