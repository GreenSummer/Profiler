export interface RunSummary {
  run_id: number;
  label: string;
  stage: string;
  started_at: string;
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
