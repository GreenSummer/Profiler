"""Parser result types. Parsers return these dataclasses; ingest persists them."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AreaReportRow:
    tool_path: str
    depth: int
    comb_area: float
    seq_area: float
    macro_area: float
    clock_area: float
    buf_inv_area: float
    inst_count: int


@dataclass
class AreaReport:
    design: str = ""
    tool_version: str = ""
    lib: str = ""
    rows: list[AreaReportRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> AreaReportRow | None:
        return self.rows[-1] if self.rows else None


@dataclass
class PathGroup:
    name: str
    wns_ns: float
    tns_ns: float
    nve: int
    fmax_mhz: float | None


@dataclass
class TimingPathRow:
    path_id: int
    startpoint: str
    endpoint: str
    path_group: str
    logic_depth: int
    slack_ns: float
    arrival_ns: float
    required_ns: float
    is_hold: bool = False


@dataclass
class TimingReport:
    design: str = ""
    tool_version: str = ""
    clocks: dict[str, float] = field(default_factory=dict)   # clock -> period ns
    groups: list[PathGroup] = field(default_factory=list)
    histogram: list[tuple[str, int]] = field(default_factory=list)  # (bucket label, count)
    paths: list[TimingPathRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def wns_total(self) -> float:
        return min((g.wns_ns for g in self.groups), default=0.0)

    @property
    def tns_total(self) -> float:
        return sum(g.tns_ns for g in self.groups)

    @property
    def nve_total(self) -> int:
        return sum(g.nve for g in self.groups)


@dataclass
class QorReport:
    design: str = ""
    tool_version: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PowerReportRow:
    tool_path: str
    depth: int
    internal: float
    switching: float
    leakage: float
    total: float


@dataclass
class PowerReport:
    design: str = ""
    tool_version: str = ""
    supply_v: float = 0.0
    toggle_rate: float | None = None
    clock_gating_efficiency: float | None = None
    categories: dict[str, float] = field(default_factory=dict)  # comb/reg/clock/macro -> mW
    rows: list[PowerReportRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> PowerReportRow | None:
        return self.rows[-1] if self.rows else None


@dataclass
class PerfReportRow:
    benchmark: str
    ref_ipc: float
    cycles_m: float
    inst_m: float
    ipc: float
    ratio_1ghz: float
    l1d_mpki: float | None = None
    l2_mpki: float | None = None
    br_mispred_pct: float | None = None


@dataclass
class PerfReport:
    method: str = ""
    tool_version: str = ""
    rows: list[PerfReportRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def geomean_ratio(self) -> float:
        if not self.rows:
            return 0.0
        prod = 1.0
        for r in self.rows:
            prod *= max(r.ratio_1ghz, 1e-9)
        return prod ** (1.0 / len(self.rows))
