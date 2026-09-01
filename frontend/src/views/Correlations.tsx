import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { Card, Empty, Table, fmt, shortModule } from "../components/ui";
import { EChart, PALETTE } from "../components/EChart";

const PERF_KEYS = ["specint_score", "geomean_ratio_1ghz", "fmax_mhz"];
const PPA_KEYS = ["area_mm2", "total_power_mw", "wns_ns", "leakage_share", "clock_gating_eff"];

const LABELS: Record<string, string> = {
  specint_score: "SPECint score", geomean_ratio_1ghz: "IPC geomean", fmax_mhz: "Fmax MHz",
  area_mm2: "Area mm²", total_power_mw: "Power mW", wns_ns: "WNS ns",
  leakage_share: "Leakage share", clock_gating_eff: "Clock gating eff",
  power_mw: "power", area_um2: "area",
};

/** least-squares fit y = a + b·x */
function linreg(xs: number[], ys: number[]): { a: number; b: number } {
  const n = xs.length;
  const mx = xs.reduce((s, x) => s + x, 0) / n;
  const my = ys.reduce((s, y) => s + y, 0) / n;
  const sxy = xs.reduce((s, x, i) => s + (x - mx) * (ys[i] - my), 0);
  const sxx = xs.reduce((s, x) => s + (x - mx) ** 2, 0);
  const b = sxx > 1e-18 ? sxy / sxx : 0;
  return { a: my - b * mx, b };
}

