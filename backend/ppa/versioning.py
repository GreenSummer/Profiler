"""Version-series analysis engine (v2): the accumulation story.

- version_series(): ordered RTL versions with headline metrics + change notes
- detect_change_points(): robust step/spike/trend detection (median + k*MAD)
  over version-to-version deltas, with module attribution; persisted as
  ChangeEvent rows and surfaced as findings under category "version_change"
- correlations(): Pearson r between performance and PPA metrics across
  versions, plus per-module correlations
- signal_search(): substring search over timing startpoints/endpoints
  (slack history per version) and raw report text
- trace_to_source(): the exact raw report lines backing a plotted value
  (via src_line provenance stored at ingest)

All statistics are deterministic Python — the LLM layer only narrates.
"""
from __future__ import annotations

import math
import re
from datetime import datetime

from sqlmodel import Session, select

from .models import (
    AreaRow, ChangeEvent, Design, Finding, Metric, PerfRow, PowerRow,
    Project, RawReport, Run, TimingPath,
)

# metric-table key -> display key used in ChangeEvent rows and the API
DISPLAY_KEYS = {
    "fom.area_mm2": "area_mm2",
    "fom.total_power_mw": "total_power_mw",
    "fom.specint_score": "specint_score",
    "fom.specint_per_ghz": "specint_per_ghz",
    "fom.fmax_mhz": "fmax_mhz",
    "perf.geomean_ratio_1ghz": "geomean_ratio_1ghz",
    "timing.wns_ns": "wns_ns",
    "timing.tns_ns": "tns_ns",
    "power.leakage_share": "leakage_share",
    "power.clock_gating_eff": "clock_gating_eff",
}
# display key -> metric-table key (reverse of above, for series lookup)
METRIC_KEYS = {v: k for k, v in DISPLAY_KEYS.items()}

SERIES_DISPLAY_KEYS = [
    "specint_score", "specint_per_ghz", "fmax_mhz", "geomean_ratio_1ghz",
    "area_mm2", "total_power_mw", "wns_ns", "tns_ns",
    "leakage_share", "clock_gating_eff",
]

# (metric-table key, mode, min change): mode "rel" = relative delta,
# "abs" = absolute delta (wns/cg where relative deltas are meaningless
# near zero crossings). z_min is the robust-z detection threshold.
_DETECT_SPECS = [
    ("fom.area_mm2", "rel", 0.010),
    ("fom.total_power_mw", "rel", 0.010),
    ("fom.specint_score", "rel", 0.010),
    ("perf.geomean_ratio_1ghz", "rel", 0.010),
    ("power.leakage_share", "rel", 0.020),
    ("timing.wns_ns", "abs", 0.020),
    ("power.clock_gating_eff", "abs", 5.0),
]
Z_MIN = 4.0


def _version_sort_key(version: str) -> tuple:
    parts = re.findall(r"\d+", version or "")
    return tuple(int(p) for p in parts) if parts else (9999,)


def _metrics_of(session: Session, run_id: int) -> dict[str, float]:
    return {m.key: m.value for m in session.exec(
        select(Metric).where(Metric.run_id == run_id)).all()}


# ---------------------------------------------------------------- series

def version_series(session: Session, project_id: int | None = None,
                   model: str = "synth") -> dict:
    """Ordered versions (one run per design) with headline metrics and
    change notes. `model` selects the provenance series (synth is the full
    RTL synthesis axis; gem5/slice/zebu/fogs are perf-model series).
    Falls back to the single project when project_id is None."""
    if project_id is None:
        project = session.exec(select(Project)).first()
        if project is None:
            return {"project_id": None, "series": []}
        project_id = project.id
    designs = session.exec(
        select(Design).where(Design.project_id == project_id,
                              Design.model == model)).all()
    designs = [d for d in designs if d.version]  # version axis only
    designs.sort(key=lambda d: (_version_sort_key(d.version), d.date))
    series = []
    for d in designs:
        run = session.exec(
            select(Run).where(Run.design_id == d.id)
            .order_by(Run.started_at)).first()
        if run is None:
            continue
        m = _metrics_of(session, run.id)
        series.append({
            "version": d.version,
            "run_id": run.id,
            "label": run.label,
            "date": d.date.date().isoformat() if isinstance(d.date, datetime) else str(d.date),
            "sha": d.rtl_git_sha,
            "change_note": d.change_note,
            "stage": run.stage,
            "metrics": {dk: m.get(mk) for dk, mk in
                        ((dk, METRIC_KEYS[dk]) for dk in SERIES_DISPLAY_KEYS)},
        })
    return {"project_id": project_id, "series": series}


