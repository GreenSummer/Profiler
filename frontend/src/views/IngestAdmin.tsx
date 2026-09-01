import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Card, Table } from "../components/ui";

export function IngestAdmin() {
  const { data: status, isLoading: loadingStatus } = useQuery({
    queryKey: ["ingest-status"], queryFn: api.ingestStatus,
  });
  const { data: rules, isLoading: loadingRules } = useQuery({
    queryKey: ["rules"], queryFn: api.rules,
  });

  const ok = (status ?? []).filter((r) => r.status === "ok").length;
  const bad = (status ?? []).length - ok;

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Ingest & Admin</h2>

      <Card
        title="Report parse status"
        right={
          <span className="text-[10px] text-slate-500">
            {ok} ok · {bad} issues · every report is content-hashed and parser-versioned
          </span>
        }
      >
        {loadingStatus ? (
          <p className="text-sm text-slate-500">loading…</p>
        ) : (
          <Table head={["Run", "Kind", "File", "SHA-256", "Parser", "Status", "Log"]}>
            {(status ?? []).map((r, i) => (
              <tr key={i}>
                <td className="px-2 py-1 font-medium">{r.run_label || `#${r.run_id}`}</td>
                <td className="px-2 py-1 font-mono text-slate-400">{r.kind}</td>
                <td className="max-w-[220px] truncate px-2 py-1 font-mono text-[10px] text-slate-500" title={r.file}>
                  {r.file.split("/").pop()}
                </td>
                <td className="px-2 py-1 font-mono text-[10px] text-slate-600">{r.sha256}</td>
                <td className="px-2 py-1 font-mono text-[10px] text-slate-500">{r.parser_version}</td>
                <td className={`px-2 py-1 font-mono text-[10px] ${r.status === "ok" ? "text-emerald-400" : "text-red-400"}`}>
                  {r.status}
                </td>
                <td className="max-w-[180px] truncate px-2 py-1 text-[10px] text-slate-600" title={r.log}>
                  {r.log || "—"}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card title="Diagnosis rule pack" right={<span className="text-[10px] text-slate-500">edit rules_pack.yaml, then re-ingest</span>}>
        {loadingRules ? (
          <p className="text-sm text-slate-500">loading…</p>
        ) : (
          <Table head={["Rule", "Category", "Severity", "Title", "Thresholds"]}>
            {(rules ?? []).map((r) => (
              <tr key={r.id}>
                <td className="px-2 py-1 font-mono text-[10px] text-sky-300">{r.id}</td>
                <td className="px-2 py-1">{r.category.replace("_", " ")}</td>
                <td className="px-2 py-1 text-[10px] uppercase text-slate-400">{r.severity}</td>
                <td className="px-2 py-1 text-slate-300">{r.title}</td>
                <td className="px-2 py-1 font-mono text-[10px] text-slate-500">
                  {Object.entries(r.params ?? {}).map(([k, v]) => `${k}=${v}`).join("  ") || "—"}
                </td>
              </tr>
            ))}
          </Table>
        )}
        <p className="mt-2 text-[10px] text-slate-600">
          Rules are deterministic: same reports, same findings, every time. Designers own the
          thresholds — no code changes needed to tune sensitivity.
        </p>
      </Card>

      <Card title="CLI quickstart">
        <pre className="overflow-x-auto rounded bg-slate-950 p-3 font-mono text-[11px] leading-relaxed text-slate-300">
{`# one-shot demo data (12-run config sweep) + ingest + golden baseline
cd backend && ../.venv/bin/python -m ppa.cli demo

# ingest your own reports (manifest.json listing the 5 report files)
../.venv/bin/python -m ppa.cli ingest <directory>

# serve API + built frontend on http://localhost:8000
../.venv/bin/python -m ppa.cli serve`}
        </pre>
        <p className="mt-2 text-[10px] text-slate-600">
          Parsers are versioned per report kind (see table above): bump the version when the tool
          output format changes, and historical runs stay interpretable.
        </p>
      </Card>
    </div>
  );
}
