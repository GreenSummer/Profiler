import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import { Card, Table, fmt } from "../components/ui";
import { EChart, PALETTE } from "../components/EChart";

const METRICS = [
  { id: "total_power_mw", label: "Power mW" },
  { id: "area_mm2", label: "Area mm²" },
  { id: "fmax_mhz", label: "Fmax MHz" },
  { id: "specint_score", label: "SPECint score" },
  { id: "specint_per_ghz", label: "SPECint/GHz" },
  { id: "epi_pj", label: "EPI pJ" },
];

export function DesignSpace() {
  const [x, setX] = useState("total_power_mw");
  const [y, setY] = useState("specint_score");
  const { setRun, toggleCompare } = useApp();
  const { data, isLoading } = useQuery({
    queryKey: ["design-space", x, y],
    queryFn: () => api.designSpace(x, y),
  });

  if (isLoading || !data) return <Card>loading…</Card>;
  const pts = data.points;
  const paretoLabels = pts.filter((p) => p.pareto).map((p) => p.label);

  const scatterOption = {
    tooltip: {
      trigger: "item" as const,
      formatter: (p: { data: { name: string; value: number[] } }) =>
        `${p.data.name}<br/>${x}: ${p.data.value[0].toFixed(3)}<br/>${y}: ${p.data.value[1].toFixed(3)}`,
    },
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    xAxis: { name: x, nameTextStyle: { color: "#94a3b8" }, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } }, scale: true },
    yAxis: { name: y, nameTextStyle: { color: "#94a3b8" }, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } }, scale: true },
    series: [
      {
        name: "dominated",
        type: "scatter" as const,
        data: pts.filter((p) => !p.pareto).map((p) => ({ name: p.label, value: [p.x, p.y], run_id: p.run_id })),
        symbolSize: 10,
        itemStyle: { color: "#475569", opacity: 0.6 },
        label: { show: true, position: "top" as const, color: "#64748b", fontSize: 9, formatter: (p: { data: { name: string } }) => p.data.name },
      },
      {
        name: "pareto optimal",
        type: "scatter" as const,
        data: pts.filter((p) => p.pareto).map((p) => ({ name: p.label, value: [p.x, p.y], run_id: p.run_id })),
        symbolSize: 16,
        itemStyle: { color: PALETTE.good, borderColor: "#a7f3d0", borderWidth: 1 },
        label: { show: true, position: "top" as const, color: "#6ee7b7", fontSize: 10, fontWeight: "bold", formatter: (p: { data: { name: string } }) => p.data.name },
      },
    ],
  };

  const parallelOption = {
    tooltip: { trigger: "item" as const },
    parallelAxis: METRICS.map((m, i) => ({
      dim: i, name: m.label, nameTextStyle: { color: "#94a3b8", fontSize: 10 },
      axisLine: { lineStyle: { color: "#334155" } }, axisLabel: { color: "#64748b", fontSize: 9 },
    })),
    parallel: { left: 40, right: 40, top: 30, bottom: 10 },
    series: [{
      type: "parallel" as const,
      lineStyle: { width: 1.5, opacity: 0.7 },
      data: pts.map((p) => ({
        name: p.label,
        value: METRICS.map((m) => Number(p.fom[m.id] ?? 0)),
        lineStyle: { color: p.pareto ? PALETTE.good : "#475569", width: p.pareto ? 2.5 : 1, opacity: p.pareto ? 0.9 : 0.35 },
      })),
    }],
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Design Space Explorer</h2>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">x</span>
          <select value={x} onChange={(e) => setX(e.target.value)} className="rounded border border-slate-700 bg-slate-800 px-2 py-1">
            {METRICS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
          <span className="text-slate-500">y</span>
          <select value={y} onChange={(e) => setY(e.target.value)} className="rounded border border-slate-700 bg-slate-800 px-2 py-1">
            {METRICS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </div>
      </div>

      <Card title={`Pareto frontier — ${paretoLabels.length}/${pts.length} optimal: ${paretoLabels.join(", ")}`}>
        <EChart option={scatterOption} height={340}
          onEvent={{ type: "click", handler: (p) => { const d = (p as { data: { run_id: number } }).data; setRun(d.run_id); toggleCompare(d.run_id); } }} />
        <p className="text-[10px] text-slate-600">Click a point to select the run and add it to the comparison tray. Green points are non-dominated.</p>
      </Card>

      <Card title="Parallel coordinates (all runs × all figures of merit)">
        <EChart option={parallelOption} height={300} />
      </Card>

      <Card title="Runs by config">
        <Table head={["Run", "Pareto", ...METRICS.map((m) => m.label)]}>
          {[...pts].sort((a, b) => Number(b.pareto) - Number(a.pareto) || b.y - a.y).map((p) => (
            <tr key={p.run_id} className="cursor-pointer hover:bg-slate-800/40" onClick={() => { setRun(p.run_id); toggleCompare(p.run_id); }}>
              <td className="px-2 py-1 font-medium">{p.label}</td>
              <td className="px-2 py-1">{p.pareto ? <span className="text-emerald-400">●</span> : <span className="text-slate-700">○</span>}</td>
              {METRICS.map((m) => (
                <td key={m.id} className="px-2 py-1 font-mono">{fmt(Number(p.fom[m.id] ?? 0), 3)}</td>
              ))}
            </tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}