# ---------------------------------------------------------------- detection

def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _detect_metric(series: list[dict], key: str, mode: str,
                   min_change: float, z_min: float = Z_MIN) -> list[dict]:
    """Candidate change points for one metric: {to_idx, delta, change, z}.
    `key` is a metric-table key; series metrics are keyed by display key."""
    display = DISPLAY_KEYS.get(key, key)
    vals = [s["metrics"].get(display) for s in series]
    deltas: list[float] = []
    changes: list[float] = []
    idxs: list[int] = []
    for i in range(1, len(vals)):
        a, b = vals[i - 1], vals[i]
        if a is None or b is None:
            continue
        d = b - a
        change = d / abs(a) if (mode == "rel" and a) else d
        deltas.append(d)
        changes.append(change)
        idxs.append(i)
    if not changes:
        return []
    # robust z on the NORMALIZED change (rel or abs per mode), so the
    # severity scale is comparable across metrics with different units
    med = _median(changes)
    mad = _median([abs(c - med) for c in changes])
    scale = max(1.4826 * mad, min_change / 4.0, 1e-12)
    out = []
    for i, d, change in zip(idxs, deltas, changes):
        z = (change - med) / scale
        if abs(z) >= z_min and abs(change) >= min_change:
            out.append({"to_idx": i, "delta": d, "change": change, "z": z})
    return out


def _classify(cands: list[dict]) -> dict[int, str]:
    """method per candidate index: step | spike | recovery | trend.
    spike = reverts next version; trend = 2+ consecutive same-sign."""
    methods: dict[int, str] = {}
    j = 0
    while j < len(cands):
        i, d = cands[j]["to_idx"], cands[j]["delta"]
        nxt = cands[j + 1] if j + 1 < len(cands) else None
        if nxt and nxt["to_idx"] == i + 1 and nxt["delta"] * d < 0 \
                and abs(nxt["delta"]) >= 0.5 * abs(d):
            methods[i] = "spike"
            methods[i + 1] = "recovery"
            j += 2
            continue
        if nxt and nxt["to_idx"] == i + 1 and nxt["delta"] * d > 0:
            k = j
            while (k < len(cands) and cands[k]["to_idx"] == i + (k - j)
                   and cands[k]["delta"] * d > 0):
                methods[cands[k]["to_idx"]] = "trend"
                k += 1
            j = k
            continue
        methods[i] = "step"
        j += 1
    return methods


def _severity(z: float) -> str:
    az = abs(z)
    if az >= 20:
        return "high"
    if az >= 8:
        return "medium"
    return "low"


def _top_module_delta(session: Session, from_run: int, to_run: int,
                      kind: str) -> tuple[str | None, float]:
    """Biggest depth-2 contributor to the change between two runs."""
    from .analysis import _delta_waterfall
    wf = _delta_waterfall(session, from_run, to_run, kind, top_n=1)
    if not wf:
        return None, 0.0
    return wf[0]["module"], wf[0]["delta"]


def _worst_path_module(session: Session, run_id: int) -> tuple[str | None, float]:
    """Deepest common-ancestor module and slack of the worst setup path."""
    from .canonicalize import common_ancestor
    t = session.exec(select(TimingPath).where(TimingPath.run_id == run_id)).all()
    worst = min((p for p in t if not p.is_hold), key=lambda p: p.slack_ns,
                default=None)
    if worst is None:
        return None, 0.0
    ca = common_ancestor(worst.startpoint, worst.endpoint)
    return (ca or worst.start_module, worst.slack_ns)


