import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useApp } from "../store";
import { Card, Delta, Empty, Table, fmt, shortModule } from "../components/ui";
import { EChart } from "../components/EChart";
import { SourceBtn } from "../components/TraceDrawer";

export function PowerExplorer() {
  const runId = useApp((s) => s.runId);
  const { data, isLoading } = useQuery({
    queryKey: ["power", runId],
    queryFn: () => api.power(runId!),
    enabled: !!runId,
  });

  if (!runId) return <Empty />;
  if (isLoading || !data) return <Card>loading…</Card>;

  const level2 = data.rows.filter((r) => r.depth === 2).sort((a, b) => b.total - a.total);

  const stackedOption = {
    tooltip: { trigger: "axis" as const },
    legend: { textStyle: { color: "#94a3b8" }, top: 0 },
    grid: { left: 8, right: 8, top: 30, bottom: 8, containLabel: true },
    xAxis: { type: "category" as const, data: level2.map((r) => shortModule(r.scope_path)), axisLabel: { color: "#94a3b8", rotate: 20, fontSize: 10 } },
    yAxis: { type: "value" as const, name: "mW", axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
    series: [
      { name: "internal", type: "bar", stack: "p", data: level2.map((r) => r.internal), itemStyle: { color: "#60a5fa" } },
      { name: "switching", type: "bar", stack: "p", data: level2.map((r) => r.switching), itemStyle: { color: "#a78bfa" } },
      { name: "leakage", type: "bar", stack: "p", data: level2.map((r) => r.leakage), itemStyle: { color: "#f87171" } },
    ],
  };

  const leakSharePct = data.rows.find((r) => r.depth === Math.min(...data.rows.map((x) => x.depth)))?.leak_share ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">
          Power Explorer — total {fmt(data.total_mw, 2)} mW
        </h2>
        <span className="text-xs text-slate-500">
          vectorless · toggle rate {fmt(data.toggle_rate, 2)} · ⚠ relative-comparison quality, not signoff
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card><div className="text-[11px] uppercase text-slate-500">Clock power share</div>
          <div className={`mt-1 font-mono text-xl ${(data.clock_power_share ?? 0) > 0.3 ? "text-yellow-400" : "text-slate-200"}`}>
            {fmt((data.clock_power_share ?? 0) * 100, 0)}%
          </div>
          <div className="text-[10px] text-slate-600">&gt;30% = gating/CTS opportunity</div>
        </Card>
        <Card><div className="text-[11px] uppercase text-slate-500">Clock gating efficiency</div>
          <div className={`mt-1 font-mono text-xl ${(data.clock_gating_eff ?? 100) < 70 ? "text-red-400" : "text-emerald-400"}`}>
            {fmt(data.clock_gating_eff, 0)}%
          </div>
          <div className="text-[10px] text-slate-600">&lt;70% = wasted clock power</div>
        </Card>
        <Card><div className="text-[11px] uppercase text-slate-500">Leakage share</div>
          <div className={`mt-1 font-mono text-xl ${leakSharePct > 0.25 ? "text-red-400" : "text-slate-200"}`}>
            {fmt(leakSharePct * 100, 0)}%
          </div>
          <div className="text-[10px] text-slate-600">&gt;25% = VT mix too aggressive</div>
        </Card>
        <Card><div className="text-[11px] uppercase text-slate-500">mW per MHz</div>
          <div className="mt-1 font-mono text-xl text-slate-200">
            {fmt(data.total_mw / 800, 4)}
          </div>
          <div className="text-[10px] text-slate-600">classic embedded figure of merit</div>
        </Card>
      </div>

      <Card title="Power by module — internal / switching / leakage">
        <EChart option={stackedOption} height={300} />
      </Card>

      <Card title="Module power table (level 2)">
        <Table head={["Module", "Total mW", "Share", "Internal", "Switching", "Leakage", "Leak%", "Density mW/mm²", "Δ vs base", ""]}>
          {level2.map((r) => (
            <tr key={r.scope_path}>
              <td className="px-2 py-1 font-medium">{shortModule(r.scope_path)}</td>
              <td className="px-2 py-1 font-mono">{fmt(r.total, 3)}</td>
              <td className="px-2 py-1 font-mono">{fmt(r.share * 100, 1)}%</td>
              <td className="px-2 py-1 font-mono text-slate-400">{fmt(r.internal, 3)}</td>
              <td className="px-2 py-1 font-mono text-slate-400">{fmt(r.switching, 3)}</td>
              <td className={`px-2 py-1 font-mono ${r.leak_share > 0.3 ? "text-red-400" : ""}`}>{fmt(r.leakage, 3)}</td>
              <td className="px-2 py-1 font-mono">{fmt(r.leak_share * 100, 0)}%</td>
              <td className="px-2 py-1 font-mono">{r.power_density_mw_um2 ? fmt(r.power_density_mw_um2 * 1e6, 0) : "—"}</td>
              <td className="px-2 py-1"><Delta pct={r.delta_vs_baseline_pct !== null ? r.delta_vs_baseline_pct * 100 : null} invert /></td>
              <td className="px-2 py-1 text-right">
                <SourceBtn target={{ run_id: runId!, kind: "power", scope_path: r.scope_path }} />
              </td>
            </tr>
          ))}
        </Table>
        <p className="mt-2 text-[10px] text-slate-600">
          High density flags IR-drop / thermal risk before physical design reports it.
          Power paths are joined to area paths via canonical hierarchy names (cross-tool, plan thesis 2).
        </p>
      </Card>
    </div>
  );
}
