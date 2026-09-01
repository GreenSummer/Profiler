import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import { Card, Delta, Empty, SevBadge, Spinner, Table, fmt, shortModule } from "../components/ui";
import { EChart } from "../components/EChart";
import { SourceBtn } from "../components/TraceDrawer";
import {
  EventTraceBtn, METRIC_LABELS, MethodBadge, eventDeltaClass, fmtEventDelta,
} from "../components/changeEvents";
import type { OverviewData, VersionCompare, VersionDrill } from "../types";

// provenance-series styling: gem5 dashed, zebu solid (the truth), the rest
// toggleable additions
const MODEL_STYLE: Record<string, { color: string; type: "solid" | "dashed" | "dotted" }> = {
  synth: { color: "#e2e8f0", type: "solid" },
  gem5: { color: "#fbbf24", type: "dashed" },
  zebu: { color: "#34d399", type: "solid" },
  slice: { color: "#60a5fa", type: "dotted" },
  fogs: { color: "#a78bfa", type: "dotted" },
};
const MODEL_LABEL: Record<string, string> = {
  synth: "full synth", gem5: "gem5 model", zebu: "zebu RTL", slice: "slice", fogs: "fogs RTL",
};

const CAT_COLORS: Record<string, string> = {
  Frontend: "#60a5fa", Backend: "#f472b6", Memblock: "#34d399",
  "L2 top": "#fbbf24", Other: "#64748b",
};

const AXIS = { color: "#94a3b8", fontSize: 10 };
const SPLIT = { lineStyle: { color: "#1e293b" } };
const TARGET_LINE = (y: number, label: string) => ({
  silent: true, symbol: "none",
  lineStyle: { color: "#f87171", type: "dotted" as const, width: 1.5 },
  label: { formatter: label, color: "#f87171", fontSize: 9, position: "insideEndTop" as const },
  data: [{ yAxis: y }],
});

function lineSeries(name: string, model: string, data: (number | null)[],
                     extra: Record<string, unknown> = {}) {
  const st = MODEL_STYLE[model] ?? MODEL_STYLE.synth;
  return {
    name, type: "line" as const, data, symbolSize: 5,
    itemStyle: { color: st.color },
    lineStyle: { color: st.color, width: 2, type: st.type },
    emphasis: { focus: "series" as const },
    ...extra,
  };
}

/** Click a version (category axis) -> drill-down. */
function drillClick(versions: string[], setDrillVersion: (v: string | null) => void) {
  return {
    type: "click",
    handler: (p: unknown) => {
      const params = p as { componentType: string; dataIndex: number };
      if (params.componentType === "series" || params.componentType === "xAxis") {
        const v = versions[params.dataIndex];
        if (v) setDrillVersion(v);
      }
    },
  };
}

// ---------------------------------------------------------------- version strip

