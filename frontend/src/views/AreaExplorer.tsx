import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import { Card, Delta, Empty, Table, fmt, shortModule } from "../components/ui";
import { EChart } from "../components/EChart";
import { SourceBtn } from "../components/TraceDrawer";
import type { AreaRowX } from "../types";

function buildTree(rows: AreaRowX[]) {
  const byPath = new Map(rows.map((r) => [r.scope_path, r]));
  const childrenOf = new Map<string, AreaRowX[]>();
  for (const r of rows) {
    const list = childrenOf.get(r.parent) ?? [];
    list.push(r);
    childrenOf.set(r.parent, list);
  }
  function node(r: AreaRowX): Record<string, unknown> {
    const kids = (childrenOf.get(r.scope_path) ?? []).map(node);
    return {
      name: r.scope_path.split("/").pop() ?? r.scope_path,
      value: r.total_area,
      path: r.scope_path,
      share: r.share,
      delta: r.delta_vs_baseline_pct,
      children: kids.length ? kids : undefined,
    };
  }
  const root = rows.find((r) => r.depth === Math.min(...rows.map((x) => x.depth)));
  return root ? node(root) : {};
}

export function AreaExplorer() {
  const runId = useApp((s) => s.runId);
  const [colorBy, setColorBy] = useState<"composition" | "delta">("composition");
  const [sizeBy, setSizeBy] = useState<"area" | "inst">("area");
  const { data, isLoading } = useQuery({
    queryKey: ["area", runId],
    queryFn: () => api.area(runId!),
    enabled: !!runId,
  });

  const tree = useMemo(() => (data ? buildTree(data.rows) : {}), [data]);

  if (!runId) return <Empty />;
  if (isLoading || !data) return <Card>loading…</Card>;

  const deltaColor = (d: number | null | undefined) => {
    if (d === null || d === undefined) return "#334155";
    if (d > 0.05) return "#dc2626";
    if (d < -0.05) return "#16a34a";
    return "#475569";
  };

  const decorate = (n: Record<string, unknown>): Record<string, unknown> => {
    const kids = (n.children as Record<string, unknown>[] | undefined) ?? [];
    return {
      ...n,
      itemStyle: colorBy === "delta"
        ? { borderColor: "#0f172a", borderWidth: 1, color: deltaColor(n.delta as number | null) }
        : undefined,
      children: kids.length ? kids.map(decorate) : undefined,
    };
  };

  const option = {
    tooltip: {
      formatter: (p: { data: { path?: string; value?: number; share?: number; delta?: number | null } }) =>
        `<b>${p.data.path ?? ""}</b><br/>area: ${fmt(p.data.value, 0)} µm² (${fmt((p.data.share ?? 0) * 100, 1)}%)` +
        (p.data.delta !== null && p.data.delta !== undefined ? `<br/>Δ vs baseline: ${p.data.delta.toFixed(1)}%` : ""),
    },
    series: [{
      type: "treemap",
      data: [decorate(tree)],
      roam: false,
      nodeClick: "zoomToNode",
      breadcrumb: { show: true, itemStyle: { color: "#1e293b", textStyle: { color: "#94a3b8" } } },
      label: { show: true, formatter: (p: { data: { name: string } }) => p.data.name, color: "#e2e8f0", fontSize: 11 },
      upperLabel: { show: true, height: 18, color: "#94a3b8" },
      itemStyle: { borderColor: "#0f172a", borderWidth: 1, gapWidth: 2 },
      levels: [
        { itemStyle: { borderColor: "#334155", borderWidth: 2, gapWidth: 3 } },
        { colorSaturation: [0.35, 0.6], itemStyle: { borderColor: "#1e293b", borderWidth: 1, gapWidth: 2 } },
      ],
    }],
  };

  const top = [...data.rows]
    .filter((r) => r.depth === 2)
    .sort((a, b) => (sizeBy === "area" ? b.total_area - a.total_area : b.inst_count - a.inst_count))
    .slice(0, 12);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Area Explorer — total {fmt(data.total_um2, 0)} µm² ({fmt(data.total_um2 / 1e6, 3)} mm²)</h2>
        <div className="flex gap-2 text-xs">
          <select value={colorBy} onChange={(e) => setColorBy(e.target.value as "composition" | "delta")}
            className="rounded border border-slate-700 bg-slate-800 px-2 py-1">
            <option value="composition">color: composition</option>
            <option value="delta">color: Δ vs baseline</option>
          </select>
          <select value={sizeBy} onChange={(e) => setSizeBy(e.target.value as "area" | "inst")}
            className="rounded border border-slate-700 bg-slate-800 px-2 py-1">
            <option value="area">size: area</option>
            <option value="inst">size: inst count</option>
          </select>
        </div>
      </div>

      <Card title="Module hierarchy treemap (click to drill down, breadcrumb to go back)">
        <EChart option={option} height={420} />
      </Card>

      <Card title={`Top level-2 modules by ${sizeBy === "area" ? "area" : "instance count"}`}>
        <Table head={["Module", "Area µm²", "Share", "Comb", "Seq", "Macro", "Buf/Inv", "Seq%", "Δ vs base", "Cells", ""]}>
          {top.map((r) => (
            <tr key={r.scope_path}>
              <td className="px-2 py-1 font-medium">{shortModule(r.scope_path)}</td>
              <td className="px-2 py-1 font-mono">{fmt(r.total_area, 0)}</td>
              <td className="px-2 py-1 font-mono">{fmt(r.share * 100, 1)}%</td>
              <td className="px-2 py-1 font-mono text-slate-400">{fmt(r.comb, 0)}</td>
              <td className="px-2 py-1 font-mono text-slate-400">{fmt(r.seq, 0)}</td>
              <td className="px-2 py-1 font-mono text-slate-400">{fmt(r.macro, 0)}</td>
              <td className="px-2 py-1 font-mono text-slate-400">{fmt(r.buf_inv, 0)}</td>
              <td className={`px-2 py-1 font-mono ${r.seq_ratio > 0.5 ? "text-yellow-400" : ""}`}>{fmt(r.seq_ratio * 100, 0)}%</td>
              <td className="px-2 py-1"><Delta pct={r.delta_vs_baseline_pct !== null ? r.delta_vs_baseline_pct * 100 : null} invert /></td>
              <td className="px-2 py-1 font-mono text-slate-400">{fmt(r.inst_count, 0)}</td>
              <td className="px-2 py-1 text-right">
                <SourceBtn target={{ run_id: runId!, kind: "area", scope_path: r.scope_path }} />
              </td>
            </tr>
          ))}
        </Table>
        <p className="mt-2 text-[10px] text-slate-600">
          Seq% &gt; 50% (yellow) = flop-heavy design: power-hungry and hard to clock-gate.
          Children roll up to parents exactly — verified by the ingest data-quality rule.
        </p>
      </Card>
    </div>
  );
}
