"""Synthetic run generator: emits realistic RTLA/PrimePower/SPECint-style
reports for a 12-point config sweep of a small out-of-order RISC-V core.

Purpose: runnable demo + parser golden fixtures without real (confidential)
tool output. Physics is approximate but self-consistent:
  - bigger ROB/LSQ -> more IPC, more area, deeper critical path (lower Fmax)
  - bigger caches -> fewer misses, more area+leakage, better mcf/omnetpp
  - clock gating -> lower clock power
  - one config has an intentional timing regression (bad CPA in the scheduler)
  - one config has an intentional power anomaly (leaky VT mix)
Hierarchy areas/powers roll up exactly (children sum to parent), matching
real report_area -hierarchy / PrimePower semantics.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

# ------------------------------------------------------------ config space

CONFIGS = [
    # name         rob  lsq  issue  l1d_kb  l1i_kb  l2_kb  btac  gated  vt_mix
    ("baseline",   64,  32,  4,     32,      32,     512,   512,   True,  "balanced"),
    ("rob96",      96,  48,  4,     32,      32,     512,   512,   True,  "balanced"),
    ("rob128",     128, 64,  4,     32,      32,     512,   512,   True,  "balanced"),
    ("rob192",     192, 96,  4,     32,      32,     512,   512,   True,  "balanced"),
    ("issue6",     64,  32,  6,     32,      32,     512,   512,   True,  "balanced"),
    ("issue8",     64,  32,  8,     32,      32,     512,   512,   True,  "balanced"),
    ("l1d64",      64,  32,  4,     64,      32,     512,   512,   True,  "balanced"),
    ("l2_1m",      64,  32,  4,     32,      32,     1024,  512,   True,  "balanced"),
    ("btac2k",     64,  32,  4,     32,      32,     512,   2048,  True,  "balanced"),
    ("nocg",       64,  32,  4,     32,      32,     512,   512,   False, "balanced"),   # clock-gating OFF
    ("leaky",      64,  32,  4,     32,      32,     512,   512,   True,  "lvt_heavy"),  # ULVT mix
    ("rob256",     256, 128, 4,     32,      32,     512,   512,   True,  "balanced"),
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


def _geom(xs: list[float]) -> float:
    return math.exp(sum(math.log(max(x, 1e-9)) for x in xs) / len(xs))


def model_config(cfg: dict) -> dict:
    """Approximate PPA response model for one config point."""
    rob, lsq, issue = cfg["rob"], cfg["lsq"], cfg["issue"]
    l1d, l2, btac = cfg["l1d_kb"], cfg["l2_kb"], cfg["btac"]
    ipc_mult = (1.0
                + 0.11 * math.log2(rob / 64) * 0.5
                + 0.06 * math.log2(issue / 4)
                + 0.02 * math.log2(l1d / 32)
                + 0.025 * math.log2(l2 / 512)
                + 0.012 * math.log2(btac / 512))
    rob_area = 4200 + rob * 210          # CAM+RAM
    lsq_area = 2600 + lsq * 190
    issue_area = 9800 + (issue - 4) * 6800
    l1d_area = 14000 * (l1d / 32) ** 0.85
    l1i_area = 13200
    l2_area = 26000 * (l2 / 512) ** 0.9
    bp_area = 3100 * (btac / 512) ** 0.8
    # fixed leaves (um^2): sched, dec, dtlb, wb, adapt, csr, clk
    total_area = (rob_area + lsq_area + issue_area + l1d_area + l1i_area
                  + l2_area + bp_area + 83000)
    base_period = 1.20  # ns target ~833 MHz
    wns = (0.055
           - 0.011 * math.log2(rob / 64) ** 1.4
           - 0.028 * (issue - 4) / 2
           - 0.004 * math.log2(l2 / 512)
           - 0.006 * math.log2(l1d / 32))
    if cfg["name"] == "rob192":          # intentional timing regression
        wns -= 0.09
    period_eff = base_period - wns
    fmax = 1000.0 / period_eff if period_eff > 0.01 else 100.0
    dyn = (34.0 * (total_area / 260000) * (fmax / 800)
           * (0.9 + 0.1 * issue / 4))
    clock_p = dyn * (0.26 if cfg["gated"] else 0.44)
    leak = total_area * (11.2e-6 if cfg["vt_mix"] != "lvt_heavy" else 41e-6)  # mW/um2
    total_p = dyn + clock_p + leak
    return {
        "ipc_mult": ipc_mult, "total_area": total_area, "wns": wns,
        "fmax_mhz": fmax, "dyn_mw": dyn, "clock_mw": clock_p,
        "leak_mw": leak, "total_mw": total_p,
        "rob_area": rob_area, "lsq_area": lsq_area, "issue_area": issue_area,
        "l1d_area": l1d_area, "l1i_area": l1i_area, "l2_area": l2_area,
        "bp_area": bp_area,
    }


def bench_rows(m: dict, cfg: dict) -> list[dict]:
    rows = []
    for name, base_ipc, l1d_mpki, l2_mpki, br_misp, char in BENCH:
        ipc = base_ipc * m["ipc_mult"]
        if char == "mem":
            ipc *= 1 + 0.06 * math.log2(cfg["l1d_kb"] / 32) + 0.08 * math.log2(cfg["l2_kb"] / 512)
        if char == "branch":
            ipc *= 1 + 0.03 * math.log2(cfg["btac"] / 512)
        if char == "compute":
            ipc *= 1 + 0.02 * math.log2(cfg["issue"] / 4)
        ratio = ipc / REF_IPC
        rows.append({
            "benchmark": name, "ipc": round(ipc, 3), "ratio_1ghz": round(ratio, 4),
            "l1d_mpki": round(l1d_mpki * (32 / cfg["l1d_kb"]) ** 0.4, 2),
            "l2_mpki": round(l2_mpki * (512 / cfg["l2_kb"]) ** 0.5, 2),
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
    "u_dtlb":  (0.60, 0.35, 0.00, 0.02, 0.03),
    "u_wb":    (0.55, 0.40, 0.00, 0.02, 0.03),
    "u_l1d":   (0.02, 0.03, 0.95, 0.00, 0.00),
    "u_adapt": (0.70, 0.22, 0.00, 0.03, 0.05),
    "u_l2mem": (0.01, 0.02, 0.97, 0.00, 0.00),
    "u_csr":   (0.45, 0.48, 0.00, 0.03, 0.04),
    "u_clk":   (0.05, 0.10, 0.00, 0.75, 0.10),
    "gen_alu": (0.88, 0.00, 0.00, 0.04, 0.08),   # gen block wraps one u_alu
}

# power weight per module: power density multiplier vs area share
_PW_W = {
    "u_l1i": 1.3, "u_l1d": 1.3, "u_l2mem": 1.2,     # memory access energy
    "u_clk": 2.6,                                     # clock tree
    "u_rob": 1.15, "u_lsq": 1.15, "u_sched": 1.1,    # hot control
    "u_bp": 0.8, "u_csr": 0.2, "u_adapt": 0.7,
}


def build_tree(m: dict) -> dict:
    """Build the canonical hierarchy with exact areas. Leaves carry model
    areas; parents are sums of their children (real roll-up semantics)."""
    alu = m["issue_area"] / 2
    leaves = {
        "core_top/u_ifu/u_bp": m["bp_area"],
        "core_top/u_ifu/u_dec": 18000.0,
        "core_top/u_ifu/u_l1i": m["l1i_area"],
        "core_top/u_ex/gen_alu_0/u_alu": alu,
        "core_top/u_ex/gen_alu_1/u_alu": alu,
        "core_top/u_ex/u_rob": m["rob_area"],
        "core_top/u_ex/u_lsq": m["lsq_area"],
        "core_top/u_ex/u_sched": 16000.0,
        "core_top/u_lsu/u_dtlb": 9000.0,
        "core_top/u_lsu/u_wb": 11000.0,
        "core_top/u_lsu/u_l1d": m["l1d_area"],
        "core_top/u_l2/u_adapt": 8000.0,
        "core_top/u_l2/u_l2mem": m["l2_area"],
        "core_top/u_csr": 15000.0,
        "core_top/u_clk": 6000.0,
    }
    # gen wrappers take their child's area (contain exactly one child)
    tree: dict[str, dict] = {}

    def node(path: str, area: float, children: list[str]):
        comp = _COMPS.get(path.rsplit("/", 1)[-1],
                          _COMPS.get("gen_alu" if "gen_alu" in path else "", None))
        if comp is None:
            # interior module: composition derived from children at emit time
            comp = None
        tree[path] = {"area": area, "children": children, "comp": comp}
        return tree[path]

    for p, a in leaves.items():
        node(p, a, [])
    node("core_top/u_ex/gen_alu_0", alu, ["core_top/u_ex/gen_alu_0/u_alu"])
    node("core_top/u_ex/gen_alu_1", alu, ["core_top/u_ex/gen_alu_1/u_alu"])
    node("core_top/u_ifu", tree["core_top/u_ifu/u_bp"]["area"] + tree["core_top/u_ifu/u_dec"]["area"] + tree["core_top/u_ifu/u_l1i"]["area"],
         ["core_top/u_ifu/u_bp", "core_top/u_ifu/u_dec", "core_top/u_ifu/u_l1i"])
    node("core_top/u_ex",
         tree["core_top/u_ex/gen_alu_0"]["area"] + tree["core_top/u_ex/gen_alu_1"]["area"]
         + tree["core_top/u_ex/u_rob"]["area"] + tree["core_top/u_ex/u_lsq"]["area"]
         + tree["core_top/u_ex/u_sched"]["area"],
         ["core_top/u_ex/gen_alu_0", "core_top/u_ex/gen_alu_1", "core_top/u_ex/u_rob",
          "core_top/u_ex/u_lsq", "core_top/u_ex/u_sched"])
    node("core_top/u_lsu",
         tree["core_top/u_lsu/u_dtlb"]["area"] + tree["core_top/u_lsu/u_wb"]["area"] + tree["core_top/u_lsu/u_l1d"]["area"],
         ["core_top/u_lsu/u_dtlb", "core_top/u_lsu/u_wb", "core_top/u_lsu/u_l1d"])
    node("core_top/u_l2", tree["core_top/u_l2/u_adapt"]["area"] + tree["core_top/u_l2/u_l2mem"]["area"],
         ["core_top/u_l2/u_adapt", "core_top/u_l2/u_l2mem"])
    top_area = (tree["core_top/u_ifu"]["area"] + tree["core_top/u_ex"]["area"]
                + tree["core_top/u_lsu"]["area"] + tree["core_top/u_l2"]["area"]
                + tree["core_top/u_csr"]["area"] + tree["core_top/u_clk"]["area"])
    node("core_top", top_area,
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


# ------------------------------------------------------------ emitters

def emit_rtla_area(m: dict, cfg: dict) -> str:
    tree = build_tree(m)
    lines = [
        "************************************************************************",
        "Report : report_area -hierarchy",
        "Design : rv_ooc_core",
        "Version: T-2022.03-SP4",
        "Library : n7_tt_0p80v_25c",
        "Date   : 2026-08-31",
        "************************************************************************",
        "Hierarchical cell area (um^2)",
        "---",
        "Module                          Comb       Seq     Macro     Clock   Buf/Inv   Cells",
    ]
    for path, depth in _walk(tree):
        area = tree[path]["area"]
        comb, seq, macro, clock, buf = _cat_split(path, area, tree)
        name = path.rsplit("/", 1)[-1]
        if path == "core_top":
            name = "core_top"          # top printed unindented
        indent = "" if path == "core_top" else "  " * depth
        cells = int(area / 1.25)
        lines.append(f"{indent}{name:<22} {comb:>10.1f} {seq:>9.1f} {macro:>9.1f} {clock:>9.1f} {buf:>9.1f} {cells:>8d}")
    comb, seq, macro, clock, buf = _cat_split("core_top", tree["core_top"]["area"], tree)
    lines.append(f"{'Total':<24} {comb:>10.1f} {seq:>9.1f} {macro:>9.1f} {clock:>9.1f} {buf:>9.1f} {int(tree['core_top']['area']/1.25):>8d}")
    return "\n".join(lines) + "\n"


def emit_rtla_timing(m: dict, cfg: dict) -> str:
    period = 1.20
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
        "Date   : 2026-08-31",
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
    critical = [
        ("core_top/u_ex/u_rob/u_sched/issue_rdy_q_reg[7]", "core_top/u_ex/gen_alu_0/u_alu/cmp_nxt_a", "reg2reg", 34, wns),
        ("core_top/u_ex/u_rob/u_sched/sel_grant_q_reg[3]", "core_top/u_ex/gen_alu_1/u_alu/cmp_nxt_b", "reg2reg", 31, wns + 0.012),
        ("core_top/u_ex/u_lsq/u_wakeup/cam_hit_q_reg[11]", "core_top/u_ex/u_lsq/u_wakeup/load_wakeup_l", "reg2reg", 29, wns + 0.021),
        ("core_top/u_ifu/u_bp/btb_hit_q_reg[5]", "core_top/u_ifu/u_dec/u_rename/dest_map_q_reg[19]", "reg2reg", 27, wns + 0.033),
        ("core_top/u_lsu/u_dtlb/pte_tag_q_reg[2]", "core_top/u_lsu/u_wb/wb_arb_grant_l", "reg2reg", 25, wns + 0.044),
        ("core_top/u_ifu/u_dec/u_scan/insn_buf_q_reg[8]", "core_top/u_ifu/u_dec/u_scan/u_deco/illegal_insn", "reg2reg", 22, wns + 0.058),
        ("core_top/u_l2/u_adapt/rsp_buf_q_reg[4]", "core_top/u_l2/u_adapt/req_issue_l", "reg2reg", 20, wns + 0.071),
    ]
    for i, (sp, ep, grp, depth, sl) in enumerate(critical, 1):
        lines.append(f"Path {i}")
        lines.append(f"  Startpoint: {sp}")
        lines.append(f"  Endpoint:   {ep}")
        lines.append(f"  Path Group: {grp}")
        lines.append(f"  Logic Depth: {depth}")
        lines.append(f"  Slack: {sl:.3f} ns (VIOLATED)" if sl < 0 else f"  Slack: {sl:.3f} ns")
        lines.append(f"  Arrival: {period - sl:.3f} ns   Required: {period:.3f} ns")
    return "\n".join(lines) + "\n"


def emit_rtla_qor(m: dict, cfg: dict) -> str:
    a = m["total_area"]
    return "\n".join([
        "************************************************************************",
        "Report : report_qor",
        "Design : rv_ooc_core",
        "Version: T-2022.03-SP4",
        "************************************************************************",
        "Metric                                  Value",
        "---",
        f"Cell Area (um^2)                  {a:>14.1f}",
        f"Sequential Area (um^2)            {a * 0.26:>14.1f}",
        f"Macro Area (um^2)                 {a * 0.16:>14.1f}",
        f"Buffer/Inverter Area (um^2)       {a * 0.075:>14.1f}",
        f"Cell Count                        {int(a / 1.25):>14d}",
        f"Critical Path Logic Levels        {34 if cfg['name'] == 'rob192' else 31:>14d}",
        f"WNS (ns)                          {m['wns']:>14.3f}",
        f"TNS (ns)                          {m['wns'] * -140 if m['wns'] < 0 else 0.0:>14.2f}",
        f"Estimated Fmax (MHz)              {m['fmax_mhz']:>14.1f}",
    ]) + "\n"


def emit_primepower(m: dict, cfg: dict) -> str:
    """PrimePower-style vectorless hierarchical report. NOTE: dot separators
    and bracketed generate indices — deliberately different spelling from
    RTLA so canonicalization is exercised end to end."""
    total = m["total_mw"]
    tree = build_tree(m)
    leak_base = 0.38 if cfg["vt_mix"] == "lvt_heavy" else 0.18

    # per-leaf raw power ~ area share x density weight, normalized to total
    leaf_paths = [p for p, _ in _walk(tree) if not tree[p]["children"]]
    raw = {}
    for p in leaf_paths:
        leaf = p.rsplit("/", 1)[-1]
        if "gen_alu" in p:
            leaf = "u_alu"
        w = _PW_W.get(leaf, 1.0)
        raw[p] = tree[p]["area"] * w
    scale = total / sum(raw.values())

    def power_of(path: str) -> float:
        if not tree[path]["children"]:
            return raw[path] * scale
        return sum(power_of(c) for c in tree[path]["children"])

    def split_ils(path: str, p_total: float) -> tuple[float, float, float]:
        leaf = path.rsplit("/", 1)[-1]
        if leaf in ("u_l1i", "u_l1d", "u_l2mem"):
            ls = leak_base + 0.12          # macros leak more
        elif leaf in ("u_rob", "u_lsq", "u_bp"):
            ls = leak_base * 0.8           # dense CAM/RAM, well-inserted VTs
        else:
            ls = leak_base
        leak = p_total * ls
        rest = p_total - leak
        return rest * 0.53, rest * 0.47, leak

    lines = [
        "************************************************************************",
        "Report : report_power -analysis_mode vectorless -hierarchy",
        "Design : rv_ooc_core",
        "Version: P-2019.06-SP1",
        "Supply : 0.80 V",
        "Default toggle rate: 0.15",
        f"Clock gating efficiency: {78.0 if cfg['gated'] else 12.0:.1f} %",
        "************************************************************************",
        "Power by category (mW)",
        "---",
        f"Combinational  {total * 0.29:>10.3f}",
        f"Register       {total * 0.18:>10.3f}",
        f"Clock          {m['clock_mw']:>10.3f}",
        f"Memory         {total * 0.16:>10.3f}",
        "",
        "Hierarchical power (mW)",
        "---",
        "Instance                          Internal  Switching   Leakage     Total",
    ]
    for path, depth in _walk(tree):
        p_tot = power_of(path)
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


def emit_specint(m: dict, cfg: dict) -> str:
    rows = bench_rows(m, cfg)
    lines = [
        "************************************************************************",
        "SPECint2006 result summary (instruction-accurate core model)",
        "Method : performance-model (sparta-based, 250M inst SimPoint)",
        "Version: v0.9.2",
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
    for (name, rob, lsq, issue, l1d, l1i, l2, btac, gated, vt) in CONFIGS:
        cfg = {"name": name, "rob": rob, "lsq": lsq, "issue": issue, "l1d_kb": l1d,
               "l1i_kb": l1i, "l2_kb": l2, "btac": btac, "gated": gated, "vt_mix": vt}
        m = model_config(cfg)
        d = out_dir / name
        d.mkdir(exist_ok=True)
        files = {
            "rtla_area.rpt": emit_rtla_area(m, cfg),
            "rtla_timing.rpt": emit_rtla_timing(m, cfg),
            "rtla_qor.rpt": emit_rtla_qor(m, cfg),
            "primepower.rpt": emit_primepower(m, cfg),
            "specint.rpt": emit_specint(m, cfg),
        }
        for fn, text in files.items():
            p = d / fn
            p.write_text(text)
            written.append(p)
    manifest = []
    for i, (name, rob, lsq, issue, l1d, l1i, l2, btac, gated, vt) in enumerate(CONFIGS):
        manifest.append({
            "label": name,
            "params": {"rob_entries": rob, "lsq_entries": lsq, "issue_width": issue,
                       "l1d_kb": l1d, "l1i_kb": l1i, "l2_kb": l2, "btac_entries": btac,
                       "clock_gating": gated, "vt_mix": vt},
            "corner": "tt_0p80v_25c",
            "stage": "rtla_predict",
            "order": i,
        })
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    written.append(out_dir / "manifest.json")
    return written


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sample_runs")
    for p in generate(out):
        print(f"wrote {p}")
