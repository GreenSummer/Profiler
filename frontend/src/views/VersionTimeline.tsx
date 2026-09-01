import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import { Card, Empty, SevBadge, Table, fmt, shortModule } from "../components/ui";
import { EChart, PALETTE } from "../components/EChart";
import {
  EventTraceBtn, METRIC_LABELS, MethodBadge, eventDeltaClass, fmtEventDelta,
} from "../components/changeEvents";

const METRICS = [
  { key: "specint_score", label: "SPECint score", color: PALETTE.good, digits: 2 },
  { key: "area_mm2", label: "Area mm²", color: PALETTE.neutral, digits: 3 },
  { key: "total_power_mw", label: "Power mW", color: PALETTE.accent, digits: 1 },
  { key: "wns_ns", label: "WNS ns", color: PALETTE.bad, digits: 3 },
];

export function VersionTimeline() {
  const { data, isLoading } = useQuery({ queryKey: ["versions"], queryFn: api.versions });
  const { data: events } = useQuery({ queryKey: ["change-points"], queryFn: api.changePoints });
  const { setRun, setVersionPair } = useApp();
  const [active, setActive] = useState<string[]>(METRICS.map((m) => m.key));
  const [normalized, setNormalized] = useState(true);
  const [pairFrom, setPairFrom] = useState("");
  const [pairTo, setPairTo] = useState("");

  if (isLoading) return <Card>loading…</Card>;
  const series = data?.series ?? [];
  const evs = events ?? [];
  if (series.length === 0) {
    return (
      <Empty msg="No version series in this database — rebuild the demo (ppa demo) or ingest a v2 manifest (one design per version)" />
    );
  }

  const baseVal = (key: string): number | null => {
    for (const v of series) {
      const x = v.metrics[key];
      if (x != null) return x;
    }
    return null;
  };

  const yVal = (x: number | null, key: string): number | null => {
    if (x == null) return null;
    if (!normalized) return x;
    const b = baseVal(key);
    return b ? +((x / b) * 100).toFixed(2) : x;
  };

  // versions that carry at least one change event -> vertical markers
  const eventVersions = [...new Set(
    evs.map((e) => series.findIndex((s) => s.version === e.to_version)),
  )].filter((i) => i >= 0).sort((a, b) => a - b);

  const firstActive = METRICS.find((m) => active.includes(m.key))?.key;

  const chartSeries = METRICS.filter((m) => active.includes(m.key)).map((m) => {
    const data = series.map((v) => yVal(v.metrics[m.key], m.key));
    const evPoints = evs
      .filter((e) => e.metric_key === m.key)
      .map((e) => {
        const idx = series.findIndex((s) => s.version === e.to_version);
        return idx >= 0 && data[idx] != null ? { coord: [idx, data[idx]] } : null;
      })
      .filter((p): p is { coord: [number, number] } => p !== null);
    return {
      name: m.label,
      type: "line" as const,
      symbolSize: 7,
      data,
      itemStyle: { color: m.color },
      lineStyle: { color: m.color, width: 2 },
      emphasis: { focus: "series" as const },
      markPoint: evPoints.length ? {
        symbol: "circle",
        symbolSize: 15,
        itemStyle: { color: "rgba(15,23,42,0.3)", borderColor: "#f59e0b", borderWidth: 2 },
        label: { show: false },
        data: evPoints,
      } : undefined,
      markLine: m.key === firstActive && eventVersions.length ? {
        silent: true,
        symbol: "none",
        lineStyle: { color: "#475569", type: "dashed" as const, width: 1, opacity: 0.7 },
        label: { show: true, position: "end" as const, color: "#64748b", fontSize: 9,
          formatter: (p: { name?: string }) => p.name ?? "" },
        data: eventVersions.map((idx) => ({ xAxis: idx, name: series[idx].version })),
      } : undefined,
    };
  });

  const chartOption = {
    tooltip: {
      trigger: "axis" as const,
      formatter: (params: unknown) => {
        const arr = (Array.isArray(params) ? params : [params]) as { dataIndex: number }[];
        const v = series[arr[0]?.dataIndex];
        if (!v) return "";
        const rows = METRICS.filter((m) => active.includes(m.key)).map((m) => {
          const val = v.metrics[m.key];
          if (val == null) return "";
          return `<div><span style="color:${m.color}">●</span> ${m.label}: <b>${fmt(val, m.digits ?? 3)}</b></div>`;
        }).join("");
        const n = evs.filter((e) => e.to_version === v.version).length;
        return (
          `<b>${v.version}</b> <span style="color:#64748b">${v.date} · ${v.sha}</span>` +
          (v.change_note ? `<div style="color:#c4b5fd;margin:2px 0">✎ ${v.change_note}</div>` : "") +
          rows +
          (n ? `<div style="color:#f59e0b;margin-top:2px">⚡ ${n} change event${n > 1 ? "s" : ""} at this version</div>` : "")
        );
      },
    },
    grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
    xAxis: {
      type: "category" as const,
      data: series.map((v) => v.version),
      axisLabel: { color: "#94a3b8", fontSize: 10 },
      boundaryGap: true,
    },
    yAxis: {
      type: "value" as const,
      name: normalized ? "index (first version = 100)" : "value",
      nameTextStyle: { color: "#94a3b8" },
      axisLabel: { color: "#94a3b8" },
      splitLine: { lineStyle: { color: "#1e293b" } },
      scale: true,
    },
    series: chartSeries,
  };

  // version-pair compare selector state (defaults: full span)
  const from = pairFrom || series[0].version;
  const to = pairTo || series[series.length - 1].version;
  const goCompare = () => {
    const fr = series.find((s) => s.version === from);
    const tr = series.find((s) => s.version === to);
    if (fr && tr && fr.version !== tr.version) setVersionPair(fr.run_id, tr.run_id);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Version Timeline</h2>
        <p className="text-xs text-slate-500">
          {series.length} versions · {series[0].version} → {series[series.length - 1].version} ·
          {" "}{evs.length} change events · detection: median + k·MAD (|z| ≥ 4) on version-to-version deltas
        </p>
      </div>

      <Card
        title="PPA across RTL versions — the accumulation story"
        right={
          <div className="flex items-center gap-2">
            {METRICS.map((m) => (
              <button
                key={m.key}
                onClick={() => setActive((cur) =>
                  cur.includes(m.key) ? cur.filter((k) => k !== m.key) : [...cur, m.key])}
                className={`rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
                  active.includes(m.key) ? "border-current bg-slate-800/60" : "border-slate-700 text-slate-600"
                }`}
                style={active.includes(m.key) ? { color: m.color } : undefined}
              >
                {m.label}
              </button>
            ))}
            <button
              onClick={() => setNormalized(!normalized)}
              className="rounded-full border border-slate-700 bg-slate-800/60 px-2 py-0.5 text-[11px] text-slate-300 hover:border-sky-400 hover:text-sky-300"
              title="normalize every metric to 100 at the first version"
            >
              {normalized ? "normalized" : "absolute"}
            </button>
          </div>
        }
      >
        <EChart
          option={chartOption}
          height={340}
          onEvent={{
            type: "click",
            handler: (p: unknown) => {
              const params = p as { componentType: string; dataIndex: number };
              if (params.componentType === "series") {
                const v = series[params.dataIndex];
                if (v) setRun(v.run_id);
              }
            },
          }}
        />
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span>compare versions:</span>
          <select value={from} onChange={(e) => setPairFrom(e.target.value)}
            className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 text-slate-200">
            {series.map((v) => <option key={v.version} value={v.version}>{v.version}</option>)}
          </select>
          <span>→</span>
          <select value={to} onChange={(e) => setPairTo(e.target.value)}
            className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 text-slate-200">
            {series.map((v) => <option key={v.version} value={v.version}>{v.version}</option>)}
          </select>
          <button onClick={goCompare} disabled={from === to}
            className="rounded bg-violet-600 px-2.5 py-0.5 text-xs font-medium text-white hover:bg-violet-500 disabled:opacity-40">
            Compare pair →
          </button>
          <span className="text-[10px] text-slate-600">· dashed verticals = detected change points · click a point to select that run</span>
        </div>
      </Card>

      <Card title={`Change events (${evs.length}) — what the detector found, with module attribution`}>
        <Table head={["Transition", "Metric", "Δ", "z", "Method", "Severity", "Attribution", "Change note", ""]}>
          {evs.map((e) => (
            <tr key={e.id} className={e.severity === "high" ? "bg-red-500/5" : ""}>
              <td className="whitespace-nowrap px-2 py-1 font-mono text-[11px] text-slate-400">
                {e.from_version} → <span className="text-slate-200">{e.to_version}</span>
              </td>
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
              <td className="max-w-[300px] truncate px-2 py-1 text-slate-400" title={e.note}>
                {e.note}
              </td>
              <td className="px-2 py-1">
                <div className="flex items-center justify-end gap-1">
                  <EventTraceBtn e={e} />
                  <button
                    onClick={() => setVersionPair(e.from_run_id, e.to_run_id)}
                    className="rounded border border-slate-700 px-1 py-0.5 text-[10px] text-slate-400 hover:border-violet-400 hover:text-violet-300"
                    title="compare these two versions"
                  >
                    cmp
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </Table>
        <p className="mt-2 text-[10px] text-slate-600">
          Δ is relative for most metrics; WNS and clock-gating efficiency are absolute (ns / points).
          z is the robust score (median + k·MAD) — |z| ≥ 20 is high, ≥ 8 medium. Attribution = the
          module owning the biggest share of the change (area/power waterfall) or the new critical path (WNS).
        </p>
      </Card>
    </div>
  );
}
