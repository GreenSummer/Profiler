"""PrimePower vectorless hierarchical power report parser.

CAVEAT (plan risk R2): built against synthetic PrimePower-style reports;
real report drop-in may need column tweaks here only.

PrimePower emits hierarchy with '.' separators and generate blocks as
`u_ex.gen_alu[0].u_alu` - canonicalize_path() maps these onto the RTLA
spelling so cross-domain joins (plan thesis 2) work.
"""
from __future__ import annotations

from .base import PowerReport, PowerReportRow
from .common import to_float
from .rtla import ParseError

VERSION = "pp-0.1"


def parse_primepower(text: str) -> PowerReport:
    rep = PowerReport()
    in_table = False
    in_categories = False
    for line in text.splitlines():
        s = line.rstrip()
        if s.startswith("Design"):
            rep.design = s.split(":", 1)[1].strip()
            continue
        if s.startswith("Tool") or s.startswith("Version"):
            rep.tool_version = s.split(":", 1)[1].strip()
            continue
        if s.startswith("Supply"):
            v = to_float(s.split(":", 1)[1].strip().rstrip("Vv").strip())
            rep.supply_v = v or 0.0
            continue
        if s.startswith("Default toggle rate"):
            t = to_float(s.split(":", 1)[1].strip())
            rep.toggle_rate = t
            continue
        if s.startswith("Clock gating efficiency"):
            t = to_float(s.split(":", 1)[1].strip().rstrip("%").strip())
            rep.clock_gating_efficiency = t
            continue
        if s.startswith("Power by category"):
            in_categories = True
            continue
        if in_categories:
            toks = s.strip().split()
            if toks and to_float(toks[-1]) is not None and len(toks) >= 2:
                name = " ".join(toks[:-1]).lower()
                rep.categories[name] = float(to_float(toks[-1]))  # type: ignore[arg-type]
                continue
            if not s.strip():
                in_categories = False
                continue
        if s.startswith("---"):
            in_table = True
            continue
        if not in_table or not s.strip():
            continue
        if s.startswith("=") or s.startswith("*"):
            continue
        toks = s.split()
        # <hierarchy> internal switching leakage total pct
        if len(toks) >= 5 and all(to_float(t) is not None for t in toks[-4:]):
            name = toks[0]
            indent = len(s) - len(s.lstrip())
            depth = indent // 2
            internal, switching, leakage, total = [float(to_float(t)) for t in toks[-4:]]  # type: ignore[arg-type]
            rep.rows.append(PowerReportRow(
                tool_path=name, depth=depth,
                internal=internal, switching=switching,
                leakage=leakage, total=total,
            ))
        elif toks and toks[0].lower() == "total" and len(toks) >= 5:
            internal, switching, leakage, total = [float(to_float(t)) for t in toks[-4:]]  # type: ignore[arg-type]
            rep.rows.append(PowerReportRow(
                tool_path="__total__", depth=0,
                internal=internal, switching=switching,
                leakage=leakage, total=total,
            ))
        else:
            rep.warnings.append(f"unparsed line: {s.strip()[:80]}")
    if not rep.rows:
        raise ParseError("primepower: no hierarchy rows found")
    return rep