def refresh_change_events(session: Session, project_id: int) -> list[dict]:
    """Recompute and persist ChangeEvents (+ version_change findings) for a
    project. Called at the end of ingest and safe to re-run."""
    # clear previous output of this detector
    for ce in session.exec(select(ChangeEvent)
                           .where(ChangeEvent.project_id == project_id)).all():
        session.delete(ce)
    design_ids = [d.id for d in session.exec(
        select(Design).where(Design.project_id == project_id)).all()]
    if design_ids:
        runs = session.exec(select(Run)).all()
        run_ids = {r.id for r in runs if r.design_id in design_ids}
        for f in session.exec(select(Finding).where(
                Finding.rule_id == "VC_CHANGE_POINT")).all():
            if f.run_id in run_ids:
                session.delete(f)
    session.commit()

    data = version_series(session, project_id)
    series = data["series"]
    if len(series) < 3:
        session.commit()
        return []

    events: list[dict] = []
    for key, mode, min_change in _DETECT_SPECS:
        cands = _detect_metric(series, key, mode, min_change)
        if not cands:
            continue
        methods = _classify(cands)
        display = DISPLAY_KEYS.get(key, key)
        for c in cands:
            i = c["to_idx"]
            frm, to = series[i - 1], series[i]
            scope, mod_delta = (None, 0.0)
            if key in ("fom.area_mm2",):
                scope, mod_delta = _top_module_delta(session, frm["run_id"], to["run_id"], "area")
            elif key in ("fom.total_power_mw",):
                scope, mod_delta = _top_module_delta(session, frm["run_id"], to["run_id"], "power")
            elif key in ("timing.wns_ns",):
                # attribute a WNS change to the owner of the new worst path
                scope, mod_delta = _worst_path_module(session, to["run_id"])
            sev = _severity(c["z"])
            ev = {
                "project_id": project_id,
                "from_run_id": frm["run_id"], "to_run_id": to["run_id"],
                "metric_key": display, "scope_path": scope,
                "delta_pct": c["change"], "magnitude": c["z"],
                "method": methods.get(i, "step"), "severity": sev,
                "note": to["change_note"],
                "from_version": frm["version"], "to_version": to["version"],
                "delta": c["delta"], "module_delta": mod_delta,
            }
            events.append(ev)

    events.sort(key=lambda e: (_version_sort_key(e["to_version"]), e["metric_key"]))
    for ev in events:
        session.add(ChangeEvent(
            project_id=ev["project_id"],
            from_run_id=ev["from_run_id"], to_run_id=ev["to_run_id"],
            metric_key=ev["metric_key"], scope_path=ev["scope_path"],
            delta_pct=ev["delta_pct"], magnitude=ev["magnitude"],
            method=ev["method"], severity=ev["severity"], note=ev["note"],
        ))
        if ev["severity"] in ("high", "medium"):
            session.add(Finding(
                run_id=ev["to_run_id"], rule_id="VC_CHANGE_POINT",
                severity=ev["severity"], category="version_change",
                scope_path=ev["scope_path"],
                title=_event_title(ev), evidence_json={
                    "from_version": ev["from_version"], "to_version": ev["to_version"],
                    "metric": ev["metric_key"], "change": round(ev["delta_pct"], 4),
                    "z": round(ev["magnitude"], 1), "method": ev["method"],
                    "top_module": ev["scope_path"], "module_delta": round(ev["module_delta"], 1),
                    "note": ev["note"]},
            ))
    session.commit()
    return events


def _event_title(ev: dict) -> str:
    disp = ev["metric_key"].replace("_", " ")
    change = ev["delta_pct"]
    if ev["metric_key"] in ("wns_ns", "clock_gating_eff"):
        pct_txt = f"{change:+.3f}"
    else:
        pct_txt = f"{change * 100:+.1f}%"
    verb = {"step": "changed", "spike": "spiked", "recovery": "recovered",
            "trend": "drifted"}[ev["method"]]
    mod = f" ({ev['scope_path'].rsplit('/', 1)[-1]})" if ev["scope_path"] else ""
    return (f"{disp} {verb} {pct_txt} at {ev['to_version']}"
            f" (vs {ev['from_version']}){mod}")


def change_points(session: Session, project_id: int | None = None) -> list[dict]:
    """Persisted ChangeEvents, enriched with version labels for the API."""
    if project_id is None:
        project = session.exec(select(Project)).first()
        project_id = project.id if project else None
    if project_id is None:
        return []
    runs = {r.id: r for r in session.exec(select(Run)).all()}
    designs = {d.id: d for d in session.exec(select(Design)).all()}
    out = []
    for ce in session.exec(select(ChangeEvent)
                           .where(ChangeEvent.project_id == project_id)).all():
        frm, to = runs.get(ce.from_run_id), runs.get(ce.to_run_id)
        d_frm = designs.get(frm.design_id) if frm else None
        d_to = designs.get(to.design_id) if to else None
        out.append({
            "id": ce.id, "from_run_id": ce.from_run_id, "to_run_id": ce.to_run_id,
            "from_version": d_frm.version if d_frm else "",
            "to_version": d_to.version if d_to else "",
            "metric_key": ce.metric_key, "scope_path": ce.scope_path,
            "delta_pct": ce.delta_pct, "magnitude": ce.magnitude,
            "method": ce.method, "severity": ce.severity, "note": ce.note,
        })
    out.sort(key=lambda e: (_version_sort_key(e["to_version"]), e["metric_key"]))
    return out


# ---------------------------------------------------------------- overview board

# release-board module categories (depth-1 cells of core_top)
_BOARD_CATEGORIES = [
    ("Frontend", "core_top/u_ifu"),
    ("Backend", "core_top/u_ex"),
    ("Memblock", "core_top/u_lsu"),
    ("L2 top", "core_top/u_l2"),
]
PERF_MODEL_ORDER = ["gem5", "slice", "zebu", "fogs"]


