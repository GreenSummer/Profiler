"""Query/analysis layer: one function per view (V1-V10 of the plan).
Also the deterministic data source for AI tools — the LLM layer calls these,
never SQL."""
from __future__ import annotations

from sqlmodel import Session, select

from . import metrics as M
from .models import (
    AreaRow, Baseline, Config, Corner, Design, Finding, Metric, PerfRow,
    PowerRow, Project, RawReport, Run, TimingPath,
)
from .rules import RunFacts


def _design_ids(session: Session, project_id: int | None = None) -> list[int]:
    from .models import Design
    q = select(Design)
    if project_id is not None:
        q = q.where(Design.project_id == project_id)
    return [d.id for d in session.exec(q).all()]


def _runs(session: Session, project_id: int | None = None) -> list[Run]:
    ids = _design_ids(session, project_id)
    return [r for r in session.exec(select(Run)).all() if r.design_id in ids]


def _metrics(session: Session, run_id: int) -> dict[str, float]:
    return {m.key: m.value for m in session.exec(
        select(Metric).where(Metric.run_id == run_id)).all()}


def baseline_run(session: Session, run_id: int) -> Run | None:
    run = session.get(Run, run_id)
    if not run:
        return None
    facts = RunFacts(session, run_id)
    if facts.project and facts.baseline_run_id:
        return session.get(Run, facts.baseline_run_id)
    return None


# ---------------------------------------------------------------- V1

def list_runs(session: Session, project_id: int | None = None) -> list[dict]:
    out = []
    for run in _runs(session, project_id):
        m = _metrics(session, run.id)
        cfg = session.get(Config, run.config_id)
        corner = session.get(Corner, run.corner_id)
        design = session.get(Design, run.design_id)
        n_findings = len(session.exec(
            select(Finding).where(Finding.run_id == run.id, Finding.status == "open")).all())
        out.append({
            "run_id": run.id, "label": run.label, "stage": run.stage,
            "started_at": run.started_at.isoformat(),
            "version": design.version if design else "",
            "model": design.model if design else "synth",
            "change_note": design.change_note if design else "",
            "config": cfg.params_json if cfg else {},
            "corner": corner.name if corner else "",
            "fom": {k[len("fom."):]: v for k, v in m.items() if k.startswith("fom.")},
            "timing": {"wns_ns": m.get("timing.wns_ns"), "tns_ns": m.get("timing.tns_ns"),
                       "nve": m.get("timing.nve")},
            "open_findings": n_findings,
        })
    return out


# ---------------------------------------------------------------- V2

