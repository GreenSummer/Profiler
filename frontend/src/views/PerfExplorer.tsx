import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useApp } from "../store";
import { Card, Delta, Empty, Table, fmt } from "../components/ui";
import { EChart } from "../components/EChart";

/** green when the benchmark improved vs baseline, red when it regressed */
const BENCH_COLOR = (d: number | null) =>
  d === null ? "#60a5fa" : d > 0.01 ? "#34d399" : d < -0.01 ? "#f87171" : "#60a5fa";

export function PerfExplorer() {
  const runId = useApp((s) => s.runId);
  const { data, isLoading } = useQuery({
    queryKey: ["perf", runId],
    queryFn: () => api.perf(runId!),
    enabled: !!runId,
  });

  if (!runId) return <Empty />;
  if (isLoading || !data) return <Card>loading…</Card>;

  const rows = data.rows;
  const meanIpc = rows.length ? rows.reduce((s, r) => s + r.ipc, 0) / rows.length : 0;
  const sorted = [...rows].sort((a, b) => b.ratio_1ghz - a.ratio_1ghz);
  const best = sorted[0];
  const worst = sorted[sorted.length - 1];

  const ipcOption: Record<string, unknown> = {
    tooltip: { trigger: "axis" },
    grid: { left: 8, right: 8, top: 24, bottom: 8, containLabel: true },
    xAxis: {
      type: "category", data: rows.map((r) => r.benchmark),
      axisLabel: { color: "#94a3b8", rotate: 35, fontSize: 10 },
    },
    yAxis: { type: "value", name: "IPC", axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
    series: [{
      type: "bar",
      data: rows.map((r) => ({ value: r.ipc, itemStyle: { color: BENCH_COLOR(r.ipc_delta_pct) } })),
    }],
  };

  const ratioOption: Record<string, unknown> = {
    tooltip: { trigger: "axis" },
    grid: { left: 8, right: 8, top: 24, bottom: 8, containLabel: true },
    xAxis: {
      type: "category", data: rows.map((r) => r.benchmark),
      axisLabel: { color: "#94a3b8", rotate: 35, fontSize: 10 },
    },
    yAxis: { type: "value", name: "SPECratio @1GHz", axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
    series: [{
      type: "bar",
      data: rows.map((r) => r.ratio_1ghz),
      itemStyle: { color: "#a78bfa" },
      ...(data.geomean_ratio_1ghz !== null && data.geomean_ratio_1ghz !== undefined
        ? {
            markLine: {
              silent: true,
              symbol: "none",
              lineStyle: { color: "#f59e0b", type: "dashed" },
              label: { color: "#f59e0b", formatter: "geomean {c}", fontSize: 10 },
              data: [{ yAxis: data.geomean_ratio_1ghz }],
            },
          }
        : {}),
    }],
  };

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Performance Explorer</h2>
        <span className="text-xs text-slate-500">
          SPECint2006 · {rows.length} benchmarks · deltas vs {data.baseline_id ? `baseline run #${data.baseline_id}` : "—"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card>
          <div className="text-[11px] uppercase text-slate-500">SPECint/GHz (geomean)</div>
          <div className="mt-1 font-mono text-xl text-slate-100">{fmt(data.geomean_ratio_1ghz, 3)}</div>
          <div className="text-xs"><Delta pct={data.geomean_delta_pct} /></div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase text-slate-500">Mean IPC</div>
          <div className="mt-1 font-mono text-xl text-slate-100">{fmt(meanIpc, 3)}</div>
          <div className="text-[10px] text-slate-600">arithmetic mean over benchmarks</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase text-slate-500">Best benchmark</div>
          <div className="mt-1 font-mono text-lg text-emerald-400">{best?.benchmark ?? "—"}</div>
          <div className="text-[10px] text-slate-600">ratio @1GHz {fmt(best?.ratio_1ghz, 2)}</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase text-slate-500">Worst benchmark</div>
          <div className="mt-1 font-mono text-lg text-red-400">{worst?.benchmark ?? "—"}</div>
          <div className="text-[10px] text-slate-600">ratio @1GHz {fmt(worst?.ratio_1ghz, 2)}</div>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Card title="IPC per benchmark — green/red = better/worse than baseline">
          <EChart option={ipcOption} height={280} />
        </Card>
        <Card title="SPECratio @1GHz per benchmark — dashed line = geomean">
          <EChart option={ratioOption} height={280} />
        </Card>
      </div>

      <Card title="Per-benchmark detail">
        <Table head={["Benchmark", "IPC", "Δ IPC vs base", "Ratio @1GHz", "L1D MPKI", "L2 MPKI", "Br mispred %"]}>
          {rows.map((r) => (
            <tr key={r.benchmark}>
              <td className="px-2 py-1 font-medium">{r.benchmark}</td>
              <td className="px-2 py-1 font-mono">{fmt(r.ipc, 3)}</td>
              <td className="px-2 py-1"><Delta pct={r.ipc_delta_pct !== null ? r.ipc_delta_pct * 100 : null} /></td>
              <td className="px-2 py-1 font-mono">{fmt(r.ratio_1ghz, 2)}</td>
              <td className="px-2 py-1 font-mono text-slate-400">{fmt(r.l1d_mpki, 2)}</td>
              <td className={`px-2 py-1 font-mono ${r.l2_mpki !== null && r.l2_mpki > 1 ? "text-yellow-400" : "text-slate-400"}`}>
                {fmt(r.l2_mpki, 2)}
              </td>
              <td className="px-2 py-1 font-mono text-slate-400">{fmt(r.br_mispred_pct, 1)}</td>
            </tr>
          ))}
        </Table>
        <p className="mt-2 text-[10px] text-slate-600">
          Net SPEC score = SPECint/GHz × Fmax: a big IPC win that costs frequency is not a win —
          check the net-score decomposition in Compare before celebrating any IPC gain.
        </p>
      </Card>
    </div>
  );
}
