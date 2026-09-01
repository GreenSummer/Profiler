export interface RunSummary {
  run_id: number;
  label: string;
  stage: string;
  started_at: string;
  version?: string;
  model?: string;
  change_note?: string;
  config: Record<string, number | boolean | string>;
  corner: string;
  fom: Record<string, number | string>;
  timing: { wns_ns: number | null; tns_ns: number | null; nve: number | null };
  open_findings: number;
}

export interface Finding {
  id: number;
  run_id: number;
  run_label?: string;
  rule_id: string;
  severity: "critical" | "high" | "medium" | "low" | "info";
  category: string;
  scope_path: string | null;
  title: string;
  evidence: Record<string, unknown>;
  status: "open" | "acknowledged" | "fixed" | "wont_fix";
  ai_explanation: string | null;
  ai_proposal: string | null;
}

export interface Scorecard {
  run: { id: number; label: string; stage: string };
  fom: Record<string, number | string>;
  fom_delta_vs_baseline: Record<string, { current: number; baseline: number; abs: number; pct: number | null }>;
  budgets: Record<string, { budget?: number | null; target?: number | null; current?: number | null }>;
  domains: {
    timing: Record<string, number | null>;
    area: Record<string, number | null>;
    power: Record<string, number | null>;
    performance: Record<string, number | null>;
  };
  findings: Finding[];
}

export interface Comparison {
  runs: { run_id: number; label: string; config: Record<string, unknown>; fom: Record<string, number> }[];
  comparisons: {
    base_label: string;
    label: string;
    config_diff: Record<string, { base: unknown; current: unknown }>;
    fom_delta: Record<string, { current: number; baseline: number; abs: number; pct: number | null }>;
    decomposition: { ipc_pct: number; freq_pct: number; cross_pct: number; net_pct: number; verdict: string };
    area_waterfall: { module: string; delta: number }[];
    power_waterfall: { module: string; delta: number }[];
  }[];
}

export interface DesignSpacePoint {
  run_id: number;
  label: string;
  x: number;
  y: number;
  pareto: boolean;
  config: Record<string, unknown>;
  fom: Record<string, number>;
}

export interface HierarchyRow {
  scope_path: string;
  parent: string;
  depth: number;
  share: number;
  delta_vs_baseline_pct: number | null;
}

export interface AreaRowX extends HierarchyRow {
  total_area: number;
  comb: number;
  seq: number;
  macro: number;
  clock: number;
  buf_inv: number;
  inst_count: number;
  seq_ratio: number;
}

export interface PowerRowX extends HierarchyRow {
  internal: number;
  switching: number;
  leakage: number;
  total: number;
  leak_share: number;
  power_density_mw_um2: number | null;
}

export interface TimingExplorerX {
  run_id: number;
  wns_ns: number | null;
  tns_ns: number | null;
  nve: number | null;
  fmax_mhz: number | null;
  groups: { name: string; wns_ns: number; tns_ns: number; nve: number; paths: number }[];
  histogram: { lo: number; hi: number; count: number }[];
  paths: { path_id: number; startpoint: string; endpoint: string; group: string; slack_ns: number; logic_depth: number; module: string }[];
  leaderboard: { module: string; top_paths: number; share: number }[];
}

export interface PerfExplorerX {
  run_id: number;
  baseline_id: number | null;
  geomean_ratio_1ghz: number | null;
  geomean_delta_pct: number | null;
  rows: { benchmark: string; ipc: number; ratio_1ghz: number; l1d_mpki: number | null; l2_mpki: number | null; br_mispred_pct: number | null; ipc_delta_pct: number | null }[];
}

export interface HotspotRow {
  module: string;
  area_um2: number;
  area_share: number;
  power_mw: number;
  power_share: number;
  power_density: number;
  criticality: number;
  area_delta_pct: number | null;
  power_delta_pct: number | null;
}

export interface ChatResult {
  content: string;
  citations: { run_id: number; run_label: string; source: string }[];
  tool_trace: { tool: string; args: unknown }[];
  offline: boolean;
  view_proposal: { view: string; run_id?: number; run_ids?: number[] } | null;
}