def _geom(xs: list[float]) -> float:
    xs = [x for x in xs if x and x > 0]
    if not xs:
        return 0.0
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def _project_of(session: Session, project_id: int | None) -> Project | None:
    if project_id is not None:
        return session.get(Project, project_id)
    return session.exec(select(Project)).first()


def _design_runs(session: Session) -> dict[tuple[str, str], int]:
    """(model, version) -> first run id, for every versioned design."""
    out: dict[tuple[str, str], int] = {}
    for d in session.exec(select(Design)).all():
        if not d.version:
            continue
        run = session.exec(select(Run).where(Run.design_id == d.id)
                           .order_by(Run.started_at)).first()
        if run is not None:
            out[(d.model or "synth", d.version)] = run.id
    return out


def _perf_rows(session: Session, run_id: int) -> dict[str, PerfRow]:
    return {r.benchmark: r for r in session.exec(
        select(PerfRow).where(PerfRow.run_id == run_id)).all()}


def overview_board(session: Session, project_id: int | None = None) -> dict:
    """One payload for the release overview board: geomean + perf/area trends
    across the provenance series, benchmark ratio/IPC trends, the synthesis
    area stack, timing closure metrics and the 6-metric PPA board."""
    project = _project_of(session, project_id)
    if project is None:
        return {"versions": [], "models": PERF_MODEL_ORDER}
    project_id = project.id
    settings = project.settings_json or {}
    target_geomean = float(settings.get("target_geomean", 1.45))
    budget = project.area_budget_mm2 or 2.0

    series = version_series(session, project_id, model="synth")["series"]
    versions = [s["version"] for s in series]
    syn_run = {s["version"]: s["run_id"] for s in series}
    syn_metrics = {s["version"]: s["metrics"] for s in series}
    dr = _design_runs(session)

    # ---- P1: geomean per model; P2/P3: benchmark ratio + IPC trends
    geomean: dict[str, list] = {
        "synth": [syn_metrics[v].get("geomean_ratio_1ghz") for v in versions]}
    ratio_by_model: dict[str, dict[str, list]] = {}
    ipc_by_model: dict[str, dict[str, list]] = {}
    bench_names: list[str] = []
    for model in PERF_MODEL_ORDER:
        gm, ratios, ipcs = [], {}, {}
        for v in versions:
            rid = dr.get((model, v))
            rows = _perf_rows(session, rid) if rid else {}
            gm.append(_geom([r.ratio_1ghz for r in rows.values()]) if rows else None)
            for b, r in rows.items():
                ratios.setdefault(b, []).append(round(r.ratio_1ghz, 4))
                ipcs.setdefault(b, []).append(round(r.ipc, 3))
                if b not in bench_names:
                    bench_names.append(b)
        geomean[model] = gm
        ratio_by_model[model] = ratios
        ipc_by_model[model] = ipcs
    benchmarks = {b: {m: ratio_by_model[m].get(b, []) for m in PERF_MODEL_ORDER}
                  for b in bench_names}
    ipc = {b: {m: ipc_by_model[m].get(b, []) for m in PERF_MODEL_ORDER}
           for b in bench_names}

    perf_per_area = []
    for v in versions:
        m = syn_metrics[v]
        score, area = m.get("specint_score"), m.get("area_mm2")
        perf_per_area.append(round(score / area, 3) if score and area else None)

    # ---- P4: area stack (4 categories + other, sums to core total)
    syn_ids = [syn_run[v] for v in versions]
    area_by_run: dict[int, dict[str, AreaRow]] = {}
    for a in session.exec(select(AreaRow)
                          .where(AreaRow.run_id.in_(syn_ids))).all():  # type: ignore[attr-defined]
        area_by_run.setdefault(a.run_id, {})[a.scope_path] = a
    stack = {cat: [] for cat, _ in _BOARD_CATEGORIES}
    stack["Other"] = []
    for v in versions:
        rmap = area_by_run.get(syn_run[v], {})
        core = rmap.get("core_top")
        core_area = core.total_area if core else 0.0
        placed = 0.0
        for cat, path in _BOARD_CATEGORIES:
            a = rmap.get(path)
            val = a.total_area if a else 0.0
            stack[cat].append(round(val / 1e6, 5))
            placed += val
        stack["Other"].append(round(max(core_area - placed, 0.0) / 1e6, 5))

    # ---- P5: timing closure metrics
    nve_by_run = {met.run_id: met.value for met in session.exec(
        select(Metric).where(Metric.key == "timing.nve",
                             Metric.run_id.in_(syn_ids))).all()}  # type: ignore[attr-defined]
    timing = {
        "wns": [syn_metrics[v].get("wns_ns") for v in versions],
        "tns": [syn_metrics[v].get("tns_ns") for v in versions],
        "nve": [int(nve_by_run.get(syn_run[v], 0)) for v in versions],
    }

    # ---- P6: board metrics (derived from stored tables; congestion has no
    # synth-stage source and stays a null placeholder)
    max_depth: dict[int, int] = {}
    for t in session.exec(select(TimingPath)
                          .where(TimingPath.run_id.in_(syn_ids))).all():  # type: ignore[attr-defined]
        if not t.is_hold:
            max_depth[t.run_id] = max(max_depth.get(t.run_id, 0), t.logic_depth)
    board = []
    for v in versions:
        rid = syn_run[v]
        rmap = area_by_run.get(rid, {})
        m = syn_metrics[v]
        core = rmap.get("core_top")
        die = rmap.get("die_total")
        core_um2 = core.total_area if core else None
        die_um2 = die.total_area if die else None
        board.append({
            "max_logic_levels": max_depth.get(rid),
            "gated_pct": m.get("clock_gating_eff"),
            "core_area_um2": core_um2,
            "die_area_um2": die_um2,
            "comb_share": round(core.comb_area / core.total_area, 4)
            if core and core.total_area else None,
            "util_proxy": round(core_um2 / die_um2, 4)
            if core_um2 and die_um2 else None,
            "congestion_overflow": None,
        })

    return {
        "project_id": project_id, "versions": versions,
        "models": PERF_MODEL_ORDER, "benchmarks_names": bench_names,
        "area_budget_mm2": budget, "target_geomean": target_geomean,
        "target_eff": round(target_geomean / budget, 4),
        "geomean": geomean,
        "perf_per_area": perf_per_area,
        "benchmarks": benchmarks,
        "ipc": ipc,
        "area_breakdown": {"categories": [c for c, _ in _BOARD_CATEGORIES] + ["Other"],
                           "values": stack},
        "timing": timing,
        "board": board,
    }


