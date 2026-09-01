import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useApp } from "../store";
import { Card, Delta, Empty, SevBadge, Table, fmt, shortModule } from "../components/ui";
import { EChart, PALETTE } from "../components/EChart";
import {
  EventTraceBtn, METRIC_LABELS, MethodBadge, eventDeltaClass, fmtEventDelta,
} from "../components/changeEvents";
import type { ChangePointEvent, VersionSeriesPoint } from "../types";

function Waterfall({ items, title, unit, traceKind, traceRunId }: {
  items: { module: string; delta: number }[]; title: string; unit: string;
  traceKind?: "area" | "power"; traceRunId?: number;
}) {
  const openTrace = useApp((s) => s.openTrace);
  const option = {
    title: { text: title, textStyle: { color: "#94a3b8", fontSize: 12 }, left: 0 },
    tooltip: { trigger: "axis" as const },
    grid: { left: 8, right: 8, top: 28, bottom: 8, containLabel: true },
    xAxis: { type: "category" as const, data: items.map((i) => shortModule(i.module)), axisLabel: { color: "#94a3b8", fontSize: 10, rotate: 20 } },
    yAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
    series: [{
      type: "bar",
      data: items.map((i) => ({
        value: i.delta,
        itemStyle: { color: i.delta >= 0 ? PALETTE.bad : PALETTE.good },
      })),
      label: { show: true, position: "top" as const, color: "#94a3b8", fontSize: 9,
        formatter: (p: { value: number }) => `${p.value >= 0 ? "+" : ""}${p.value.toFixed(0)}` },
    }],
  };
  return (
    <Card title={`${title} (${unit})`}>
      <EChart
        option={option}
        height={260}
        onEvent={traceKind && traceRunId ? {
          type: "click",
          handler: (p: unknown) => {
            const params = p as { componentType: string; dataIndex: number };
            if (params.componentType === "series") {
              const it = items[params.dataIndex];
              if (it) openTrace({ run_id: traceRunId, kind: traceKind, scope_path: it.module });
            }
          },
        } : undefined}
      />
      {traceKind && traceRunId && (
        <p className="mt-1 text-[10px] text-slate-600">click a bar to trace its raw report lines ⌖</p>
      )}
    </Card>
  );
}

/** Version-transition header shown when both compared runs sit on the version
 * axis: change note of the target version + detected events in the span. */
function VersionHeader({ baseV, curV, events }: {
  baseV: VersionSeriesPoint; curV: VersionSeriesPoint; events: ChangePointEvent[];
}) {
  const adjacent = events.some((e) => e.from_version === baseV.version && e.to_version === curV.version);
  return (
    <div className="rounded-lg border border-violet-500/30 bg-violet-500/5 p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="rounded bg-violet-500/20 px-1.5 py-0.5 font-mono text-xs text-violet-300">
          {baseV.version} → {curV.version}
        </span>
        <span className="text-slate-300">✎ {curV.change_note}</span>
        <span className="ml-auto font-mono text-[10px] text-slate-500">
          {curV.sha} · {curV.date}
        </span>
      </div>
      {events.length > 0 ? (
        <div className="mt-2">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
            detected changes in this {adjacent ? "transition" : `span (${baseV.version}..${curV.version})`}
          </p>
          <Table head={["Metric", "Δ", "z", "Method", "Severity", "Attribution", ""]}>
            {events.map((e) => (
              <tr key={e.id}>
                <td className="px-2 py-1">{METRIC_LABELS[e.metric_key] ?? e.metric_key}</td>
                <td className={`px-2 py-1 font-mono ${eventDeltaClass(e.metric_key, e.delta_pct)}`}>
                  {fmtEventDelta(e.metric_key, e.delta_pct)}
                </td>
                <td className="px-2 py-1 font-mono text-slate-500">{e.magnitude.toFixed(1)}</td>
                <td className="px-2 py-1"><MethodBadge method={e.method} /></td>
                <td className="px-2 py-1"><SevBadge severity={e.severity} /></td>
                <td className="px-2 py-1 font-mono text-[10px] text-slate-400">
                  {e.scope_path ? shortModule(e.scope_path) : "—"}
                </td>
                <td className="px-2 py-1 text-right"><EventTraceBtn e={e} /></td>
              </tr>
            ))}
          </Table>
        </div>
      ) : (
        <p className="mt-2 text-xs text-slate-500">
          no statistically significant changes in this span — only ±0.5% noise
        </p>
      )}
    </div>
  );
}

