"""Deterministic rule engine (plan section 6.4): rules-first diagnosis.
The YAML pack declares thresholds/titles; evaluators here are pure Python.
The LLM only ever NARRATES findings that a rule already established."""
from __future__ import annotations

from pathlib import Path

import yaml
from sqlmodel import Session, select

from .models import (
    AreaRow, Baseline, Config, Finding, Metric, PerfRow, PowerRow,
    Project, RawReport, Run, TimingPath,
)

RULES_FILE = Path(__file__).parent / "rules_pack.yaml"


def load_rules(path: Path = RULES_FILE) -> list[dict]:
    data = yaml.safe_load(path.read_text())
    return data.get("rules", [])


class RunFacts:
    """Everything a rule evaluator may look at, precomputed once per run."""

    def __init__(self, session: Session, run_id: int):
        from .models import Design
        self.run_id = run_id
        self.run = session.get(Run, run_id)
        self.metrics = {
            m.key: m.value for m in session.exec(
                select(Metric).where(Metric.run_id == run_id)).all()
        }
        self.area = session.exec(select(AreaRow).where(AreaRow.run_id == run_id)).all()
        self.power = session.exec(select(PowerRow).where(PowerRow.run_id == run_id)).all()
        self.perf = session.exec(select(PerfRow).where(PerfRow.run_id == run_id)).all()
        self.paths = session.exec(select(TimingPath).where(TimingPath.run_id == run_id)).all()
        self.reports = session.exec(select(RawReport).where(RawReport.run_id == run_id)).all()
        self.project = None
        self.config_name = ""
        self.config_params = {}
        if self.run:
            design = session.get(Design, self.run.design_id)
            self.project = session.get(Project, design.project_id) if design else None
            cfg = session.get(Config, self.run.config_id)
            self.config_name = cfg.name if cfg else ""
            self.config_params = cfg.params_json if cfg else {}
        # baseline context
        self.baseline_run_id: int | None = None
        if self.project:
            bl = session.exec(select(Baseline).where(Baseline.project_id == self.project.id)).first()
            if bl and bl.run_id != run_id:
                self.baseline_run_id = bl.run_id
                self.baseline_metrics = {
                    m.key: m.value for m in session.exec(
                        select(Metric).where(Metric.run_id == bl.run_id)).all()
                }
                self.baseline_area = {
                    a.scope_path: a for a in session.exec(
                        select(AreaRow).where(AreaRow.run_id == bl.run_id)).all()}
                self.baseline_perf = {
                    p.benchmark: p for p in session.exec(
                        select(PerfRow).where(PerfRow.run_id == bl.run_id)).all()}
            else:
                self.baseline_metrics = {}
                self.baseline_area = {}
                self.baseline_perf = {}
        else:
            self.baseline_metrics = {}
            self.baseline_area = {}
            self.baseline_perf = {}

    def area_at_depth(self, depth: int) -> list[AreaRow]:
        return sorted([a for a in self.area if a.depth == depth],
                      key=lambda a: -a.total_area)

    def power_by_path(self) -> dict[str, PowerRow]:
        return {p.scope_path: p for p in self.power}


# ---------------------------------------------------------------- evaluators

