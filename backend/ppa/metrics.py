"""Metrics engine (plan section 2): Tier-3 figures of merit, Tier-2 domain
summaries, derived ratios, and net-score decomposition. All arithmetic lives
here in Python — the LLM layer is never allowed to compute (plan §6.3).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------- inputs

@dataclass
class TimingSummary:
    wns_ns: float = 0.0
    tns_ns: float = 0.0
    nve: int = 0
    target_period_ns: float = 1.0
    groups: list[dict] = field(default_factory=list)      # {name, wns, tns, nve, fmax}
    histogram: list[dict] = field(default_factory=list)   # {bucket, count}
    slack_list: list[float] = field(default_factory=list)

    @property
    def fmax_mhz(self) -> float:
        # Fmax = 1 / (T_target - WNS)  (setup, positive-WNS designs scale too)
        period = self.target_period_ns - self.wns_ns
        if period <= 0:
            return 0.0
        return 1000.0 / period


@dataclass
class AreaSummary:
    total_um2: float = 0.0
    comb_um2: float = 0.0
    seq_um2: float = 0.0
    macro_um2: float = 0.0
    clock_um2: float = 0.0
    inst_count: int = 0
    util_pct: float | None = None

    @property
    def seq_ratio(self) -> float:
        return self.seq_um2 / self.total_um2 if self.total_um2 else 0.0


@dataclass
class PowerSummary:
    internal_mw: float = 0.0
    switching_mw: float = 0.0
    leakage_mw: float = 0.0
    total_mw: float = 0.0
    clock_power_mw: float = 0.0
    register_power_mw: float = 0.0
    comb_power_mw: float = 0.0
    macro_power_mw: float = 0.0
    toggle_rate: float | None = None
    clock_gating_eff: float | None = None
    vectorless: bool = True

    @property
    def leakage_share(self) -> float:
        return self.leakage_mw / self.total_mw if self.total_mw else 0.0

    @property
    def clock_power_share(self) -> float:
        return self.clock_power_mw / self.total_mw if self.total_mw else 0.0


@dataclass
class PerfSummary:
    per_benchmark: list[dict] = field(default_factory=list)  # {benchmark, ipc, ratio, ...}
    method: str = ""

    @property
    def geomean_ratio_1ghz(self) -> float:
        rs = [r["ratio_1ghz"] for r in self.per_benchmark if r.get("ratio_1ghz")]
        if not rs:
            return 0.0
        return math.exp(sum(math.log(r) for r in rs) / len(rs))

    @property
    def mean_ipc(self) -> float:
        ipcs = [r["ipc"] for r in self.per_benchmark if r.get("ipc")]
        return sum(ipcs) / len(ipcs) if ipcs else 0.0


# ---------------------------------------------------------------- figures of merit

def figures_of_merit(
    timing: TimingSummary,
    area: AreaSummary,
    power: PowerSummary,
    perf: PerfSummary,
    *,
    nand2_area_um2: float,
    fixed_freq_mhz: float | None = None,
) -> dict:
    """Tier-3 figures of merit (plan section 2 table).

    freq source: fixed override or timing-derived Fmax. Always report which
    one was used — the frequency assumption must never be hidden.
    """
    freq_mhz = fixed_freq_mhz if fixed_freq_mhz else timing.fmax_mhz
    freq_ghz = freq_mhz / 1000.0
    spec_per_ghz = perf.geomean_ratio_1ghz
    score = spec_per_ghz * freq_ghz
    area_mm2 = area.total_um2 / 1e6
    power_w = power.total_mw / 1000.0
    ipc = perf.mean_ipc

    fom = {
        "specint_score": score,
        "specint_per_ghz": spec_per_ghz,
        "fmax_mhz": freq_mhz,
        "freq_source": "fixed" if fixed_freq_mhz else "timing",
        "area_mm2": area_mm2,
        "area_kge": area.total_um2 / nand2_area_um2 / 1000.0 if nand2_area_um2 else 0.0,
        "total_power_mw": power.total_mw,
        "mean_ipc": ipc,
        # efficiencies
        "area_eff_score_per_mm2": score / area_mm2 if area_mm2 else 0.0,
        "power_eff_score_per_w": score / power_w if power_w else 0.0,
        "mw_per_mhz": power.total_mw / freq_mhz if freq_mhz else 0.0,
    }
    # EPI in pJ/inst: power_uW / (inst per us) = mW*1e3 uW / (M inst/s)
    inst_per_s = ipc * freq_mhz * 1e6
    fom["epi_pj"] = power.total_mw * 1e3 / inst_per_s if inst_per_s else 0.0
    # EDP / ED2P (energy x delay, delay = 1/freq)
    if freq_mhz and power.total_mw:
        energy_mj = power.total_mw / 1000.0  # mW = mJ/s; per second basis
        delay_s = 1.0 / (freq_mhz * 1e6)
        fom["edp"] = energy_mj * delay_s
        fom["ed2p"] = energy_mj * delay_s * delay_s
    else:
        fom["edp"] = fom["ed2p"] = 0.0
    return fom


# ---------------------------------------------------------------- comparison

def delta(cur: float, base: float) -> dict:
    return {
        "current": cur,
        "baseline": base,
        "abs": cur - base,
        "pct": ((cur - base) / base * 100.0) if base else None,
    }


def roi(delta_score_pct: float | None, delta_cost_pct: float | None) -> float | None:
    """area_ROI / power_ROI: % score gain per % cost gain (plan section 2)."""
    if delta_score_pct is None or delta_cost_pct is None or abs(delta_cost_pct) < 1e-9:
        return None
    return delta_score_pct / delta_cost_pct


def net_score_decomposition(base: dict, cur: dict) -> dict:
    """Thesis 1 made computable: score = spec_per_ghz x freq_ghz, so
    dScore% = dPerGHz% + dFreq% + cross term. Attribution for the V3 waterfall."""
    if not base.get("specint_score") or not cur.get("specint_score"):
        return {}
    b_pgz, c_pgz = base["specint_per_ghz"], cur["specint_per_ghz"]
    b_f, c_f = base["fmax_mhz"], cur["fmax_mhz"]
    d_pgz = (c_pgz - b_pgz) / b_pgz * 100.0
    d_f = (c_f - b_f) / b_f * 100.0
    d_total = (cur["specint_score"] - base["specint_score"]) / base["specint_score"] * 100.0
    cross = d_pgz * d_f / 100.0
    return {
        "ipc_pct": d_pgz,           # microarchitecture contribution
        "freq_pct": d_f,            # physical contribution
        "cross_pct": cross,
        "net_pct": d_total,
        "verdict": "win" if d_total > 0 else ("loss" if d_total < 0 else "flat"),
    }


def compare_fom(base: dict, cur: dict) -> dict:
    """Figure-of-merit delta table with area/power ROI (V3)."""
    keys = [k for k in cur if isinstance(cur.get(k), (int, float))
            and isinstance(base.get(k), (int, float))
            and k not in ("freq_source",)]
    out = {k: delta(cur[k], base[k]) for k in keys}
    ds = out.get("specint_score", {}).get("pct")
    out["area_roi"] = roi(ds, out.get("area_mm2", {}).get("pct"))
    out["power_roi"] = roi(ds, out.get("total_power_mw", {}).get("pct"))
    return out


# ---------------------------------------------------------------- domain summaries

def summarize_area(rows: list[dict], util_pct: float | None = None) -> AreaSummary:
    """rows: hierarchical dicts {scope_path, depth, total_area, comb_area, ...}.
    Summaries read the TOP row only — parents contain children, so summing
    the table double-counts (the text-to-SQL trap)."""
    if not rows:
        return AreaSummary()
    top = min(rows, key=lambda r: r["depth"])
    return AreaSummary(
        total_um2=top["total_area"], comb_um2=top["comb_area"], seq_um2=top["seq_area"],
        macro_um2=top["macro_area"], clock_um2=top["clock_area"],
        inst_count=top["inst_count"], util_pct=util_pct,
    )


def summarize_power(rows: list[dict], categories: dict[str, float] | None = None,
                    toggle_rate: float | None = None,
                    clock_gating_eff: float | None = None) -> PowerSummary:
    if not rows:
        return PowerSummary()
    top = min(rows, key=lambda r: r["depth"])
    cat = categories or {}
    return PowerSummary(
        internal_mw=top["internal"], switching_mw=top["switching"],
        leakage_mw=top["leakage"], total_mw=top["total"],
        clock_power_mw=cat.get("clock", 0.0),
        register_power_mw=cat.get("register", 0.0),
        comb_power_mw=cat.get("combinational", cat.get("comb", 0.0)),
        macro_power_mw=cat.get("macro", cat.get("memory", 0.0)),
        toggle_rate=toggle_rate, clock_gating_eff=clock_gating_eff,
    )


def summarize_timing(groups: list[dict], target_period_ns: float,
                     histogram: list[dict] | None = None,
                     slack_list: list[float] | None = None) -> TimingSummary:
    setup = [g for g in groups if "hold" not in g.get("name", "").lower()]
    wns = min((g["wns_ns"] for g in setup), default=0.0)
    return TimingSummary(
        wns_ns=wns, tns_ns=sum(g["tns_ns"] for g in setup),
        nve=sum(g["nve"] for g in setup),
        target_period_ns=target_period_ns,
        groups=groups, histogram=histogram or [], slack_list=slack_list or [],
    )


# ---------------------------------------------------------------- pareto

def pareto_front(points: list[dict], x: str, y: str, x_max: bool = False, y_max: bool = True) -> set[int]:
    """Indices of non-dominated points. Objective directions configurable;
    defaults: minimize x, maximize y (e.g. x=power, y=score)."""
    nd: set[int] = set()
    for i, p in enumerate(points):
        dominated = False
        for j, q in enumerate(points):
            if i == j:
                continue
            qx_better = (q[x] > p[x]) if x_max else (q[x] < p[x])
            qy_better = (q[y] > p[y]) if y_max else (q[y] < p[y])
            qx_eq = abs(q[x] - p[x]) < 1e-12
            qy_eq = abs(q[y] - p[y]) < 1e-12
            if (qx_better or qx_eq) and (qy_better or qy_eq) and (qx_better or qy_better):
                dominated = True
                break
        if not dominated:
            nd.add(i)
    return nd
