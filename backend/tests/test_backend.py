"""Backend test suite: parsers, canonicalization, metrics, rules, API."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from ppa.canonicalize import canonicalize_path, owner_module
from ppa.db import make_engine, init_db
from ppa.ingest import ingest_directory
from ppa.metrics import figures_of_merit, net_score_decomposition, pareto_front
from ppa.parsers.primepower import parse_primepower
from ppa.parsers.rtla import parse_rtla_area, parse_rtla_timing
from ppa.parsers.specint import parse_specint
from ppa.sample_data import generate


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
    area = parse_rtla_area((tmp_path / "baseline" / "rtla_area.rpt").read_text())
    assert area.rows and area.rows[0].tool_path == "core_top"
    total = area.rows[-1]
    assert total.comb_area > 0 and total.inst_count > 100000
    # roll-up: children sum to parent
    kids = sum(r.comb_area for r in area.rows if r.depth == 1)
    assert abs(kids - total.comb_area) / total.comb_area < 0.01

    timing = parse_rtla_timing((tmp_path / "baseline" / "rtla_timing.rpt").read_text())
    assert timing.groups and timing.clocks.get("clk") == 1.20
    assert len(timing.paths) >= 5

    power = parse_primepower((tmp_path / "baseline" / "primepower.rpt").read_text())
    assert power.rows and power.clock_gating_efficiency == 78.0
    assert power.categories["clock"] > 0

    perf = parse_specint((tmp_path / "baseline" / "specint.rpt").read_text())
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


def test_ingest_and_rules(db):
    engine, result = db
    assert len(result["runs"]) == 12
    with Session(engine) as s:
        from sqlmodel import select
        from ppa.models import Finding, Run
        runs = s.exec(select(Run)).all()
        labels = {r.label for r in runs}
        assert "rob192" in labels and "leaky" in labels
        findings = s.exec(select(Finding)).all()
        by_rule = {}
        for f in findings:
            by_rule.setdefault(f.rule_id, []).append(f)
        # the intentional anomalies must be caught
        assert any(f.rule_id == "XDOM_NET_SCORE_DOWN" for f in findings), "rob192 net-loss not caught"
        assert any(f.rule_id == "PWR_LEAK_SHARE" for f in findings), "leaky config not caught"
        assert any(f.rule_id == "TIM_WNS_NEG" for f in findings), "timing violation not caught"
        # cross-tool join must be clean (plan R1)
        assert not any(f.rule_id == "DQ_UNMATCHED_PATHS" for f in findings)


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
    assert len(runs) == 12
    rid = runs[0]["run_id"]
    assert "specint_score" in runs[0]["fom"]
    sc = client.get(f"/api/scorecard/{rid}").json()
    assert sc["fom"]["specint_score"] > 0
    assert "budgets" in sc
    cmp = client.get(f"/api/compare?run_ids={rid},{rid + 2}").json()
    assert cmp["comparisons"][0]["decomposition"]["net_pct"] != 0
    ds = client.get("/api/design-space").json()
    assert any(p["pareto"] for p in ds["points"])
    hs = client.get(f"/api/hotspot/{rid}").json()
    assert any(r["area_share"] > 0.25 for r in hs["rows"])
    fnd = client.get("/api/findings").json()
    assert len(fnd) > 20
    # AI offline fallback
    resp = client.post("/api/ai/chat", json={
        "messages": [{"role": "user", "content": "give me an overview of baseline"}],
        "run_context": {"view": "scorecard", "run_id": rid},
    }).json()
    assert resp["offline"] is True
    assert "SPECint" in resp["content"] or "score" in resp["content"]
    assert resp["citations"]
