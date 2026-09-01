"""The AI agent: tool-calling loop over the typed tool layer, with a
deterministic offline fallback so the demo works without a local model.

Trust contract (plan 6.3), enforced structurally:
  - the model can only select tools, never compute
  - every tool result is deterministic Python output
  - citations travel with each tool call
  - refusal ("I don't have that data") is preferred over guessing
"""
from __future__ import annotations

import json
import re
from typing import Literal

from sqlmodel import Session

from ..config import settings
from . import llm
from .context_pack import build_run_pack
from .tools import TOOLS_SPEC, execute_tool

SYSTEM_PROMPT = """You are the PPA-Profiler assistant, an expert in RISC-V processor
power-performance-area analysis, embedded in a design analysis web tool.

STRICT RULES — violating any of these destroys user trust permanently:
1. NEVER compute, estimate, or invent a number. Every number you state must come
   verbatim from a tool result in this conversation. Copy digits exactly.
2. If no tool result contains the answer, say "I don't have that data" and suggest
   which view or run would contain it. Never guess.
3. When you state a fact, mention the run label or version it came from.
4. Use the tools before answering. For a question about a specific run, call
   get_context_pack first. For comparisons, call compare_runs.
5. You may call propose_view to navigate the user's UI to relevant data.
6. For version questions use the version tools: get_version_series (the series
   with change notes), get_change_points (detected jumps with attribution),
   get_correlations (perf x PPA across versions), search_signals (timing
   signals by name), trace_to_source (raw report lines behind a value).

DOMAIN KNOWLEDGE:
- The project tracks an RTL version series (v0.1..v0.16, one config): every
  version has a git sha and a change note; version-to-version differences are
  caused by the RTL change described in that note.
- SPECint2006 score = SPECint/GHz (geomean of benchmark ratios) x Fmax(GHz).
  Changes decompose into IPC (microarchitecture) and frequency (physical) parts.
- WNS/TNS: worst/total negative slack; NVE = violating endpoints.
- Area splits: combinational, sequential, macro (SRAM), clock network, buffers.
- Power splits: internal, switching, leakage; clock power share and clock-gating
  efficiency are the most actionable power levers.
- Change points: step = persistent change, spike + recovery = reverted temporary
  change, trend = multi-version drift. Severity comes from a robust z-score
  (median + k*MAD over version-to-version deltas); magnitude is that z.
- area_ROI = %score gain / %area cost; below ~0.3 usually rejected in review.
- Vectorless power is best for RELATIVE comparison; treat absolutes cautiously.

STYLE: concise, direct, engineer-to-engineer. Lead with the answer. Prefer short
tables (markdown) for numeric comparisons. End with one concrete recommended
next step when it is justified by the data.
"""


def _model_size_b(model: str | None) -> float | None:
    """Rough parameter-count hint parsed from names like 'qwen3:0.6b'."""
    return llm.model_size_b(model)


# Mid-size local models handle a few tools better than many; the context
# pack already embeds findings, top paths and per-benchmark data, so this
# compact set covers overview + comparison + navigation questions.
COMPACT_TOOL_NAMES = {"get_context_pack", "list_runs"}


