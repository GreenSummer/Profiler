import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "../api";
import { useApp, type TraceTarget } from "../store";
import { fmt } from "./ui";
import type { TraceTargetInfo } from "../types";

const KIND_LABEL: Record<string, string> = {
  area: "area report", power: "power report", timing: "timing report",
  perf: "SPECint report", rtla_area: "RTLA area report",
  rtla_timing: "RTLA timing report", rtla_qor: "RTLA QoR report",
  primepower: "PrimePower report", specint: "SPECint report",
};

/** Human description of what is being traced, from the API's target block. */
function targetDesc(t: TraceTargetInfo): string {
  switch (t.kind) {
    case "area":
      return `${t.scope_path} — ${fmt(t.value, 1)} µm²`;
    case "power":
      return `${t.scope_path} — ${fmt(t.value, 3)} mW`;
    case "timing":
      return `path ${t.path_id}: ${t.startpoint} → ${t.endpoint} (slack ${fmt(t.slack_ns, 3)} ns)`;
    case "perf":
      return `${t.benchmark} — IPC ${fmt(t.ipc, 3)}`;
    default:
      return t.line !== undefined ? `report line ${t.line}` : "";
  }
}

export function TraceDrawer() {
  const trace = useApp((s) => s.trace);
  const closeTrace = useApp((s) => s.closeTrace);
  const { data, isLoading, error } = useQuery({
    queryKey: ["trace", trace?.run_id, trace?.kind, trace?.scope_path,
      trace?.path_id, trace?.benchmark, trace?.line],
    queryFn: () => api.trace(trace!),
    enabled: !!trace,
  });

  useEffect(() => {
    if (!trace) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeTrace(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [trace, closeTrace]);

  if (!trace) return null;
  const report = data?.report;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-slate-950/60" onClick={closeTrace} />
      <div className="relative z-10 flex h-full w-[620px] max-w-[92vw] flex-col border-l border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
          <span className="text-sm font-semibold text-sky-300">⌖ source trace</span>
          <div className="flex items-center gap-2 text-[10px] text-slate-500">
            <span className="font-mono">run #{trace.run_id}</span>
            <button onClick={closeTrace} className="rounded border border-slate-700 px-1.5 py-0.5 text-slate-400 hover:border-red-400 hover:text-red-300">
              esc ✕
            </button>
          </div>
        </div>

        <div className="space-y-2 border-b border-slate-800 px-4 py-2 text-xs">
          {isLoading && <p className="text-slate-500">resolving provenance…</p>}
          {error && <p className="text-red-400">trace failed: {error instanceof Error ? error.message : String(error)}</p>}
          {data?.target && (
            <p className="font-mono text-[11px] leading-relaxed text-slate-300">{targetDesc(data.target)}</p>
          )}
          {report && (
            <p className="flex flex-wrap gap-x-3 text-[10px] text-slate-500">
              <span className="font-mono text-slate-400">{report.file.split("/").pop()}</span>
              <span>sha256 {report.sha256}</span>
              <span>parser {report.parser_version}</span>
              <span className={report.parse_status === "ok" ? "text-emerald-500" : "text-yellow-500"}>{report.parse_status}</span>
              <span>{KIND_LABEL[report.kind] ?? report.kind}</span>
            </p>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-auto p-3">
          {data?.lines && (
            <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-2 font-mono text-[11px] leading-relaxed">
              {data.lines.map((l) => (
                <div key={l.no} className={`flex gap-3 whitespace-pre rounded px-1 ${
                  l.hit ? "bg-sky-500/10 text-sky-200" : "text-slate-400"
                }`}>
                  <span className={`w-10 shrink-0 select-none text-right ${l.hit ? "text-sky-400" : "text-slate-600"}`}>{l.no}</span>
                  <span className="min-w-0 flex-1">{l.text}</span>
                </div>
              ))}
            </div>
          )}
          <p className="mt-2 text-[10px] text-slate-600">
            Highlighted lines are the exact provenance of the plotted value (stored at ingest,
            keyed by line number in the original report). sha256 + parser version guarantee the
            text matches what was parsed.
          </p>
        </div>
      </div>
    </div>
  );
}

/** The "⌖ src" affordance: opens the trace drawer for one value. */
export function SourceBtn({ target, title }: { target: TraceTarget; title?: string }) {
  const openTrace = useApp((s) => s.openTrace);
  return (
    <button
      onClick={(e) => { e.stopPropagation(); openTrace(target); }}
      title={title ?? "trace to raw report source lines"}
      className="rounded border border-slate-700 px-1 py-0.5 text-[10px] leading-none text-slate-500 hover:border-sky-400 hover:text-sky-300"
    >
      ⌖ src
    </button>
  );
}

/** Trace the worst setup path of a run (WNS change events have no path_id). */
export function WorstPathSourceBtn({ runId }: { runId: number }) {
  const { data } = useQuery({
    queryKey: ["timing", runId],
    queryFn: () => api.timing(runId),
    enabled: !!runId,
  });
  const p = data?.paths?.[0]; // sorted by slack: index 0 = worst
  if (!p) return <span className="text-slate-700">—</span>;
  return <SourceBtn target={{ run_id: runId, kind: "timing", path_id: p.path_id }} />;
}
