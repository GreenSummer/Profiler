import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import { fmt } from "./ui";

/** Global search: modules, timing signals (with slack history), report text.
 * The query doubles as the timing-view signal filter (store.searchQuery). */
export function GlobalSearch() {
  const searchQuery = useApp((s) => s.searchQuery);
  const setSearchQuery = useApp((s) => s.setSearchQuery);
  const { setRun, setView, openTrace } = useApp();
  const [debounced, setDebounced] = useState(searchQuery);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(searchQuery), 300);
    return () => clearTimeout(t);
  }, [searchQuery]);

  // close the dropdown on outside click
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const q = debounced.trim();
  const { data, isFetching } = useQuery({
    queryKey: ["search", q],
    queryFn: () => api.search(q),
    enabled: q.length >= 2,
  });

  const results = data ?? { query: q, modules: [], signals: [], text: [] };
  const n = results.modules.length + results.signals.length + results.text.length;
  const show = open && q.length >= 2;

  function goModule(runId: number) {
    setRun(runId);
    setView("area");
    setOpen(false);
  }
  function goSignal(runId: number) {
    setRun(runId);
    setView("timing"); // searchQuery stays as the signal filter
    setOpen(false);
  }
  function goText(runId: number, kind: string, line: number) {
    openTrace({ run_id: runId, kind, line });
    setOpen(false);
  }

  return (
    <div ref={boxRef} className="relative">
      <input
        value={searchQuery}
        onChange={(e) => { setSearchQuery(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}
        placeholder="search signals / modules / report text…"
        className="w-56 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-200 placeholder:text-slate-600 focus:border-sky-500/60 focus:outline-none"
      />
      {isFetching && q.length >= 2 && (
        <span className="absolute right-2 top-1.5 text-[10px] text-slate-600">…</span>
      )}

      {show && (
        <div className="absolute left-0 top-8 z-50 max-h-[70vh] w-[520px] max-w-[80vw] overflow-y-auto rounded-lg border border-slate-700 bg-slate-900 shadow-2xl">
          {n === 0 && !isFetching && (
            <p className="px-3 py-3 text-xs text-slate-500">no matches for “{q}”</p>
          )}

          {results.modules.length > 0 && (
            <Section title={`Modules (${results.modules.length})`}>
              {results.modules.map((m) => (
                <button key={m.scope_path} onClick={() => goModule(m.run_id)}
                  className="block w-full px-3 py-1.5 text-left font-mono text-[11px] text-slate-300 hover:bg-slate-800">
                  {m.scope_path}
                  <span className="ml-2 text-[10px] text-slate-600">→ area explorer</span>
                </button>
              ))}
            </Section>
          )}

          {results.signals.length > 0 && (
            <Section title={`Timing signals (${results.signals.length})`}>
              {results.signals.map((s) => {
                const worst = s.history.reduce((w, h) => (h.slack_ns < w.slack_ns ? h : w), s.history[0]);
                return (
                  <button key={`${s.startpoint}|${s.endpoint}`} onClick={() => goSignal(s.history[s.history.length - 1].run_id)}
                    className="block w-full px-3 py-1.5 text-left hover:bg-slate-800">
                    <div className="truncate font-mono text-[11px] text-slate-300">
                      {s.startpoint} → {s.endpoint}
                    </div>
                    <div className="text-[10px] text-slate-500">
                      {s.module} · {s.history.length} versions · worst {worst.version}:{" "}
                      <span className={worst.slack_ns < 0 ? "text-red-400" : "text-emerald-400"}>
                        {fmt(worst.slack_ns, 3)} ns
                      </span>
                      <span className="ml-1 text-slate-600">→ timing view filtered</span>
                    </div>
                  </button>
                );
              })}
            </Section>
          )}

          {results.text.length > 0 && (
            <Section title={`Report text (${results.text.length})`}>
              {results.text.slice(0, 12).map((t, i) => (
                <button key={`${t.run_id}:${t.kind}:${t.line}:${i}`} onClick={() => goText(t.run_id, t.kind, t.line)}
                  className="block w-full px-3 py-1.5 text-left hover:bg-slate-800">
                  <div className="truncate font-mono text-[11px] text-slate-400">{t.text}</div>
                  <div className="text-[10px] text-slate-600">
                    {t.version} · {t.file}:{t.line} · {t.kind}
                    <span className="ml-1">→ trace drawer</span>
                  </div>
                </button>
              ))}
            </Section>
          )}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-b border-slate-800 last:border-b-0">
      <div className="bg-slate-800/40 px-3 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </div>
      {children}
    </div>
  );
}
