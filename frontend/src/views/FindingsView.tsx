import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import { Card, Empty, SevBadge, fmt, shortModule } from "../components/ui";
import type { Finding } from "../types";

const CATEGORIES = ["", "timing", "area", "power", "performance", "cross_domain", "data_quality"];
const STATUSES = ["open", "acknowledged", "fixed", "wont_fix"];

const STATUS_STYLE: Record<string, string> = {
  open: "text-red-300",
  acknowledged: "text-yellow-300",
  fixed: "text-emerald-300",
  wont_fix: "text-slate-500",
};

function Evidence({ ev }: { ev: Record<string, unknown> }) {
  const entries = Object.entries(ev ?? {}).slice(0, 8);
  if (!entries.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {entries.map(([k, v]) => (
        <span key={k} className="rounded bg-slate-800/80 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
          {k}: {typeof v === "number" ? fmt(v, 3) : String(v)}
        </span>
      ))}
    </div>
  );
}

function FindingCard({ f }: { f: Finding }) {
  const qc = useQueryClient();
  const setChatOpen = useApp((s) => s.setChatOpen);
  const setChatPrefill = useApp((s) => s.setChatPrefill);
  const [voted, setVoted] = useState<"up" | "down" | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["findings"] });
    qc.invalidateQueries({ queryKey: ["runs"] });
    qc.invalidateQueries({ queryKey: ["scorecard"] });
  };

  const setStatus = async (status: string) => {
    setBusy(true);
    try {
      await api.patchFinding(f.id, { status });
      refresh();
    } finally {
      setBusy(false);
    }
  };

  const vote = async (verdict: "up" | "down") => {
    if (voted) return;
    setVoted(verdict);
    await api.findingFeedback(f.id, verdict);
  };

  const askAi = () => {
    setChatPrefill(
      `Explain the finding "${f.title}" (rule ${f.rule_id}, run ${f.run_label || f.run_id})` +
      (f.scope_path ? ` on module ${shortModule(f.scope_path)}` : "") +
      ": what is the likely root cause and what should I change?",
    );
    setChatOpen(true);
  };

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="flex items-start gap-2">
        <SevBadge severity={f.severity} />
        <div className="min-w-0 flex-1">
          <div className="text-sm text-slate-200">{f.title}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] uppercase tracking-wide text-slate-500">
            <span className="rounded bg-slate-800 px-1 py-0.5 font-mono normal-case">{f.rule_id}</span>
            <span>{f.category}</span>
            {f.scope_path && <span>· {shortModule(f.scope_path)}</span>}
            <span>· run {f.run_label || f.run_id}</span>
            <span>· <b className={`font-semibold ${STATUS_STYLE[f.status] ?? ""}`}>{f.status}</b></span>
          </div>
          <Evidence ev={f.evidence} />
          {f.ai_explanation && (
            <p className="mt-1.5 rounded border border-violet-500/30 bg-violet-500/5 px-2 py-1 text-xs text-violet-300">
              AI: {f.ai_explanation}
            </p>
          )}
          {f.ai_proposal && (
            <p className="mt-1 text-xs text-violet-400/80">Proposal: {f.ai_proposal}</p>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <div className="flex gap-1">
            <button disabled={busy} onClick={() => setStatus("acknowledged")}
              className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400 hover:border-yellow-500/50 hover:text-yellow-300 disabled:opacity-40">
              ack
            </button>
            <button disabled={busy} onClick={() => setStatus("fixed")}
              className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400 hover:border-emerald-500/50 hover:text-emerald-300 disabled:opacity-40">
              fixed
            </button>
            <button disabled={busy} onClick={() => setStatus("wont_fix")}
              className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400 hover:border-slate-500 hover:text-slate-300 disabled:opacity-40">
              won't fix
            </button>
          </div>
          <div className="flex gap-1">
            <button onClick={() => vote("up")} title="helpful rule — keep it"
              className={`rounded border px-1.5 py-0.5 text-[10px] ${
                voted === "up" ? "border-emerald-500 text-emerald-300" : "border-slate-700 text-slate-500 hover:text-emerald-300"
              }`}>
              {voted === "up" ? "✓" : "👍"}
            </button>
            <button onClick={() => vote("down")} title="noise — threshold needs tuning"
              className={`rounded border px-1.5 py-0.5 text-[10px] ${
                voted === "down" ? "border-red-500 text-red-300" : "border-slate-700 text-slate-500 hover:text-red-300"
              }`}>
              {voted === "down" ? "✓" : "👎"}
            </button>
            <button onClick={askAi}
              className="rounded border border-violet-500/50 bg-violet-500/10 px-1.5 py-0.5 text-[10px] text-violet-300 hover:bg-violet-500/20">
              ✦ ask AI
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function FindingsView() {
  const runId = useApp((s) => s.runId);
  const [scope, setScope] = useState<"current" | "all">("current");
  const [severity, setSeverity] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("open");

  const { data, isLoading } = useQuery({
    queryKey: ["findings", scope, runId, severity, category, status],
    queryFn: () => api.findings({
      run_id: scope === "current" && runId ? runId : undefined,
      severity: severity || undefined,
      category: category || undefined,
      status: status || undefined,
    }),
  });

  const findings = data ?? [];
  const counts = findings.reduce<Record<string, number>>((acc, f) => {
    acc[f.severity] = (acc[f.severity] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Diagnosis — rule engine findings</h2>
        <div className="flex flex-wrap gap-2 text-xs">
          <select value={scope} onChange={(e) => setScope(e.target.value as "current" | "all")}
            className="rounded border border-slate-700 bg-slate-800 px-2 py-1">
            <option value="current">scope: current run</option>
            <option value="all">scope: all runs</option>
          </select>
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}
            className="rounded border border-slate-700 bg-slate-800 px-2 py-1">
            <option value="">all severities</option>
            {["critical", "high", "medium", "low", "info"].map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={category} onChange={(e) => setCategory(e.target.value)}
            className="rounded border border-slate-700 bg-slate-800 px-2 py-1">
            <option value="">all categories</option>
            {CATEGORIES.filter(Boolean).map((c) => <option key={c} value={c}>{c.replace("_", " ")}</option>)}
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)}
            className="rounded border border-slate-700 bg-slate-800 px-2 py-1">
            {STATUSES.map((s) => <option key={s} value={s}>{s === "open" ? "status: open" : s}</option>)}
          </select>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        <span className="text-slate-500">{findings.length} findings</span>
        {["critical", "high", "medium", "low", "info"].map((s) =>
          counts[s] ? <span key={s}><SevBadge severity={s} /> × {counts[s]}</span> : null,
        )}
      </div>

      {isLoading ? (
        <Card>loading…</Card>
      ) : findings.length === 0 ? (
        <Empty msg="No findings match the filters — either the design is clean or the filters are too narrow." />
      ) : (
        <div className="space-y-2">
          {findings.map((f) => <FindingCard key={f.id} f={f} />)}
        </div>
      )}

      <p className="text-[10px] text-slate-600">
        Findings come from the deterministic YAML rule pack (backend/ppa/rules_pack.yaml) — the LLM only
        explains them, it never invents them. 👍/👎 feedback drives future threshold tuning.
      </p>
    </div>
  );
}
