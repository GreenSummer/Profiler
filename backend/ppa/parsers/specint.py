"""SPECint2006 result parser. Accepts the per-benchmark table emitted by the
runspec/parse script or a custom harness summary (ref IPC, cycles, insts).

CAVEAT (plan risk R2): synthetic format; adjust column order here only.
"""
from __future__ import annotations

from .base import PerfReport, PerfReportRow
from .common import to_float
from .rtla import ParseError

VERSION = "specint-0.1"

BENCHMARKS = [
    "400.perlbench", "401.bzip2", "403.gcc", "429.mcf", "445.gobmk",
    "456.hmmer", "458.sjeng", "462.libquantum", "464.h264ref",
    "471.omnetpp", "473.astar", "483.xalancbmk",
]


def parse_specint(text: str) -> PerfReport:
    rep = PerfReport()
    in_table = False
    for line in text.splitlines():
        s = line.rstrip()
        if s.startswith("Method"):
            rep.method = s.split(":", 1)[1].strip()
            continue
        if s.startswith("Tool") or s.startswith("Version"):
            rep.tool_version = s.split(":", 1)[1].strip()
            continue
        if s.startswith("Benchmark"):
            in_table = True
            continue
        if not in_table or not s.strip():
            continue
        if s.startswith("---") or s.startswith("="):
            continue
        toks = s.split()
        # <bench> ref_ipc cycles_M insts_M ipc ratio@1GHz l1d_mpki l2_mpki br_mispred%
        if len(toks) >= 6 and toks[0].split(".")[0].isdigit():
            bench = toks[0]
            vals = [to_float(t) for t in toks[1:9]]
            nums = [v if v is not None else 0.0 for v in vals]
            while len(nums) < 8:
                nums.append(0.0)
            row = PerfReportRow(
                benchmark=bench,
                ref_ipc=nums[0],
                cycles_m=nums[1],
                inst_m=nums[2],
                ipc=nums[3],
                ratio_1ghz=nums[4],
                l1d_mpki=nums[5] or None,
                l2_mpki=nums[6] or None,
                br_mispred_pct=nums[7] or None,
            )
            rep.rows.append(row)
        elif toks[0].lower() == "geomean":
            pass
        else:
            rep.warnings.append(f"unparsed line: {s.strip()[:80]}")
    if not rep.rows:
        raise ParseError("specint: no benchmark rows found")
    return rep
