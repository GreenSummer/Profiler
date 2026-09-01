import { create } from "zustand";

export type ViewId =
  | "timeline" | "run-explorer" | "scorecard" | "compare" | "design-space"
  | "correlations" | "area" | "power" | "timing" | "performance" | "hotspot"
  | "findings" | "ingest";

/** One plotted value's raw-report provenance target (trace drawer). */
export interface TraceTarget {
  run_id: number;
  kind: string;           // area | power | timing | perf | raw report kind
  scope_path?: string;    // area / power
  path_id?: number;       // timing
  benchmark?: string;     // perf
  line?: number;          // raw report kind (search text hit)
}

interface AppState {
  view: ViewId;
  runId: number | null;          // selected run (global selection context)
  baselineRunId: number | null;  // reference for every delta
  compareIds: number[];          // comparison tray (also the version pair)
  chatOpen: boolean;
  chatPrefill: string | null;    // question injected into the chat panel (e.g. from Findings)
  searchQuery: string;           // global search / timing signal filter
  trace: TraceTarget | null;     // raw-data trace drawer
  drillVersion: string | null;   // release-board drill-down (e.g. "v0.5")
  overviewVersions: string[];    // release-board multi-version compare tray
  setView: (v: ViewId) => void;
  setRun: (id: number | null) => void;
  setBaseline: (id: number) => void;
  toggleCompare: (id: number) => void;
  clearCompare: () => void;
  setCompareIds: (ids: number[]) => void;
  /** Jump to Compare with exactly the two runs of a version transition. */
  setVersionPair: (fromId: number, toId: number) => void;
  setChatOpen: (open: boolean) => void;
  setChatPrefill: (q: string | null) => void;
  setSearchQuery: (q: string) => void;
  openTrace: (t: TraceTarget) => void;
  closeTrace: () => void;
  /** Open (or clear) the release-board drill-down for a version. */
  setDrillVersion: (v: string | null) => void;
  toggleOverviewVersion: (v: string) => void;
  clearOverviewVersions: () => void;
  applyProposal: (view: string, runId?: number, runIds?: number[]) => void;
}

function readUrl(): Partial<AppState> {
  const p = new URLSearchParams(location.hash.slice(1));
  const out: Partial<AppState> = {};
  if (p.get("view")) out.view = p.get("view") as ViewId;
  if (p.get("run")) out.runId = Number(p.get("run"));
  if (p.get("baseline")) out.baselineRunId = Number(p.get("baseline"));
  if (p.get("compare")) out.compareIds = p.get("compare")!.split(",").map(Number).filter(Boolean);
  if (p.get("q")) out.searchQuery = p.get("q")!;
  if (p.get("drill")) out.drillVersion = p.get("drill");
  if (p.get("ov")) out.overviewVersions = p.get("ov")!.split(",").filter(Boolean);
  const t = p.get("trace");
  if (t) {
    const [rid, kind] = t.split(":");
    if (rid && kind) {
      const ref = p.get("tref") ?? "";
      const target: TraceTarget = { run_id: Number(rid), kind };
      if (kind === "timing") target.path_id = Number(ref);
      else if (kind === "perf") target.benchmark = ref;
      else if (kind === "area" || kind === "power") target.scope_path = ref;
      else target.line = Number(ref);
      if (ref) out.trace = target;
    }
  }
  return out;
}

function writeUrl(s: AppState) {
  const p = new URLSearchParams();
  p.set("view", s.view);
  if (s.runId) p.set("run", String(s.runId));
  if (s.baselineRunId) p.set("baseline", String(s.baselineRunId));
  if (s.compareIds.length) p.set("compare", s.compareIds.join(","));
  if (s.searchQuery) p.set("q", s.searchQuery);
  if (s.drillVersion) p.set("drill", s.drillVersion);
  if (s.overviewVersions.length) p.set("ov", s.overviewVersions.join(","));
  if (s.trace) {
    p.set("trace", `${s.trace.run_id}:${s.trace.kind}`);
    const ref = s.trace.kind === "timing" ? String(s.trace.path_id ?? "")
      : s.trace.kind === "perf" ? (s.trace.benchmark ?? "")
      : s.trace.kind === "area" || s.trace.kind === "power" ? (s.trace.scope_path ?? "")
      : String(s.trace.line ?? "");
    if (ref) p.set("tref", ref);
  }
  history.replaceState(null, "", `#${p.toString()}`);
}

const initial = readUrl();

export const useApp = create<AppState>((set, get) => ({
  view: initial.view ?? "timeline",
  runId: initial.runId ?? null,
  baselineRunId: initial.baselineRunId ?? null,
  compareIds: initial.compareIds ?? [],
  chatOpen: false,
  chatPrefill: null,
  searchQuery: initial.searchQuery ?? "",
  trace: initial.trace ?? null,
  drillVersion: initial.drillVersion ?? null,
  overviewVersions: initial.overviewVersions ?? [],
  setView: (view) => { set({ view }); writeUrl(get()); },
  setRun: (runId) => { set({ runId }); writeUrl(get()); },
  setBaseline: (baselineRunId) => { set({ baselineRunId }); writeUrl(get()); },
  toggleCompare: (id) => {
    const cur = get().compareIds;
    const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id].slice(-4);
    set({ compareIds: next });
    writeUrl(get());
  },
  clearCompare: () => { set({ compareIds: [] }); writeUrl(get()); },
  setCompareIds: (compareIds) => { set({ compareIds }); writeUrl(get()); },
  setVersionPair: (fromId, toId) => {
    set({ compareIds: [fromId, toId], runId: toId, view: "compare" });
    writeUrl(get());
  },
  setChatOpen: (chatOpen) => set({ chatOpen }),
  setChatPrefill: (chatPrefill) => set({ chatPrefill }),
  setSearchQuery: (searchQuery) => { set({ searchQuery }); writeUrl(get()); },
  openTrace: (trace) => { set({ trace }); writeUrl(get()); },
  closeTrace: () => { set({ trace: null }); writeUrl(get()); },
  setDrillVersion: (drillVersion) => {
    // the drill-down panel lives on the Runs page
    set({ drillVersion, view: drillVersion ? "run-explorer" : get().view });
    writeUrl(get());
  },
  toggleOverviewVersion: (v) => {
    const cur = get().overviewVersions;
    const next = cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v].slice(-4);
    set({ overviewVersions: next });
    writeUrl(get());
  },
  clearOverviewVersions: () => { set({ overviewVersions: [] }); writeUrl(get()); },
  applyProposal: (view, runId, runIds) => {
    set({
      view: (view as ViewId) ?? get().view,
      runId: runId ?? get().runId,
      compareIds: runIds ?? get().compareIds,
    });
    writeUrl(get());
  },
}));

/** Context passed to the AI so "why is this worse?" resolves without restating. */
export function aiContext() {
  const s = useApp.getState();
  return {
    view: s.view,
    run_id: s.runId,
    baseline_run_id: s.baselineRunId,
    compare_ids: s.compareIds,
    search_query: s.searchQuery || undefined,
  };
}
