import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useApp } from "../store";
import { Card, Delta, Empty, Kpi, SevBadge, Table, fmt } from "../components/ui";

export function Scorecard() {
  const runId = useApp((s) => s.runId);
  const { data, isLoading } = useQuery({
    queryKey: ["scorecard", runId],
    queryFn: () => api.scorecard(runId!),
    enabled: !!runId,
  });

  if (!runId) return <Empty />;
  if (isLoading || !data) return <Card>loading…</Card>;

  const f = data.fom;
  const d = data.fom_delta_vs_baseline;
  const t = data.domains.timing;
  const a = data.domains.area;
  const p = data.domains.power;
  const perf = data.domains.performance;

  const areaBudget = data.budgets.area_mm2;
  const powerBudget = data.budgets.power_mw;
  const fmaxTarget = data.budgets.fmax_mhz;

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">PPA Scorecard — <span className="text-sky-400">{data.run.label}</span></h2>
        <span className="text-xs text-slate-500">stage: {data.run.stage} · freq source: {String(f.freq_source)}-derived</span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="SPECint2006 score" value={fmt(Number(f.specint_score), 2)}
          delta={<Delta pct={d.specint_score?.pct} />}
          target={d.specint_score ? `base ${fmt(d.specint_score.baseline, 2)}` : undefined} />
        <Kpi label="SPECint/GHz" value={fmt(Number(f.specint_per_ghz), 3)}
          delta={<Delta pct={d.specint_per_ghz?.pct} />} />
        <Kpi label="Fmax" value={fmt(Number(f.fmax_mhz), 0)} unit="MHz"
          delta={<Delta pct={d.fmax_mhz?.pct} />}
          target={fmaxTarget?.target ? `target ${fmt(fmaxTarget.target, 0)}` : undefined}
          overBudget={!!fmaxTarget?.target && Number(f.fmax_mhz) < fmaxTarget.target} />
        <Kpi label="Area" value={fmt(Number(f.area_mm2), 3)} unit="mm²"
          delta={<Delta pct={d.area_mm2?.pct} invert />}
          target={areaBudget?.budget ? `budget ${fmt(areaBudget.budget, 2)}` : undefined}
          overBudget={!!areaBudget?.budget && Number(f.area_mm2) > areaBudget.budget} />
        <Kpi label="Total power" value={fmt(Number(f.total_power_mw), 1)} unit="mW"
          delta={<Delta pct={d.total_power_mw?.pct} invert />}
          target={powerBudget?.budget ? `budget ${fmt(powerBudget.budget, 0)}` : undefined}
          overBudget={!!powerBudget?.budget && Number(f.total_power_mw) > powerBudget.budget} />
        <Kpi label="Area efficiency" value={fmt(Number(f.area_eff_score_per_mm2), 2)} unit="score/mm²"
          delta={<Delta pct={d.area_eff_score_per_mm2?.pct} />} />
        <Kpi label="Power efficiency" value={fmt(Number(f.power_eff_score_per_w), 1)} unit="score/W"
          delta={<Delta pct={d.power_eff_score_per_w?.pct} />} />
        <Kpi label="Energy per inst" value={fmt(Number(f.epi_pj), 2)} unit="pJ"
          delta={<Delta pct={d.epi_pj?.pct} invert />} />
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Card title="Timing">
          <Table head={["WNS ns", "TNS ns", "NVE", "Fmax MHz"]}>
            <tr>
              <td className={`px-2 py-1 font-mono ${(t.wns_ns ?? 0) < 0 ? "text-red-400" : "text-emerald-400"}`}>{fmt(t.wns_ns, 3)}</td>
              <td className="px-2 py-1 font-mono">{fmt(t.tns_ns, 1)}</td>
              <td className="px-2 py-1 font-mono">{fmt(t.nve, 0)}</td>
              <td className="px-2 py-1 font-mono">{fmt(t.fmax_mhz, 0)}</td>
            </tr>
          </Table>
        </Card>
        <Card title="Area">
          <Table head={["Total µm²", "Comb", "Seq", "Macro", "Cells"]}>
            <tr>
              <td className="px-2 py-1 font-mono">{fmt(a.total_um2, 0)}</td>
              <td className="px-2 py-1 font-mono">{fmt(a.comb_um2, 0)}</td>
              <td className="px-2 py-1 font-mono">{fmt(a.seq_um2, 0)}</td>
              <td className="px-2 py-1 font-mono">{fmt(a.macro_um2, 0)}</td>
              <td className="px-2 py-1 font-mono">{fmt(a.inst_count, 0)}</td>
            </tr>
          </Table>
        </Card>
        <Card title="Power" right={<span className="text-[10px] text-slate-500">vectorless · toggle {fmt(p.toggle_rate, 2)}</span>}>
          <Table head={["Total mW", "Internal", "Switching", "Leakage", "Leak %", "Clock %", "CG eff"]}>
            <tr>
              <td className="px-2 py-1 font-mono">{fmt(p.total_mw, 1)}</td>
              <td className="px-2 py-1 font-mono">{fmt(p.internal_mw, 1)}</td>
              <td className="px-2 py-1 font-mono">{fmt(p.switching_mw, 1)}</td>
              <td className="px-2 py-1 font-mono">{fmt(p.leakage_mw, 1)}</td>
              <td className="px-2 py-1 font-mono">{fmt(Number(p.leakage_share) * 100, 0)}%</td>
              <td className="px-2 py-1 font-mono">{fmt(Number(p.clock_power_share) * 100, 0)}%</td>
              <td className="px-2 py-1 font-mono">{fmt(p.clock_gating_eff, 0)}%</td>
            </tr>
          </Table>
        </Card>
        <Card title="Performance">
          <Table head={["SPECint/GHz (geomean)", "Mean IPC"]}>
            <tr>
              <td className="px-2 py-1 font-mono">{fmt(perf.geomean_ratio_1ghz, 3)}</td>
              <td className="px-2 py-1 font-mono">{fmt(perf.mean_ipc, 3)}</td>
            </tr>
          </Table>
        </Card>
      </div>

      <Card title={`Open findings (${data.findings.length})`}>
        {data.findings.length === 0 ? (
          <p className="text-sm text-slate-500">No findings — the rule engine sees nothing abnormal.</p>
        ) : (
          <ul className="space-y-1.5">
            {data.findings.slice(0, 8).map((fd) => (
              <li key={fd.id} className="flex items-start gap-2 text-sm">
                <SevBadge severity={fd.severity} />
                <span className="text-slate-300">{fd.title}</span>
                <span className="ml-auto text-[10px] uppercase text-slate-600">{fd.category}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