def chat(session: Session, messages: list[dict], run_context: dict | None = None,
         ) -> dict:
    """One assistant turn. Returns {content, citations, tool_trace, offline, view_proposal}."""
    probe = llm.probe()
    if not probe.get("available"):
        return offline_answer(session, messages, run_context)
    model = probe.get("target_model")  # resolved against installed models
    # sub-threshold models cannot drive the tool loop reliably; answering with
    # the deterministic analyst is instant and always cited, instead of burning
    # minutes of narration rounds before falling back anyway
    size = llm.model_size_b(model)
    if size is not None and size < settings.ai_min_model_b:
        return offline_answer(session, messages, run_context,
                              reason="small_model", model=model)
    tools_spec = TOOLS_SPEC
    if (size or 99) < 8:
        # mid-size models handle a few tools better than many; the context
        # pack already embeds findings, top paths and per-benchmark data
        tools_spec = [t for t in TOOLS_SPEC
                      if t["function"]["name"] in COMPACT_TOOL_NAMES]

    convo: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if run_context:
        convo.append({"role": "system", "content":
                      "Current UI context (user is looking at this): "
                      + json.dumps(run_context, default=str)[:2000]})
    convo.extend(m for m in messages if m.get("role") in ("user", "assistant")
                 and not m.get("offline"))

    citations: list[dict] = []
    trace: list[dict] = []
    view_proposal: dict | None = None
    nudges = 0

    for _round in range(settings.ai_max_tool_rounds):
        # force at least one tool call: small models otherwise narrate instead of
        # fetching data, and every number must be tool-sourced (trust contract)
        force = "required" if not trace else None
        try:
            resp = llm.chat_completion(convo, tools=tools_spec, model=model,
                                       tool_choice=force)
        except llm.LLMUnavailable:
            return offline_answer(session, messages, run_context)
        choice = resp["choices"][0]["message"]
        tool_calls = choice.get("tool_calls") or []

        if not tool_calls:
            content = (choice.get("content") or "").strip()
            # accept only after at least one tool call: every number must be
            # tool-sourced (trust contract). Otherwise nudge, then fall back
            # to the deterministic analyst at loop exhaustion.
            if content and trace:
                return {"content": content,
                        "citations": citations, "tool_trace": trace,
                        "offline": False, "view_proposal": view_proposal}
            if content and nudges < 2:
                nudges += 1
                convo.append({"role": "assistant", "content": content[:500]})
                convo.append({"role": "user", "content":
                              "Call get_context_pack (or list_runs) now to fetch "
                              "the real numbers; do not answer from memory."})
            continue

        convo.append(choice)
        for tc in tool_calls:
            fn = tc["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                result, cites = execute_tool(session, fn["name"], args)
            except Exception as e:  # noqa: BLE001 - feed errors back to the model
                result = json.dumps({"error": f"tool '{fn['name']}' failed: {e}"})
                cites = []
            citations.extend(cites)
            trace.append({"tool": fn["name"], "args": args,
                          "result_bytes": len(result)})
            # capture view proposals so the UI can offer a one-click jump
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "view_proposal" in parsed:
                    view_proposal = parsed["view_proposal"]
            except (json.JSONDecodeError, TypeError):
                pass
            convo.append({
                "role": "tool", "tool_call_id": tc.get("id", ""),
                "content": result,
            })

    # exhausted rounds: force a final answer without tools
    if not trace:
        # model never called a tool: fall back to the deterministic analyst so
        # every number shown stays engine-computed and cited (trust contract)
        return offline_answer(session, messages, run_context, reason="no_tools")
    convo.append({"role": "user", "content":
                  "Please answer now using only the tool results above."})
    try:
        resp = llm.chat_completion(convo, model=model)
        content = resp["choices"][0]["message"].get("content", "")
    except llm.LLMUnavailable:
        return offline_answer(session, messages, run_context)
    return {"content": content, "citations": citations, "tool_trace": trace,
            "offline": False, "view_proposal": view_proposal}


# ---------------------------------------------------------------- offline

def offline_answer(session: Session, messages: list[dict],
                   run_context: dict | None = None, reason: str = "offline",
                   model: str | None = None) -> dict:
    """Deterministic fallback analyst: answers common question shapes directly
    from context packs so the tool is useful before a local model is installed."""
    last_user = next((m["content"] for m in reversed(messages)
                      if m.get("role") == "user"), "")
    q = last_user.lower()
    rid = (run_context or {}).get("run_id")
    trace = [{"tool": "offline_analyst", "args": {"q": last_user[:100]}}]

    def note():
        if reason == "small_model":
            return ("\n\n---\n*Deterministic analyst mode: the local model "
                    f"`{model or settings.ai_model}` is too small to drive the "
                    f"analysis tools reliably (needs >= {settings.ai_min_model_b:g}B "
                    "parameters). This answer was assembled deterministically from "
                    "context packs. Pull a larger model (e.g. "
                    "`ollama pull qwen2.5:14b-instruct`) or set PPA_AI_MODEL for "
                    "full conversational analysis.*")
        if reason == "no_tools":
            return ("\n\n---\n*The local model could not use the analysis tools "
                    "reliably, so this answer was assembled deterministically from "
                    "context packs.*")
        return ("\n\n---\n*Offline analyst mode: no local LLM endpoint reachable "
                f"at `{settings.ai_base_url}`. This answer was assembled "
                "deterministically from context packs. Start Ollama "
                f"(`ollama serve` + `ollama pull {settings.ai_model}`) for full "
                "conversational analysis.*")

    # pick a run: explicit context, or a name match from the question
    from .. import analysis
    runs = analysis.list_runs(session)
    if not runs:
        return {"content": "No runs ingested yet. Use the Ingest page or run "
                           "`ppa ingest <dir>` first." + note(),
                "citations": [], "tool_trace": trace, "offline": True,
                "view_proposal": None}
    target = None
    if rid:
        target = next((r for r in runs if r["run_id"] == rid), None)
    if target is None:
        for r in runs:
            if r["label"].lower() in q:
                target = r
                break
    if target is None:
        target = runs[0]

    # ---- v2 version-centric patterns ------------------------------------
    from .. import versioning
    series = versioning.version_series(session)["series"]
    events = versioning.change_points(session) if series else []

    def _ev_line(e: dict) -> str:
        pct = e["delta_pct"]
        pct_txt = (f"{pct:+.3f}" if e["metric_key"] in ("wns_ns", "clock_gating_eff")
                   else f"{pct * 100:+.1f}%")
        mod = f" in `{e['scope_path']}`" if e["scope_path"] else ""
        return (f"- **{e['from_version']} → {e['to_version']}**: {e['metric_key']} "
                f"{pct_txt} ({e['method']}, z = {e['magnitude']:.0f}, {e['severity']})"
                f"{mod} — “{e['note']}”")

    if "correlat" in q:
        corr = versioning.correlations(session)
        words = set(q.replace("_", " ").split())

        def _mentioned(p: dict) -> bool:
            return any(len(w) >= 4 and (w in p["perf"] or w in p["ppa"])
                       for w in words)

        pairs = sorted(corr["pairs"],
                       key=lambda p: (not _mentioned(p), -abs(p["r"])))
        lines = ["### Performance × PPA correlations across versions", ""]
        for p in pairs[:8]:
            lines.append(f"- {p['perf']} × {p['ppa']}: **r = {p['r']:+.3f}** (n = {p['n']})")
        if corr["modules"]:
            lines.append("")
            lines.append("Strongest module-level correlations with the score:")
            for mod in corr["modules"][:4]:
                lines.append(f"- `{mod['module']}` {mod['metric']}: r = {mod['r']:+.3f}")
        lines.append("")
        lines.append("See the Correlations view for the full matrix and scatter plots.")
        return {"content": "\n".join(lines) + note(),
                "citations": [{"run_id": 0, "run_label": "version series",
                               "source": "correlation engine"}],
                "tool_trace": trace, "offline": True,
                "view_proposal": {"view": "correlations"}}

    if "signal" in q or "search" in q:
        m = (re.search(r"['\"]([\w\[\]$.]+)['\"]", last_user)
             or re.search(r"(?:matching|match(?:es|ed)?|search(?:ing)?\s+for|like|named|called)"
                          r"\s+([\w\[\]$]+)", q))
        query = m.group(1) if m else ""
        if not query:
            stop = {"signal", "signals", "search", "show", "find", "matching",
                    "match", "slack", "history", "please", "which", "what",
                    "with", "for", "the", "timing"}
            cands = [w for w in re.findall(r"[a-z_][\w\[\]]*", q)
                     if w not in stop and len(w) >= 2]
            query = max(cands, key=len) if cands else ""
        if len(query) >= 2:
            res = versioning.signal_search(session, query)
            lines = [f"### Signals matching `{query}`", ""]
            worst_ref = None
            for sig in res["signals"][:6]:
                h = sig["history"]
                if not h:
                    continue
                worst = min(h, key=lambda x: x["slack_ns"])
                if worst_ref is None or worst["slack_ns"] < worst_ref[1]:
                    worst_ref = (worst["run_id"], worst["slack_ns"])
                lines.append(
                    f"- `{sig['startpoint'].rsplit('/', 1)[-1]}` → "
                    f"`{sig['endpoint'].rsplit('/', 1)[-1]}` ({sig['module']}): "
                    f"{len(h)} versions ({h[0]['version']}–{h[-1]['version']}), "
                    f"worst slack {worst['slack_ns']:+.3f} ns at {worst['version']}")
            if res["text"]:
                t0 = res["text"][0]
                lines.append("")
                lines.append(f"Plus {len(res['text'])} raw-report text matches "
                             f"(first: {t0['file']} line {t0['line']}, {t0['version']}).")
            if not res["signals"] and not res["text"]:
                lines.append(f"No timing signals or report text match `{query}`.")
            lines.append("")
            lines.append("The Timing view shows full paths; the trace drawer shows "
                         "the raw report lines for any of them.")
            return {"content": "\n".join(lines) + note(),
                    "citations": [{"run_id": worst_ref[0] if worst_ref else 0,
                                   "run_label": "signal search",
                                   "source": "timing reports"}],
                    "tool_trace": trace, "offline": True,
                    "view_proposal": ({"view": "timing", "run_id": worst_ref[0]}
                                      if worst_ref else {"view": "timeline"})}

    _METRIC_WORDS = {
        "area": "area_mm2", "power": "total_power_mw", "wns": "wns_ns",
        "timing": "wns_ns", "slack": "wns_ns", "leak": "leakage_share",
        "leakage": "leakage_share", "score": "specint_score",
        "perf": "specint_score", "performance": "specint_score",
        "ipc": "geomean_ratio_1ghz", "gating": "clock_gating_eff",
    }
    jump_q = any(w in q for w in ("jump", "spike", "regress", "drop", "climb",
                                  "fall", "worse", "improve", "increase",
                                  "decrease", "grow", "shift"))
    metric = next((mk for w, mk in _METRIC_WORDS.items() if w in q), None)
    if ("why" in q or jump_q) and metric:
        m_events = sorted([e for e in events if e["metric_key"] == metric],
                          key=lambda e: -abs(e["magnitude"]))
        lines = [f"### Detected `{metric}` change points", ""]
        for e in m_events[:6]:
            lines.append(_ev_line(e))
        if not m_events:
            lines.append(f"No statistically significant `{metric}` changes across "
                         "the version series — all deltas were within noise.")
        lines.append("")
        lines.append("Open the Version Timeline for the plotted series; every "
                     "event links to raw report lines via the trace drawer.")
        return {"content": "\n".join(lines) + note(),
                "citations": [{"run_id": 0, "run_label": "version series",
                               "source": "change-point detector"}],
                "tool_trace": trace, "offline": True,
                "view_proposal": {"view": "timeline"}}

    vers = re.findall(r"v(\d+(?:\.\d+)?)", q)
    if vers and any(k in q for k in ("change", "happen", "different", "event")):
        vt = "v" + vers[0]
        idx = {s["version"]: i for i, s in enumerate(series)}
        after = "after" in q or "since" in q
        if after:
            vi = idx.get(vt, len(series))
            sel = [e for e in events if idx.get(e["to_version"], 10 ** 9) > vi]
            head = f"### Changes after {vt}"
        else:
            sel = [e for e in events if e["to_version"] == vt]
            head = f"### Changes at {vt}"
        lines = [head, ""]
        for e in sel[:8]:
            lines.append(_ev_line(e))
        if not sel:
            note_v = next((s["change_note"] for s in series
                           if s["version"] == vt), "")
            lines.append(f"No detected change points at {vt} — version-to-version "
                         "deltas were within statistical noise.")
            if note_v:
                lines.append(f"Change note for {vt}: “{note_v}”")
        return {"content": "\n".join(lines) + note(),
                "citations": [{"run_id": 0, "run_label": "version series",
                               "source": "change-point detector"}],
                "tool_trace": trace, "offline": True,
                "view_proposal": {"view": "timeline"}}

    if series and any(k in q for k in ("version", "timeline", "history",
                                       "progress", "trend")):
        first, last = series[0], series[-1]
        fm, lm = first["metrics"], last["metrics"]
        lines = [f"### Version series {first['version']}–{last['version']} "
                 f"({len(series)} versions)", ""]
        lines.append(f"- Score {fm['specint_score']:.2f} → {lm['specint_score']:.2f}, "
                     f"area {fm['area_mm2']:.3f} → {lm['area_mm2']:.3f} mm², "
                     f"power {fm['total_power_mw']:.1f} → {lm['total_power_mw']:.1f} mW, "
                     f"WNS {fm['wns_ns']:+.3f} → {lm['wns_ns']:+.3f} ns")
        lines.append(f"- {len(events)} change points detected")
        lines.append("")
        lines.append("Most significant events:")
        for e in sorted(events, key=lambda e: -abs(e["magnitude"]))[:5]:
            lines.append(_ev_line(e))
        return {"content": "\n".join(lines) + note(),
                "citations": [{"run_id": first["run_id"], "run_label": first["version"],
                               "source": "version series"},
                              {"run_id": last["run_id"], "run_label": last["version"],
                               "source": "version series"}],
                "tool_trace": trace, "offline": True,
                "view_proposal": {"view": "timeline"}}

    # ---- run-centric patterns --------------------------------------------
    if any(k in q for k in ("compare", "vs", "versus", "better", "roi", "trade")):
        # find a second run mentioned
        other = next((r for r in runs if r["label"].lower() in q
                      and r["run_id"] != target["run_id"]), None)
        if other:
            cmp_data = analysis.compare(session, [target["run_id"], other["run_id"]])
            c = cmp_data["comparisons"][0] if cmp_data.get("comparisons") else {}
            lines = [f"### {c.get('base_label')} -> {c.get('label')}", ""]
            diff = ", ".join(f"{k}={v['base']}->{v['current']}"
                             for k, v in (c.get("config_diff") or {}).items())
            if diff:
                lines.append(f"Config changes: {diff}")
            d = c.get("decomposition") or {}
            if d:
                lines.append("")
                lines.append(f"- Net SPECint score: **{d.get('net_pct', 0):+.1f}%** "
                             f"(IPC {d.get('ipc_pct', 0):+.1f}%, freq {d.get('freq_pct', 0):+.1f}%)")
            fd = c.get("fom_delta") or {}
            for k in ("area_mm2", "total_power_mw"):
                if k in fd and fd[k].get("pct") is not None:
                    lines.append(f"- {k}: {fd[k]['pct']:+.1f}%")
            roi_a = fd.get("area_roi") if isinstance(fd.get("area_roi"), dict) else None
            lines.append("")
            lines.append("See the Compare view for the full waterfall attribution.")
            return {"content": "\n".join(lines) + note(),
                    "citations": [{"run_id": target["run_id"], "run_label": target["label"],
                                   "source": "comparison"},
                                  {"run_id": other["run_id"], "run_label": other["label"],
                                   "source": "comparison"}],
                    "tool_trace": trace, "offline": True,
                    "view_proposal": {"view": "compare",
                                      "run_ids": [target["run_id"], other["run_id"]]}}

    if any(k in q for k in ("finding", "abnormal", "wrong", "error", "diagnos", "problem", "issue")):
        fnd = analysis.findings(session, run_id=target["run_id"])
        if not fnd:
            return {"content": f"No open findings on run `{target['label']}`." + note(),
                    "citations": [], "tool_trace": trace, "offline": True,
                    "view_proposal": {"view": "findings", "run_id": target["run_id"]}}
        lines = [f"### Findings on `{target['label']}` ({len(fnd)})", ""]
        for f in fnd[:10]:
            lines.append(f"- **[{f['severity'].upper()}] {f['category']}**: {f['title']}")
        lines.append("")
        lines.append("See the Diagnosis Center for evidence and proposals.")
        return {"content": "\n".join(lines) + note(),
                "citations": [{"run_id": target["run_id"], "run_label": target["label"],
                               "source": "rule engine"}],
                "tool_trace": trace, "offline": True,
                "view_proposal": {"view": "findings", "run_id": target["run_id"]}}

    # default: run overview from the context pack
    pack = build_run_pack(session, target["run_id"])
    f = pack.get("figures_of_merit", {})
    lines = [f"### Run `{target['label']}` overview", ""]
    rv = pack.get("run", {})
    if rv.get("version"):
        lines.append(f"- Version: **{rv['version']}** — {rv.get('change_note', '')}")
    lines.append(f"- Net SPECint2006 score: **{f.get('specint_score', 0):.2f}** "
                 f"(SPECint/GHz {f.get('specint_per_ghz', 0):.2f} x "
                 f"{f.get('fmax_mhz', 0):.0f} MHz)")
    lines.append(f"- Area: {f.get('area_mm2', 0):.3f} mm2 ({f.get('area_kge', 0):.0f} kGE)")
    lines.append(f"- Power: {f.get('total_power_mw', 0):.1f} mW "
                 f"(mW/MHz {f.get('mw_per_mhz', 0):.3f})")
    d = pack.get("fom_delta_vs_baseline", {}).get("specint_score", {})
    if d.get("pct") is not None:
        lines.append(f"- vs baseline: score {d['pct']:+.1f}%")
    top = pack.get("top_modules_by_area_power", [])
    if top:
        lines.append("")
        lines.append("Largest modules (area/power/criticality): " +
                     ", ".join(f"`{t['module'].split('/')[-1]}` "
                               f"({t['area_share']:.0%}/{t['power_share']:.0%}/"
                               f"{t['criticality']:.0%})" for t in top[:4]))
    return {"content": "\n".join(lines) + note(),
            "citations": [{"run_id": target["run_id"], "run_label": target["label"],
                           "source": "context pack"}],
            "tool_trace": trace, "offline": True,
            "view_proposal": {"view": "scorecard", "run_id": target["run_id"]}}
