import { SourceBtn, WorstPathSourceBtn } from "./TraceDrawer";
import type { ChangePointEvent } from "../types";

export const METRIC_LABELS: Record<string, string> = {
  specint_score: "SPECint score", specint_per_ghz: "SPECint/GHz", fmax_mhz: "Fmax MHz",
  geomean_ratio_1ghz: "IPC geomean", area_mm2: "Area mm²", total_power_mw: "Power mW",
  wns_ns: "WNS ns", tns_ns: "TNS ns", leakage_share: "Leakage share",
  clock_gating_eff: "Clock gating eff",
};

/** delta_pct is a fraction for most metrics (+8% = 0.08) but an absolute
 * delta for wns_ns (ns) and clock_gating_eff (percentage points). */
export function fmtEventDelta(metric: string, d: number): string {
  if (metric === "wns_ns" || metric === "clock_gating_eff") {
    return `${d >= 0 ? "+" : ""}${d.toFixed(metric === "wns_ns" ? 3 : 1)}`;
  }
  return `${d >= 0 ? "+" : ""}${(d * 100).toFixed(1)}%`;
}

/** metrics where an increase is good (everything else: red when up) */
const GOOD_UP = new Set([
  "specint_score", "specint_per_ghz", "fmax_mhz", "geomean_ratio_1ghz",
  "wns_ns", "clock_gating_eff",
]);

export function eventDeltaClass(metric: string, d: number): string {
  const good = GOOD_UP.has(metric) ? d > 0 : d < 0;
  return good ? "text-emerald-400" : "text-red-400";
}

const METHOD_STYLE: Record<string, string> = {
  step: "bg-sky-500/15 text-sky-300",
  spike: "bg-red-500/15 text-red-300",
  recovery: "bg-emerald-500/15 text-emerald-300",
  trend: "bg-yellow-500/15 text-yellow-300",
};

export function MethodBadge({ method }: { method: string }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${METHOD_STYLE[method] ?? "bg-slate-500/15 text-slate-300"}`}>
      {method}
    </span>
  );
}

/** ⌖-trace affordance for one change event: area/power events carry a module
 * scope; WNS events trace to the worst path of the target run. */
export function EventTraceBtn({ e }: { e: ChangePointEvent }) {
  if (e.metric_key === "area_mm2" && e.scope_path) {
    return <SourceBtn target={{ run_id: e.to_run_id, kind: "area", scope_path: e.scope_path }} />;
  }
  if (e.metric_key === "total_power_mw" && e.scope_path) {
    return <SourceBtn target={{ run_id: e.to_run_id, kind: "power", scope_path: e.scope_path }} />;
  }
  if (e.metric_key === "wns_ns") {
    return <WorstPathSourceBtn runId={e.to_run_id} />;
  }
  return <span className="text-slate-700">—</span>;
}