export function Correlations() {
  const { data, isLoading } = useQuery({ queryKey: ["correlations"], queryFn: api.correlations });
  const { data: versions } = useQuery({ queryKey: ["versions"], queryFn: api.versions });
  const [pair, setPair] = useState<{ perf: string; ppa: string } | null>(null);

  if (isLoading) return <Card>loading…</Card>;
  const pairs = data?.pairs ?? [];
  const modules = data?.modules ?? [];
  const series = versions?.series ?? [];
  if (pairs.length === 0) {
    return <Empty msg="Not enough versions for correlations — need at least 3 runs on the version axis" />;
  }

  // default to the strongest pair until the user picks a cell
  const strongest = [...pairs].sort((a, b) => Math.abs(b.r) - Math.abs(a.r))[0];
  const sel = pair ?? { perf: strongest.perf, ppa: strongest.ppa };

  // ---- heatmap: perf (cols) x ppa (rows)
  const cell = (perf: string, ppa: string) => pairs.find((p) => p.perf === perf && p.ppa === ppa);
  const heatData = PERF_KEYS.flatMap((perf, xi) =>
    PPA_KEYS.map((ppa, yi) => {
      const c = cell(perf, ppa);
      return c ? [xi, yi, c.r] : null;
    }),
  ).filter((d): d is [number, number, number] => d !== null);

  const heatOption = {
    tooltip: {
      formatter: (p: { value: [number, number, number] }) => {
        const perf = PERF_KEYS[p.value[0]];
        const ppa = PPA_KEYS[p.value[1]];
        const c = cell(perf, ppa);
        return c
          ? `${LABELS[perf] ?? perf} × ${LABELS[ppa] ?? ppa}<br/>r = <b>${c.r.toFixed(3)}</b> (n=${c.n})`
          : "no data";
      },
    },
    grid: { left: 8, right: 8, top: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: "category" as const, data: PERF_KEYS.map((k) => LABELS[k] ?? k),
      axisLabel: { color: "#94a3b8", fontSize: 10 },
      splitArea: { show: true, areaStyle: { color: ["#0f172a", "#111c30"] } },
    },
    yAxis: {
      type: "category" as const, data: PPA_KEYS.map((k) => LABELS[k] ?? k),
      axisLabel: { color: "#94a3b8", fontSize: 10 },
      splitArea: { show: true, areaStyle: { color: ["#0f172a", "#111c30"] } },
    },
    visualMap: {
      min: -1, max: 1, calculable: false,
      orient: "horizontal", left: "center", bottom: 0,
      textStyle: { color: "#94a3b8", fontSize: 10 },
      inRange: { color: ["#f87171", "#1e293b", "#34d399"] },
    },
    series: [{
      type: "heatmap",
      data: heatData,
      label: {
        show: true, color: "#e2e8f0", fontSize: 10,
        formatter: (p: { value: [number, number, number] }) => p.value[2].toFixed(2),
      },
      itemStyle: { borderColor: "#0f172a", borderWidth: 2 },
    }],
  };

  // ---- scatter + fit for the selected pair
  const pts = series
    .map((v) => ({ version: v.version, x: v.metrics[sel.ppa], y: v.metrics[sel.perf] }))
    .filter((p): p is { version: string; x: number; y: number } => p.x != null && p.y != null);
  const fit = pts.length >= 2 ? linreg(pts.map((p) => p.x), pts.map((p) => p.y)) : null;
  const xs = pts.map((p) => p.x);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);

  const scatterOption = {
    tooltip: {
      formatter: (p: { data: { name: string; value: [number, number] } }) =>
        `${p.data.name}<br/>${LABELS[sel.ppa] ?? sel.ppa}: ${fmt(p.data.value[0], 3)}<br/>${LABELS[sel.perf] ?? sel.perf}: ${fmt(p.data.value[1], 3)}`,
    },
    grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
    xAxis: {
      type: "value" as const, name: LABELS[sel.ppa] ?? sel.ppa,
      nameTextStyle: { color: "#94a3b8" },
      axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } },
      scale: true,
    },
    yAxis: {
      type: "value" as const, name: LABELS[sel.perf] ?? sel.perf,
      nameTextStyle: { color: "#94a3b8" },
      axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } },
      scale: true,
    },
    series: [
      {
        type: "scatter" as const,
        data: pts.map((p) => ({ name: p.version, value: [p.x, p.y] })),
        symbolSize: 10,
        itemStyle: { color: PALETTE.neutral, opacity: 0.85 },
        label: {
          show: true, position: "top" as const, color: "#94a3b8", fontSize: 9,
          formatter: (p: { data: { name: string } }) => p.data.name,
        },
      },
      ...(fit ? [{
        type: "line" as const,
        data: [[xMin, fit.a + fit.b * xMin], [xMax, fit.a + fit.b * xMax]],
        symbol: "none",
        lineStyle: { color: PALETTE.accent, width: 2, type: "dashed" as const },
        tooltip: { show: false },
      }] : []),
    ],
  };

  const selR = cell(sel.perf, sel.ppa);

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Correlations</h2>
        <p className="text-xs text-slate-500">
          Pearson r across {series.length} versions — pure observation, not causation:
          both metrics may follow a third factor (e.g. LVT creep raising power and area together).
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
        <Card title="Perf × PPA correlation matrix (click a cell to scatter)" className="lg:col-span-2">
          <EChart
            option={heatOption}
            height={300}
            onEvent={{
              type: "click",
              handler: (p: unknown) => {
                const params = p as { componentType: string; value: [number, number, number] };
                if (params.componentType === "series") {
                  setPair({ perf: PERF_KEYS[params.value[0]], ppa: PPA_KEYS[params.value[1]] });
                }
              },
            }}
          />
        </Card>
        <Card
          title={`Scatter — ${LABELS[sel.perf] ?? sel.perf} vs ${LABELS[sel.ppa] ?? sel.ppa}`}
          right={
            selR ? (
              <span className={`font-mono text-sm font-semibold ${
                Math.abs(selR.r) > 0.7 ? "text-violet-300" : "text-slate-400"
              }`}>
                r = {selR.r.toFixed(3)}
              </span>
            ) : undefined
          }
          className="lg:col-span-3"
        >
          <EChart option={scatterOption} height={300} />
          <p className="text-[10px] text-slate-600">
            Each point is one RTL version; dashed line is the least-squares fit.
            {fit ? ` slope: ${fit.b >= 0 ? "+" : ""}${fmt(fit.b, 3)} ${LABELS[sel.perf] ?? sel.perf} per unit ${LABELS[sel.ppa] ?? sel.ppa}.` : ""}
          </p>
        </Card>
      </div>

      <Card title="Module correlations — whose area/power tracks the net score">
        <Table head={["Module", "Metric", "r", "|r|", "n", ""]}>
          {modules.map((m) => (
            <tr key={`${m.module}:${m.metric}`} className={Math.abs(m.r) > 0.7 ? "bg-violet-500/5" : ""}>
              <td className="px-2 py-1 font-medium">{shortModule(m.module)}</td>
              <td className="px-2 py-1 text-slate-400">{LABELS[m.metric] ?? m.metric}</td>
              <td className={`px-2 py-1 font-mono ${m.r > 0 ? "text-emerald-400" : "text-red-400"}`}>
                {m.r >= 0 ? "+" : ""}{m.r.toFixed(3)}
              </td>
              <td className="px-2 py-1 font-mono text-slate-500">{Math.abs(m.r).toFixed(3)}</td>
              <td className="px-2 py-1 font-mono text-slate-500">{m.n}</td>
              <td className="px-2 py-1">
                <div className="h-2 w-full max-w-[220px] overflow-hidden rounded bg-slate-800">
                  <div
                    className={`h-full ${m.r > 0 ? "bg-emerald-500/70" : "bg-red-500/70"}`}
                    style={{ width: `${Math.min(Math.abs(m.r), 1) * 100}%` }}
                  />
                </div>
              </td>
            </tr>
          ))}
        </Table>
        <p className="mt-2 text-[10px] text-slate-600">
          |r| &gt; 0.7 highlighted: this module grew/shrank in lock-step with the score — a
          candidate cause (e.g. BTAC capacity behind both the IPC gain and the area step) or a
          fellow traveller. Check the change events before crediting it.
        </p>
      </Card>
    </div>
  );
}
