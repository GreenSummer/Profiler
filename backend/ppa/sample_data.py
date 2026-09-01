"""Synthetic run generator v3: a 16-version RTL evolution of a small
out-of-order RISC-V core at ONE constant config (the daily-synthesis story),
observed through five provenance series per version:

  synth   full RTL synthesis (area/timing/qor/power/perf reports)
  gem5    cycle-model perf simulation (specint report only, ~+2% optimistic)
  slice   slice-based perf model (specint only, +-1% around zebu)
  zebu    Zebu RTL emulation (specint only, the perf "truth")
  fogs    fast-gate-level perf model (specint only, +-2% around zebu)

Purpose: runnable demo + parser golden fixtures without real (confidential)
tool output. Every version runs the same EDA flow (stage=synth, one corner);
only the RTL differs, described by a git sha and a change note.

Physics is approximate but self-consistent (children roll up to parents,
matching report_area -hierarchy / PrimePower semantics) and carries five
planted PPA events so change-point detection has something true to find:

  v0.5   area step:    new u_byp module (full bypass network), total +~8%
  v0.7   timing cliff: un-retimed MAC path in u_mul, WNS 0.05 -> -0.07 ns
  v0.8   recovery:     MAC retimed, WNS back to +0.03
  v0.9   power spike:  clock-gating insertion disabled (u_clk power x1.45)
  v0.10  recovery:     gating re-enabled
  v0.11-13 leakage trend: VT mix creeps toward LVT (leak share ~8% -> ~17%)
  v0.14  good trade:   BTAC 512->2k: IPC +~3% for area +~2%

All other version-to-version variation is deterministic +/-0.5% noise,
an order of magnitude below the detector threshold.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

# ------------------------------------------------------------ version series

BASE_CONFIG = {
    "name": "soc_cfg_a", "rob": 64, "lsq": 32, "issue": 4, "l1d_kb": 32,
    "l1i_kb": 32, "l2_kb": 512, "btac": 512, "gated": True, "vt_mix": "balanced",
}

VERSIONS = [
    # label    date        sha       change note
    ("v0.1",  "2026-05-04", "8f2c1ad", "initial bring-up: OoO pipeline functional, no optimization"),
    ("v0.2",  "2026-05-11", "3d97e02", "fixed LSQ age-bit bug; RTL cleanup"),
    ("v0.3",  "2026-05-18", "b41aa7c", "decoder lint fixes; no functional change"),
    ("v0.4",  "2026-05-25", "c07f5b9", "added CSR performance counters"),
    ("v0.5",  "2026-06-01", "e5d2083", "added full bypass network in EX (load-to-use forwarding)"),
    ("v0.6",  "2026-06-08", "7a93d4f", "minor scheduler tweaks"),
    ("v0.7",  "2026-06-15", "d2f8a11", "added MAC instruction to EX; multiply path un-retimed"),
    ("v0.8",  "2026-06-22", "91c4e6b", "retimed MAC pipeline; timing recovered"),
    ("v0.9",  "2026-06-29", "4be7f39", "power script regression: clock-gating insertion disabled"),
    ("v0.10", "2026-07-06", "f60a2c8", "re-enabled clock-gating insertion; power restored"),
    ("v0.11", "2026-07-13", "2c8d91e", "VT mix shifted toward LVT for the scheduler"),
    ("v0.12", "2026-07-20", "a1e5b73", "LVT scope widened to the LSU"),
    ("v0.13", "2026-07-27", "8d3c40f", "LVT scope widened to the L2 adapter"),
    ("v0.14", "2026-08-03", "b7e9d15", "BTAC entries 512->2k (branch-target capacity)"),
    ("v0.15", "2026-08-10", "5f0a8c2", "bug fixes; no PPA-relevant change"),
    ("v0.16", "2026-08-17", "9b4e7d1", "cleanup + CDC lint fixes"),
]

BENCH = [
    # name          base_ipc  l1d_mpki l2_mpki br_misp  character
    ("400.perlbench", 1.90, 1.8, 0.35, 3.1, "int"),
    ("401.bzip2",     1.45, 3.9, 0.60, 2.6, "mem"),
    ("403.gcc",       1.55, 2.6, 0.42, 5.8, "branch"),
    ("429.mcf",       0.72, 8.8, 3.90, 1.2, "mem"),
    ("445.gobmk",     1.70, 1.6, 0.28, 2.9, "int"),
    ("456.hmmer",     2.10, 1.1, 0.18, 1.4, "compute"),
    ("458.sjeng",     1.85, 1.4, 0.24, 1.8, "int"),
    ("462.libquantum",2.40, 4.5, 1.10, 0.4, "compute"),
    ("464.h264ref",   1.60, 2.2, 0.55, 2.2, "mem"),
    ("471.omnetpp",   0.95, 7.2, 2.60, 6.5, "mem"),
    ("473.astar",     1.50, 4.1, 0.95, 3.3, "mem"),
    ("483.xalancbmk", 1.05, 6.5, 2.10, 7.2, "mem"),
]

REF_IPC = 1.0   # reference machine IPC for ratio@1GHz

# total power normalization: unnoised v0.1 raw weight sum -> 33 mW
_K_MW = 33.0 / 234288.0


def _geom(xs: list[float]) -> float:
    return math.exp(sum(math.log(max(x, 1e-9)) for x in xs) / len(xs))


# ------------------------------------------------------------ version model

def model_version(idx: int) -> dict:
    """PPA model of VERSIONS[idx] (0-based): cumulative events + noise."""
    rnd = random.Random(9000 + idx)

    # ---- event state
    u_byp_area = 15400.0 if idx >= 4 else 0.0            # v0.5 bypass network
    wns = 0.05                                            # v0.1..v0.6
    if idx == 6:
        wns = -0.07                                       # v0.7 MAC cliff
    elif idx >= 7:
        wns = 0.03                                        # v0.8+ retimed
    clk_w_mult = 1.45 if idx == 8 else 1.0                # v0.9 CG collapse
    cg_eff = 55.0 if idx == 8 else 78.0
    leak_steps = min(max(idx - 9, 0), 3) if idx >= 10 else 0  # v0.11..13 creep
    leak_mult = 1.30 ** leak_steps
    ipc_mult = 1.024 if idx >= 13 else 1.0                # v0.14 BTAC
    branch_boost = 1.045 if idx >= 13 else 1.0
    bp_area_mult = 2.2 if idx >= 13 else 1.0              # BTAC 512->2k
    logic_levels = 38 if idx == 6 else (34 if idx >= 7 else 31)

    def noisy(v: float, pct: float = 0.005) -> float:
        return v * (1.0 + rnd.uniform(-pct, pct))

    # ---- leaf areas (um^2); parents roll up exactly from these
    leaves: dict[str, float] = {
        "core_top/u_ifu/u_bp": noisy(3100.0 * bp_area_mult),
        "core_top/u_ifu/u_dec": noisy(18000.0),
        "core_top/u_ifu/u_l1i": noisy(13200.0),
        "core_top/u_ex/gen_alu_0/u_alu": noisy(4900.0),
        "core_top/u_ex/gen_alu_1/u_alu": noisy(4900.0),
        "core_top/u_ex/u_rob": noisy(17640.0),
        "core_top/u_ex/u_lsq": noisy(8680.0),
        "core_top/u_ex/u_sched": noisy(16000.0),
        "core_top/u_ex/u_mul": noisy(11800.0),
        "core_top/u_lsu/u_dtlb": noisy(9000.0),
        "core_top/u_lsu/u_wb": noisy(11000.0),
        "core_top/u_lsu/u_l1d": noisy(14000.0),
        "core_top/u_l2/u_adapt": noisy(8000.0),
        "core_top/u_l2/u_l2mem": noisy(26000.0),
        "core_top/u_csr": noisy(15000.0),
        "core_top/u_clk": noisy(6000.0),
    }
    if u_byp_area:
        leaves["core_top/u_ex/u_byp"] = noisy(u_byp_area)

    # ---- timing
    wns += rnd.uniform(-0.003, 0.003)
    period = 1.20
    fmax = 1000.0 / (period - wns)
    critical_module = "u_mul" if idx >= 6 else "u_sched"

    # ---- per-leaf power weights (density multipliers)
    def weight(path: str) -> float:
        leaf = path.rsplit("/", 1)[-1]
        if "gen_alu" in path:
            leaf = "u_alu"
        w = _PW_W.get(leaf, 1.0)
        if leaf == "u_clk":
            w *= clk_w_mult
        return w

    raw = {p: a * weight(p) for p, a in leaves.items()}
    total_mw = sum(raw.values()) * _K_MW

    return {
        "version": VERSIONS[idx][0], "idx": idx,
        "leaves": leaves, "raw_power": raw, "total_mw": total_mw,
        "wns": wns, "fmax_mhz": fmax, "period_ns": period,
        "critical_module": critical_module, "logic_levels": logic_levels,
        "cg_eff": cg_eff, "leak_mult": leak_mult,
        "ipc_mult": ipc_mult, "branch_boost": branch_boost,
    }


def bench_rows(m: dict) -> list[dict]:
    rows = []
    for bi, (name, base_ipc, l1d_mpki, l2_mpki, br_misp, char) in enumerate(BENCH):
        rnd = random.Random(7000 + m["idx"] * 100 + bi)
        ipc = base_ipc * m["ipc_mult"]
        if char == "branch":
            ipc *= m["branch_boost"]
        ipc *= 1.0 + rnd.uniform(-0.005, 0.005)
        ratio = ipc / REF_IPC
        rows.append({
            "benchmark": name, "ipc": round(ipc, 3), "ratio_1ghz": round(ratio, 4),
            "l1d_mpki": l1d_mpki, "l2_mpki": l2_mpki,
            "br_mispred_pct": br_misp,
            "cycles_m": round(2300 / ipc, 1), "inst_m": round(2300.0, 1),
        })
    return rows


# perf-model provenance series: systematic bias vs the emulation truth
# (zebu) + deterministic per-model noise. All models share the planted IPC
# events, so trends agree while the model gaps stay visible.
PERF_MODELS = ["gem5", "slice", "zebu", "fogs"]
_MODEL_BIAS = {"gem5": 1.02, "slice": 1.0, "zebu": 1.0, "fogs": 1.0}
_MODEL_NOISE = {"gem5": 0.005, "slice": 0.01, "zebu": 0.003, "fogs": 0.02}


def bench_rows_model(m: dict, model: str) -> list[dict]:
    """Per-benchmark rows for one perf-model series (specint report)."""
    rows = []
    for bi, (name, base_ipc, l1d_mpki, l2_mpki, br_misp, char) in enumerate(BENCH):
        rnd = random.Random(50000 + sum(ord(c) for c in model) * 37
                           + m["idx"] * 100 + bi)
        ipc = base_ipc * m["ipc_mult"]
        if char == "branch":
            ipc *= m["branch_boost"]
        ipc *= _MODEL_BIAS[model]
        ipc *= 1.0 + rnd.uniform(-_MODEL_NOISE[model], _MODEL_NOISE[model])
        ratio = ipc / REF_IPC
        rows.append({
            "benchmark": name, "ipc": round(ipc, 3), "ratio_1ghz": round(ratio, 4),
            "l1d_mpki": l1d_mpki, "l2_mpki": l2_mpki,
            "br_mispred_pct": br_misp,
            "cycles_m": round(2300 / ipc, 1), "inst_m": round(2300.0, 1),
        })
    return rows


# ------------------------------------------------------------ hierarchy tree

# composition per module: (comb, seq, macro, clock, buf) shares, sum = 1.0
COMB, SEQ, MACRO, CLK, BUF = range(5)
_COMPS = {
    "u_bp":    (0.30, 0.55, 0.00, 0.05, 0.10),
    "u_dec":   (0.55, 0.38, 0.00, 0.03, 0.04),
    "u_l1i":   (0.02, 0.03, 0.95, 0.00, 0.00),
    "u_alu":   (0.88, 0.00, 0.00, 0.04, 0.08),
    "u_rob":   (0.35, 0.60, 0.00, 0.02, 0.03),
    "u_lsq":   (0.40, 0.55, 0.00, 0.02, 0.03),
    "u_sched": (0.62, 0.33, 0.00, 0.02, 0.03),
    "u_mul":   (0.72, 0.24, 0.00, 0.02, 0.02),
    "u_byp":   (0.78, 0.14, 0.00, 0.03, 0.05),
    "u_dtlb":  (0.60, 0.35, 0.00, 0.02, 0.03),
    "u_wb":    (0.55, 0.40, 0.00, 0.02, 0.03),
    "u_l1d":   (0.02, 0.03, 0.95, 0.00, 0.00),
    "u_adapt": (0.70, 0.22, 0.00, 0.03, 0.05),
    "u_l2mem": (0.01, 0.02, 0.97, 0.00, 0.00),
    "u_csr":   (0.45, 0.48, 0.00, 0.03, 0.04),
    "u_clk":   (0.05, 0.10, 0.00, 0.75, 0.10),
}

# power weight per module: power density multiplier vs area
_PW_W = {
    "u_l1i": 1.3, "u_l1d": 1.3, "u_l2mem": 1.2,     # memory access energy
    "u_clk": 8.0,                                     # clock tree
    "u_rob": 1.15, "u_lsq": 1.15, "u_sched": 1.1,    # hot control
    "u_mul": 1.1, "u_byp": 1.05,
    "u_bp": 0.8, "u_csr": 0.2, "u_adapt": 0.7,
}


def build_tree(m: dict) -> dict:
    """Canonical hierarchy with exact areas: leaves carry the model areas,
    parents are sums of their children (real roll-up semantics)."""
    leaves = m["leaves"]
    tree: dict[str, dict] = {}

    def node(path: str, area: float, children: list[str]):
        comp = _COMPS.get(path.rsplit("/", 1)[-1])
        if comp is None and "gen_alu" in path:
            comp = _COMPS["u_alu"]
        tree[path] = {"area": area, "children": children, "comp": comp}
        return tree[path]

    def sum_node(path: str, children: list[str]):
        area = sum(tree[c]["area"] for c in children)
        return node(path, area, children)

    for p, a in leaves.items():
        node(p, a, [])
    for i in (0, 1):
        sum_node(f"core_top/u_ex/gen_alu_{i}", [f"core_top/u_ex/gen_alu_{i}/u_alu"])
    ex_kids = ["core_top/u_ex/gen_alu_0", "core_top/u_ex/gen_alu_1",
               "core_top/u_ex/u_rob", "core_top/u_ex/u_lsq",
               "core_top/u_ex/u_sched", "core_top/u_ex/u_mul"]
    if "core_top/u_ex/u_byp" in leaves:
        ex_kids.append("core_top/u_ex/u_byp")
    sum_node("core_top/u_ex", ex_kids)
    sum_node("core_top/u_ifu", ["core_top/u_ifu/u_bp", "core_top/u_ifu/u_dec",
                                "core_top/u_ifu/u_l1i"])
    sum_node("core_top/u_lsu", ["core_top/u_lsu/u_dtlb", "core_top/u_lsu/u_wb",
                                "core_top/u_lsu/u_l1d"])
    sum_node("core_top/u_l2", ["core_top/u_l2/u_adapt", "core_top/u_l2/u_l2mem"])
    node("core_top",
         tree["core_top/u_ifu"]["area"] + tree["core_top/u_ex"]["area"]
         + tree["core_top/u_lsu"]["area"] + tree["core_top/u_l2"]["area"]
         + tree["core_top/u_csr"]["area"] + tree["core_top/u_clk"]["area"],
         ["core_top/u_ifu", "core_top/u_ex", "core_top/u_lsu", "core_top/u_l2",
          "core_top/u_csr", "core_top/u_clk"])
    return tree


def _cat_split(path: str, area: float, tree: dict) -> tuple[float, float, float, float, float]:
    """(comb, seq, macro, clock, buf) for a node; interior nodes sum children."""
    n = tree[path]
    if n["comp"] is not None:
        c, s, ma, ck, b = n["comp"]
        return area * c, area * s, area * ma, area * ck, area * b
    tot = [0.0] * 5
    for ch in n["children"]:
        cs = _cat_split(ch, tree[ch]["area"], tree)
        for i in range(5):
            tot[i] += cs[i]
    return tuple(tot)  # type: ignore[return-value]


def _walk(tree: dict, path: str = "core_top", depth: int = 0):
    yield path, depth
    for ch in tree[path]["children"]:
        yield from _walk(tree, ch, depth + 1)


def power_of(m: dict, path: str, tree: dict) -> float:
    """Leaf power in mW (raw weight x constant scale); parents roll up."""
    if not tree[path]["children"]:
        return m["raw_power"][path] * _K_MW
    return sum(power_of(m, c, tree) for c in tree[path]["children"])


# ------------------------------------------------------------ emitters

def emit_rtla_area(m: dict) -> str:
    tree = build_tree(m)
    lines = [
        "************************************************************************",
        "Report : report_area -hierarchy",
        "Design : rv_ooc_core",
        "Version: T-2022.03-SP4",
        "Library : n7_tt_0p80v_25c",
        f"Date   : {VERSIONS[m['idx']][1]}",
        "************************************************************************",
        "Hierarchical cell area (um^2)",
        "---",
        "Module                          Comb       Seq     Macro     Clock   Buf/Inv   Cells",
    ]
    for path, depth in _walk(tree):
        area = tree[path]["area"]
        comb, seq, macro, clock, buf = _cat_split(path, area, tree)
        name = path.rsplit("/", 1)[-1]
        indent = "" if path == "core_top" else "  " * depth
        cells = int(area / 1.25)
        lines.append(f"{indent}{name:<22} {comb:>10.1f} {seq:>9.1f} {macro:>9.1f} {clock:>9.1f} {buf:>9.1f} {cells:>8d}")
    comb, seq, macro, clock, buf = _cat_split("core_top", tree["core_top"]["area"], tree)
    lines.append(f"{'Total':<24} {comb:>10.1f} {seq:>9.1f} {macro:>9.1f} {clock:>9.1f} {buf:>9.1f} {int(tree['core_top']['area']/1.25):>8d}")
    # die floor: core placed at 62% utilization; the row is the core split
    # plus unplaced logic overhead, so its categories sum to the die area
    core_area = tree["core_top"]["area"]
    die_area = core_area / 0.62
    over = die_area - core_area
    dc, ds, dm, dck, db = comb, seq, macro, clock, buf
    lines.append(f"{'die_total':<24} {dc + over * 0.58:>10.1f} {ds + over * 0.30:>9.1f} {dm:>9.1f} {dck:>9.1f} {db + over * 0.12:>9.1f} {int(die_area / 1.25):>8d}")
    return "\n".join(lines) + "\n"


def emit_rtla_timing(m: dict) -> str:
    period = m["period_ns"]
    wns = m["wns"]
    fmax = m["fmax_mhz"]
    groups = [
        ("reg2reg", wns, wns * -140 if wns < 0 else 0.0, 96 if wns < 0 else 3, fmax),
        ("in2reg", wns + 0.08, (-(wns + 0.08) * 40) if wns < -0.08 else 0.0, 12 if wns < -0.08 else 0, 1000 / (period - (wns + 0.08))),
        ("reg2out", wns + 0.12, 0.0, 0, 1000 / (period - (wns + 0.12))),
        ("cg_hold", 0.05, 0.0, 0, 0.0),
    ]
    lines = [
        "************************************************************************",
        "Report : report_timing -summary -max_paths 200",
        "Design : rv_ooc_core",
        "Version: T-2022.03-SP4",
        f"Date   : {VERSIONS[m['idx']][1]}",
        "************************************************************************",
        "Clock clk  period 1.20 ns",
        "",
        "Path Group      WNS (ns)    TNS (ns)   NVE    Fmax (MHz)",
        "---",
    ]
    for g in groups:
        lines.append(f"{g[0]:<14} {g[1]:>9.3f} {g[2]:>11.2f} {g[3]:>6d} {g[4]:>12.1f}")
    tot_wns = min(g[1] for g in groups)
    tot_tns = sum(g[2] for g in groups)
    tot_nve = sum(g[3] for g in groups)
    lines.append(f"{'Total':<14} {tot_wns:>9.3f} {tot_tns:>11.2f} {tot_nve:>6d} {fmax:>12.1f}")
    lines.append("")
    lines.append("Setup slack histogram (ns, endpoint count)")
    lines.append("---")
    hist = [(-0.25, 2), (-0.20, 4), (-0.15, 9), (-0.10, 14), (-0.05, 28),
            (0.00, 41), (0.05, 63), (0.10, 95), (0.15, 130), (0.20, 88),
            (0.25, 60), (0.30, 37), (0.40, 21), (0.50, 12), (0.60, 5)]
    for bucket, count in hist:
        shifted = bucket + wns     # wns>0 shifts whole distribution right
        lines.append(f"[{shifted:>6.2f}] {count:>6d}")
    lines.append("")
    lines.append("Top violating paths (setup, clock clk)")
    lines.append("---")
    # pre-v0.7 the scheduler owns the critical path; from v0.7 the un-retimed
    # (later retimed) MAC path in u_mul is worst -- the signal-search story
    critical = [
        ("core_top/u_ex/u_rob/u_sched/issue_rdy_q_reg[7]", "core_top/u_ex/gen_alu_0/u_alu/cmp_nxt_a", "reg2reg", 34, wns),
        ("core_top/u_ex/u_rob/u_sched/sel_grant_q_reg[3]", "core_top/u_ex/gen_alu_1/u_alu/cmp_nxt_b", "reg2reg", 31, wns + 0.012),
        ("core_top/u_ex/u_lsq/u_wakeup/cam_hit_q_reg[11]", "core_top/u_ex/u_lsq/u_wakeup/load_wakeup_l", "reg2reg", 29, wns + 0.021),
        ("core_top/u_ifu/u_bp/btb_hit_q_reg[5]", "core_top/u_ifu/u_dec/u_rename/dest_map_q_reg[19]", "reg2reg", 27, wns + 0.033),
        ("core_top/u_lsu/u_dtlb/pte_tag_q_reg[2]", "core_top/u_lsu/u_wb/wb_arb_grant_l", "reg2reg", 25, wns + 0.044),
        ("core_top/u_ifu/u_dec/u_scan/insn_buf_q_reg[8]", "core_top/u_ifu/u_dec/u_scan/u_deco/illegal_insn", "reg2reg", 22, wns + 0.058),
        ("core_top/u_l2/u_adapt/rsp_buf_q_reg[4]", "core_top/u_l2/u_adapt/req_issue_l", "reg2reg", 20, wns + 0.071),
    ]
    mac_paths = [
        ("core_top/u_ex/u_mul/mac_part_q_reg[11]", "core_top/u_ex/u_mul/mac_acc_q_reg[63]", "reg2reg", m["logic_levels"], wns),
        ("core_top/u_ex/u_mul/mul_start_q_reg[2]", "core_top/u_ex/u_mul/mac_part_q_reg[11]", "reg2reg", m["logic_levels"] - 5, wns + 0.017),
        ("core_top/u_ex/u_mul/mac_acc_q_reg[63]", "core_top/u_ex/u_wb/wb_data_l", "reg2reg", m["logic_levels"] - 7, wns + 0.026),
    ]
    if m["idx"] >= 6:
        # MAC paths own the top slots; the scheduler path slips to 2nd
        critical[0] = (critical[0][0], critical[0][1], critical[0][2], critical[0][3], wns + 0.012)
        critical = mac_paths + critical
    for i, (sp, ep, grp, depth, sl) in enumerate(critical, 1):
        lines.append(f"Path {i}")
        lines.append(f"  Startpoint: {sp}")
        lines.append(f"  Endpoint:   {ep}")
        lines.append(f"  Path Group: {grp}")
        lines.append(f"  Logic Depth: {depth}")
        lines.append(f"  Slack: {sl:.3f} ns (VIOLATED)" if sl < 0 else f"  Slack: {sl:.3f} ns")
        lines.append(f"  Arrival: {period - sl:.3f} ns   Required: {period:.3f} ns")
    return "\n".join(lines) + "\n"


def emit_rtla_qor(m: dict) -> str:
    a = sum(m["leaves"].values())
    return "\n".join([
        "************************************************************************",
        "Report : report_qor",
        "Design : rv_ooc_core",
        "Version: T-2022.03-SP4",
        f"Date   : {VERSIONS[m['idx']][1]}",
        "************************************************************************",
        "Metric                                  Value",
        "---",
        f"Cell Area (um^2)                  {a:>14.1f}",
        f"Sequential Area (um^2)            {a * 0.26:>14.1f}",
        f"Macro Area (um^2)                 {a * 0.16:>14.1f}",
        f"Buffer/Inverter Area (um^2)       {a * 0.075:>14.1f}",
        f"Cell Count                        {int(a / 1.25):>14d}",
        f"Critical Path Logic Levels        {m['logic_levels']:>14d}",
        f"WNS (ns)                          {m['wns']:>14.3f}",
        f"TNS (ns)                          {m['wns'] * -140 if m['wns'] < 0 else 0.0:>14.2f}",
        f"Estimated Fmax (MHz)              {m['fmax_mhz']:>14.1f}",
    ]) + "\n"


def emit_primepower(m: dict) -> str:
    """PrimePower-style vectorless hierarchical report. Dot separators and
    bracketed generate indices -- deliberately different spelling from RTLA
    so canonicalization is exercised end to end."""
    tree = build_tree(m)
    total = m["total_mw"]
    leak_mult = m["leak_mult"]

    def split_ils(path: str, p_total: float) -> tuple[float, float, float]:
        leaf = path.rsplit("/", 1)[-1]
        if leaf in ("u_l1i", "u_l1d", "u_l2mem"):
            ls = (0.12 if leaf != "u_l2mem" else 0.14) * leak_mult   # macros leak more
        elif leaf in ("u_rob", "u_lsq", "u_bp"):
            ls = 0.064 * leak_mult                                   # dense CAM/RAM
        else:
            ls = 0.08 * leak_mult
        leak = p_total * min(ls, 0.5)
        rest = p_total - leak
        return rest * 0.53, rest * 0.47, leak

    lines = [
        "************************************************************************",
        "Report : report_power -analysis_mode vectorless -hierarchy",
        "Design : rv_ooc_core",
        "Version: P-2019.06-SP1",
        f"Date   : {VERSIONS[m['idx']][1]}",
        "Supply : 0.80 V",
        "Default toggle rate: 0.15",
        f"Clock gating efficiency: {m['cg_eff']:.1f} %",
        "************************************************************************",
        "Power by category (mW)",
        "---",
    ]
    clock_mw = power_of(m, "core_top/u_clk", tree)
    rest = total - clock_mw
    lines.append(f"Combinational  {rest * 0.40:>10.3f}")
    lines.append(f"Register       {rest * 0.26:>10.3f}")
    lines.append(f"Clock          {clock_mw:>10.3f}")
    lines.append(f"Memory         {rest * 0.34:>10.3f}")
    lines.append("")
    lines.append("Hierarchical power (mW)")
    lines.append("---")
    lines.append("Instance                          Internal  Switching   Leakage     Total")
    for path, depth in _walk(tree):
        p_tot = power_of(m, path, tree)
        inte, swi, leak = split_ils(path, p_tot)
        # render with '.' separators and gen blocks bracketed (PP style)
        segs = []
        for seg in path.split("/"):
            if seg.startswith("gen_alu_"):
                idx = seg.rsplit("_", 1)[1]
                segs.append(f"gen_alu[{idx}]")
            else:
                segs.append(seg)
        name = ".".join(segs)
        indent = "" if path == "core_top" else "  " * depth
        lines.append(f"{indent}{name:<34} {inte:>9.3f} {swi:>10.3f} {leak:>9.3f} {p_tot:>9.3f}")
    inte, swi, leak = split_ils("core_top", total)
    lines.append(f"{'Total':<34} {inte:>9.3f} {swi:>10.3f} {leak:>9.3f} {total:>9.3f}")
    return "\n".join(lines) + "\n"


def emit_specint(m: dict) -> str:
    rows = bench_rows(m)
    lines = [
        "************************************************************************",
        "SPECint2006 result summary (instruction-accurate core model)",
        "Method : performance-model (sparta-based, 250M inst SimPoint)",
        "Version: v0.9.2",
        f"Date   : {VERSIONS[m['idx']][1]}",
        "************************************************************************",
        "Benchmark        Ref IPC   Cycles(M)   Insts(M)     IPC   Ratio@1GHz  L1D MPKI  L2 MPKI  BrMisp%",
        "---",
    ]
    for r in rows:
        lines.append(
            f"{r['benchmark']:<14} {REF_IPC:>8.2f} {r['cycles_m']:>11.1f} {r['inst_m']:>11.1f}"
            f" {r['ipc']:>7.3f} {r['ratio_1ghz']:>11.4f} {r['l1d_mpki']:>9.2f} {r['l2_mpki']:>8.2f} {r['br_mispred_pct']:>7.1f}"
        )
    gm = _geom([r["ratio_1ghz"] for r in rows])
    lines.append(f"{'Geomean':<14} {REF_IPC:>8.2f} {'':>11} {'':>11} {'':>7} {gm:>11.4f}")
    return "\n".join(lines) + "\n"


_METHOD = {
    "gem5": "gem5 full-system cycle model (SE mode, SimPoint)",
    "slice": "slice-based perf model (32-slice aggregation)",
    "zebu": "Zebu RTL emulation (workload checkpoints)",
    "fogs": "fast gate-level simulation (gate model, sampled)",
}


def emit_specint_model(m: dict, model: str) -> str:
    """specint report for one perf-model series (identical format)."""
    rows = bench_rows_model(m, model)
    lines = [
        "************************************************************************",
        "SPECint2006 result summary (instruction-accurate core model)",
        f"Method : {_METHOD[model]}",
        "Version: v0.9.2",
        f"Date   : {VERSIONS[m['idx']][1]}",
        "************************************************************************",
        "Benchmark        Ref IPC   Cycles(M)   Insts(M)     IPC   Ratio@1GHz  L1D MPKI  L2 MPKI  BrMisp%",
        "---",
    ]
    for r in rows:
        lines.append(
            f"{r['benchmark']:<14} {REF_IPC:>8.2f} {r['cycles_m']:>11.1f} {r['inst_m']:>11.1f}"
            f" {r['ipc']:>7.3f} {r['ratio_1ghz']:>11.4f} {r['l1d_mpki']:>9.2f} {r['l2_mpki']:>8.2f} {r['br_mispred_pct']:>7.1f}"
        )
    gm = _geom([r["ratio_1ghz"] for r in rows])
    lines.append(f"{'Geomean':<14} {REF_IPC:>8.2f} {'':>11} {'':>11} {'':>7} {gm:>11.4f}")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------ driver

def generate(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    manifest = []
    for idx, (label, date, sha, note) in enumerate(VERSIONS):
        m = model_version(idx)
        # ---- full synthesis series (5 reports)
        d = out_dir / label
        d.mkdir(exist_ok=True)
        files = {
            "rtla_area.rpt": emit_rtla_area(m),
            "rtla_timing.rpt": emit_rtla_timing(m),
            "rtla_qor.rpt": emit_rtla_qor(m),
            "primepower.rpt": emit_primepower(m),
            "specint.rpt": emit_specint(m),
        }
        for fn, text in files.items():
            p = d / fn
            p.write_text(text)
            written.append(p)
        manifest.append({
            "label": label,
            "version": label,
            "model": "synth",
            "sha": sha,
            "date": date,
            "change_note": note,
            "params": dict(BASE_CONFIG),
            "corner": "tt_0p80v_25c",
            "stage": "synth",
            "order": idx * 10,
        })
        # ---- perf-model series (one specint report each)
        for mi, model in enumerate(PERF_MODELS):
            mlabel = f"{label}-{model}"
            md = out_dir / mlabel
            md.mkdir(exist_ok=True)
            p = md / "specint.rpt"
            p.write_text(emit_specint_model(m, model))
            written.append(p)
            manifest.append({
                "label": mlabel,
                "version": label,
                "model": model,
                "sha": sha,
                "date": date,
                "change_note": note,
                "params": dict(BASE_CONFIG),
                "corner": "tt_0p80v_25c",
                "stage": "sim",
                "order": idx * 10 + mi + 1,
            })
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    written.append(out_dir / "manifest.json")
    return written


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sample_runs")
    for p in generate(out):
        print(f"wrote {p}")