def scorecard(session: Session, run_id: int) -> dict:
    run = session.get(Run, run_id)
    if not run:
        return {}
    m = _metrics(session, run_id)
    project = None
    design = session.get(Design, run.design_id)
    if design:
        project = session.get(Project, design.project_id)
    bl = baseline_run(session, run_id)
    bl_m = _metrics(session, bl.id) if bl else {}

    fom = {k[len("fom."):]: v for k, v in m.items() if k.startswith("fom.")}
    bl_fom = {k[len("fom."):]: v for k, v in bl_m.items() if k.startswith("fom.")}

    budgets = {}
    if project:
        budgets = {
            "area_mm2": {"budget": project.area_budget_mm2,
                         "current": fom.get("area_mm2")},
            "power_mw": {"budget": project.power_budget_mw,
                         "current": fom.get("total_power_mw")},
            "fmax_mhz": {"target": project.target_freq_mhz,
                         "current": fom.get("fmax_mhz")},
        }
    top_findings = session.exec(
        select(Finding).where(Finding.run_id == run_id)
        .order_by(Finding.severity)).all()[:8]
    return {
        "run": {"id": run.id, "label": run.label, "stage": run.stage},
        "fom": fom,
        "fom_delta_vs_baseline": {
            k: M.delta(fom[k], bl_fom[k]) for k in fom
            if isinstance(fom.get(k), (int, float)) and isinstance(bl_fom.get(k), (int, float))
        } if bl_fom else {},
        "budgets": budgets,
        "domains": {
            "timing": {"wns_ns": m.get("timing.wns_ns"), "tns_ns": m.get("timing.tns_ns"),
                       "nve": m.get("timing.nve"), "fmax_mhz": m.get("timing.fmax_mhz")},
            "area": {"total_um2": m.get("area.total_um2"), "comb_um2": m.get("area.comb_um2"),
                     "seq_um2": m.get("area.seq_um2"), "macro_um2": m.get("area.macro_um2"),
                     "inst_count": m.get("area.inst_count")},
            "power": {"total_mw": m.get("power.total_mw"),
                      "internal_mw": m.get("power.internal_mw"),
                      "switching_mw": m.get("power.switching_mw"),
                      "leakage_mw": m.get("power.leakage_mw"),
                      "leakage_share": m.get("power.leakage_share"),
                      "clock_power_mw": m.get("power.clock_power_mw"),
                      "clock_power_share": m.get("power.clock_power_share"),
                      "clock_gating_eff": m.get("power.clock_gating_eff"),
                      "toggle_rate": m.get("power.toggle_rate")},
            "performance": {"geomean_ratio_1ghz": m.get("perf.geomean_ratio_1ghz"),
                            "mean_ipc": m.get("perf.mean_ipc")},
        },
        "findings": [_finding_dict(f) for f in top_findings],
    }


def _finding_dict(f: Finding) -> dict:
    return {
        "id": f.id, "run_id": f.run_id, "rule_id": f.rule_id,
        "severity": f.severity, "category": f.category, "scope_path": f.scope_path,
        "title": f.title, "evidence": f.evidence_json, "status": f.status,
        "ai_explanation": f.ai_explanation, "ai_proposal": f.ai_proposal,
    }


# ---------------------------------------------------------------- V3

def compare(session: Session, run_ids: list[int]) -> dict:
    if not run_ids:
        return {}
    runs = []
    for rid in run_ids:
        run = session.get(Run, rid)
        if run:
            m = _metrics(session, rid)
            cfg = session.get(Config, run.config_id)
            runs.append({
                "run_id": rid, "label": run.label,
                "fom": {k[len("fom."):]: v for k, v in m.items() if k.startswith("fom.")},
                "metrics": m, "config": cfg.params_json if cfg else {},
            })
    base = runs[0]
    comparisons = []
    for cur in runs[1:]:
        cmp_fom = M.compare_fom(base["fom"], cur["fom"])
        decomp = M.net_score_decomposition(base["fom"], cur["fom"])
        comparisons.append({
            "base_label": base["label"], "label": cur["label"],
            "fom_delta": cmp_fom, "decomposition": decomp,
            "config_diff": _config_diff(base["config"], cur["config"]),
            "area_waterfall": _delta_waterfall(session, base["run_id"], cur["run_id"], "area"),
            "power_waterfall": _delta_waterfall(session, base["run_id"], cur["run_id"], "power"),
        })
    return {"runs": [{"run_id": r["run_id"], "label": r["label"], "config": r["config"],
                      "fom": r["fom"]} for r in runs],
            "comparisons": comparisons}


def _config_diff(a: dict, b: dict) -> dict:
    out = {}
    for k in sorted(set(a) | set(b)):
        av, bv = a.get(k), b.get(k)
        if av != bv:
            out[k] = {"base": av, "current": bv}
    return out


