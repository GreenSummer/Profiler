import type {
  AreaRowX, ChatResult, Comparison, DesignSpacePoint, Finding, HotspotRow,
  PerfExplorerX, PowerRowX, RunSummary, Scorecard, TimingExplorerX,
} from "./types";
import type { AiStatus } from "./ai/badge";

const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export const api = {
  runs: () => get<RunSummary[]>("/runs"),
  scorecard: (runId: number) => get<Scorecard>(`/scorecard/${runId}`),
  compare: (runIds: number[]) => get<Comparison>(`/compare?run_ids=${runIds.join(",")}`),
  designSpace: (x: string, y: string) => get<{ x_metric: string; y_metric: string; points: DesignSpacePoint[] }>(`/design-space?x=${x}&y=${y}`),
  area: (runId: number) => get<{ run_id: number; total_um2: number; rows: AreaRowX[] }>(`/area/${runId}`),
  power: (runId: number) => get<{ run_id: number; total_mw: number; rows: PowerRowX[]; clock_power_share: number | null; clock_gating_eff: number | null; toggle_rate: number | null }>(`/power/${runId}`),
  timing: (runId: number) => get<TimingExplorerX>(`/timing/${runId}`),
  perf: (runId: number) => get<PerfExplorerX>(`/perf/${runId}`),
  hotspot: (runId: number) => get<{ run_id: number; rows: HotspotRow[] }>(`/hotspot/${runId}`),
  findings: (params: Record<string, string | number | undefined> = {}) => {
    const q = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== "")
      .map(([k, v]) => `${k}=${v}`).join("&");
    return get<Finding[]>(`/findings${q ? "?" + q : ""}`);
  },
  ingestStatus: () => get<{ run_id: number; run_label: string; kind: string; file: string; sha256: string; parser_version: string; status: string; log: string }[]>("/ingest-status"),
  rules: () => get<{ id: string; category: string; severity: string; title: string; params?: Record<string, number> }[]>("/rules"),
  aiStatus: () => get<AiStatus>("/ai/status"),
  aiChat: (messages: { role: string; content: string }[], runContext: unknown) =>
    post<ChatResult>("/ai/chat", { messages, run_context: runContext }),
  patchFinding: (id: number, patch: { status?: string }) =>
    fetch(`${BASE}/findings/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) }),
  findingFeedback: (id: number, verdict: "up" | "down", comment = "") =>
    post(`/findings/${id}/feedback`, { verdict, comment }),
};
