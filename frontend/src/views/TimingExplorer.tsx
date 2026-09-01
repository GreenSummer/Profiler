import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useApp } from "../store";
import { Card, Empty, Table, fmt, shortModule } from "../components/ui";
import { EChart, PALETTE } from "../components/EChart";
import { SourceBtn } from "../components/TraceDrawer";

export function TimingExplorer() {
  const runId = useApp((s) => s.runId);
  const searchQuery = useApp((s) => s.searchQuery);
  const setSearchQuery = useApp((s) => s.setSearchQuery);
  const { data, isLoading } = useQuery({
    queryKey: ["timing", runId],
    queryFn: () => api.timing(runId!),
    enabled: !!runId,
  });

  if (!runId) return <Empty />;
  if (isLoading || !data) return <Card>loading…</Card>;

  // signal filter: the global search query doubles as the timing filter
  const q = searchQuery.trim().toLowerCase();
  const paths = q
    ? data.paths.filter((p) =>
        p.startpoint.toLowerCase().includes(q) ||
        p.endpoint.toLowerCase().includes(q) ||
        p.module.toLowerCase().includes(q))
    : data.paths;

  const histOption = {
    tooltip: { trigger: "axis" as const },
    grid: { left: 8, right: 8, top: 24, bottom: 8, containLabel: true },
    xAxis: { type: "category" as const, data: data.histogram.map((h) => h.lo.toFixed(2)), name: "slack ns", nameTextStyle: { color: "#94a3b8" }, axisLabel: { color: "#94a3b8", fontSize: 9 } },
    yAxis: { type: "value" as const, name: "endpoints", axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
    series: [{
      type: "bar",
      data: data.histogram.map((h) => ({
        value: h.count,
        itemStyle: { color: h.hi <= 0 ? PALETTE.bad : PALETTE.neutral },
      })),
    }],
  };

  const boardOption = {
    tooltip: { trigger: "axis" as const },
    grid: { left: 8, right: 8, top: 24, bottom: 8, containLabel: true },
    xAxis: { type: "category" as const, data: data.leaderboard.map((l) => shortModule(l.module)), axisLabel: { color: "#94a3b8", rotate: 20, fontSize: 10 } },
    yAxis: { type: "value" as const, axisLabel: { color: "#94a3b8" }, splitLine: { lineStyle: { color: "#1e293b" } } },
    series: [{
      type: "bar",
      data: data.leaderboard.map((l) => l.top_paths),
      itemStyle: { color: (data.leaderboard[0] && l0Share(data.leaderboard[0].share) > 0.3) ? "#f87171" : PALETTE.neutral },
      label: { show: true, position: "top" as const, color: "#94a3b8" },
    }],
  };

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Timing Explorer</h2>
        <div className="flex gap-4 text-sm">
          <span>WNS <span className={`font-mono ${(data.wns_ns ?? 0) < 0 ? "text-red-400" : "text-emerald-400"}`}>{fmt(data.wns_ns, 3)} ns</span></span>
          <span>TNS <span className="font-mono">{fmt(data.tns_ns, 1)} ns</span></span>
          <span>NVE <span className="font-mono">{fmt(data.nve, 0)}</span></span>
          <span>Fmax <span className="font-mono">{fmt(data.fmax_mhz, 0)} MHz</span></span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Card title="Setup slack histogram — shape tells you: one broken path vs a systemic wall">
          <EChart option={histOption} height={260} />
        </Card>
        <Card title="Critical-module leaderboard — who owns the top paths">
          <EChart option={boardOption} height={260} />
          <p className="text-[10px] text-slate-600">
            A module staying #1 across many runs is a structural problem, not a P&R problem.
          </p>
        </Card>
      </div>

      <Card title="Path group summary">
        <Table head={["Group", "WNS ns", "TNS ns", "Violating", "Paths shown"]}>
          {data.groups.map((g) => (
            <tr key={g.name}>
              <td className="px-2 py-1 font-medium">{g.name}</td>
              <td className={`px-2 py-1 font-mono ${g.wns_ns < 0 ? "text-red-400" : "text-emerald-400"}`}>{fmt(g.wns_ns, 3)}</td>
              <td className="px-2 py-1 font-mono">{fmt(g.tns_ns, 1)}</td>
              <td className="px-2 py-1 font-mono">{g.nve}</td>
              <td className="px-2 py-1 font-mono text-slate-400">{g.paths}</td>
            </tr>
          ))}
        </Table>
      </Card>

      <Card
        title={`Worst setup paths${q ? ` — filtered by “${searchQuery.trim()}”` : ""}`}
        right={
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="filter signals…"
            className="rounded border border-slate-700 bg-slate-800 px-2 py-0.5 text-[11px] text-slate-200 placeholder:text-slate-600 focus:border-sky-500/60 focus:outline-none"
          />
        }
      >
        {paths.length === 0 ? (
          <p className="py-6 text-center text-xs text-slate-500">
            no paths match “{searchQuery.trim()}” in this run — try the global search for a
            slack history across versions
          </p>
        ) : (
          <Table head={["#", "Startpoint", "Endpoint", "Group", "Slack ns", "Logic depth", "Module", ""]}
          >
            {paths.slice(0, 15).map((p) => (
              <tr key={p.path_id} className={p.slack_ns < 0 ? "bg-red-500/5" : ""}>
                <td className="px-2 py-1 text-slate-500">{p.path_id}</td>
                <td className="px-2 py-1 font-mono text-[10px] text-slate-400">{p.startpoint}</td>
                <td className="px-2 py-1 font-mono text-[10px] text-slate-400">{p.endpoint}</td>
                <td className="px-2 py-1">{p.group}</td>
                <td className={`px-2 py-1 font-mono ${p.slack_ns < 0 ? "text-red-400" : ""}`}>{fmt(p.slack_ns, 3)}</td>
                <td className={`px-2 py-1 font-mono ${p.logic_depth > 25 ? "text-yellow-400" : ""}`}>{p.logic_depth}</td>
                <td className="px-2 py-1">{shortModule(p.module)}</td>
                <td className="px-2 py-1 text-right">
                  <SourceBtn target={{ run_id: runId, kind: "timing", path_id: p.path_id }} />
                </td>
              </tr>
            ))}
          </Table>
        )}
        <p className="mt-2 text-[10px] text-slate-600">
          Logic depth &gt; 25 highlighted: long combinational chains are usually a µarch structure issue (fewer, wider stages beat pipelining fixes at synthesis).
        </p>
      </Card>
    </div>
  );
}

function l0Share(s: number) { return s; }
