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
3. When you state a fact, mention the run label it came from.
4. Use the tools before answering. For a question about a specific run, call
   get_context_pack first. For comparisons, call compare_runs.
5. You may call propose_view to navigate the user's UI to relevant data.

DOMAIN KNOWLEDGE:
- SPECint2006 score = SPECint/GHz (geomean of benchmark ratios) x Fmax(GHz).
  Changes decompose into IPC (microarchitecture) and frequency (physical) parts.
- WNS/TNS: worst/total negative slack; NVE = violating endpoints.
- Area splits: combinational, sequential, macro (SRAM), clock network, buffers.
- Power splits: internal, switching, leakage; clock power share and clock-gating
  efficiency are the most actionable power levers.
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

    if any(k in q for k in ("compare", "vs", "versus", "better", "roi", "trade")):
        # find a second run mentioned
        other = next((r for r in runs if r["label"].lower() in q
                      and r["run_id"] != target["run_id"]), None)
        if other:
            cmp_data = analysis.compare(session, [target["run_id"], other["run_id"]])
            c = cmp_data["comparisons"][0] if cmp_data.get("comparisons") else {}
            lines = [f"### {c.get('base')} -> {c.get('label')}", ""]
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
