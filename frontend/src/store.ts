import { create } from "zustand";

export type ViewId =
  | "run-explorer" | "scorecard" | "compare" | "design-space" | "area"
  | "power" | "timing" | "performance" | "hotspot" | "findings" | "ingest";

interface AppState {
  view: ViewId;
  runId: number | null;          // selected run (global selection context)
  baselineRunId: number | null;  // reference for every delta
  compareIds: number[];          // comparison tray
  chatOpen: boolean;
  chatPrefill: string | null;    // question injected into the chat panel (e.g. from Findings)
  setView: (v: ViewId) => void;
  setRun: (id: number | null) => void;
  setBaseline: (id: number) => void;
  toggleCompare: (id: number) => void;
  clearCompare: () => void;
  setChatOpen: (open: boolean) => void;
  setChatPrefill: (q: string | null) => void;
  applyProposal: (view: string, runId?: number, runIds?: number[]) => void;
}

function readUrl(): Partial<AppState> {
  const p = new URLSearchParams(location.hash.slice(1));
  const out: Partial<AppState> = {};
  if (p.get("view")) out.view = p.get("view") as ViewId;
  if (p.get("run")) out.runId = Number(p.get("run"));
  if (p.get("baseline")) out.baselineRunId = Number(p.get("baseline"));
  if (p.get("compare")) out.compareIds = p.get("compare")!.split(",").map(Number).filter(Boolean);
  return out;
}

function writeUrl(s: AppState) {
  const p = new URLSearchParams();
  p.set("view", s.view);
  if (s.runId) p.set("run", String(s.runId));
  if (s.baselineRunId) p.set("baseline", String(s.baselineRunId));
  if (s.compareIds.length) p.set("compare", s.compareIds.join(","));
  history.replaceState(null, "", `#${p.toString()}`);
}

const initial = readUrl();

export const useApp = create<AppState>((set, get) => ({
  view: initial.view ?? "run-explorer",
  runId: initial.runId ?? null,
  baselineRunId: initial.baselineRunId ?? null,
  compareIds: initial.compareIds ?? [],
  chatOpen: false,
  chatPrefill: null,
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
  setChatOpen: (chatOpen) => set({ chatOpen }),
  setChatPrefill: (chatPrefill) => set({ chatPrefill }),
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
  };
}