def _ev_tim_wns(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    wns = f.metrics.get("timing.wns_ns", 0.0)
    if wns < 0:
        sev = "critical" if wns < p.get("scale_high_at", -0.10) else "high"
        return [(sev, {}, {"wns": wns})]
    return []


def _ev_tim_nve(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    nve = f.metrics.get("timing.nve", 0)
    if nve >= p.get("nve_threshold", 50):
        return [("medium", {}, {"nve": nve, "tns": f.metrics.get("timing.tns_ns", 0.0)})]
    return []


def _ev_tim_mod_dominates(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    top = [t for t in f.paths if not t.is_hold][:100]
    if not top:
        return []
    counts: dict[str, int] = {}
    for t in top:
        counts[t.start_module] = counts.get(t.start_module, 0) + 1
    out = []
    for mod, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        share = n / len(top)
        if share > p.get("share_threshold", 0.30):
            out.append(("medium", {"module": mod}, {"module": mod, "share": share}))
    return out


def _ev_tim_deep_logic(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    th = p.get("threshold", 25)
    out = []
    for t in f.paths:
        if t.logic_depth > th and t.slack_ns < 0:
            out.append(("medium", {"module": t.start_module},
                        {"depth": t.logic_depth, "threshold": th}))
            break
    return out


def _ev_area_over_budget(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    budget = f.project.area_budget_mm2 if f.project else None
    area = f.metrics.get("fom.area_mm2", 0.0)
    if budget and area > budget:
        return [("high", {}, {"area_mm2": area, "budget_mm2": budget})]
    return []


def _ev_area_seq_ratio(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    seq = f.metrics.get("area.seq_um2", 0.0)
    total = f.metrics.get("area.total_um2", 0.0)
    if total and seq / total > p.get("threshold", 0.50):
        return [("low", {}, {"ratio": seq / total})]
    return []


def _ev_area_mod_growth(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    if not f.baseline_area:
        return []
    th = p.get("threshold", 0.05)
    out = []
    for a in f.area_at_depth(2)[:15]:
        b = f.baseline_area.get(a.scope_path)
        if b and b.total_area > 0:
            pct = (a.total_area - b.total_area) / b.total_area
            if pct > th:
                out.append(("medium", {"module": a.scope_path},
                            {"module": a.scope_path.rsplit('/', 1)[-1], "pct": pct}))
    return out


def _ev_pwr_leak_share(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    share = f.metrics.get("power.leakage_share", 0.0)
    if share > p.get("threshold", 0.25):
        return [("high", {}, {"share": share})]
    return []


def _ev_pwr_clock_share(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    share = f.metrics.get("power.clock_power_share", 0.0)
    if share > p.get("threshold", 0.30):
        return [("medium", {}, {"share": share})]
    return []


def _ev_pwr_cg_low(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    eff = f.metrics.get("power.clock_gating_eff", 0.0)
    if 0 < eff < p.get("threshold", 70):
        return [("medium", {}, {"eff": eff})]
    return []


def _ev_pwr_density(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    th = p.get("threshold_mw_um2", 0.00045)
    pw = f.power_by_path()
    out = []
    for a in f.area_at_depth(2):
        p_row = pw.get(a.scope_path)
        if p_row and a.total_area > 0:
            density = p_row.total / a.total_area
            if density > th:
                out.append(("medium", {"module": a.scope_path},
                            {"module": a.scope_path.rsplit('/', 1)[-1],
                             "density": density * 1e6}))  # report as mW/mm^2
    return out


def _ev_pwr_over_budget(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    budget = f.project.power_budget_mw if f.project else None
    power = f.metrics.get("power.total_mw", 0.0)
    if budget and power > budget:
        return [("high", {}, {"power_mw": power, "budget_mw": budget})]
    return []


def _ev_perf_regress(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    if not f.baseline_perf:
        return []
    th = p.get("threshold", 0.01)
    out = []
    deltas = {}
    for r in f.perf:
        b = f.baseline_perf.get(r.benchmark)
        if b and b.ipc > 0:
            pct = (r.ipc - b.ipc) / b.ipc
            deltas[r.benchmark] = pct
            if pct < -th:
                out.append(("medium", {"module": r.benchmark},
                            {"benchmark": r.benchmark, "pct": pct}))
    # isolated outlier: lone regression while geomean fine
    gm_b = f.baseline_metrics.get("perf.geomean_ratio_1ghz", 0.0)
    gm_c = f.metrics.get("perf.geomean_ratio_1ghz", 0.0)
    if gm_b and gm_c:
        gm_pct = (gm_c - gm_b) / gm_b
        negs = {k: v for k, v in deltas.items() if v < -th}
        if len(negs) == 1 and gm_pct >= 0:
            bench, pct = next(iter(negs.items()))
            out.append(("info", {"module": bench},
                        {"benchmark": bench, "pct": pct, "gm": gm_pct}))
    return out


def _ev_xdom_net(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    if not f.baseline_metrics:
        return []
    ipc = f.metrics.get("perf.geomean_ratio_1ghz", 0.0)
    ipc_b = f.baseline_metrics.get("perf.geomean_ratio_1ghz", 0.0)
    score = f.metrics.get("fom.specint_score", 0.0)
    score_b = f.baseline_metrics.get("fom.specint_score", 0.0)
    if not (ipc and ipc_b and score and score_b):
        return []
    d_ipc = (ipc - ipc_b) / ipc_b
    d_score = (score - score_b) / score_b
    if d_ipc > 0 and d_score < 0:
        return [("high", {}, {"ipc": d_ipc, "score": d_score})]
    return []


def _ev_xdom_roi_area(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    return _roi_check(f, p, "fom.area_mm2", "area")


def _ev_xdom_roi_power(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    return _roi_check(f, p, "fom.total_power_mw", "power")


def _roi_check(f: RunFacts, p: dict, metric_key: str, label: str) -> list[tuple[str, dict, dict]]:
    if not f.baseline_metrics:
        return []
    score = f.metrics.get("fom.specint_score", 0.0)
    score_b = f.baseline_metrics.get("fom.specint_score", 0.0)
    cur, base = f.metrics.get(metric_key), f.baseline_metrics.get(metric_key)
    if not (score and score_b and cur and base):
        return []
    ds = (score - score_b) / score_b
    dc = (cur - base) / base
    if dc <= 0:
        return []
    roi = ds / dc
    if roi < p.get("threshold", 0.3):
        return [("medium", {}, {"roi": roi, f"{label}_pct": dc, "score_pct": ds})]
    return []


def _ev_dq_missing(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    kinds = {"rtla_area", "rtla_timing", "rtla_qor", "primepower", "specint"}
    have = {r.kind for r in f.reports}
    out = []
    for k in sorted(kinds - have):
        out.append(("high", {}, {"kind": k}))
    return out


def _ev_dq_warnings(f: RunFacts, p: dict) -> list[tuple[str, dict, dict]]:
    out = []
    for r in f.reports:
        if r.parse_status == "error":
            out.append(("high", {}, {"kind": r.kind, "n": 1}))
        elif r.parse_status == "warnings" and r.parse_log:
            n = len(r.parse_log.splitlines())
            if n > 0:
                out.append(("low", {}, {"kind": r.kind, "n": n}))
    return out


EVALUATORS = {
    "TIM_WNS_NEG": _ev_tim_wns,
    "TIM_NVE_HIGH": _ev_tim_nve,
    "TIM_MOD_DOMINATES": _ev_tim_mod_dominates,
    "TIM_DEEP_LOGIC": _ev_tim_deep_logic,
    "AREA_OVER_BUDGET": _ev_area_over_budget,
    "AREA_SEQ_RATIO": _ev_area_seq_ratio,
    "AREA_MOD_GROWTH": _ev_area_mod_growth,
    "PWR_LEAK_SHARE": _ev_pwr_leak_share,
    "PWR_CLOCK_SHARE": _ev_pwr_clock_share,
    "PWR_CG_LOW": _ev_pwr_cg_low,
    "PWR_DENSITY_HIGH": _ev_pwr_density,
    "PWR_OVER_BUDGET": _ev_pwr_over_budget,
    "PERF_BENCH_REGRESS": _ev_perf_regress,
    "PERF_ISOLATED_OUTLIER": _ev_perf_regress,  # merged into _ev_perf_regress
    "XDOM_NET_SCORE_DOWN": _ev_xdom_net,
    "XDOM_AREA_ROI_LOW": _ev_xdom_roi_area,
    "XDOM_POWER_ROI_LOW": _ev_xdom_roi_power,
    "DQ_MISSING_REPORT": _ev_dq_missing,
    "DQ_PARSE_WARNINGS": _ev_dq_warnings,
}


def run_rule_engine(session: Session, project_id: int) -> list[Finding]:
    """Evaluate the pack for every run of the project; returns findings."""
    from .models import Design
    rules = load_rules()
    design_ids = [d.id for d in session.exec(
        select(Design).where(Design.project_id == project_id)).all()]
    runs = [r for r in session.exec(select(Run)).all() if r.design_id in design_ids]
    run_ids = {r.id for r in runs}
    old = session.exec(select(Finding)).all()
    for f in old:
        if f.run_id in run_ids:
            session.delete(f)
    session.commit()

    findings: list[Finding] = []
    for run in runs:
        facts = RunFacts(session, run.id)
        for rule in rules:
            ev = EVALUATORS.get(rule["id"])
            if ev is None:
                continue
            params = rule.get("params", {})
            try:
                hits = ev(facts, params)
            except Exception:  # noqa: BLE001 — a broken rule must not kill ingest
                continue
            for sev_override, scope, fmt in hits:
                title = _render_title(rule, fmt)
                findings.append(Finding(
                    run_id=run.id, rule_id=rule["id"],
                    severity=sev_override or rule.get("severity", "medium"),
                    category=rule.get("category", "cross_domain"),
                    scope_path=scope.get("module"),
                    title=title, evidence_json={k: v for k, v in fmt.items()
                                                if isinstance(v, (int, float, str))},
                ))
    for f in findings:
        session.add(f)
    session.commit()
    return findings


def _render_title(rule: dict, fmt: dict) -> str:
    title = rule.get("title", rule["id"])
    try:
        return title.format(**fmt)
    except (KeyError, ValueError):
        return title
