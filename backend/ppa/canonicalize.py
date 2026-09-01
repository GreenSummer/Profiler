"""Hierarchy path canonicalization (plan risk R1).

RTLA, PrimePower and the RTL disagree on instance path spelling:
  separators:      'u_dec/u_rob'  vs  'u_dec.u_rob'
  generate blocks: 'u_ex/gen_alu_0_/u_alu' vs 'u_ex.gen_alu[0].u_alu'
This module maps every spelling onto one canonical form:
  'u_ex/gen_alu_0/u_alu'
Both the original (tool_path) and canonical form are stored; unmatched
paths are surfaced as data-quality findings, never silently dropped.
"""
from __future__ import annotations

import re

_GEN_IDX = re.compile(r"^(.*?)\[+(\d+)\]+$")
_DANGLING = re.compile(r"_+/")


def canonicalize_path(raw: str) -> str:
    """Normalize a tool-reported hierarchy path to canonical form."""
    p = raw.strip().strip('"')
    if not p:
        return ""
    # unifier 1: separators '.' or '\' -> '/'
    p = p.replace("\\", "/").replace(".", "/")
    # unifier 2: generate index brackets -> '_<idx>'
    out: list[str] = []
    for seg in p.split("/"):
        seg = seg.strip()
        if not seg:
            continue
        m = _GEN_IDX.match(seg)
        if m:
            base, idx = m.group(1), m.group(2)
            seg = f"{base.rstrip('_')}_{idx}"
        out.append(seg)
    p = "/".join(out)
    # unifier 3: dangling underscores left by 'gen_x_0_' style names
    p = _DANGLING.sub("/", p)
    return p.strip("/")


def depth_of(path: str) -> int:
    return 0 if not path else path.count("/") + 1


def parent_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def common_ancestor(a: str, b: str) -> str:
    aa, bb = a.split("/"), b.split("/")
    out: list[str] = []
    for x, y in zip(aa, bb):
        if x != y:
            break
        out.append(x)
    return "/".join(out)


def owner_module(startpoint: str, endpoint: str, top: str = "core_top") -> str:
    """Attribute a timing path to the module that owns it: the deepest common
    ancestor of start/endpoint, or the second-level module when the path
    crosses top level."""
    ca = common_ancestor(startpoint, endpoint)
    segs = [s for s in ca.split("/") if s]
    if len(segs) >= 2:
        return "/".join(segs[:2])
    # path crosses major blocks: attribute to startpoint's level-2 module
    ssegs = [s for s in startpoint.split("/") if s]
    if len(ssegs) >= 2:
        return "/".join(ssegs[:2])
    return top


def match_report(known: set[str], reported: set[str]) -> tuple[set[str], set[str]]:
    """Return (matched, unmatched) canonical paths of `reported` vs `known`."""
    return reported & known, reported - known