// ---- v2: version-centric analysis ----

export interface VersionSeriesPoint {
  version: string;
  run_id: number;
  label: string;
  date: string;
  sha: string;
  change_note: string;
  stage: string;
  metrics: Record<string, number | null>;
}

export interface VersionSeries {
  project_id: number | null;
  series: VersionSeriesPoint[];
}

export interface ChangePointEvent {
  id: number;
  from_run_id: number;
  to_run_id: number;
  from_version: string;
  to_version: string;
  metric_key: string;
  scope_path: string | null;
  /** fraction for most metrics (0.08 = +8%); absolute delta for wns_ns and clock_gating_eff */
  delta_pct: number;
  /** robust z (magnitude) of the change */
  magnitude: number;
  method: string;
  severity: string;
  note: string;
}

export interface CorrelationsData {
  pairs: { perf: string; ppa: string; r: number; n: number }[];
  modules: { module: string; metric: string; r: number; n: number }[];
}

export interface SearchResults {
  query: string;
  modules: { scope_path: string; run_id: number }[];
  signals: {
    startpoint: string;
    endpoint: string;
    module: string;
    history: { run_id: number; version: string; slack_ns: number; path_id: number }[];
  }[];
  text: { run_id: number; version: string; kind: string; file: string; line: number; text: string }[];
}

export interface TraceTargetInfo {
  kind: string;
  scope_path?: string;
  value?: number;
  path_id?: number;
  startpoint?: string;
  endpoint?: string;
  slack_ns?: number;
  benchmark?: string;
  ipc?: number;
  line?: number;
}

export interface TraceResult {
  found: boolean;
  run_id: number;
  kind: string;
  target?: TraceTargetInfo;
  report?: { kind: string; file: string; sha256: string; parser_version: string; parse_status: string };
  src_line?: number;
  lines?: { no: number; text: string; hit: boolean }[];
  error?: string;
}

// ---- v3: release overview board + drill-down/compare ----

export interface OverviewBoardRow {
  max_logic_levels: number | null;
  gated_pct: number | null;
  core_area_um2: number | null;
  die_area_um2: number | null;
  comb_share: number | null;
  util_proxy: number | null;
  congestion_overflow: number | null;
}

export interface OverviewData {
  project_id: number;
  versions: string[];
  models: string[];                       // gem5 | slice | zebu | fogs
  benchmarks_names: string[];
  area_budget_mm2: number;
  target_geomean: number;
  target_eff: number;
  geomean: Record<string, (number | null)[]>;   // model (incl. synth) -> per version
  perf_per_area: (number | null)[];             // synth score/mm2
  benchmarks: Record<string, Record<string, number[]>>;  // benchmark -> model -> ratio
  ipc: Record<string, Record<string, number[]>>;         // benchmark -> model -> ipc
  area_breakdown: { categories: string[]; values: Record<string, number[]> };
  timing: { wns: (number | null)[]; tns: (number | null)[]; nve: number[] };
  board: OverviewBoardRow[];
}

export interface VersionDrill {
  version: string;
  found: boolean;
  run_id?: number;
  sha?: string;
  date?: string;
  change_note?: string;
  events?: ChangePointEvent[];
  modules?: { scope_path: string; area_um2: number; power_mw: number | null; area_delta_pct: number | null; power_delta_pct: number | null }[];
  signals?: { path_id: number; startpoint: string; endpoint: string; slack_ns: number; logic_depth: number; module: string }[];
}

export interface VersionCompare {
  versions: string[];
  run_ids: number[];
  modules: { scope_path: string; area_mm2: (number | null)[]; power_mw: (number | null)[]; area_delta_pct: (number | null)[]; power_delta_pct: (number | null)[] }[];
  benchmarks: { benchmark: string; ipc: (number | null)[]; ipc_delta_pct: (number | null)[] }[];
  signals: { startpoint: string; endpoint: string; module: string; path_ids: number[]; slacks: number[]; worst: number }[];
}
