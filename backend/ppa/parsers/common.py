"""Shared parsing helpers."""
from __future__ import annotations

import re

_NUM = re.compile(r"^-?[\d,]+(\.\d+)?$")


def to_float(token: str) -> float | None:
    """'12,345.6' -> 12345.6 ; '1.2e-3' -> 0.0012 ; else None."""
    token = token.strip()
    if not token:
        return None
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def is_number(token: str) -> bool:
    return bool(_NUM.match(token.strip()))


def split_row(line: str) -> list[str]:
    return line.split()


def parse_kv(line: str, sep: str = ":") -> tuple[str, str] | None:
    if sep in line:
        k, v = line.split(sep, 1)
        return k.strip(), v.strip()
    return None