export function Compare() {
  const { compareIds, runId, toggleCompare } = useApp();
  const ids = compareIds.length >= 2 ? compareIds : runId ? [runId] : [];
  const { data, isLoading } = useQuery({
    queryKey: ["compare", ids.join(",")],
    queryFn: () => api.compare(ids),
    enabled: ids.length >= 2,
  });
  const { data: versions } = useQuery({ queryKey: ["versions"], queryFn: api.versions });
  const { data: events } = useQuery({ queryKey: ["change-points"], queryFn: api.changePoints });

  if (ids.length < 2) {
    return <Empty msg="Select at least two runs in Run Explorer (±cmp) to compare" />;
  }
  if (isLoading || !data) return <Card>loading…</Card>;

  const series = versions?.series ?? [];
  const versionOf = (rid: number | undefined) => series.find((s) => s.run_id === rid);

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Compare / Delta</h2>
        <div className="flex items-center gap-1 text-xs">
          {data.runs.map((r) => (
            <span key={r.run_id} className="rounded bg-slate-800 px-2 py-0.5">
              {r.label}
              <button onClick={() => toggleCompare(r.run_id)} className="ml-1 text-slate-500 hover:text-red-400">×</button>
            </span>
          ))}
        </div>
      </div>

      {data.comparisons.map((c, i) => {
        const dec = c.decomposition;
        // backend compares runs[0] (base) against each later run
        const baseRunId = data.runs[0]?.run_id;
        const curRunId = data.runs[i + 1]?.run_id;
        const baseV = versionOf(baseRunId);
        const curV = versionOf(curRunId);
        let spanEvents: ChangePointEvent[] = [];
        if (baseV && curV) {
          const bi = series.findIndex((s) => s.version === baseV.version);
          const ci = series.findIndex((s) => s.version === curV.version);
          if (bi >= 0 && ci > bi) {
            spanEvents = (events ?? []).filter((e) => {
              const fi = series.findIndex((s) => s.version === e.from_version);
              const ti = series.findIndex((s) => s.version === e.to_version);
              return fi >= bi && ti <= ci;
            });
          } else if (bi > ci) {
            // reversed pair: events between cur..base, reported against the base→cur direction
            spanEvents = (events ?? []).filter((e) => {
              const fi = series.findIndex((s) => s.version === e.from_version);
              const ti = series.findIndex((s) => s.version === e.to_version);
              return fi >= ci && ti <= bi;
            });
          }
        }
        // backend returns roi entries as plain numbers, not delta objects
        const roiA = c.fom_delta["area_roi"] as unknown as number | undefined;
        const roiP = c.fom_delta["power_roi"] as unknown as number | undefined;
        return (
          <div key={i} className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/30 p-4">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold text-slate-200">{c.base_label} → {c.label}</h3>
              <span className={`rounded px-2 py-0.5 text-xs font-semibold ${
                dec.verdict === "win" ? "bg-emerald-500/20 text-emerald-300" :
                dec.verdict === "loss" ? "bg-red-500/20 text-red-300" : "bg-slate-600/30 text-slate-300"
              }`}>
                net {dec.net_pct >= 0 ? "+" : ""}{dec.net_pct.toFixed(2)}%
              </span>
            </div>

            {/* version-transition context (F5): change note + detected events */}
            {baseV && curV && (
              <VersionHeader baseV={baseV} curV={curV} events={spanEvents} />
            )}

            {/* what changed */}
            {Object.keys(c.config_diff).length > 0 && (
              <div className="flex flex-wrap gap-2 text-xs">
                {Object.entries(c.config_diff).map(([k, v]) => (
                  <span key={k} className="rounded bg-slate-800 px-2 py-1 font-mono">
                    {k}: <span className="text-slate-500">{String(v.base)}</span>
                    <span className="mx-1 text-slate-600">→</span>
                    <span className="text-sky-300">{String(v.current)}</span>
                  </span>
                ))}
              </div>
            )}

            {/* net score decomposition: thesis 1 */}
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <Card title="Net score decomposition (SPECint = SPECint/GHz × Fmax)">
                <EChart
                  option={{
                    tooltip: { trigger: "axis" as const },
                    grid: { left: 8, right: 8, top: 24, bottom: 8, containLabel: true },
                    xAxis: { type: "value" as const, axisLabel: { color: "#94a3b8", formatter: "{value}%" }, splitLine: { lineStyle: { color: "#1e293b" } } },
                    yAxis: { type: "category" as const, data: ["freq (physical)", "IPC (µarch)", "net"], axisLabel: { color: "#94a3b8" } },
                    series: [{
                      type: "bar",
                      data: [
                        { value: dec.freq_pct, itemStyle: { color: dec.freq_pct >= 0 ? PALETTE.good : PALETTE.bad } },
                        { value: dec.ipc_pct, itemStyle: { color: dec.ipc_pct >= 0 ? PALETTE.good : PALETTE.bad } },
                        { value: dec.net_pct, itemStyle: { color: dec.net_pct >= 0 ? PALETTE.good : PALETTE.bad } },
                      ],
                      label: { show: true, position: "right" as const, color: "#cbd5e1", fontSize: 10, formatter: (p: { value: number }) => `${p.value >= 0 ? "+" : ""}${p.value.toFixed(2)}%` },
                    }],
                  }}
                  height={200}
                />
                {dec.ipc_pct > 0 && dec.net_pct < 0 && (
                  <p className="mt-2 rounded bg-red-500/10 px-2 py-1 text-xs text-red-300">
                    IPC improved but net score regressed — the frequency loss dominates. This is the classic
                    µarch-vs-physical trade going the wrong way.
                  </p>
                )}
              </Card>

              <Card title="Figures of merit delta">
                <Table head={["Metric", "Base", "Current", "Δ%", "ROI"]}>
                  {(["specint_score", "specint_per_ghz", "fmax_mhz", "area_mm2", "total_power_mw", "epi_pj"] as const)
                    .filter((k) => c.fom_delta[k])
                    .map((k) => {
                      const v = c.fom_delta[k];
                      return (
                        <tr key={k}>
                          <td className="px-2 py-1">{k}</td>
                          <td className="px-2 py-1 font-mono text-slate-500">{fmt(v.baseline, 3)}</td>
                          <td className="px-2 py-1 font-mono">{fmt(v.current, 3)}</td>
                          <td className="px-2 py-1"><Delta pct={v.pct} invert={k === "area_mm2" || k === "total_power_mw" || k === "epi_pj"} /></td>
                          <td className="px-2 py-1 font-mono text-slate-400">
                            {k === "area_mm2" && typeof roiA === "number" ? `${roiA.toFixed(2)} score%/area%` :
                             k === "total_power_mw" && typeof roiP === "number" ? `${roiP.toFixed(2)} score%/power%` : ""}
                          </td>
                        </tr>
                      );
                    })}
                </Table>
                <p className="mt-2 text-[10px] text-slate-600">ROI &lt; 0.3 means the score gain didn't pay for its cost — usually rejected in review.</p>
              </Card>
            </div>

            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <Waterfall items={c.area_waterfall} title="Area delta by module" unit="µm²" traceKind="area" traceRunId={curRunId} />
              <Waterfall items={c.power_waterfall} title="Power delta by module" unit="mW" traceKind="power" traceRunId={curRunId} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
