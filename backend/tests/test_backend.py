"""Backend test suite (v2: version-centric series, v3: multi-model series).

The sample generator plants 5 events into a 16-version series (v0.1..v0.16,
single config, deterministic +-0.5% noise). v3 extends every version with 4
perf-model runs (gem5/slice/zebu/fogs) alongside the full synth run, so the
demo DB holds 80 runs across 5 provenance series. These tests pin the whole
stack: parser line provenance, ingest, change-point detection (all planted
events, no false alarms on noise transitions), perf x PPA correlations,
signal search, trace-to-source, the release overview board, per-version
drill-down / multi-version compare, the API endpoints and the offline
analyst patterns.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from ppa import versioning
from ppa.canonicalize import canonicalize_path, owner_module
from ppa.db import make_engine, init_db
from ppa.ingest import ingest_directory
from ppa.metrics import figures_of_merit, net_score_decomposition, pareto_front
from ppa.models import ChangeEvent, Finding, Run, TimingPath
from ppa.parsers.primepower import parse_primepower
from ppa.parsers.rtla import parse_rtla_area, parse_rtla_timing
from ppa.parsers.specint import parse_specint
from ppa.sample_data import generate

VERSION_LABELS = [f"v0.{i}" for i in range(1, 17)]
# transitions carrying a planted event; every other transition is pure noise
EVENT_VERSIONS = {"v0.5", "v0.7", "v0.8", "v0.9", "v0.10",
                  "v0.11", "v0.12", "v0.13", "v0.14"}


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ppadb")
    engine = make_engine(tmp / "test.db")
    init_db(engine)
    runs_dir = tmp / "runs"
    generate(runs_dir)
    with Session(engine) as s:
        result = ingest_directory(s, runs_dir, "test-proj")
    return engine, result


# ------------------------------------------------------------------ v1 core

def test_canonicalize():
    assert canonicalize_path("u_ex.gen_alu[0].u_alu") == "u_ex/gen_alu_0/u_alu"
    assert canonicalize_path("u_ex\\u_rob") == "u_ex/u_rob"
    assert canonicalize_path("u_ex/gen_alu_0_/u_alu") == "u_ex/gen_alu_0/u_alu"
    assert canonicalize_path("core_top.u_ex.u_rob") == "core_top/u_ex/u_rob"


def test_owner_module():
    assert owner_module("core_top/u_ex/u_rob/a", "core_top/u_ex/u_rob/b") == "core_top/u_ex"
    assert owner_module("core_top/u_ex/a", "core_top/u_ifu/b") == "core_top/u_ex"


def test_parsers(tmp_path):
    generate(tmp_path)
    area = parse_rtla_area((tmp_path / "v0.1" / "rtla_area.rpt").read_text())
    assert area.rows and area.rows[0].tool_path == "core_top"
    total = next(r for r in area.rows if r.tool_path == "Total")
    assert total.comb_area > 0 and total.inst_count > 100000
    # roll-up: children sum to parent
    kids = sum(r.comb_area for r in area.rows if r.depth == 1)
    assert abs(kids - total.comb_area) / total.comb_area < 0.01
    # v3: the die_total row models the core at 62% site utilization
    die = next(r for r in area.rows if r.tool_path == "die_total")
    core_total = (total.comb_area + total.seq_area + total.macro_area
                  + total.clock_area + total.buf_inv_area)
    die_total = (die.comb_area + die.seq_area + die.macro_area
                 + die.clock_area + die.buf_inv_area)
    assert die_total == pytest.approx(core_total / 0.62, rel=0.001)
    # v2: every parsed record carries 1-based source provenance
    assert all(r.src_line >= 1 for r in area.rows)

    timing = parse_rtla_timing((tmp_path / "v0.1" / "rtla_timing.rpt").read_text())
    assert timing.groups and timing.clocks.get("clk") == 1.20
    assert len(timing.paths) >= 5
    assert all(p.src_line >= 1 for p in timing.paths)
    # from v0.7 the un-retimed MAC multiply path owns the critical path
    t7 = parse_rtla_timing((tmp_path / "v0.7" / "rtla_timing.rpt").read_text())
    worst = min(t7.paths, key=lambda p: p.slack_ns)
    assert "u_mul" in worst.startpoint and worst.slack_ns < 0

    power = parse_primepower((tmp_path / "v0.1" / "primepower.rpt").read_text())
    assert power.rows and power.clock_gating_efficiency == 78.0
    assert power.categories["clock"] > 0

    perf = parse_specint((tmp_path / "v0.1" / "specint.rpt").read_text())
    assert len(perf.rows) == 12
    assert 1.0 < perf.geomean_ratio < 2.0


def test_figures_of_merit():
    from ppa.metrics import AreaSummary, PerfSummary, PowerSummary, TimingSummary
    t = TimingSummary(wns_ns=0.05, target_period_ns=1.0)
    a = AreaSummary(total_um2=200000, comb_um2=100000, seq_um2=50000)
    p = PowerSummary(internal_mw=10, switching_mw=10, leakage_mw=5, total_mw=25)
    perf = PerfSummary(per_benchmark=[{"benchmark": "b", "ipc": 1.5, "ratio_1ghz": 1.5}])
    fom = figures_of_merit(t, a, p, perf, nand2_area_um2=0.0594)
    assert fom["fmax_mhz"] == pytest.approx(1000 / 0.95)
    assert fom["specint_score"] == pytest.approx(1.5 * fom["fmax_mhz"] / 1000)
    assert fom["freq_source"] == "timing"
    fixed = figures_of_merit(t, a, p, perf, nand2_area_um2=0.0594, fixed_freq_mhz=1000)
    assert fixed["freq_source"] == "fixed"


def test_decomposition():
    base = {"specint_score": 1.0, "specint_per_ghz": 1.0, "fmax_mhz": 1000}
    cur = {"specint_score": 0.99, "specint_per_ghz": 1.03, "fmax_mhz": 961}  # ipc up, net down
    d = net_score_decomposition(base, cur)
    assert d["ipc_pct"] > 0
    assert d["net_pct"] < 0
    assert d["verdict"] == "loss"


def test_pareto():
    pts = [{"x": 1, "y": 1}, {"x": 2, "y": 2}, {"x": 3, "y": 3}, {"x": 3, "y": 1}]
    nd = pareto_front(pts, "x", "y")
    assert nd == {0, 1, 2}  # (3,1) dominated by (2,2) and (3,3)


# ------------------------------------------------------------------ v2 ingest

def test_ingest_and_rules(db):
    engine, result = db
    # v3: 16 versions x (1 synth + 4 perf models) = 80 runs
    assert len(result["runs"]) == 80
    with Session(engine) as s:
        runs = s.exec(select(Run)).all()
        synth = [r for r in runs if r.stage == "synth"]
        sim = [r for r in runs if r.stage == "sim"]
        assert {r.label for r in synth} == set(VERSION_LABELS)
        assert len(sim) == 64
        assert {r.label for r in sim} == {
            f"{v}-{m}" for v in VERSION_LABELS
            for m in ("gem5", "slice", "zebu", "fogs")}
        findings = s.exec(select(Finding)).all()
        by_rule: dict[str, list[Finding]] = {}
        for f in findings:
            by_rule.setdefault(f.rule_id, []).append(f)
        # the planted anomalies must be caught by the rule engine
        assert by_rule.get("TIM_WNS_NEG"), "v0.7 WNS cliff not caught"
        assert by_rule.get("PWR_CG_LOW"), "v0.9 clock-gating collapse not caught"
        assert by_rule.get("XDOM_NET_SCORE_DOWN"), "v0.7 net-score loss not caught"
        # change points above severity thresholds surface as findings
        vc = by_rule.get("VC_CHANGE_POINT", [])
        assert len(vc) == 15
        assert all(f.category == "version_change" for f in vc)
        # cross-tool join must be clean (plan R1)
        assert not by_rule.get("DQ_UNMATCHED_PATHS")
        # detector output is persisted as ChangeEvent rows
        assert len(s.exec(select(ChangeEvent)).all()) == 17


# ------------------------------------------------------------------ v2 series

def test_version_series(db):
    engine, _ = db
    with Session(engine) as s:
        series = versioning.version_series(s)["series"]
        # explicit model filter equals the default (synth is the truth series)
        explicit = versioning.version_series(s, model="synth")["series"]
        zebu = versioning.version_series(s, model="zebu")["series"]
    assert [p["version"] for p in explicit] == VERSION_LABELS
    assert [p["version"] for p in zebu] == VERSION_LABELS
    assert all(p["stage"] == "sim" for p in zebu)
    assert [p["version"] for p in series] == VERSION_LABELS
    first = series[0]
    assert first["label"] == "v0.1" and first["stage"] == "synth"
    assert first["sha"] == "8f2c1ad" and first["date"] == "2026-05-04"
    assert "bypass" in series[4]["change_note"]  # v0.5
    assert all(p["change_note"] for p in series)
    m1, m5, m14 = series[0]["metrics"], series[4]["metrics"], series[13]["metrics"]
    # FOM sanity on the planted series
    assert m1["specint_score"] == pytest.approx(1.293, abs=0.02)
    assert m1["area_mm2"] == pytest.approx(0.187, abs=0.005)
    assert m1["wns_ns"] == pytest.approx(0.05, abs=0.01)
    assert m5["area_mm2"] == pytest.approx(0.202, abs=0.005)  # +8% bypass network
    assert m14["leakage_share"] == pytest.approx(0.176, abs=0.01)  # LVT drift
    assert all(p["metrics"]["total_power_mw"] > 0 for p in series)


# -------------------------------------------------------------- change points

def test_change_points(db):
    engine, result = db
    # re-running the detector is idempotent (ingest already ran it once)
    with Session(engine) as s:
        again = versioning.refresh_change_events(s, result["project_id"])
        assert len(again) == 17
        events = versioning.change_points(s)
        vc = s.exec(select(Finding).where(Finding.rule_id == "VC_CHANGE_POINT")).all()
        assert len(vc) == 15
    assert len(events) == 17
    by = {(e["to_version"], e["metric_key"]): e for e in events}
    # no false alarms: events land only on the planted transitions
    assert {e["to_version"] for e in events} == EVENT_VERSIONS

    # planted event 1 -- v0.5 bypass network: area +8%, attributed to u_ex
    e = by[("v0.5", "area_mm2")]
    assert e["delta_pct"] == pytest.approx(0.080, abs=0.005)
    assert e["method"] == "step" and e["severity"] == "high"
    assert e["scope_path"] == "core_top/u_ex"
    assert e["from_version"] == "v0.4"
    assert by[("v0.5", "total_power_mw")]["delta_pct"] == pytest.approx(0.068, abs=0.01)

    # planted event 2 -- v0.7 MAC instruction: WNS cliff + score spike, u_mul
    e = by[("v0.7", "wns_ns")]
    assert e["delta_pct"] == pytest.approx(-0.121, abs=0.01)  # absolute ns
    assert e["method"] == "spike" and e["severity"] == "high"
    assert e["scope_path"] == "core_top/u_ex/u_mul"
    assert by[("v0.7", "specint_score")]["method"] == "spike"
    # ...and the v0.8 retime recovers both
    assert by[("v0.8", "wns_ns")]["method"] == "recovery"
    assert by[("v0.8", "specint_score")]["method"] == "recovery"

    # planted event 3 -- v0.9 CG insertion disabled: gating collapses
    e = by[("v0.9", "clock_gating_eff")]
    assert e["delta_pct"] == pytest.approx(-23.0, abs=1.0)  # absolute points
    assert e["method"] == "spike"
    e = by[("v0.9", "total_power_mw")]
    assert e["severity"] == "high" and e["method"] == "spike"
    assert e["scope_path"] == "core_top/u_clk"
    assert by[("v0.10", "clock_gating_eff")]["method"] == "recovery"

    # planted event 4 -- VT mix drift: leakage climbs as a 3-version trend
    for v in ("v0.11", "v0.12", "v0.13"):
        e = by[(v, "leakage_share")]
        assert e["method"] == "trend" and e["severity"] == "high"
        assert e["delta_pct"] > 0.2

    # planted event 5 -- v0.14 BTAC: the good trade (score gain >> area cost)
    assert by[("v0.14", "specint_score")]["delta_pct"] == pytest.approx(0.029, abs=0.01)
    assert by[("v0.14", "geomean_ratio_1ghz")]["delta_pct"] == pytest.approx(0.028, abs=0.01)
    assert by[("v0.14", "area_mm2")]["scope_path"] == "core_top/u_ifu"
    assert (by[("v0.14", "specint_score")]["delta_pct"]
            > by[("v0.14", "area_mm2")]["delta_pct"])


# ---------------------------------------------------------------- correlations

def test_correlations(db):
    engine, _ = db
    with Session(engine) as s:
        corr = versioning.correlations(s)
    r = {(p["perf"], p["ppa"]): p for p in corr["pairs"]}
    assert len(corr["pairs"]) == 15  # 3 perf x 5 PPA, all defined on n=16
    assert all(p["n"] == 16 for p in corr["pairs"])
    # planted relations: score tracks WNS (IPC -> timing pressure), and Fmax
    # follows WNS almost exactly (it is derived from it)
    assert r[("specint_score", "wns_ns")]["r"] == pytest.approx(0.897, abs=0.02)
    assert r[("fmax_mhz", "wns_ns")]["r"] > 0.99
    # LVT drift + BTAC: IPC and leakage rise together across the series
    assert r[("geomean_ratio_1ghz", "leakage_share")]["r"] > 0.7
    # module-level table: strongest |r| first, bounded, full series
    mods = corr["modules"]
    assert mods and len(mods) <= 12
    assert all(abs(m["r"]) <= 1 and m["n"] == 16 for m in mods)
    assert mods[0]["module"] == "core_top/u_clk"  # clock tree tracks the score
    assert any(m["module"] == "core_top/u_csr" and m["r"] < 0 for m in mods)


# -------------------------------------------------------- v3 overview board

def test_overview_board(db):
    engine, _ = db
    with Session(engine) as s:
        ov = versioning.overview_board(s)
    # shape: 16 versions, 5 geomean series (4 perf models + full synth)
    assert ov["versions"] == VERSION_LABELS
    assert set(ov["geomean"]) == {"synth", "gem5", "slice", "zebu", "fogs"}
    assert all(len(v) == 16 for v in ov["geomean"].values())
    assert len(ov["perf_per_area"]) == 16
    assert ov["target_geomean"] == pytest.approx(1.45)
    assert ov["area_budget_mm2"] == pytest.approx(2.0)
    assert ov["target_eff"] == pytest.approx(1.45 / 2.0)
    assert len(ov["benchmarks_names"]) == 12
    # per-benchmark trend shapes: 12 benchmarks x 4 perf models x 16 versions
    for bench in ov["benchmarks_names"]:
        for series in ("benchmarks", "ipc"):
            per = ov[series][bench]
            assert set(per) == {"gem5", "slice", "zebu", "fogs"}
            assert all(len(per[m]) == 16 for m in per)
    # model ordering at v0.16: gem5 carries the +2% bias; zebu is the truth
    last = {m: v[-1] for m, v in ov["geomean"].items()}
    assert last["gem5"] > last["zebu"] > last["slice"]
    assert last["gem5"] / last["zebu"] == pytest.approx(1.02, abs=0.01)
    # noisy models stay close to the truth
    for m in ("slice", "fogs", "synth"):
        assert abs(last[m] - last["zebu"]) / last["zebu"] < 0.05
    # the v0.14 BTAC IPC event is shared by every perf model
    for m in ("gem5", "slice", "zebu", "fogs"):
        bench = ov["ipc"]["429.mcf"][m]
        assert bench[13] > bench[12] * 1.01  # index 13 = v0.14
    # area stack: categories sum to the synth core area per version
    ab = ov["area_breakdown"]
    assert ab["categories"] == ["Frontend", "Backend", "Memblock", "L2 top", "Other"]
    for i, v in enumerate(ov["versions"]):
        stack = sum(ab["values"][c][i] for c in ab["categories"])
        if v == "v0.5":
            assert stack == pytest.approx(0.20238, abs=0.001)
    # timing series + NVE spike around the v0.7 MAC cliff
    assert len(ov["timing"]["wns"]) == 16
    assert ov["timing"]["nve"][6] == 96  # v0.7
    # board metrics: every version populated, congestion has no synth source
    assert len(ov["board"]) == 16
    for row in ov["board"]:
        assert row["congestion_overflow"] is None
        assert row["util_proxy"] == pytest.approx(0.62, abs=0.001)
        assert row["max_logic_levels"] and row["gated_pct"] is not None
    assert ov["board"][6]["max_logic_levels"] == 38  # v0.7 MAC path


def test_version_drill(db):
    engine, _ = db
    with Session(engine) as s:
        d5 = versioning.version_drill(s, "v0.5")
        d7 = versioning.version_drill(s, "v0.7")
        bad = versioning.version_drill(s, "v9.9")
    assert bad["found"] is False
    # v0.5: bypass network — change note, detected events, u_ex growth
    assert d5["found"] and d5["run_id"] and "bypass" in d5["change_note"]
    ev = {(e["metric_key"]) for e in d5["events"]}
    assert "area_mm2" in ev
    mods = {m["scope_path"]: m for m in d5["modules"]}
    assert len(mods) == 6  # u_ifu u_ex u_lsu u_l2 u_csr u_clk
    assert mods["core_top/u_ex"]["area_delta_pct"] == pytest.approx(0.239, abs=0.01)
    assert d5["signals"] and all("path_id" in sg for sg in d5["signals"])
    # v0.7: the MAC multiply path owns the worst slack
    assert d7["found"]
    assert "mac" in d7["signals"][0]["startpoint"]
    assert d7["signals"][0]["slack_ns"] == pytest.approx(-0.069, abs=0.005)


def test_version_compare_multi(db):
    engine, _ = db
    with Session(engine) as s:
        cmp = versioning.version_compare_multi(s, ["v0.8", "v0.3", "v0.5"])
    # versions sorted, synth run resolved per version
    assert cmp["versions"] == ["v0.3", "v0.5", "v0.8"]
    assert len(cmp["run_ids"]) == 3
    mods = {m["scope_path"]: m for m in cmp["modules"]}
    assert len(mods) == 6
    uex = mods["core_top/u_ex"]
    assert uex["area_mm2"] == pytest.approx([0.06399, 0.07928, 0.07911], abs=0.001)
    # deltas are relative to the first selected version (zero by definition)
    for m in cmp["modules"]:
        assert m["area_delta_pct"][0] == 0.0
        assert m["power_delta_pct"][0] == 0.0
    assert uex["area_delta_pct"][1] == pytest.approx(0.2389, abs=0.01)
    # zebu IPC matrix for all 12 benchmarks, first-version deltas zero
    assert len(cmp["benchmarks"]) == 12
    for b in cmp["benchmarks"]:
        assert len(b["ipc"]) == 3 and b["ipc_delta_pct"][0] == 0.0
    # signals present in ALL selected versions: MAC paths only exist from
    # v0.7 onward, so none of them survives the v0.3/v0.5/v0.8 intersection
    assert cmp["signals"]
    assert all("mac" not in sg["startpoint"] for sg in cmp["signals"])
    assert all(len(sg["slacks"]) == 3 for sg in cmp["signals"])


# ---------------------------------------------------------------- search/trace

def test_signal_search(db):
    engine, _ = db
    with Session(engine) as s:
        res = versioning.signal_search(s, "mac")
    # the three MAC multiply paths exist from v0.7 onward
    assert len(res["signals"]) == 3
    for sig in res["signals"]:
        hist = sig["history"]
        assert len(hist) == 10  # v0.7..v0.16
        assert hist[0]["version"] == "v0.7" and hist[-1]["version"] == "v0.16"
        assert sig["module"].startswith("core_top/u_ex")
    # two of the three MAC paths start and end inside u_mul; the third
    # (mac_acc -> writeback) crosses modules, so its owner is u_ex
    assert sum("u_mul" in sig["module"] for sig in res["signals"]) == 2
    worst = min((h for sig in res["signals"] for h in sig["history"]),
                key=lambda h: h["slack_ns"])
    assert worst["version"] == "v0.7"
    assert worst["slack_ns"] == pytest.approx(-0.069, abs=0.005)
    # raw report text hits carry file + line provenance ("mac" also
    # matches "Macro" headers in the area/qor reports -- both are hits)
    assert res["text"]
    assert all(t["line"] >= 1 and t["kind"] for t in res["text"])
    assert any(t["kind"] == "rtla_timing" and "mac" in t["text"].lower()
               for t in res["text"])
    # module search
    with Session(engine) as s:
        mods = versioning.signal_search(s, "u_mul")["modules"]
    assert any(m["scope_path"] == "core_top/u_ex/u_mul" for m in mods)
    # guard: too-short queries return empty
    with Session(engine) as s:
        empty = versioning.signal_search(s, "m")
    assert not empty["signals"] and not empty["text"]


def test_trace_to_source(db):
    engine, _ = db
    with Session(engine) as s:
        series = versioning.version_series(s)["series"]
        rid1 = series[0]["run_id"]
        rid5 = next(p["run_id"] for p in series if p["version"] == "v0.5")
        rid7 = next(p["run_id"] for p in series if p["version"] == "v0.7")

        # area value -> the exact hierarchy line of the RTLA report
        tr = versioning.trace_to_source(s, rid5, "area", scope_path="core_top/u_ex")
        assert tr["found"] and tr["report"]["kind"] == "rtla_area"
        hits = [l for l in tr["lines"] if l["hit"]]
        assert len(hits) == 1 and "u_ex" in hits[0]["text"]
        assert tr["src_line"] == hits[0]["no"]

        # timing path -> its full 8-line block in the timing report
        worst = s.exec(select(TimingPath).where(TimingPath.run_id == rid7)
                       .order_by(TimingPath.slack_ns)).first()
        tr = versioning.trace_to_source(s, rid7, "timing", path_id=worst.path_id)
        assert tr["found"] and tr["report"]["kind"] == "rtla_timing"
        hits = [l for l in tr["lines"] if l["hit"]]
        assert len(hits) == 8
        assert any("Startpoint" in l["text"] for l in hits)
        assert tr["target"]["startpoint"] == worst.startpoint

        # perf benchmark -> its result row
        tr = versioning.trace_to_source(s, rid1, "perf", benchmark="400.perlbench")
        assert tr["found"]
        assert "400.perlbench" in [l for l in tr["lines"] if l["hit"]][0]["text"]

        # line mode (global-search text drilldown): raw kind + line number
        tr = versioning.trace_to_source(s, rid1, "rtla_qor", line=3)
        assert tr["found"]
        hits = [l for l in tr["lines"] if l["hit"]]
        assert len(hits) == 1 and hits[0]["no"] == 3

        # unknown target: refuse rather than guess
        tr = versioning.trace_to_source(s, rid5, "area", scope_path="no/such/module")
        assert tr["found"] is False


# ---------------------------------------------------------------------- API

def test_api(db, monkeypatch):
    engine, _ = db
    from ppa.db import get_engine, get_session
    import ppa.main as main_mod
    # force the offline analyst so the test is hermetic even when a local
    # Ollama happens to be running on the dev machine
    import ppa.ai.llm as llm_mod
    monkeypatch.setattr(llm_mod, "probe",
                        lambda *a, **k: {"available": False, "error": "hermetic test"})
    main_mod.get_engine = lambda: engine  # point app at test DB
    main_mod.app.dependency_overrides[get_session] = lambda: iter(Session(engine))
    client = TestClient(main_mod.app)

    runs = client.get("/api/runs").json()
    assert len(runs) == 80  # 16 synth + 64 perf-model runs
    assert {r["model"] for r in runs} == {"synth", "gem5", "slice", "zebu", "fogs"}
    rid = runs[0]["run_id"]
    assert runs[0].get("version") == "v0.1"
    assert "specint_score" in runs[0]["fom"]

    # ---- v3 release overview endpoints ------------------------------------
    ov = client.get("/api/overview").json()
    assert ov["versions"] == VERSION_LABELS
    assert set(ov["geomean"]) == {"synth", "gem5", "slice", "zebu", "fogs"}

    dl = client.get("/api/version-drill", params={"version": "v0.5"}).json()
    assert dl["found"] and dl["modules"]
    dl = client.get("/api/version-drill", params={"version": "v9.9"}).json()
    assert dl["found"] is False

    vc = client.get("/api/version-compare",
                    params={"versions": "v0.3,v0.5,v0.8"}).json()
    assert vc["versions"] == ["v0.3", "v0.5", "v0.8"]
    assert client.get("/api/version-compare",
                      params={"versions": "v0.3"}).status_code == 400

    # ---- v2 endpoints ----------------------------------------------------
    vers = client.get("/api/versions").json()
    assert len(vers["series"]) == 16
    assert vers["series"][0]["change_note"]

    cps = client.get("/api/change-points").json()
    assert len(cps) == 17
    assert any(c["to_version"] == "v0.5" and c["metric_key"] == "area_mm2"
               for c in cps)

    corr = client.get("/api/correlations").json()
    pair = next(p for p in corr["pairs"]
                if p["perf"] == "specint_score" and p["ppa"] == "wns_ns")
    assert pair["r"] > 0.8
    assert corr["modules"]

    sr = client.get("/api/search", params={"q": "mac"}).json()
    assert len(sr["signals"]) == 3 and sr["text"]

    tr = client.get("/api/trace", params={
        "run_id": rid, "kind": "area", "scope_path": "core_top/u_ex"}).json()
    assert tr["found"] and tr["src_line"] >= 1
    tr = client.get("/api/trace", params={
        "run_id": rid, "kind": "rtla_qor", "line": 3}).json()
    assert tr["found"] and sum(1 for l in tr["lines"] if l["hit"]) == 1

    # ---- existing views keep working on the v2 series --------------------
    sc = client.get(f"/api/scorecard/{rid}").json()
    assert sc["fom"]["specint_score"] > 0
    assert "budgets" in sc
    cmp = client.get(f"/api/compare?run_ids={rid},{runs[2]['run_id']}").json()
    assert cmp["comparisons"][0]["decomposition"]["net_pct"] != 0
    ds = client.get("/api/design-space").json()
    assert any(p["pareto"] for p in ds["points"])
    hs = client.get(f"/api/hotspot/{rid}").json()
    assert max(r["area_share"] for r in hs["rows"]) > 0.1
    fnd = client.get("/api/findings").json()
    assert len(fnd) > 20

    # ---- offline analyst patterns ----------------------------------------
    def ask(content):
        return client.post("/api/ai/chat", json={
            "messages": [{"role": "user", "content": content}],
            "run_context": {"view": "scorecard", "run_id": rid},
        }).json()

    resp = ask("what changed in v0.5")
    assert resp["offline"] is True
    assert resp["view_proposal"]["view"] == "timeline"
    assert "area_mm2" in resp["content"] and "bypass" in resp["content"]
    assert resp["citations"]

    resp = ask("what changed after v0.10")
    assert resp["view_proposal"]["view"] == "timeline"
    assert "leakage_share" in resp["content"]

    resp = ask("why did the power jump")
    assert resp["view_proposal"]["view"] == "timeline"
    assert "total_power_mw" in resp["content"]

    resp = ask("how does power correlate with score")
    assert resp["view_proposal"]["view"] == "correlations"
    assert "r = " in resp["content"]

    resp = ask("show signals matching mac")
    assert resp["view_proposal"]["view"] == "timing"
    assert "mac" in resp["content"]

    resp = ask("give me an overview of v0.1")
    assert resp["offline"] is True
    assert resp["view_proposal"]["view"] == "scorecard"
    assert "score" in resp["content"]
    assert resp["citations"]
