"""SQLite schema (SQLModel). Mirrors plan section 3: identity/provenance,
hybrid tall+typed metrics, and the analysis layer."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- identity

class Project(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    process_node: str = "N7"
    nand2_area_um2: float = 0.0594
    target_freq_mhz: float = 1000.0
    area_budget_mm2: float | None = None
    power_budget_mw: float | None = None
    # Designer-tunable settings (regression thresholds, rule overrides, AI config)
    settings_json: dict = Field(default_factory=dict, sa_column=Column(JSON))


class Design(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    rtl_git_sha: str = "unknown"
    rtl_branch: str = "main"
    description: str = ""
    date: datetime = Field(default_factory=utcnow)


class Config(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    design_id: int = Field(foreign_key="design.id", index=True)
    name: str = Field(index=True)
    params_json: dict = Field(default_factory=dict, sa_column=Column(JSON))


class Corner(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    process: str = "tt"
    voltage: float = 0.80
    temp: float = 25.0
    lib_set: str = "n7_tt_0p80v_25c"
    rc_corner: str = "typical"


class Run(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    design_id: int = Field(foreign_key="design.id", index=True)
    config_id: int = Field(foreign_key="config.id", index=True)
    corner_id: int = Field(foreign_key="corner.id", index=True)
    label: str = ""                      # human name, e.g. "rob128"
    tool: str = ""                       # tool bundle that produced the reports
    tool_version: str = ""
    stage: str = "rtla_predict"          # rtla_predict | synth | place | cts | route
    started_at: datetime = Field(default_factory=utcnow)
    status: str = "complete"
    workdir_path: str = ""


class RawReport(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    kind: str = Field(index=True)        # rtla_area | rtla_timing | rtla_qor | primepower | specint
    file_path: str = ""
    sha256: str = ""
    bytes: int = 0
    parser_version: str = ""
    parse_status: str = "ok"             # ok | warnings | error
    parse_log: str = ""


# ---------------------------------------------------------------- metrics

class Metric(SQLModel, table=True):
    """Tall table: absorbs whatever the parsers discover that has no typed home."""
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    key: str = Field(index=True)
    value: float = 0.0
    unit: str = ""
    scope_path: str | None = Field(default=None, index=True)


class AreaRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    scope_path: str = Field(index=True)
    parent_path: str = ""
    depth: int = 0
    total_area: float = 0.0              # um^2
    comb_area: float = 0.0
    seq_area: float = 0.0
    macro_area: float = 0.0
    clock_area: float = 0.0
    buf_inv_area: float = 0.0
    inst_count: int = 0


class PowerRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    scope_path: str = Field(index=True)
    parent_path: str = ""
    depth: int = 0
    internal: float = 0.0                # mW
    switching: float = 0.0
    leakage: float = 0.0
    total: float = 0.0


class TimingPath(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    path_id: int = 0
    clock: str = "clk"
    path_group: str = Field(index=True)
    slack_ns: float = 0.0
    required_ns: float = 0.0
    arrival_ns: float = 0.0
    startpoint: str = ""
    endpoint: str = ""
    start_module: str = ""               # owning module (canonical)
    end_module: str = ""
    logic_depth: int = 0
    is_hold: bool = False


class PerfRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    benchmark: str = Field(index=True)
    ref_ipc: float = 0.0
    cycles_m: float = 0.0
    inst_m: float = 0.0
    ipc: float = 0.0
    ratio_1ghz: float = 0.0
    l1d_mpki: float | None = None
    l2_mpki: float | None = None
    br_mispred_pct: float | None = None


# ---------------------------------------------------------------- analysis

class ScopeAlias(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    tool_path: str = Field(index=True)
    canonical_path: str = Field(index=True)


class Baseline(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    run_id: int = Field(foreign_key="run.id")
    label: str = ""
    is_golden: bool = False


class Finding(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    rule_id: str = Field(index=True)
    severity: str = "medium"             # critical | high | medium | low | info
    category: str = Field(index=True)    # timing | area | power | performance | cross_domain | data_quality
    scope_path: str | None = None
    title: str = ""
    evidence_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "open"                 # open | acknowledged | fixed | wont_fix
    ai_explanation: str | None = None
    ai_proposal: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Annotation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    scope_path: str | None = None
    author: str = "anonymous"
    body: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class ChatSession(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str = ""
    context_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class ChatMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="chatsession.id", index=True)
    role: str                            # user | assistant
    content: str = ""
    tool_trace: list = Field(default_factory=list, sa_column=Column(JSON))
    citations: list = Field(default_factory=list, sa_column=Column(JSON))
    offline: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class RuleFeedback(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    finding_id: int = Field(foreign_key="finding.id", index=True)
    verdict: str = "up"                  # up | down
    comment: str = ""
    author: str = "anonymous"
    created_at: datetime = Field(default_factory=utcnow)
