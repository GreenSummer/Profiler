"""RTLA (RTL-Architect) report parsers: report_area -hierarchy,
report_timing summary, report_qor. Versioned; formats modeled on
Synopsys-style text reports.

CAVEAT (plan risk R2): these were built against synthetic reports because
real RTLA output was not available. Before first use with real reports,
run `ppa check-format <file>` and adjust token positions here only.
"""
from __future__ import annotations

import re

from .base import AreaReport, AreaReportRow, PathGroup, QorReport, TimingPathRow, TimingReport
from .common import to_float

VERSION = "rtla-0.1"


class ParseError(Exception):
    pass


# ------------------------------------------------------------------ area

def parse_rtla_area(text: str) -> AreaReport:
    rep = AreaReport()
    in_table = False
    for line in text.splitlines():
        s = line.rstrip()
        if s.startswith("Design"):
            rep.design = s.split(":", 1)[1].strip()
            continue
        if s.startswith("Tool") or s.startswith("Version"):
            rep.tool_version = s.split(":", 1)[1].strip()
            continue
        if s.startswith("Library"):
            rep.lib = s.split(":", 1)[1].strip()
            continue
        if s.startswith("---"):
            in_table = True
            continue
        if not in_table or not s.strip():
            continue
        if s.startswith("=") or s.startswith("*"):
            continue
        toks = s.split()
        # hierarchy row: <name> [attr...] comb seq macro clock buf/inv cells
        if len(toks) >= 7 and all(to_float(t) is not None for t in toks[-6:]):
            name = toks[0]
            indent = len(s) - len(s.lstrip())
            depth = indent // 2
            vals = [float(to_float(t)) for t in toks[-6:]]  # type: ignore[arg-type]
            comb, seq, macro, clock, buf_inv, cells = vals
            rep.rows.append(AreaReportRow(
                tool_path=name, depth=depth,
                comb_area=comb, seq_area=seq, macro_area=macro,
                clock_area=clock, buf_inv_area=buf_inv, inst_count=int(cells),
            ))
        elif toks and toks[0].lower() == "total" and len(toks) >= 7:
            vals = [float(to_float(t)) for t in toks[-6:]]  # type: ignore[arg-type]
            comb, seq, macro, clock, buf_inv, cells = vals
            rep.rows.append(AreaReportRow(
                tool_path="__total__", depth=0,
                comb_area=comb, seq_area=seq, macro_area=macro,
                clock_area=clock, buf_inv_area=buf_inv, inst_count=int(cells),
            ))
        else:
            rep.warnings.append(f"unparsed line: {s.strip()[:80]}")
    if not rep.rows:
        raise ParseError("rtla_area: no hierarchy rows found")
    return rep


# ------------------------------------------------------------------ timing

_CLOCK = re.compile(r"Clock\s+(\S+)\s*.*period\s+([\d.]+)\s*ns", re.IGNORECASE)
_GROUP = re.compile(r"^(\S+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(\d+)\s+(-?[\d.]+)\s*$")
_BUCKET = re.compile(r"^\[([^]]+)\]\s+(\d+)$")


def parse_rtla_timing(text: str) -> TimingReport:
    rep = TimingReport()
    section = "header"
    cur_path: dict[str, str] = {}
    for raw in text.splitlines():
        s = raw.rstrip()
        m = _CLOCK.search(s)
        if m:
            rep.clocks[m.group(1)] = float(m.group(2))
            continue
        if s.startswith("Design"):
            rep.design = s.split(":", 1)[1].strip()
            continue
        if s.startswith("Tool") or s.startswith("Version"):
            rep.tool_version = s.split(":", 1)[1].strip()
            continue
        if "Path Group" in s and "WNS" in s:
            section = "groups"
            continue
        if "slack histogram" in s.lower():
            section = "hist"
            continue
        if "Top violating paths" in s or "Top paths" in s:
            section = "paths"
            continue
        if s.startswith("Path ") and section == "paths":
            if cur_path:
                rep.paths.append(_mk_path(cur_path))
            cur_path = {"path_id": s.split()[1]}
            continue
        if section == "groups":
            m = _GROUP.match(s.strip())
            if m:
                name, wns, tns, nve, fmax = m.groups()
                if name.lower() != "total":
                    rep.groups.append(PathGroup(name, float(wns), float(tns), int(nve), float(fmax)))
            continue
        if section == "hist":
            m = _BUCKET.match(s.strip())
            if m:
                rep.histogram.append((m.group(1), int(m.group(2))))
            continue
        if section == "paths" and ":" in s and cur_path:
            k, v = s.split(":", 1)
            k = k.strip().lower()
            if k in ("startpoint", "endpoint", "path group", "logic depth", "slack", "arrival", "required"):
                cur_path[k.replace(" ", "_")] = v.strip()
                # continuation line for startpoint/endpoint (leading spaces, no colon)
            elif raw.startswith(" ") and raw.strip() and not raw.strip().startswith("("):
                pass
    if cur_path and section == "paths":
        rep.paths.append(_mk_path(cur_path))
    if not rep.groups:
        raise ParseError("rtla_timing: no path-group summary found")
    return rep


def _mk_path(d: dict[str, str]) -> TimingPathRow:
    slack = float(to_float(d.get("slack", "0")) or 0.0)
    return TimingPathRow(
        path_id=int(to_float(d.get("path_id", "0")) or 0),
        startpoint=d.get("startpoint", ""),
        endpoint=d.get("endpoint", ""),
        path_group=d.get("path_group", "reg2reg"),
        logic_depth=int(to_float(d.get("logic_depth", "0")) or 0),
        slack_ns=slack,
        arrival_ns=float(to_float(d.get("arrival", "0")) or 0.0),
        required_ns=float(to_float(d.get("required", "0")) or 0.0),
        is_hold="hold" in d.get("path_group", "").lower() or "hold" in d.get("slack", "").lower(),
    )


# ------------------------------------------------------------------ qor

def parse_rtla_qor(text: str) -> QorReport:
    rep = QorReport()
    started = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Design"):
            rep.design = s.split(":", 1)[1].strip()
            continue
        if s.startswith("Tool") or s.startswith("Version"):
            rep.tool_version = s.split(":", 1)[1].strip()
            continue
        if s.startswith("Metric"):
            started = True
            continue
        if not started or not s or s.startswith("-") or s.startswith("*"):
            continue
        parts = s.split()
        if len(parts) >= 2:
            name = " ".join(parts[:-1])
            val = to_float(parts[-1])
            if val is not None:
                rep.metrics[name] = val
            else:
                rep.warnings.append(f"unparsed qor line: {s[:80]}")
    if not rep.metrics:
        raise ParseError("rtla_qor: no metric rows found")
    return rep