# ---------------------------------------------------------------- drill + compare

def _synth_run_for(session: Session, version: str,
                   project_id: int | None = None) -> tuple[Design | None, Run | None]:
    q = select(Design).where(Design.version == version, Design.model == "synth")
    if project_id is not None:
        q = q.where(Design.project_id == project_id)
    design = session.exec(q).first()
    if design is None:
        return None, None
    run = session.exec(select(Run).where(Run.design_id == design.id)
                       .order_by(Run.started_at)).first()
    return design, run


def _module_area_rows(session: Session, run_id: int) -> dict[str, AreaRow]:
    """Top-level module rows (core_top/u_* live at depth 2 here; the report
    total row is depth 0/1 and excluded)."""
    return {a.scope_path: a for a in session.exec(
        select(AreaRow).where(AreaRow.run_id == run_id, AreaRow.depth == 2,
                              AreaRow.scope_path != "Total")).all()}


def version_drill(session: Session, version: str,
                  project_id: int | None = None) -> dict:
    """Module- and signal-level drill-down for one synthesis version:
    change note, detected events, depth-1 module table with deltas vs the
    previous version, and the worst timing signals (trace-ready)."""
    design, run = _synth_run_for(session, version, project_id)
    if design is None or run is None:
        return {"version": version, "found": False}
    events = [e for e in change_points(session, project_id)
              if e["to_version"] == version]

    # previous synth version for deltas
    series = version_series(session, project_id, model="synth")["series"]
    idx = next((i for i, s in enumerate(series) if s["version"] == version), None)
    prev_run = series[idx - 1]["run_id"] if idx else None

    area = _module_area_rows(session, run.id)
    power = {p.scope_path: p for p in session.exec(
        select(PowerRow).where(PowerRow.run_id == run.id)).all()}
    prev_area = (_module_area_rows(session, prev_run) if prev_run else {})
    prev_power = ({p.scope_path: p for p in session.exec(
        select(PowerRow).where(PowerRow.run_id == prev_run)).all()}
        if prev_run else {})
    modules = []
    for path, a in sorted(area.items()):
        p = power.get(path)
        pa, pp = prev_area.get(path), prev_power.get(path)
        modules.append({
            "scope_path": path,
            "area_um2": round(a.total_area / 1e6, 5),
            "power_mw": p.total if p else None,
            "area_delta_pct": ((a.total_area - pa.total_area) / pa.total_area)
            if pa and pa.total_area else None,
            "power_delta_pct": ((p.total - pp.total) / pp.total)
            if p and pp and pp.total else None,
        })

    paths = [t for t in session.exec(
        select(TimingPath).where(TimingPath.run_id == run.id)).all()
        if not t.is_hold]
    paths.sort(key=lambda t: t.slack_ns)
    signals = [{
        "path_id": t.path_id, "startpoint": t.startpoint, "endpoint": t.endpoint,
        "slack_ns": t.slack_ns, "logic_depth": t.logic_depth,
        "module": t.start_module,
    } for t in paths[:10]]

    return {
        "version": version, "found": True, "run_id": run.id,
        "sha": design.rtl_git_sha, "change_note": design.change_note,
        "date": design.date.date().isoformat()
        if isinstance(design.date, datetime) else str(design.date),
        "events": events, "modules": modules, "signals": signals,
    }