function VersionStrip({ ov }: { ov: OverviewData }) {
  const { drillVersion, setDrillVersion, overviewVersions, toggleOverviewVersion,
          clearOverviewVersions } = useApp();
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-[10px] uppercase tracking-wide text-slate-600">
        releases · click = drill-down · ☑ = compare
      </span>
      {ov.versions.map((v) => {
        const active = drillVersion === v;
        const picked = overviewVersions.includes(v);
        return (
          <span key={v} className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
            active ? "border-sky-400 bg-sky-500/15 text-sky-200"
                   : picked ? "border-violet-500/60 bg-violet-500/10 text-violet-200"
                   : "border-slate-700 text-slate-400 hover:border-slate-500"}`}>
            <input type="checkbox" checked={picked} className="accent-violet-500"
              onChange={() => toggleOverviewVersion(v)}
              onClick={(e) => e.stopPropagation()} title="add to multi-version compare" />
            <button onClick={() => setDrillVersion(active ? null : v)}>{v}</button>
          </span>
        );
      })}
      {overviewVersions.length > 0 && (
        <button onClick={clearOverviewVersions}
          className="ml-1 rounded border border-slate-700 px-2 py-0.5 text-[10px] text-slate-500 hover:border-red-400 hover:text-red-300">
          clear ({overviewVersions.length})
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- P1: geomean + perf/area

function PanelGeomean({ ov }: { ov: OverviewData }) {
  const setDrillVersion = useApp((s) => s.setDrillVersion);
  const gmOption = {
    tooltip: { trigger: "axis" as const },
    legend: { textStyle: { color: "#94a3b8", fontSize: 10 }, top: 0 },
    grid: { left: 8, right: 16, top: 26, bottom: 8, containLabel: true },
    xAxis: { type: "category" as const, data: ov.versions, axisLabel: AXIS, boundaryGap: true },
    yAxis: { type: "value" as const, name: "geomean ratio @1GHz", nameTextStyle: AXIS,
             axisLabel: AXIS, splitLine: SPLIT, scale: true },
    series: [
      ...Object.entries(ov.geomean).map(([model, vals]) =>
        lineSeries(MODEL_LABEL[model] ?? model, model, vals)),
      { ...lineSeries("target", "synth", ov.versions.map(() => ov.target_geomean),
          { symbol: "none", lineStyle: { color: "#f87171", width: 1.5, type: "dotted" as const },
            itemStyle: { color: "#f87171" } }), name: "target" },
    ],
  };
  const ppaOption = {
    tooltip: { trigger: "axis" as const },
    grid: { left: 8, right: 16, top: 26, bottom: 8, containLabel: true },
    xAxis: { type: "category" as const, data: ov.versions, axisLabel: AXIS, boundaryGap: true },
    yAxis: { type: "value" as const, name: "SPECint/GHz/mm²", nameTextStyle: AXIS,
             axisLabel: AXIS, splitLine: SPLIT, scale: true },
    series: [{
      name: "perf per area", type: "line" as const, data: ov.perf_per_area, symbolSize: 5,
      itemStyle: { color: "#60a5fa" }, lineStyle: { color: "#60a5fa", width: 2 },
      areaStyle: { color: "rgba(96,165,250,0.08)" },
      markLine: TARGET_LINE(ov.target_eff,
        `target ${ov.target_eff} (${ov.target_geomean} @ ${ov.area_budget_mm2} mm²)`),
    }],
  };
  return (
    <Card title="1 · Geomean performance trend & performance per area"
      right={<span className="text-[10px] text-slate-600">
        target geomean {ov.target_geomean} · area constraint {ov.area_budget_mm2} mm²
      </span>}>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <EChart option={gmOption} height={280} onEvent={drillClick(ov.versions, setDrillVersion)} />
        <EChart option={ppaOption} height={280} onEvent={drillClick(ov.versions, setDrillVersion)} />
      </div>
      <p className="mt-1 text-[10px] text-slate-600">
        Left: geomean SPECint ratio across gem5 model, slice, zebu RTL, fogs RTL and full synth
        vs the release target (dotted). Right: efficiency = SPECint score per mm² of synth area;
        the dotted line is the target efficiency at the {ov.area_budget_mm2} mm² constraint.
      </p>
    </Card>
  );
}

// ---------------------------------------------------------------- P2/P3: benchmark trends

function PanelBench({ ov, mode, bench, setBench }: {
  ov: OverviewData; mode: "ratio" | "ipc"; bench: string; setBench: (b: string) => void;
}) {
  const setDrillVersion = useApp((s) => s.setDrillVersion);
  const [extra, setExtra] = useState<string[]>([]);
  const src = mode === "ratio" ? ov.benchmarks : ov.ipc;
  const models = ["gem5", "zebu", ...extra];
  const perModel = src[bench] ?? {};
  const yName = mode === "ratio" ? "ratio @1GHz" : "IPC";

  const option = {
    tooltip: { trigger: "axis" as const },
    legend: { textStyle: { color: "#94a3b8", fontSize: 10 }, top: 0 },
    grid: { left: 8, right: 16, top: 26, bottom: 8, containLabel: true },
    xAxis: { type: "category" as const, data: ov.versions, axisLabel: AXIS, boundaryGap: true },
    yAxis: { type: "value" as const, name: yName, nameTextStyle: AXIS,
             axisLabel: AXIS, splitLine: SPLIT, scale: true },
    series: models.map((m) => lineSeries(MODEL_LABEL[m] ?? m, m, perModel[m] ?? [])),
  };

  // per-release detail table (zebu = truth, gem5 gap vs zebu)
  const z = perModel.zebu ?? [];
  const g = perModel.gem5 ?? [];

  return (
    <Card
      title={mode === "ratio"
        ? "2 · SPECint benchmark performance trend"
        : "3 · Bring-up benchmark IPC trends"}
      right={
        <div className="flex flex-wrap items-center gap-1">
          {ov.benchmarks_names.map((b) => (
            <button key={b} onClick={() => setBench(b)}
              className={`rounded-full border px-1.5 py-0.5 text-[10px] ${
                b === bench ? "border-sky-400 bg-sky-500/15 text-sky-200"
                            : "border-slate-700 text-slate-500 hover:border-slate-500"}`}>
              {b.split(".")[1]}
            </button>
          ))}
          <span className="mx-1 text-slate-700">|</span>
          {["slice", "fogs"].map((m) => (
            <button key={m}
              onClick={() => setExtra((c) => c.includes(m) ? c.filter((x) => x !== m) : [...c, m])}
              className={`rounded-full border px-1.5 py-0.5 text-[10px] ${
                extra.includes(m) ? "border-current bg-slate-800/60" : "border-slate-700 text-slate-600"}`}
              style={extra.includes(m) ? { color: MODEL_STYLE[m].color } : undefined}>
              {m}
            </button>
          ))}
        </div>
      }>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
        <EChart option={option} height={260} onEvent={drillClick(ov.versions, setDrillVersion)} />
        <div className="max-h-[260px] overflow-auto">
          <Table head={["Release", "zebu", "Δ vs prev", "gem5 gap"]}>
            {ov.versions.map((v, i) => {
              const zi = z[i], gi = g[i], prev = i > 0 ? z[i - 1] : null;
              const d = zi != null && prev != null && prev !== 0 ? ((zi - prev) / prev) * 100 : null;
              const gap = zi != null && gi != null && zi !== 0 ? ((gi - zi) / zi) * 100 : null;
              return (
                <tr key={v} className="cursor-pointer hover:bg-slate-800/40"
                  onClick={() => setDrillVersion(v)}>
                  <td className="px-2 py-0.5 font-mono text-[11px] text-slate-300">{v}</td>
                  <td className="px-2 py-0.5 font-mono">{fmt(zi, mode === "ratio" ? 3 : 2)}</td>
                  <td className="px-2 py-0.5"><Delta pct={d} digits={1} /></td>
                  <td className="px-2 py-0.5 font-mono text-[11px] text-slate-500">
                    {gap == null ? "—" : `${gap >= 0 ? "+" : ""}${gap.toFixed(1)}%`}
                  </td>
                </tr>
              );
            })}
          </Table>
        </div>
      </div>
      <p className="mt-1 text-[10px] text-slate-600">
        gem5 dashed vs zebu solid (the emulation truth); slice/fogs are toggleable.
        The table lists each release's {yName}, its change vs the previous release, and the
        gem5-vs-zebu model gap.
      </p>
    </Card>
  );
}

// ---------------------------------------------------------------- P4: area stack

function PanelArea({ ov }: { ov: OverviewData }) {
  const setDrillVersion = useApp((s) => s.setDrillVersion);
  const ab = ov.area_breakdown;
  const option = {
    tooltip: {
      trigger: "axis" as const,
      axisPointer: { type: "shadow" as const },
      valueFormatter: (v: number) => `${fmt(v, 4)} mm²`,
    },
    legend: { textStyle: { color: "#94a3b8", fontSize: 10 }, top: 0 },
    grid: { left: 8, right: 16, top: 26, bottom: 8, containLabel: true },
    xAxis: { type: "category" as const, data: ov.versions, axisLabel: AXIS },
    yAxis: { type: "value" as const, name: "area mm²", nameTextStyle: AXIS,
             axisLabel: AXIS, splitLine: SPLIT },
    series: ab.categories.map((cat) => ({
      name: cat, type: "bar" as const, stack: "area", data: ab.values[cat] ?? [],
      itemStyle: { color: CAT_COLORS[cat] ?? "#94a3b8" },
      barWidth: "62%",
      markLine: cat === ab.categories[0]
        ? { silent: true, symbol: "none",
            lineStyle: { color: "#ef4444", type: "dashed" as const, width: 1.5 },
            label: { formatter: `${ov.area_budget_mm2} mm² target`, color: "#ef4444",
                     fontSize: 10, position: "insideEndTop" as const },
            data: [{ yAxis: ov.area_budget_mm2 }] }
        : undefined,
    })),
  };
  return (
    <Card title="4 · Synthesis area breakdown — cumulative across release tags"
      right={<span className="text-[10px] text-slate-600">
        Frontend = u_ifu · Backend = u_ex · Memblock = u_lsu · L2 top = u_l2 · Other = u_csr + u_clk
      </span>}>
      <EChart option={option} height={300} onEvent={drillClick(ov.versions, setDrillVersion)} />
    </Card>
  );
}

// ---------------------------------------------------------------- P5: timing

function PanelTiming({ ov }: { ov: OverviewData }) {
  const setDrillVersion = useApp((s) => s.setDrillVersion);
  const option = {
    tooltip: { trigger: "axis" as const },
    legend: { textStyle: { color: "#94a3b8", fontSize: 10 }, top: 0 },
    grid: { left: 8, right: 8, top: 26, bottom: 8, containLabel: true },
    xAxis: { type: "category" as const, data: ov.versions, axisLabel: AXIS, boundaryGap: true },
    yAxis: [
      { type: "value" as const, name: "WNS ns", nameTextStyle: AXIS, axisLabel: AXIS, splitLine: SPLIT },
      { type: "value" as const, name: "TNS ns", nameTextStyle: AXIS, axisLabel: AXIS,
        splitLine: { show: false } },
      { type: "value" as const, name: "NVE", nameTextStyle: AXIS, axisLabel: AXIS,
        splitLine: { show: false } },
    ],
    series: [
      { name: "WNS", type: "line" as const, yAxisIndex: 0, data: ov.timing.wns, symbolSize: 6,
        itemStyle: { color: "#f87171" }, lineStyle: { color: "#f87171", width: 2 },
        markLine: { silent: true, symbol: "none",
          lineStyle: { color: "#7f1d1d", type: "solid" as const, width: 1 },
          label: { show: false }, data: [{ yAxis: 0 }] } },
      { name: "TNS", type: "line" as const, yAxisIndex: 1, data: ov.timing.tns, symbolSize: 5,
        itemStyle: { color: "#fbbf24" }, lineStyle: { color: "#fbbf24", width: 2 } },
      { name: "NVE", type: "bar" as const, yAxisIndex: 2, data: ov.timing.nve,
        itemStyle: { color: "rgba(167,139,250,0.55)" }, barWidth: "45%" },
    ],
  };
  return (
    <Card title="5 · Synthesis timing metrics — closure progress across releases"
      right={<span className="text-[10px] text-slate-600">
        WNS/TNS lines (ns) · NVE violating-endpoint bars
      </span>}>
      <EChart option={option} height={280} onEvent={drillClick(ov.versions, setDrillVersion)} />
    </Card>
  );
}

// ---------------------------------------------------------------- P6: board grid

function MiniTile({ title, note, children }: {
  title: string; note?: string; children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-2">
      <div className="mb-1 flex items-baseline justify-between px-1">
        <span className="text-[11px] font-semibold text-slate-400">{title}</span>
        {note && <span className="text-[9px] text-slate-600">{note}</span>}
      </div>
      {children}
    </div>
  );
}

function miniOption(vals: (number | null)[], versions: string[], color: string,
                    extraSeries: Record<string, unknown>[] = [],
                    markLines: unknown[] = []) {
  return {
    tooltip: { trigger: "axis" as const },
    grid: { left: 4, right: 8, top: 8, bottom: 4, containLabel: true },
    xAxis: { type: "category" as const, data: versions, axisLabel: { ...AXIS, fontSize: 8 },
             boundaryGap: true },
    yAxis: { type: "value" as const, axisLabel: { ...AXIS, fontSize: 8 }, splitLine: SPLIT,
             scale: true },
    series: [
      { type: "line" as const, data: vals, symbolSize: 4,
        itemStyle: { color }, lineStyle: { color, width: 1.5 },
        markLine: markLines.length ? { silent: true, symbol: "none", data: markLines,
          label: { show: false } } : undefined },
      ...extraSeries,
    ],
  };
}

function PanelBoard({ ov }: { ov: OverviewData }) {
  const b = ov.board;
  const vs = ov.versions;
  return (
    <Card title="6 · PPA metrics board — synthesis health across releases"
      right={<span className="text-[10px] text-slate-600">
        derived from stored synth reports · utilization is a core/die proxy
      </span>}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <MiniTile title="Utilization (core/die proxy)" note="%">
          <EChart height={150} option={miniOption(
            b.map((r) => r.util_proxy == null ? null : +(r.util_proxy * 100).toFixed(1)),
            vs, "#60a5fa")}/>
        </MiniTile>
        <MiniTile title="Core vs total (die) area" note="mm²">
          <EChart height={150} option={{
            ...miniOption(b.map((r) => r.core_area_um2 == null ? null : +(r.core_area_um2 / 1e6).toFixed(4)), vs, "#34d399"),
            series: [
              { name: "core", type: "line" as const,
                data: b.map((r) => r.core_area_um2 == null ? null : +(r.core_area_um2 / 1e6).toFixed(4)),
                symbolSize: 4, itemStyle: { color: "#34d399" }, lineStyle: { color: "#34d399", width: 1.5 } },
              { name: "die", type: "line" as const,
                data: b.map((r) => r.die_area_um2 == null ? null : +(r.die_area_um2 / 1e6).toFixed(4)),
                symbolSize: 4, itemStyle: { color: "#94a3b8" },
                lineStyle: { color: "#94a3b8", width: 1.5, type: "dashed" as const } },
            ],
            tooltip: { trigger: "axis" as const },
          }}/>
        </MiniTile>
        <MiniTile title="Max logic levels" note="critical path">
          <EChart height={150} option={miniOption(
            b.map((r) => r.max_logic_levels), vs, "#f472b6", [],
            [{ yAxis: 25, lineStyle: { color: "#7f1d1d", type: "dashed" as const } }])}/>
        </MiniTile>
        <MiniTile title="Gated registers" note="clock-gating eff %">
          <EChart height={150} option={miniOption(
            b.map((r) => r.gated_pct), vs, "#34d399", [],
            [{ yAxis: 70, lineStyle: { color: "#7f1d1d", type: "dashed" as const } }])}/>
        </MiniTile>
        <MiniTile title="Congestion overflow" note="%">
          <div className="flex h-[150px] flex-col items-center justify-center gap-1 rounded bg-slate-900/40">
            <span className="font-mono text-2xl text-slate-700">—</span>
            <span className="text-[10px] text-slate-600">requires place/route data</span>
            <span className="text-[9px] text-slate-700">not available at the synth stage</span>
          </div>
        </MiniTile>
        <MiniTile title="Comb vs non-comb area" note="share of core">
          <EChart height={150} option={{
            ...miniOption(b.map((r) => r.comb_share == null ? null : +(r.comb_share * 100).toFixed(1)), vs, "#fbbf24"),
            series: [
              { name: "comb", type: "line" as const, stack: "s", areaStyle: { opacity: 0.25 },
                data: b.map((r) => r.comb_share == null ? null : +(r.comb_share * 100).toFixed(1)),
                symbolSize: 4, itemStyle: { color: "#fbbf24" }, lineStyle: { color: "#fbbf24", width: 1.5 } },
              { name: "non-comb", type: "line" as const, stack: "s", areaStyle: { opacity: 0.15 },
                data: b.map((r) => r.comb_share == null ? null : +((1 - r.comb_share) * 100).toFixed(1)),
                symbolSize: 4, itemStyle: { color: "#64748b" }, lineStyle: { color: "#64748b", width: 1.5 } },
            ],
            tooltip: { trigger: "axis" as const },
          }}/>
        </MiniTile>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- drill-down

function DrillPanel({ version }: { version: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["version-drill", version],
    queryFn: () => api.versionDrill(version),
  });
  const { setDrillVersion, setRun, setView } = useApp();

  return (
    <Card
      title={<>Drill-down: <span className="text-sky-300">{version}</span></>}
      right={
        <button onClick={() => setDrillVersion(null)}
          className="rounded border border-slate-700 px-2 py-0.5 text-[10px] text-slate-400 hover:border-red-400 hover:text-red-300">
          ✕ close
        </button>
      }>
      {isLoading && <Spinner />}
      {data && !data.found && <Empty msg={`No synthesis run for version ${version}`} />}
      {data?.found && <DrillBody d={data} onOpenRun={(view) => {
        if (data.run_id) { setRun(data.run_id); setView(view); }
      }} />}
    </Card>
  );
}

function DrillBody({ d, onOpenRun }: {
  d: VersionDrill; onOpenRun: (view: "area" | "power" | "timing") => void;
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-violet-500/30 bg-violet-500/5 p-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="font-mono font-semibold text-violet-200">{d.version}</span>
          <span className="text-slate-500">{d.date}</span>
          <span className="font-mono text-[10px] text-slate-500">sha {d.sha}</span>
          <span className="text-[10px] text-slate-600">run #{d.run_id}</span>
        </div>
        {d.change_note && (
          <p className="mt-1 text-xs text-violet-200/90">✎ {d.change_note}</p>
        )}
      </div>

      {!!d.events?.length && (
        <div>
          <h4 className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">
            Detected changes at this version
          </h4>
          <Table head={["Metric", "Δ", "z", "Method", "Severity", "Attribution", "Note", ""]}>
            {d.events.map((e) => (
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
                <td className="max-w-[260px] truncate px-2 py-1 text-slate-400" title={e.note}>{e.note}</td>
                <td className="px-2 py-1 text-right"><EventTraceBtn e={e} /></td>
              </tr>
            ))}
          </Table>
        </div>
      )}

      <div>
        <h4 className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">
          Modules — area / power vs previous version
        </h4>
        <Table head={["Module", "Area mm²", "Δ area", "Power mW", "Δ power", ""]}>
          {(d.modules ?? []).map((m) => (
            <tr key={m.scope_path} className="hover:bg-slate-800/40">
              <td className="px-2 py-1 font-mono text-[11px] text-slate-300">{shortModule(m.scope_path)}</td>
              <td className="px-2 py-1 font-mono">{fmt(m.area_um2, 4)}</td>
              <td className="px-2 py-1"><Delta pct={m.area_delta_pct == null ? null : m.area_delta_pct * 100} invert /></td>
              <td className="px-2 py-1 font-mono">{fmt(m.power_mw, 2)}</td>
              <td className="px-2 py-1"><Delta pct={m.power_delta_pct == null ? null : m.power_delta_pct * 100} invert /></td>
              <td className="px-2 py-1">
                <div className="flex items-center justify-end gap-1">
                  {d.run_id && <SourceBtn target={{ run_id: d.run_id, kind: "area", scope_path: m.scope_path }} />}
                  {d.run_id && <SourceBtn target={{ run_id: d.run_id, kind: "power", scope_path: m.scope_path }} />}
                  <button onClick={() => onOpenRun("area")}
                    className="rounded border border-slate-700 px-1 py-0.5 text-[10px] text-slate-500 hover:border-sky-400 hover:text-sky-300"
                    title="open this run in the Area explorer">⌂ area</button>
                  <button onClick={() => onOpenRun("power")}
                    className="rounded border border-slate-700 px-1 py-0.5 text-[10px] text-slate-500 hover:border-sky-400 hover:text-sky-300"
                    title="open this run in the Power explorer">⌂ pwr</button>
                </div>
              </td>
            </tr>
          ))}
        </Table>
      </div>

      <div>
        <h4 className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">
          Worst signals — trace-ready
        </h4>
        <Table head={["#", "Startpoint → Endpoint", "Module", "Slack ns", "Depth", ""]}>
          {(d.signals ?? []).map((s) => (
            <tr key={s.path_id} className="hover:bg-slate-800/40">
              <td className="px-2 py-1 font-mono text-slate-600">{s.path_id}</td>
              <td className="px-2 py-1 font-mono text-[10px] text-slate-300">
                {shortModule(s.startpoint)} → {shortModule(s.endpoint)}
              </td>
              <td className="px-2 py-1 font-mono text-[10px] text-slate-500">{shortModule(s.module)}</td>
              <td className={`px-2 py-1 font-mono ${s.slack_ns < 0 ? "text-red-400" : "text-slate-400"}`}>
                {fmt(s.slack_ns, 3)}
              </td>
              <td className="px-2 py-1 font-mono text-slate-500">{s.logic_depth}</td>
              <td className="px-2 py-1">
                <div className="flex items-center justify-end gap-1">
                  {d.run_id && <SourceBtn target={{ run_id: d.run_id, kind: "timing", path_id: s.path_id }} />}
                  <button onClick={() => onOpenRun("timing")}
                    className="rounded border border-slate-700 px-1 py-0.5 text-[10px] text-slate-500 hover:border-sky-400 hover:text-sky-300"
                    title="open this run in the Timing explorer">⌂ timing</button>
                </div>
              </td>
            </tr>
          ))}
        </Table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- multi-version compare

function ComparePanel({ versions }: { versions: string[] }) {
  const { data, isLoading } = useQuery({
    queryKey: ["version-compare", versions.join(",")],
    queryFn: () => api.versionCompare(versions),
  });
  const { clearOverviewVersions, setCompareIds, setView } = useApp();

  return (
    <Card
      title={<>Compare versions: {versions.map((v) =>
        <span key={v} className="ml-1 font-mono text-violet-300">{v}</span>)}</>}
      right={
        <div className="flex items-center gap-2">
          <button onClick={clearOverviewVersions}
            className="rounded border border-slate-700 px-2 py-0.5 text-[10px] text-slate-400 hover:border-red-400 hover:text-red-300">
            ✕ clear
          </button>
          {data && data.run_ids.length >= 2 && (
            <button onClick={() => { setCompareIds(data.run_ids); setView("compare"); }}
              className="rounded bg-violet-600 px-2.5 py-0.5 text-[11px] font-medium text-white hover:bg-violet-500">
              Open in Compare view →
            </button>
          )}
        </div>
      }>
      {isLoading && <Spinner />}
      {data && <CompareBody c={data} />}
    </Card>
  );
}

function CompareBody({ c }: { c: VersionCompare }) {
  return (
    <div className="space-y-4">
      <CompareAreaTable c={c} metric="area_mm2" label="Area mm²" />
      <CompareAreaTable c={c} metric="power_mw" label="Power mW" />
      <div>
        <h4 className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">
          Per-benchmark IPC (zebu) — deltas vs {c.versions[0]}
        </h4>
        <Table head={["Benchmark", ...c.versions.flatMap((v) => [v, "Δ"])]}>
          {c.benchmarks.map((b) => (
            <tr key={b.benchmark} className="hover:bg-slate-800/40">
              <td className="px-2 py-1 font-mono text-[11px] text-slate-300">{b.benchmark}</td>
              {b.ipc.map((v, i) => (
                <FragmentCell key={i} v={v} d={b.ipc_delta_pct[i]} digits={3} />
              ))}
            </tr>
          ))}
        </Table>
      </div>
      <div>
        <h4 className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">
          Signal slack ns — signals present in every selected version
        </h4>
        <Table head={["Signal", ...c.versions]}>
          {c.signals.map((s, i) => (
            <tr key={i} className="hover:bg-slate-800/40">
              <td className="px-2 py-1 font-mono text-[10px] text-slate-300">
                {shortModule(s.startpoint)} → {shortModule(s.endpoint)}
              </td>
              {s.slacks.map((v, j) => (
                <td key={j} className={`px-2 py-1 font-mono ${v < 0 ? "text-red-400" : "text-slate-400"}`}>
                  {fmt(v, 3)}
                </td>
              ))}
            </tr>
          ))}
        </Table>
        {!c.signals.length && <p className="text-xs text-slate-600">
          No signal is present in the top paths of every selected version.
        </p>}
      </div>
    </div>
  );
}

/** value + delta cells as a flat pair per version */
function FragmentCell({ v, d, digits }: { v: number | null; d: number | null; digits: number }) {
  return (
    <>
      <td className="px-2 py-1 font-mono">{fmt(v, digits)}</td>
      <td className="px-2 py-1"><Delta pct={d == null ? null : d * 100} /></td>
    </>
  );
}

function CompareAreaTable({ c, metric, label }: {
  c: VersionCompare; metric: "area_mm2" | "power_mw"; label: string;
}) {
  return (
    <div>
      <h4 className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">
        Module {label} — deltas vs {c.versions[0]}
      </h4>
      <Table head={["Module", ...c.versions.flatMap((v) => [v, "Δ"])]}>
        {c.modules.map((m) => {
          const vals = metric === "area_mm2" ? m.area_mm2 : m.power_mw;
          const deltas = metric === "area_mm2" ? m.area_delta_pct : m.power_delta_pct;
          return (
            <tr key={m.scope_path} className="hover:bg-slate-800/40">
              <td className="px-2 py-1 font-mono text-[11px] text-slate-300">{shortModule(m.scope_path)}</td>
              {vals.map((v, i) => (
                <FragmentCell key={i} v={v} d={deltas[i]} digits={metric === "area_mm2" ? 4 : 2} />
              ))}
            </tr>
          );
        })}
      </Table>
    </div>
  );
}

// ---------------------------------------------------------------- container

export function OverviewBoard() {
  const { data: ov, isLoading } = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const { drillVersion, overviewVersions } = useApp();
  const [bench, setBench] = useState("400.perlbench");

  if (isLoading) return <Card>loading…</Card>;
  if (!ov || ov.versions.length === 0) {
    return <Empty msg="No version series in this database — rebuild the demo (ppa demo) or ingest a versioned manifest" />;
  }
  const activeBench = ov.benchmarks_names.includes(bench) ? bench : ov.benchmarks_names[0];

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h3 className="text-base font-semibold text-slate-200">Release Overview Board</h3>
        <p className="text-xs text-slate-500">
          {ov.versions.length} releases · {ov.versions[0]} → {ov.versions[ov.versions.length - 1]} ·
          {" "}5 provenance series (gem5 / slice / zebu / fogs / full synth)
        </p>
      </div>
      <VersionStrip ov={ov} />
      <PanelGeomean ov={ov} />
      <PanelBench ov={ov} mode="ratio" bench={activeBench} setBench={setBench} />
      <PanelBench ov={ov} mode="ipc" bench={activeBench} setBench={setBench} />
      <PanelArea ov={ov} />
      <PanelTiming ov={ov} />
      <PanelBoard ov={ov} />
      {drillVersion && <DrillPanel version={drillVersion} />}
      {overviewVersions.length >= 2 && <ComparePanel versions={overviewVersions} />}
      {overviewVersions.length === 1 && (
        <p className="text-xs text-slate-600">Select at least one more version (☑ above) for the multi-version compare.</p>
      )}
    </div>
  );
}