def _delta_waterfall(session: Session, base_id: int, cur_id: int,
                     kind: str, top_n: int = 10) -> list[dict]:
    if kind == "area":
        table, col = AreaRow, AreaRow.total_area
    else:
        table, col = PowerRow, PowerRow.total
    base_rows = {r.scope_path: r for r in session.exec(
        select(table).where(table.run_id == base_id)).all()}
    cur_rows = session.exec(select(table).where(table.run_id == cur_id)).all()
    contribs = []
    for r in cur_rows:
        if r.depth != 2:   # attribute at level-2 module granularity
            continue
        b = base_rows.get(r.scope_path)
        cur_v, base_v = getattr(r, "total" if kind == "power" else "total_area"), (
            getattr(b, "total" if kind == "power" else "total_area") if b else 0.0)
        d = cur_v - base_v
        if abs(d) > 1e-9:
            contribs.append({"module": r.scope_path, "delta": d})
    contribs.sort(key=lambda c: -abs(c["delta"]))
    return contribs[:top_n]


# ---------------------------------------------------------------- V4

def design_space(session: Session, x: str = "total_power_mw", y: str = "specint_score",
                 project_id: int | None = None) -> dict:
    points = []
    for run in _runs(session, project_id):
        m = _metrics(session, run.id)
        fom = {k[len("fom."):]: v for k, v in m.items() if k.startswith("fom.")}
        cfg = session.get(Config, run.config_id)
        points.append({
            "run_id": run.id, "label": run.label,
            "x": fom.get(x, 0.0), "y": fom.get(y, 0.0),
            "config": cfg.params_json if cfg else {}, "fom": fom,
        })
    nd = M.pareto_front(points, "x", "y", x_max=False, y_max=True)
    for i, p in enumerate(points):
        p["pareto"] = i in nd
    return {"x_metric": x, "y_metric": y, "points": points}


# ---------------------------------------------------------------- V5/V6

def area_explorer(session: Session, run_id: int) -> dict:
    rows = session.exec(select(AreaRow).where(AreaRow.run_id == run_id)).all()
    bl = baseline_run(session, run_id)
    bl_rows = {r.scope_path: r for r in session.exec(
        select(AreaRow).where(AreaRow.run_id == bl.id)).all()} if bl else {}
    min_depth = min((r.depth for r in rows), default=0)
    total = next((r.total_area for r in rows if r.depth == min_depth), 0.0)
    items = []
    for r in rows:
        b = bl_rows.get(r.scope_path)
        d_pct = ((r.total_area - b.total_area) / b.total_area) if b and b.total_area else None
        items.append({
            "scope_path": r.scope_path, "parent": r.parent_path, "depth": r.depth,
            "total_area": r.total_area, "comb": r.comb_area, "seq": r.seq_area,
            "macro": r.macro_area, "clock": r.clock_area, "buf_inv": r.buf_inv_area,
            "inst_count": r.inst_count, "share": r.total_area / total if total else 0.0,
            "delta_vs_baseline_pct": d_pct,
            "seq_ratio": r.seq_area / r.total_area if r.total_area else 0.0,
        })
    items.sort(key=lambda i: i["scope_path"])
    return {"run_id": run_id, "total_um2": total, "rows": items}


def power_explorer(session: Session, run_id: int) -> dict:
    rows = session.exec(select(PowerRow).where(PowerRow.run_id == run_id)).all()
    area = {r.scope_path: r for r in session.exec(
        select(AreaRow).where(AreaRow.run_id == run_id)).all()}
    bl = baseline_run(session, run_id)
    bl_rows = {r.scope_path: r for r in session.exec(
        select(PowerRow).where(PowerRow.run_id == bl.id)).all()} if bl else {}
    min_depth = min((r.depth for r in rows), default=0)
    total = next((r.total for r in rows if r.depth == min_depth), 0.0)
    items = []
    for r in rows:
        b = bl_rows.get(r.scope_path)
        d_pct = ((r.total - b.total) / b.total) if b and b.total else None
        a = area.get(r.scope_path)
        items.append({
            "scope_path": r.scope_path, "parent": r.parent_path, "depth": r.depth,
            "internal": r.internal, "switching": r.switching, "leakage": r.leakage,
            "total": r.total, "share": r.total / total if total else 0.0,
            "delta_vs_baseline_pct": d_pct,
            "leak_share": r.leakage / r.total if r.total else 0.0,
            "power_density_mw_um2": (r.total / a.total_area) if a and a.total_area else None,
        })
    items.sort(key=lambda i: i["scope_path"])
    m = _metrics(session, run_id)
    return {"run_id": run_id, "total_mw": total, "rows": items,
            "clock_power_share": m.get("power.clock_power_share"),
            "clock_gating_eff": m.get("power.clock_gating_eff"),
            "toggle_rate": m.get("power.toggle_rate")}