def version_compare_multi(session: Session, versions: list[str],
                          project_id: int | None = None) -> dict:
    """Module area/power + IPC + signal-slack matrices across several
    synthesis versions; deltas are relative to the earliest selected."""
    vs = sorted({v for v in versions if v}, key=_version_sort_key)
    pairs = [_synth_run_for(session, v, project_id) for v in vs]
    vs = [v for v, (d, r) in zip(vs, pairs) if d and r]
    run_ids = [r.id for _, r in pairs if r]
    if len(vs) < 2:
        return {"versions": vs, "run_ids": run_ids, "modules": [],
                "benchmarks": [], "signals": []}

    # ---- module matrix (top-level modules)
    area_by_run: dict[int, dict[str, AreaRow]] = {}
    power_by_run: dict[int, dict[str, PowerRow]] = {}
    for rid in run_ids:
        area_by_run[rid] = _module_area_rows(session, rid)
        power_by_run[rid] = {p.scope_path: p for p in session.exec(
            select(PowerRow).where(PowerRow.run_id == rid)).all()}
    paths_seen: set[str] = set()
    for rid in run_ids:
        paths_seen |= set(area_by_run[rid])
    modules = []
    base_rid = run_ids[0]
    for path in sorted(paths_seen):
        base_a = area_by_run[base_rid].get(path)
        base_p = power_by_run[base_rid].get(path)
        a_vals, p_vals, a_d, p_d = [], [], [], []
        for rid in run_ids:
            a = area_by_run[rid].get(path)
            p = power_by_run[rid].get(path)
            a_vals.append(round(a.total_area / 1e6, 5) if a else None)
            p_vals.append(p.total if p else None)
            a_d.append((a.total_area - base_a.total_area) / base_a.total_area
                       if a and base_a and base_a.total_area else None)
            p_d.append((p.total - base_p.total) / base_p.total
                       if p and base_p and base_p.total else None)
        modules.append({"scope_path": path, "area_mm2": a_vals,
                        "power_mw": p_vals, "area_delta_pct": a_d,
                        "power_delta_pct": p_d})

    # ---- per-benchmark IPC (zebu = the synth-adjacent perf model)
    dr = _design_runs(session)
    zebu_runs = [dr.get(("zebu", v)) for v in vs]
    zrows = [_perf_rows(session, rid) if rid else {} for rid in zebu_runs]
    bench_names = sorted({b for rows in zrows for b in rows})
    bench_out = []
    for b in bench_names:
        ipcs = [rows.get(b).ipc if rows.get(b) else None for rows in zrows]
        base = ipcs[0]
        bench_out.append({
            "benchmark": b, "ipc": [round(x, 3) if x else None for x in ipcs],
            "ipc_delta_pct": [((x - base) / base) if x and base else None
                              for x in ipcs],
        })

    # ---- signal slack matrix (signals present in ALL selected versions)
    hist: dict[tuple[str, str], dict[int, TimingPath]] = {}
    for rid in run_ids:
        for t in session.exec(select(TimingPath)
                              .where(TimingPath.run_id == rid)).all():
            if not t.is_hold:
                hist.setdefault((t.startpoint, t.endpoint), {})[rid] = t
    signals = []
    for (sp, ep), by_run in hist.items():
        if any(rid not in by_run for rid in run_ids):
            continue
        slacks = [by_run[rid].slack_ns for rid in run_ids]
        signals.append({
            "startpoint": sp, "endpoint": ep,
            "module": by_run[run_ids[0]].start_module,
            "path_ids": [by_run[rid].path_id for rid in run_ids],
            "slacks": slacks, "worst": min(slacks),
        })
    signals.sort(key=lambda s: s["worst"])
    return {"versions": vs, "run_ids": run_ids, "modules": modules,
            "benchmarks": bench_out, "signals": signals[:20]}


