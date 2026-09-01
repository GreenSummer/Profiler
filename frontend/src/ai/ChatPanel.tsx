import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import { aiBadge } from "./badge";

interface Msg {
  role: "user" | "assistant";
  content: string;
  citations?: { run_id: number; run_label: string; source: string }[];
  tools?: string[];
  viewProposal?: { view: string; run_id?: number; run_ids?: number[] } | null;
  offline?: boolean;
}

const SUGGESTIONS = [
  "Give me an overview of the current run",
  "Compare the current run against the baseline",
  "What are the most severe findings right now?",
  "Which modules dominate area and power?",
];

export function ChatPanel({ context }: { context: () => unknown }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const chatPrefill = useApp((s) => s.chatPrefill);
  const setChatPrefill = useApp((s) => s.setChatPrefill);
  const applyProposal = useApp((s) => s.applyProposal);
  const { data: aiStatus } = useQuery({ queryKey: ["ai-status"], queryFn: api.aiStatus });
  const badge = aiBadge(aiStatus);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    setInput("");
    const history: Msg[] = [...messages, { role: "user", content: question }];
    setMessages(history);
    setBusy(true);
    try {
      const res = await api.aiChat(
        history.map((m) => ({ role: m.role, content: m.content })),
        context(),
      );
      setMessages([...history, {
        role: "assistant",
        content: res.content,
        citations: res.citations,
        tools: res.tool_trace?.map((t) => t.tool),
        viewProposal: res.view_proposal,
        offline: res.offline,
      }]);
    } catch (e) {
      setMessages([...history, {
        role: "assistant",
        content: `⚠ request failed: ${e instanceof Error ? e.message : String(e)}`,
        offline: true,
      }]);
    } finally {
      setBusy(false);
    }
  }

  // a question injected from elsewhere (e.g. "✦ ask AI" on a finding) auto-sends
  useEffect(() => {
    if (chatPrefill) {
      const q = chatPrefill;
      setChatPrefill(null);
      void send(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatPrefill]);

  return (
    <div className="flex h-full flex-col bg-slate-900/60">
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
        <span className="text-sm font-semibold text-violet-300">✦ PPA Assistant</span>
        <span
          title={badge.title}
          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${badge.cls}`}
        >
          {badge.text}
        </span>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {messages.length === 0 && (
          <div className="space-y-2">
            <p className="text-xs text-slate-500">
              Ask about PPA data in the selected run. Every number in the answer is computed by the
              analysis engine and cited — the model never does arithmetic itself.
            </p>
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => void send(s)}
                className="block w-full rounded border border-slate-700 bg-slate-800/60 px-2.5 py-1.5 text-left text-xs text-slate-300 hover:border-violet-500/50 hover:text-violet-200">
                {s}
              </button>
            ))}
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
            <div className={
              m.role === "user"
                ? "max-w-[90%] rounded-lg bg-sky-500/20 px-3 py-2 text-xs text-sky-100"
                : "max-w-[95%] rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs text-slate-200"
            }>
              <div className="whitespace-pre-wrap leading-relaxed">{m.content}</div>

              {m.role === "assistant" && (
                <>
                  {m.tools && m.tools.length > 0 && (
                    <div className="mt-1.5 text-[10px] text-slate-600">
                      tools: {m.tools.join(", ")}
                    </div>
                  )}
                  {m.citations && m.citations.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {m.citations.map((c, j) => (
                        <span key={j} className="rounded bg-slate-800/80 px-1.5 py-0.5 text-[10px] text-slate-400">
                          {c.run_label || `run #${c.run_id}`} · {c.source}
                        </span>
                      ))}
                    </div>
                  )}
                  {m.viewProposal && (
                    <button
                      onClick={() => applyProposal(m.viewProposal!.view, m.viewProposal!.run_id, m.viewProposal!.run_ids)}
                      className="mt-2 rounded border border-violet-500/50 bg-violet-500/10 px-2 py-1 text-[11px] text-violet-300 hover:bg-violet-500/20"
                    >
                      → open {m.viewProposal.view} view
                    </button>
                  )}
                  {m.offline && (
                    <div className="mt-1.5 text-[10px] text-slate-600">
                      {aiStatus?.mode === "deterministic"
                        ? "answered by the deterministic analyst — the local model is too small for tool-calling; pull a larger model (e.g. ollama pull qwen2.5:14b-instruct) for conversational answers"
                        : "answered by the deterministic offline analyst (no LLM reachable — start Ollama for richer answers)"}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        ))}

        {busy && (
          <div className="max-w-[95%] rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs text-slate-500">
            analyzing<span className="animate-pulse">…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-slate-800 p-2">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(input);
              }
            }}
            rows={2}
            placeholder="ask about area, power, timing, performance…"
            className="min-h-[44px] flex-1 resize-none rounded border border-slate-700 bg-slate-800 px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-violet-500/60 focus:outline-none"
          />
          <button
            onClick={() => void send(input)}
            disabled={busy || !input.trim()}
            className="rounded bg-violet-600 px-3 py-2 text-xs font-semibold text-white hover:bg-violet-500 disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