# ---------------------------------------------------------------- V7

def timing_explorer(session: Session, run_id: int) -> dict:
    facts = RunFacts(session, run_id)
    paths = [t for t in facts.paths if not t.is_hold]
    paths.sort(key=lambda t: t.slack_ns)
    # group summary
    groups: dict[str, dict] = {}
    for t in paths:
        g = groups.setdefault(t.path_group, {"name": t.path_group, "wns_ns": 0.0,
                                             "tns_ns": 0.0, "nve": 0, "paths": 0})
        g["paths"] += 1
        g["wns_ns"] = min(g["wns_ns"], t.slack_ns) if g["paths"] > 1 else t.slack_ns
        if t.slack_ns < 0:
            g["nve"] += 1
            g["tns_ns"] += t.slack_ns
    # slack histogram from paths (coarse) + reported histogram if present
    hist = []
    if paths:
        lo = min(p.slack_ns for p in paths)
        hi = max(p.slack_ns for p in paths)
        n_bins = 12
        width = (hi - lo) / n_bins if hi > lo else 1.0
        bins = [0] * n_bins
        for p in paths:
            b = min(int((p.slack_ns - lo) / width), n_bins - 1)
            bins[b] += 1
        hist = [{"lo": round(lo + i * width, 3), "hi": round(lo + (i + 1) * width, 3),
                 "count": c} for i, c in enumerate(bins)]
    # critical-module leaderboard
    counts: dict[str, int] = {}
    for t in paths[:100]:
        counts[t.start_module] = counts.get(t.start_module, 0) + 1
    leaderboard = [{"module": k, "top_paths": v, "share": v / min(len(paths), 100)}
                   for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
    return {
        "run_id": run_id,
        "wns_ns": facts.metrics.get("timing.wns_ns"),
        "tns_ns": facts.metrics.get("timing.tns_ns"),
        "nve": facts.metrics.get("timing.nve"),
        "fmax_mhz": facts.metrics.get("timing.fmax_mhz"),
        "groups": list(groups.values()),
        "histogram": hist,
        "paths": [{
            "path_id": t.path_id, "startpoint": t.startpoint, "endpoint": t.endpoint,
            "group": t.path_group, "slack_ns": t.slack_ns, "logic_depth": t.logic_depth,
            "module": t.start_module,
        } for t in paths[:50]],
        "leaderboard": leaderboard,
    }


# ---------------------------------------------------------------- V8

def perf_explorer(session: Session, run_id: int, baseline_id: int | None = None) -> dict:
    rows = session.exec(select(PerfRow).where(PerfRow.run_id == run_id)).all()
    bl = session.get(Run, baseline_id) if baseline_id else baseline_run(session, run_id)
    bl_rows = {r.benchmark: r for r in session.exec(
        select(PerfRow).where(PerfRow.run_id == bl.id)).all()} if bl else {}
    out = []
    for r in rows:
        b = bl_rows.get(r.benchmark)
        ipc_pct = ((r.ipc - b.ipc) / b.ipc) if b and b.ipc else None
        out.append({
            "benchmark": r.benchmark, "ipc": r.ipc, "ratio_1ghz": r.ratio_1ghz,
            "l1d_mpki": r.l1d_mpki, "l2_mpki": r.l2_mpki,
            "br_mispred_pct": r.br_mispred_pct, "ipc_delta_pct": ipc_pct,
        })
    m = _metrics(session, run_id)
    bl_m = _metrics(session, bl.id) if bl else {}
    return {
        "run_id": run_id,
        "baseline_id": bl.id if bl else None,
        "geomean_ratio_1ghz": m.get("perf.geomean_ratio_1ghz"),
        "geomean_delta_pct": (
            (m.get("perf.geomean_ratio_1ghz", 0) - bl_m.get("perf.geomean_ratio_1ghz", 0))
            / bl_m["perf.geomean_ratio_1ghz"] * 100
        ) if bl_m.get("perf.geomean_ratio_1ghz") else None,
        "rows": out,
    }


# ---------------------------------------------------------------- V9

def hotspot(session: Session, run_id: int) -> dict:
    facts = RunFacts(session, run_id)
    power = {p.scope_path: p for p in facts.power}
    bl_area = facts.baseline_area
    bl_power: dict[str, PowerRow] = {}
    if facts.baseline_run_id:
        bl_power = {p.scope_path: p for p in session.exec(
            select(PowerRow).where(PowerRow.run_id == facts.baseline_run_id)).all()}
    top_paths = [t for t in facts.paths if not t.is_hold][:100]
    crit: dict[str, int] = {}
    for t in top_paths:
        crit[t.start_module] = crit.get(t.start_module, 0) + 1
    total_area = next((a.total_area for a in facts.area
                       if a.depth == min((x.depth for x in facts.area), default=1)), 0.0)
    total_power = next((p.total for p in facts.power
                        if p.depth == min((x.depth for x in facts.power), default=1)), 0.0)
    rows = []
    for a in facts.area:
        if a.depth != 2:
            continue
        p = power.get(a.scope_path)
        share_a = a.total_area / total_area if total_area else 0.0
        share_p = (p.total / total_power) if p and total_power else 0.0
        crit_share = crit.get(a.scope_path, 0) / len(top_paths) if top_paths else 0.0
        b_a = bl_area.get(a.scope_path)
        b_p = bl_power.get(a.scope_path)
        rows.append({
            "module": a.scope_path, "area_um2": a.total_area, "area_share": share_a,
            "power_mw": p.total if p else 0.0, "power_share": share_p,
            "power_density": (p.total / a.total_area) if p and a.total_area else 0.0,
            "criticality": crit_share,
            "area_delta_pct": ((a.total_area - b_a.total_area) / b_a.total_area)
            if b_a and b_a.total_area else None,
            "power_delta_pct": ((p.total - b_p.total) / b_p.total)
            if p and b_p and b_p.total else None,
        })
    rows.sort(key=lambda r: -(r["area_share"] + r["power_share"] + r["criticality"]))
    return {"run_id": run_id, "rows": rows}


# ---------------------------------------------------------------- V10

def findings(session: Session, run_id: int | None = None,
             severity: str | None = None, category: str | None = None,
             status: str | None = None) -> list[dict]:
    q = select(Finding)
    if run_id:
        q = q.where(Finding.run_id == run_id)
    if severity:
        q = q.where(Finding.severity == severity)
    if category:
        q = q.where(Finding.category == category)
    if status:
        q = q.where(Finding.status == status)
    out = []
    for f in session.exec(q).all():
        d = _finding_dict(f)
        run = session.get(Run, f.run_id)
        d["run_label"] = run.label if run else ""
        out.append(d)
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    out.sort(key=lambda d: (order.get(d["severity"], 9), d["category"]))
    return out


# ---------------------------------------------------------------- V11

def ingest_status(session: Session) -> list[dict]:
    out = []
    for r in session.exec(select(RawReport)).all():
        run = session.get(Run, r.run_id)
        out.append({
            "run_id": r.run_id, "run_label": run.label if run else "",
            "kind": r.kind, "file": r.file_path, "sha256": r.sha256[:12],
            "parser_version": r.parser_version, "status": r.parse_status,
            "log": r.parse_log[:500],
        })
    return out