# ---------------------------------------------------------------- correlations

def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 1e-18 or syy <= 1e-18:
        return None
    return sxy / math.sqrt(sxx * syy)


_PERF_KEYS = ["specint_score", "geomean_ratio_1ghz", "fmax_mhz"]
_PPA_KEYS = ["area_mm2", "total_power_mw", "wns_ns", "leakage_share",
             "clock_gating_eff"]


def correlations(session: Session, project_id: int | None = None) -> dict:
    """Perf x PPA correlation matrix across the version series, plus
    per-module area/power correlation with the net score."""
    series = version_series(session, project_id)["series"]
    pairs = []
    for pk in _PERF_KEYS:
        for qk in _PPA_KEYS:
            xs = [s["metrics"].get(pk) for s in series]
            ys = [s["metrics"].get(qk) for s in series]
            xy = [(x, y) for x, y in zip(xs, ys)
                  if x is not None and y is not None]
            r = _pearson([x for x, _ in xy], [y for _, y in xy])
            if r is not None:
                pairs.append({"perf": pk, "ppa": qk, "r": round(r, 3),
                              "n": len(xy)})

    # module-level: area / power series vs net score
    if series:
        score_by_run = {s["run_id"]: s["metrics"].get("specint_score")
                        for s in series}
        run_ids = [s["run_id"] for s in series]
        area_vals: dict[str, dict[int, float]] = {}
        power_vals: dict[str, dict[int, float]] = {}
        for rid in run_ids:
            for a in session.exec(select(AreaRow)
                                  .where(AreaRow.run_id == rid)).all():
                if a.depth == 2:
                    area_vals.setdefault(a.scope_path, {})[rid] = a.total_area
            for p in session.exec(select(PowerRow)
                                  .where(PowerRow.run_id == rid)).all():
                if p.depth == 2:
                    power_vals.setdefault(p.scope_path, {})[rid] = p.total
        mods = []
        for path, vals in area_vals.items():
            xy = [(v, score_by_run[rid]) for rid, v in vals.items()
                  if score_by_run.get(rid) is not None]
            r = _pearson([x for x, _ in xy], [y for _, y in xy])
            if r is not None and len(xy) >= 8:
                mods.append({"module": path, "metric": "area_um2",
                             "r": round(r, 3), "n": len(xy)})
        for path, vals in power_vals.items():
            xy = [(v, score_by_run[rid]) for rid, v in vals.items()
                  if score_by_run.get(rid) is not None]
            r = _pearson([x for x, _ in xy], [y for _, y in xy])
            if r is not None and len(xy) >= 8:
                mods.append({"module": path, "metric": "power_mw",
                             "r": round(r, 3), "n": len(xy)})
        mods.sort(key=lambda m: -abs(m["r"]))
    else:
        mods = []
    return {"pairs": pairs, "modules": mods[:12]}


# ---------------------------------------------------------------- signal search

def signal_search(session: Session, query: str, limit: int = 40) -> dict:
    """Search modules, timing signals (with slack history across versions)
    and raw report text. Case-insensitive substring match."""
    q = (query or "").strip().lower()
    if len(q) < 2:
        return {"query": query, "modules": [], "signals": [], "text": []}

    runs = session.exec(select(Run)).all()
    designs = {d.id: d for d in session.exec(select(Design)).all()}
    run_version = {r.id: (designs.get(r.design_id).version
                          if designs.get(r.design_id) else r.label)
                   for r in runs}

    # --- modules (canonical hierarchy paths)
    modules: list[dict] = []
    seen: set[str] = set()
    for a in session.exec(select(AreaRow)).all():
        if q in a.scope_path.lower() and a.scope_path not in seen:
            seen.add(a.scope_path)
            modules.append({"scope_path": a.scope_path, "run_id": a.run_id})
            if len(modules) >= 10:
                break

    # --- timing signals: group (startpoint, endpoint) -> slack history
    groups: dict[tuple[str, str], list[dict]] = {}
    for t in session.exec(select(TimingPath)).all():
        if q in t.startpoint.lower() or q in t.endpoint.lower():
            groups.setdefault((t.startpoint, t.endpoint), []).append({
                "run_id": t.run_id, "version": run_version.get(t.run_id, ""),
                "slack_ns": t.slack_ns, "path_id": t.path_id,
            })
    signals = []
    from .canonicalize import common_ancestor
    for (sp, ep), hist in groups.items():
        hist.sort(key=lambda h: _version_sort_key(h["version"]))
        first = session.exec(select(TimingPath).where(
            TimingPath.startpoint == sp, TimingPath.endpoint == ep)).first()
        signals.append({
            "startpoint": sp, "endpoint": ep,
            "module": common_ancestor(sp, ep) or (first.start_module if first else ""),
            "history": hist,
        })
        if len(signals) >= 15:
            break

    # --- raw report text
    text: list[dict] = []
    for r in session.exec(select(RawReport)).all():
        if not r.content:
            continue
        for no, line in enumerate(r.content.splitlines(), 1):
            if q in line.lower():
                text.append({
                    "run_id": r.run_id, "version": run_version.get(r.run_id, ""),
                    "kind": r.kind, "file": r.file_path.rsplit("/", 1)[-1],
                    "line": no, "text": line.strip()[:160],
                })
                if len(text) >= limit:
                    return {"query": query, "modules": modules,
                            "signals": signals, "text": text}
    return {"query": query, "modules": modules, "signals": signals, "text": text}


