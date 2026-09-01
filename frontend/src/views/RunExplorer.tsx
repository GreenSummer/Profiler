import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import { Card, Delta, Table, fmt } from "../components/ui";
import { OverviewBoard } from "./OverviewBoard";

const COLS: { key: string; label: string; digits?: number; invert?: boolean }[] = [
  { key: "specint_score", label: "SPECint score", digits: 2 },
  { key: "specint_per_ghz", label: "SPECint/GHz", digits: 3 },
  { key: "fmax_mhz", label: "Fmax MHz", digits: 0 },
  { key: "area_mm2", label: "Area mm²", digits: 3 },
  { key: "total_power_mw", label: "Power mW", digits: 1 },
  { key: "mw_per_mhz", label: "mW/MHz", digits: 3 },
  { key: "area_eff_score_per_mm2", label: "score/mm²", digits: 2 },
  { key: "epi_pj", label: "EPI pJ", digits: 2, invert: true },
];

export function RunExplorer() {
  const { data: runs, isLoading } = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  const { runId, baselineRunId, compareIds, setRun, setBaseline, toggleCompare, setView } = useApp();
  const [sortKey, setSortKey] = useState("run_id");
  const [asc, setAsc] = useState(true);

  if (isLoading) return <Card>loading…</Card>;
  const rows = [...(runs ?? [])].sort((a, b) => {
    const va = sortKey === "run_id" ? a.run_id : Number(a.fom[sortKey] ?? a.timing?.[sortKey as keyof typeof a.timing] ?? 0);
    const vb = sortKey === "run_id" ? b.run_id : Number(b.fom[sortKey] ?? b.timing?.[sortKey as keyof typeof b.timing] ?? 0);
    return asc ? va - vb : vb - va;
  });
  const base = runs?.find((r) => r.run_id === baselineRunId);

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Run Explorer</h2>
        <p className="text-xs text-slate-500">
          {rows.length} runs · baseline: <span className="text-sky-400">{base?.label ?? "unset"}</span> ·
          deltas below are vs baseline
        </p>
      </div>
      <Card>
        <Table head={["", "Run", "Stage", ...COLS.map((c) => c.label), "WNS ns", "Findings", ""]}>
          {rows.map((r) => {
            const isBase = r.run_id === baselineRunId;
            return (
              <tr key={r.run_id} className={`cursor-pointer hover:bg-slate-800/40 ${r.run_id === runId ? "bg-sky-500/10" : ""}`}
                onClick={() => setRun(r.run_id)}>
                <td className="px-2 py-1.5">
                  <input type="radio" checked={isBase} onClick={(e) => { e.stopPropagation(); setBaseline(r.run_id); }}
                    title="set as baseline" className="accent-sky-500" />
                </td>
                <td className="px-2 py-1.5 font-medium text-slate-200">
                  {r.label}
                  {isBase && <span className="ml-1 rounded bg-sky-500/20 px-1 text-[9px] font-bold uppercase text-sky-300">base</span>}
                  {compareIds.includes(r.run_id) && <span className="ml-1 rounded bg-violet-500/20 px-1 text-[9px] font-bold uppercase text-violet-300">cmp</span>}
                </td>
                <td className="px-2 py-1.5 text-slate-500">{r.stage}</td>
                {COLS.map((c) => {
                  const v = Number(r.fom[c.key] ?? 0);
                  const bv = Number(base?.fom[c.key] ?? 0);
                  const pct = base && bv ? (v - bv) / bv * 100 : null;
                  return (
                    <td key={c.key} className="px-2 py-1.5 font-mono">
                      <div className="flex flex-col leading-tight">
                        <span>{fmt(v, c.digits ?? 3)}</span>
                        {base && r.run_id !== base.run_id && (
                          <span className="text-[10px]"><Delta pct={pct} invert={c.invert} digits={1} /></span>
                        )}
                      </div>
                    </td>
                  );
                })}
                <td className={`px-2 py-1.5 font-mono ${(r.timing.wns_ns ?? 0) < 0 ? "text-red-400" : "text-slate-400"}`}>
                  {fmt(r.timing.wns_ns, 3)}
                </td>
                <td className="px-2 py-1.5">
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                    r.open_findings > 6 ? "bg-red-500/20 text-red-300" : r.open_findings > 0 ? "bg-yellow-500/20 text-yellow-300" : "bg-emerald-500/20 text-emerald-300"
                  }`}>{r.open_findings}</span>
                </td>
                <td className="px-2 py-1.5 text-right">
                  <button
                    onClick={(e) => { e.stopPropagation(); toggleCompare(r.run_id); }}
                    className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400 hover:border-violet-400 hover:text-violet-300"
                    title="add to comparison">
                    ±cmp
                  </button>
                </td>
              </tr>
            );
          })}
        </Table>
      </Card>
      {compareIds.length >= 2 && (
        <div className="flex justify-end">
          <button onClick={() => setView("compare")}
            className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-500">
            Compare {compareIds.length} selected runs →
          </button>
        </div>
      )}
      <p className="text-xs text-slate-600">
        Tip: radio button sets the baseline for all deltas · ±cmp builds the comparison tray ·
        SPECint score = SPECint/GHz × Fmax — the net number a frequency/IPC trade is judged on.
      </p>
      <OverviewBoard />
    </div>
  );
}
