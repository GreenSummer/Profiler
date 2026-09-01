"""Precomputed PPA Context Packs (plan section 6.2): compact, LLM-friendly
digests built by deterministic Python. The assistant reads facts from these
packs and tools — it never generates SQL and never does arithmetic."""
from __future__ import annotations

from sqlmodel import Session

from .. import analysis


def build_run_pack(session: Session, run_id: int) -> dict:
    """Compact digest of a single run: FOM, domain summaries, top modules,
    top paths, per-benchmark scores, open findings."""
    sc = analysis.scorecard(session, run_id)
    if not sc:
        return {}
    hs = analysis.hotspot(session, run_id)
    tm = analysis.timing_explorer(session, run_id)
    pf = analysis.perf_explorer(session, run_id)
    runs = {r["run_id"]: r for r in analysis.list_runs(session)}
    run = runs.get(run_id, {})
    return {
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


def build_comparison_pack(session: Session, run_ids: list[int]) -> dict:
    """Digest of a comparison: config diff + FOM deltas + decomposition."""
    cmp_data = analysis.compare(session, run_ids)
    packs = [build_run_pack(session, rid) for rid in run_ids[:2]]
    compact = {
        "runs": cmp_data.get("runs", []),
        "comparisons": [],
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
    compact["packs"] = [p for p in packs if p]
    return compact