# ---------------------------------------------------------------- trace

_TRACE_KINDS = {"area": ("rtla_area", AreaRow), "power": ("primepower", PowerRow),
                "timing": ("rtla_timing", TimingPath), "perf": ("specint", PerfRow)}
_RAW_KINDS = {"rtla_area", "rtla_timing", "rtla_qor", "primepower", "specint"}


def _report_header(report: RawReport) -> dict:
    return {"kind": report.kind, "file": report.file_path,
            "sha256": report.sha256[:12],
            "parser_version": report.parser_version,
            "parse_status": report.parse_status}


def trace_to_source(session: Session, run_id: int, kind: str,
                    scope_path: str | None = None, path_id: int | None = None,
                    benchmark: str | None = None, line: int | None = None,
                    context: int = 5) -> dict:
    """Exact raw report lines backing one plotted value (src_line provenance).

    kind may instead be a raw report kind (rtla_area, primepower, …) together
    with `line` — the drill-down path for global-search text hits."""
    if kind in _RAW_KINDS:
        report = session.exec(select(RawReport).where(
            RawReport.run_id == run_id, RawReport.kind == kind)).first()
        if report is None or not report.content:
            return {"found": False, "run_id": run_id, "kind": kind,
                    "error": "raw report text not stored"}
        lines = report.content.splitlines()
        src = max(1, min(int(line or 1), len(lines)))
        start = max(1, src - context)
        end = min(len(lines), src + context)
        return {
            "found": True, "run_id": run_id, "kind": kind,
            "target": {"kind": kind, "line": src},
            "report": _report_header(report), "src_line": src,
            "lines": [{"no": no, "text": lines[no - 1], "hit": no == src}
                      for no in range(start, end + 1)],
        }
    if kind not in _TRACE_KINDS:
        raise ValueError(f"kind must be one of {sorted(_TRACE_KINDS)}")
    report_kind, table = _TRACE_KINDS[kind]
    row = None
    q = select(table).where(table.run_id == run_id)
    if kind == "timing":
        if path_id is None:
            raise ValueError("path_id required for timing trace")
        q = q.where(TimingPath.path_id == path_id)
    elif kind == "perf":
        if benchmark is None:
            raise ValueError("benchmark required for perf trace")
        q = q.where(PerfRow.benchmark == benchmark)
    else:
        if scope_path is None:
            raise ValueError("scope_path required for area/power trace")
        q = q.where(table.scope_path == scope_path)
    row = session.exec(q).first()
    if row is None:
        return {"found": False, "run_id": run_id, "kind": kind}

    report = session.exec(select(RawReport).where(
        RawReport.run_id == run_id, RawReport.kind == report_kind)).first()
    if report is None or not report.content:
        return {"found": False, "run_id": run_id, "kind": kind,
                "error": "raw report text not stored"}

    lines = report.content.splitlines()
    src = row.src_line or 1
    # timing blocks span ~7 lines from the "Path N" header; others 1 line
    span = 8 if kind == "timing" else 1
    start = max(1, src - context)
    end = min(len(lines), src + span + context)
    out_lines = [{"no": no, "text": lines[no - 1],
                  "hit": src <= no < src + span}
                 for no in range(start, end + 1)]
    target = {"kind": kind}
    if kind == "timing":
        target.update({"path_id": row.path_id, "startpoint": row.startpoint,
                       "endpoint": row.endpoint, "slack_ns": row.slack_ns})
    elif kind == "perf":
        target.update({"benchmark": row.benchmark, "ipc": row.ipc})
    else:
        target.update({"scope_path": row.scope_path,
                       "value": row.total_area if kind == "area" else row.total})
    return {
        "found": True, "run_id": run_id, "kind": kind, "target": target,
        "report": _report_header(report),
        "src_line": src, "lines": out_lines,
    }
