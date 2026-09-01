import { useQuery } from "@tanstack/react-query";
import { useApp, aiContext, type ViewId } from "./store";
import { api } from "./api";
import { RunExplorer } from "./views/RunExplorer";
import { Scorecard } from "./views/Scorecard";
import { Compare } from "./views/Compare";
import { DesignSpace } from "./views/DesignSpace";
import { VersionTimeline } from "./views/VersionTimeline";
import { Correlations } from "./views/Correlations";
import { AreaExplorer } from "./views/AreaExplorer";
import { PowerExplorer } from "./views/PowerExplorer";
import { TimingExplorer } from "./views/TimingExplorer";
import { PerfExplorer } from "./views/PerfExplorer";
import { Hotspot } from "./views/Hotspot";
import { FindingsView } from "./views/FindingsView";
import { IngestAdmin } from "./views/IngestAdmin";
import { ChatPanel } from "./ai/ChatPanel";
import { aiBadge } from "./ai/badge";
import { GlobalSearch } from "./components/GlobalSearch";
import { TraceDrawer } from "./components/TraceDrawer";

const NAV: { id: ViewId; label: string; group: string }[] = [
  { id: "timeline", label: "Version Timeline", group: "Overview" },
  { id: "run-explorer", label: "Runs", group: "Overview" },
  { id: "scorecard", label: "Scorecard", group: "Overview" },
  { id: "compare", label: "Compare", group: "Overview" },
  { id: "design-space", label: "Design Space", group: "Insight" },
  { id: "correlations", label: "Correlations", group: "Insight" },
  { id: "hotspot", label: "Hotspot Matrix", group: "Insight" },
  { id: "area", label: "Area", group: "Domain" },
  { id: "power", label: "Power", group: "Domain" },
  { id: "timing", label: "Timing", group: "Domain" },
  { id: "performance", label: "Performance", group: "Domain" },
  { id: "findings", label: "Diagnosis", group: "AI" },
  { id: "ingest", label: "Ingest & Admin", group: "AI" },
];

function TopBar() {
  const { data: runs } = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  const { runId, baselineRunId, compareIds, setRun, setBaseline, view } = useApp();
  const { data: aiStatus } = useQuery({ queryKey: ["ai-status"], queryFn: api.aiStatus });
  const badge = aiBadge(aiStatus);

  const runsSorted = [...(runs ?? [])].sort((a, b) => a.run_id - b.run_id);
  return (
    <header className="flex items-center gap-3 border-b border-slate-800 bg-slate-900/80 px-4 py-2 backdrop-blur">
      <div className="flex items-center gap-2">
        <div className="flex h-7 w-7 items-center justify-center rounded bg-gradient-to-br from-sky-500 to-violet-600 font-bold text-white text-xs">PPA</div>
        <span className="font-semibold text-slate-200">PPA-Profiler</span>
      </div>
      <span className="text-xs text-slate-600 hidden md:inline">{NAV.find((n) => n.id === view)?.group}</span>
      <div className="ml-4 flex items-center gap-2 text-xs">
        <label className="text-slate-500">Run</label>
        <select
          className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-slate-200"
          value={runId ?? ""}
          onChange={(e) => setRun(Number(e.target.value) || null)}
        >
          <option value="">—</option>
          {runsSorted.map((r) => <option key={r.run_id} value={r.run_id}>{r.label}</option>)}
        </select>
        <label className="text-slate-500">Baseline</label>
        <select
          className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-slate-200"
          value={baselineRunId ?? ""}
          onChange={(e) => setBaseline(Number(e.target.value))}
        >
          <option value="">—</option>
          {runsSorted.map((r) => <option key={r.run_id} value={r.run_id}>{r.label}</option>)}
        </select>
        {compareIds.length > 0 && (
          <span className="rounded bg-violet-500/20 px-2 py-0.5 text-violet-300">
            compare: {compareIds.length} runs
          </span>
        )}
      </div>
      <div className="ml-2 flex items-center gap-3">
        <GlobalSearch />
      </div>
      <div className="ml-auto flex items-center gap-3">
        <span
          title={badge.title}
          className={`rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${badge.cls}`}
        >
          {badge.text}
        </span>
      </div>
    </header>
  );
}

function Sidebar() {
  const { view, setView, chatOpen, setChatOpen } = useApp();
  const groups = [...new Set(NAV.map((n) => n.group))];
  return (
    <nav className="flex w-44 shrink-0 flex-col border-r border-slate-800 bg-slate-900/40 py-3">
      {groups.map((g) => (
        <div key={g} className="mb-3">
          <div className="px-4 pb-1 text-[10px] font-semibold uppercase tracking-widest text-slate-600">{g}</div>
          {NAV.filter((n) => n.group === g).map((n) => (
            <button
              key={n.id}
              onClick={() => setView(n.id)}
              className={`block w-full px-4 py-1.5 text-left text-sm transition-colors ${
                view === n.id ? "border-l-2 border-sky-400 bg-sky-500/10 text-sky-300" : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
              }`}
            >
              {n.label}
            </button>
          ))}
        </div>
      ))}
      <button
        onClick={() => setChatOpen(!chatOpen)}
        className={`mt-auto mx-3 rounded border px-3 py-2 text-sm font-medium transition-colors ${
          chatOpen ? "border-violet-500 bg-violet-500/20 text-violet-200" : "border-slate-700 bg-slate-800 text-slate-300 hover:border-violet-500/50"
        }`}
      >
        ✦ AI Assistant
      </button>
    </nav>
  );
}

function CurrentView() {
  const view = useApp((s) => s.view);
  switch (view) {
    case "timeline": return <VersionTimeline />;
    case "scorecard": return <Scorecard />;
    case "compare": return <Compare />;
    case "design-space": return <DesignSpace />;
    case "correlations": return <Correlations />;
    case "area": return <AreaExplorer />;
    case "power": return <PowerExplorer />;
    case "timing": return <TimingExplorer />;
    case "performance": return <PerfExplorer />;
    case "hotspot": return <Hotspot />;
    case "findings": return <FindingsView />;
    case "ingest": return <IngestAdmin />;
    default: return <RunExplorer />;
  }
}

export default function App() {
  const chatOpen = useApp((s) => s.chatOpen);
  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-y-auto p-4">
          <CurrentView />
        </main>
        {chatOpen && (
          <aside className="w-[400px] shrink-0 border-l border-slate-800">
            <ChatPanel context={() => aiContext()} />
          </aside>
        )}
      </div>
      <TraceDrawer />
    </div>
  );
}
