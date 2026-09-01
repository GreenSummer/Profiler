"""Ingest pipeline: parse reports -> canonicalize paths -> persist -> derive
metrics. Every report keeps sha256 + parser_version + parse status so a tool
upgrade can be detected and reparsed (plan risk R2)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from sqlmodel import Session, select

from . import metrics as M
from .canonicalize import canonicalize_path, depth_of, owner_module, parent_of
from .models import (
    AreaRow, Baseline, Config, Corner, Design, Finding, Metric, PerfRow,
    PowerRow, Project, RawReport, Run, ScopeAlias, TimingPath, utcnow,
)
from .parsers import primepower as pp_parser
from .parsers import rtla as rtla_parser
from .parsers import specint as specint_parser
from .parsers.base import (
    AreaReport, PathGroup, PerfReport, PowerReport, QorReport, TimingReport,
)
from .rules import run_rule_engine

REPORT_SPECS = [
    ("rtla_area", "rtla_area.rpt", rtla_parser.parse_rtla_area, rtla_parser.VERSION),
    ("rtla_timing", "rtla_timing.rpt", rtla_parser.parse_rtla_timing, rtla_parser.VERSION),
    ("rtla_qor", "rtla_qor.rpt", rtla_parser.parse_rtla_qor, rtla_parser.VERSION),
    ("primepower", "primepower.rpt", pp_parser.parse_primepower, pp_parser.VERSION),
    ("specint", "specint.rpt", specint_parser.parse_specint, specint_parser.VERSION),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _full_paths_area(rep: AreaReport) -> list[tuple[str, AreaReportRow]]:
    """Reconstruct full paths from indentation (RTLA prints leaf names)."""
    out: list[tuple[str, AreaReportRow]] = []
    stack: list[str] = []
    for row in rep.rows:
        if row.tool_path == "__total__":
            continue
        if row.depth == 0:
            stack = [row.tool_path]
        else:
            stack = stack[:row.depth]
            stack.append(row.tool_path)
        out.append(("/".join(stack), row))
    return out


def _reconstruct_total(rows: list[tuple[str, AreaReportRow]]) -> AreaReportRow | None:
    tops = [r for p, r in rows if r.depth == 0]
    return tops[0] if tops else None


# ---------------------------------------------------------------- ingest

def ingest_run(session: Session, run_dir: Path, entry: dict, project: Project,
               design: Design, corner: Corner) -> Run:
    label = entry.get("label", run_dir.name)
    model = entry.get("model", "synth")
    # perf-model runs only carry a specint report; missing synth reports
    # are expected there, not a data-quality error
    applicable = set(REPORT_SPECS[4:] if model != "synth" else REPORT_SPECS)
    # config (get or create by name for this design)
    cfg = session.exec(
        select(Config).where(Config.design_id == design.id, Config.name == label)
    ).first()
    if cfg is None:
        cfg = Config(design_id=design.id, name=label, params_json=entry.get("params", {}))
        session.add(cfg)
        session.flush()

    run = Run(
        design_id=design.id, config_id=cfg.id, corner_id=corner.id,
        label=label, tool="rtla+primepower+perfsim" if model == "synth" else model,
        tool_version="T-2022.03-SP4/P-2019.06-SP1",
        stage=entry.get("stage", "synth"),
        workdir_path=str(run_dir),
    )
    session.add(run)
    session.flush()

    area_rows: list[AreaRow] = []
    power_rows: list[PowerRow] = []
    timing_paths: list[TimingPath] = []
    perf_rows: list[PerfRow] = []
    metric_rows: list[Metric] = []
    alias_rows: list[ScopeAlias] = []
    area_paths: set[str] = set()
    power_paths: set[str] = set()
    parsed: dict[str, object] = {}

    for kind, fname, fn, pver in REPORT_SPECS:
        if (kind, fname) not in {(k, f) for k, f, _, _ in applicable}:
            continue
        f = run_dir / fname
        if not f.exists():
            session.add(RawReport(run_id=run.id, kind=kind, file_path=str(f),
                                  parse_status="error", parse_log="missing file"))
            continue
        text = f.read_text(errors="replace")
        try:
            rep = fn(text)
            status = "ok" if not rep.warnings else "warnings"
            log = "\n".join(rep.warnings[:50])
        except Exception as e:  # noqa: BLE001 — keep ingesting other reports
            session.add(RawReport(run_id=run.id, kind=kind, file_path=str(f),
                                  sha256=_sha256(f), bytes=f.stat().st_size,
                                  content=text,
                                  parser_version=pver, parse_status="error",
                                  parse_log=str(e)))
            continue
        session.add(RawReport(run_id=run.id, kind=kind, file_path=str(f),
                              sha256=_sha256(f), bytes=f.stat().st_size,
                              content=text,
                              parser_version=pver, parse_status=status, parse_log=log))
        parsed[kind] = rep

    # ---- area
    if (rep := parsed.get("rtla_area")) is not None:
        for path, row in _full_paths_area(rep):  # type: ignore[arg-type]
            cpath = canonicalize_path(path)
            area_paths.add(cpath)
            area_rows.append(AreaRow(
                run_id=run.id, scope_path=cpath, parent_path=parent_of(cpath),
                depth=depth_of(cpath), total_area=row.comb_area + row.seq_area + row.macro_area + row.clock_area + row.buf_inv_area,
                comb_area=row.comb_area, seq_area=row.seq_area, macro_area=row.macro_area,
                clock_area=row.clock_area, buf_inv_area=row.buf_inv_area,
                inst_count=row.inst_count, src_line=row.src_line,
            ))
            alias_rows.append(ScopeAlias(run_id=run.id, tool_path=path, canonical_path=cpath))

    # ---- power (dot-separated full paths from PrimePower)
    if (rep := parsed.get("primepower")) is not None:
        for row in rep.rows:  # type: ignore[union-attr]
            if row.tool_path == "__total__":
                continue
            cpath = canonicalize_path(row.tool_path)
            power_paths.add(cpath)
            power_rows.append(PowerRow(
                run_id=run.id, scope_path=cpath, parent_path=parent_of(cpath),
                depth=depth_of(cpath), internal=row.internal, switching=row.switching,
                leakage=row.leakage, total=row.total, src_line=row.src_line,
            ))
            alias_rows.append(ScopeAlias(run_id=run.id, tool_path=row.tool_path, canonical_path=cpath))

    # ---- timing
    if (rep := parsed.get("rtla_timing")) is not None:
        for p in rep.paths:  # type: ignore[union-attr]
            sp, ep = canonicalize_path(p.startpoint), canonicalize_path(p.endpoint)
            timing_paths.append(TimingPath(
                run_id=run.id, path_id=p.path_id, clock="clk", path_group=p.path_group,
                slack_ns=p.slack_ns, required_ns=p.required_ns, arrival_ns=p.arrival_ns,
                startpoint=p.startpoint, endpoint=p.endpoint,
                start_module=owner_module(sp, ep), end_module=owner_module(sp, ep),
                logic_depth=p.logic_depth, is_hold=p.is_hold, src_line=p.src_line,
            ))

    # ---- performance
    if (rep := parsed.get("specint")) is not None:
        for r in rep.rows:  # type: ignore[union-attr]
            perf_rows.append(PerfRow(
                run_id=run.id, benchmark=r.benchmark, ref_ipc=r.ref_ipc,
                cycles_m=r.cycles_m, inst_m=r.inst_m, ipc=r.ipc,
                ratio_1ghz=r.ratio_1ghz, l1d_mpki=r.l1d_mpki, l2_mpki=r.l2_mpki,
                br_mispred_pct=r.br_mispred_pct, src_line=r.src_line,
            ))

    # ---- qor raw metrics
    if (rep := parsed.get("rtla_qor")) is not None:
        for k, v in rep.metrics.items():  # type: ignore[union-attr]
            metric_rows.append(Metric(run_id=run.id, key=f"qor.{k}", value=v))

    # ---- derived metrics (summaries + FOM)
    timing_sum = _timing_summary(parsed)
    area_sum = M.summarize_area(
        [{"scope_path": r.scope_path, "depth": r.depth, "total_area": r.total_area,
          "comb_area": r.comb_area, "seq_area": r.seq_area, "macro_area": r.macro_area,
          "clock_area": r.clock_area, "inst_count": r.inst_count} for r in area_rows]
    ) if area_rows else M.AreaSummary()
    power_sum = _power_summary(parsed, power_rows)
    perf_sum = M.PerfSummary(
        per_benchmark=[{"benchmark": r.benchmark, "ipc": r.ipc, "ratio_1ghz": r.ratio_1ghz,
                        "l1d_mpki": r.l1d_mpki, "l2_mpki": r.l2_mpki,
                        "br_mispred_pct": r.br_mispred_pct} for r in perf_rows],
        method=str(getattr(parsed.get("specint"), "method", "") or ""),
    )
    fom = M.figures_of_merit(
        timing_sum, area_sum, power_sum, perf_sum,
        nand2_area_um2=project.nand2_area_um2,
    )

    def put(key: str, value: float, unit: str = ""):
        metric_rows.append(Metric(run_id=run.id, key=key, value=value, unit=unit))

    put("timing.wns_ns", timing_sum.wns_ns, "ns")
    put("timing.tns_ns", timing_sum.tns_ns, "ns")
    put("timing.nve", timing_sum.nve, "endpoints")
    put("timing.fmax_mhz", timing_sum.fmax_mhz, "MHz")
    put("area.total_um2", area_sum.total_um2, "um^2")
    put("area.comb_um2", area_sum.comb_um2, "um^2")
    put("area.seq_um2", area_sum.seq_um2, "um^2")
    put("area.macro_um2", area_sum.macro_um2, "um^2")
    put("area.inst_count", area_sum.inst_count)
    put("power.total_mw", power_sum.total_mw, "mW")
    put("power.internal_mw", power_sum.internal_mw, "mW")
    put("power.switching_mw", power_sum.switching_mw, "mW")
    put("power.leakage_mw", power_sum.leakage_mw, "mW")
    put("power.leakage_share", power_sum.leakage_share)
    put("power.clock_power_mw", power_sum.clock_power_mw, "mW")
    put("power.clock_power_share", power_sum.clock_power_share)
    put("power.clock_gating_eff", power_sum.clock_gating_eff or 0.0, "%")
    put("power.toggle_rate", power_sum.toggle_rate or 0.0)
    put("perf.geomean_ratio_1ghz", perf_sum.geomean_ratio_1ghz)
    put("perf.mean_ipc", perf_sum.mean_ipc)
    for k, v in fom.items():
        if isinstance(v, (int, float)):
            put(f"fom.{k}", float(v))

    for r in area_rows:
        session.add(r)
    for r in power_rows:
        session.add(r)
    for r in timing_paths:
        session.add(r)
    for r in perf_rows:
        session.add(r)
    for r in metric_rows:
        session.add(r)
    for r in alias_rows:
        session.add(r)
    session.commit()

    # data-quality: unmatched power paths vs area paths (plan R1)
    unmatched = power_paths - area_paths
    if unmatched:
        session.add(Finding(
            run_id=run.id, rule_id="DQ_UNMATCHED_PATHS", severity="medium",
            category="data_quality", scope_path=None,
            title=f"{len(unmatched)} power-report hierarchy paths did not match area-report paths",
            evidence_json={"paths": sorted(unmatched)[:20]},
        ))
        session.commit()
    return run


def _timing_summary(parsed: dict) -> M.TimingSummary:
    rep = parsed.get("rtla_timing")
    if rep is None:
        return M.TimingSummary()
    groups = [{"name": g.name, "wns_ns": g.wns_ns, "tns_ns": g.tns_ns,
               "nve": g.nve, "fmax_mhz": g.fmax_mhz or 0.0} for g in rep.groups]
    hist = [{"bucket": float(b), "count": c} for b, c in rep.histogram]
    period = min(rep.clocks.values()) if rep.clocks else 1.0
    return M.summarize_timing(groups, period, hist,
                              [p.slack_ns for p in rep.paths])


def _power_summary(parsed: dict, rows: list[PowerRow]) -> M.PowerSummary:
    rep = parsed.get("primepower")
    if rep is None:
        return M.PowerSummary()
    dicts = [{"scope_path": r.scope_path, "depth": r.depth, "internal": r.internal,
              "switching": r.switching, "leakage": r.leakage, "total": r.total}
             for r in rows]
    return M.summarize_power(dicts, categories=rep.categories,
                             toggle_rate=rep.toggle_rate,
                             clock_gating_eff=rep.clock_gating_efficiency)


def _design_for_entry(session: Session, project: Project, entry: dict) -> Design:
    """v2 manifests carry one RTL version per entry; v1 manifests share one
    design for the whole sweep. v3 manifests add a provenance model
    (synth | gem5 | slice | zebu | fogs): one design per (version, model)."""
    version = entry.get("version")
    if version:
        model = entry.get("model", "synth")
        design = session.exec(
            select(Design).where(Design.project_id == project.id,
                                  Design.version == version,
                                  Design.model == model)
        ).first()
        if design is None:
            from datetime import datetime
            date = entry.get("date")
            design = Design(
                project_id=project.id, version=version, model=model,
                rtl_git_sha=entry.get("sha", "unknown"),
                rtl_branch=entry.get("branch", "main"),
                description=entry.get("description", ""),
                change_note=entry.get("change_note", ""),
                date=datetime.fromisoformat(date) if date else utcnow(),
            )
            session.add(design)
            session.flush()
        return design
    design = session.exec(select(Design).where(Design.project_id == project.id)).first()
    if design is None:
        design = Design(project_id=project.id, rtl_git_sha="a1b2c3d",
                        rtl_branch="main", description="rv_ooc_core demo sweep")
        session.add(design)
        session.flush()
    return design


def ingest_directory(session: Session, root: Path, project_name: str = "riscv-demo") -> dict:
    """Ingest every run directory listed in manifest.json."""
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"no manifest.json under {root}")
    import json
    manifest = json.loads(manifest_path.read_text())

    project = session.exec(select(Project).where(Project.name == project_name)).first()
    if project is None:
        project = Project(name=project_name, process_node="N7",
                          nand2_area_um2=0.0594, target_freq_mhz=833.0,
                          area_budget_mm2=2.0, power_budget_mw=150.0,
                          settings_json={"target_geomean": 1.45})
        session.add(project)
        session.flush()
    corner = session.exec(select(Corner).where(Corner.name == "tt_0p80v_25c")).first()
    if corner is None:
        corner = Corner(name="tt_0p80v_25c", process="tt", voltage=0.80, temp=25.0)
        session.add(corner)
        session.flush()

    run_ids: list[int] = []
    for entry in sorted(manifest, key=lambda e: e.get("order", 0)):
        rd = root / entry["label"]
        if not rd.is_dir():
            continue
        design = _design_for_entry(session, project, entry)
        run = ingest_run(session, rd, entry, project, design, corner)
        run_ids.append(run.id)

    # golden baseline: first manifest entry if none set
    has_baseline = session.exec(select(Baseline).where(Baseline.project_id == project.id)).first()
    if not has_baseline and run_ids:
        session.add(Baseline(project_id=project.id, run_id=run_ids[0],
                             label="golden", is_golden=True))
        session.commit()

    # rule engine over all runs (needs baseline context)
    findings = run_rule_engine(session, project.id)
    # statistical change-point detection over the version series (B4)
    from .versioning import refresh_change_events
    change_events = refresh_change_events(session, project.id)
    return {"project_id": project.id, "runs": run_ids, "findings": len(findings),
            "change_events": len(change_events)}
