import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useApp } from "../store";
import { Card, Delta, Empty, Table, fmt, shortModule } from "../components/ui";
import { EChart } from "../components/EChart";

export function Hotspot() {
  const runId = useApp((s) => s.runId);
  const { data, isLoading } = useQuery({
    queryKey: ["hotspot", runId],
    queryFn: () => api.hotspot(runId!),
    enabled: !!runId,
  });

  if (!runId) return <Empty />;
  if (isLoading || !data) return <Card>loading…</Card>;

  const rows = data.rows;
  const maxDensity = Math.max(...rows.map((r) => r.power_density * 1e6), 1);
  const axisMax = Math.ceil(
    Math.max(...rows.flatMap((r) => [r.area_share, r.power_share]), 0) * 100 / 10,
  ) * 10 + 5;

  const option: Record<string, unknown> = {
    tooltip: {
      formatter: (p: { data: { name: string; value: number[] } }) => {
        const [a, pw, crit, dens] = p.data.value;
        return `<b>${p.data.name}</b><br/>area share: ${a.toFixed(1)}%` +
          `<br/>power share: ${pw.toFixed(1)}%` +
          `<br/>criticality: ${crit.toFixed(0)}% of top paths` +
          `<br/>density: ${dens.toFixed(0)} mW/mm²`;
      },
    },
    grid: { left: 8, right: 74, top: 24, bottom: 8, containLabel: true },
    xAxis: {
      type: "value", name: "area share %", max: axisMax,
      nameTextStyle: { color: "#94a3b8" }, axisLabel: { color: "#94a3b8" },
      splitLine: { lineStyle: { color: "#1e293b" } },
    },
    yAxis: {
      type: "value", name: "power share %", max: axisMax,
      nameTextStyle: { color: "#94a3b8" }, axisLabel: { color: "#94a3b8" },
      splitLine: { lineStyle: { color: "#1e293b" } },
    },
    visualMap: {
      show: true, dimension: 3, min: 0, max: maxDensity,
      calculable: true, right: 0, top: "center", itemHeight: 90,
      inRange: { color: ["#38bdf8", "#fbbf24", "#ef4444"] },
      textStyle: { color: "#94a3b8", fontSize: 10 },
    },
    series: [{
      type: "scatter",
      data: rows.map((r) => ({
        name: shortModule(r.module),
        value: [r.area_share * 100, r.power_share * 100, r.criticality * 100, r.power_density * 1e6],
      })),
      symbolSize: (val: number[]) => 10 + Math.min(val[2] * 0.8, 34),
      itemStyle: { opacity: 0.85, borderColor: "#0f172a" },
      label: {
        show: true,
        formatter: (p: { data: { name: string } }) => p.data.name,
        color: "#cbd5e1", fontSize: 9,
      },
      labelLayout: { hideOverlap: true },
      markLine: {
        silent: true, symbol: "none",
        lineStyle: { color: "#475569", type: "dashed" },
        label: { color: "#64748b", formatter: "power share = area share", fontSize: 10 },
        data: [{ coords: [[0, 0], [axisMax, axisMax]] }],
      },
    }],
  };

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Hotspot Matrix</h2>
        <span className="text-xs text-slate-500">
          level-2 modules · area × power × timing criticality, joined across tools
        </span>
      </div>

      <Card title="Where does the design hurt? — bubble size = timing criticality, color = power density">
        <EChart option={option} height={420} />
        <p className="mt-1 text-[10px] text-slate-600">
          Above the diagonal = burns a larger share of power than its share of area (gating / VT candidates).
          Top-right = expensive everywhere: area, power and critical paths at once.
        </p>
      </Card>

      <Card title="Module hotspot table">
        <Table head={["Module", "Area µm²", "Area share", "Power mW", "Power share", "Density mW/mm²", "Criticality", "Δ Area", "Δ Power"]}>
          {rows.map((r) => (
            <tr key={r.module} className={r.criticality > 0.2 ? "bg-red-500/5" : ""}>
              <td className="px-2 py-1 font-medium">{shortModule(r.module)}</td>
              <td className="px-2 py-1 font-mono">{fmt(r.area_um2, 0)}</td>
              <td className="px-2 py-1 font-mono">{fmt(r.area_share * 100, 1)}%</td>
              <td className="px-2 py-1 font-mono">{fmt(r.power_mw, 2)}</td>
              <td className="px-2 py-1 font-mono">{fmt(r.power_share * 100, 1)}%</td>
              <td className={`px-2 py-1 font-mono ${r.power_density * 1e6 > 450 ? "text-red-400" : ""}`}>
                {fmt(r.power_density * 1e6, 0)}
              </td>
              <td className={`px-2 py-1 font-mono ${r.criticality > 0.2 ? "text-red-400" : ""}`}>
                {fmt(r.criticality * 100, 0)}%
              </td>
              <td className="px-2 py-1"><Delta pct={r.area_delta_pct !== null ? r.area_delta_pct * 100 : null} invert /></td>
              <td className="px-2 py-1"><Delta pct={r.power_delta_pct !== null ? r.power_delta_pct * 100 : null} invert /></td>
            </tr>
          ))}
        </Table>
        <p className="mt-2 text-[10px] text-slate-600">
          Criticality = share of the 100 worst setup paths owned by the module (cross-tool join,
          plan thesis 2). Rows highlighted = module owns &gt;20% of critical paths.
        </p>
      </Card>
    </div>
  );
}
