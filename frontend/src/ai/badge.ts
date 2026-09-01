/** AI status badge logic shared by the TopBar and the ChatPanel. */
export interface AiStatus {
  available: boolean;
  mode?: string;
  models?: string[];
  target_model?: string;
  configured_model?: string;
  min_model_b?: number;
  error?: string;
}

export function aiBadge(s?: AiStatus): { text: string; cls: string; title: string } {
  const mode = s?.mode ?? (s?.available ? "llm" : "offline");
  if (mode === "llm") {
    return {
      text: `LLM: ${s?.target_model ?? "ready"}`,
      cls: "bg-emerald-500/20 text-emerald-300",
      title: `on-prem model ${s?.target_model ?? "?"} · configured ${s?.configured_model ?? "?"}`,
    };
  }
  if (mode === "deterministic") {
    return {
      text: "deterministic mode",
      cls: "bg-amber-500/20 text-amber-300",
      title: `local model ${s?.target_model ?? "?"} is below the ${s?.min_model_b ?? 4}B tool-calling threshold — answers come from the deterministic analyst`,
    };
  }
  return {
    text: "LLM offline",
    cls: "bg-slate-600/30 text-slate-400",
    title: s?.error ?? "no local LLM endpoint reachable",
  };
}
