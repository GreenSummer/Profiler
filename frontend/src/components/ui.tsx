import type { ReactNode } from "react";

export function Card({ title, children, right, className = "" }: {
  title?: ReactNode; children: ReactNode; right?: ReactNode; className?: string;
}) {
  return (
    <div className={`rounded-lg border border-slate-800 bg-slate-900/60 ${className}`}>
      {title && (
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
          <h3 className="text-sm font-semibold text-slate-300">{title}</h3>
          {right}
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  );
}

const SEV_STYLE: Record<string, string> = {
  critical: "bg-red-500/20 text-red-300 border-red-500/40",
  high: "bg-orange-500/20 text-orange-300 border-orange-500/40",
  medium: "bg-yellow-500/20 text-yellow-300 border-yellow-500/40",
  low: "bg-sky-500/20 text-sky-300 border-sky-500/40",
  info: "bg-slate-500/20 text-slate-300 border-slate-500/40",
};

export function SevBadge({ severity }: { severity: string }) {
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${SEV_STYLE[severity] ?? SEV_STYLE.info}`}>
      {severity}
    </span>
  );
}

export function Delta({ pct, invert = false, digits = 1 }: {
  pct: number | null | undefined; invert?: boolean; digits?: number;
}) {
  if (pct === null || pct === undefined || Number.isNaN(pct)) {
    return <span className="text-slate-600">—</span>;
  }
  const good = invert ? pct < 0 : pct > 0;
  const color = Math.abs(pct) < 0.05 ? "text-slate-400" : good ? "text-emerald-400" : "text-red-400";
  return <span className={`font-mono ${color}`}>{pct >= 0 ? "+" : ""}{pct.toFixed(digits)}%</span>;
}

export function Kpi({ label, value, unit, delta, invertDelta, target, overBudget }: {
  label: string; value: string; unit?: string; delta?: ReactNode;
  invertDelta?: boolean; target?: ReactNode; overBudget?: boolean;
}) {
  return (
    <div className={`rounded-lg border p-3 ${overBudget ? "border-red-500/50 bg-red-500/5" : "border-slate-800 bg-slate-900/60"}`}>
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className="font-mono text-xl font-semibold text-slate-100">{value}</span>
        {unit && <span className="text-xs text-slate-500">{unit}</span>}
      </div>
      <div className="mt-1 flex items-center justify-between text-xs">
        <span>{delta}</span>
        <span className="text-slate-500">{target}</span>
      </div>
    </div>
  );
}

export function fmt(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function shortModule(path: string | null | undefined): string {
  if (!path) return "—";
  return path.split("/").slice(1).join("/") || path;
}

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="border-b border-slate-800 text-[11px] uppercase tracking-wide text-slate-500">
            {head.map((h) => <th key={h} className="px-2 py-1.5 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/60">{children}</tbody>
      </table>
    </div>
  );
}

export function Empty({ msg = "Select a run first" }: { msg?: string }) {
  return <div className="flex h-64 items-center justify-center text-sm text-slate-600">{msg}</div>;
}

export function Spinner() {
  return <div className="flex h-40 items-center justify-center text-sm text-slate-500">loading…</div>;
}
