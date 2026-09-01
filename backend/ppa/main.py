"""FastAPI application: view APIs (V1-V11) + version analysis (v2) + AI
endpoints + static frontend."""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session

from . import analysis
from . import versioning
from .ai import llm
from .ai.agent import chat as ai_chat
from .config import settings
from .db import get_engine, get_session, init_db
from .models import ChatMessage, ChatSession, Finding, RuleFeedback

app = FastAPI(title="PPA-Profiler", version="0.1.0",
              description="RISC-V Power-Performance-Area analysis workbench")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


def session_dep():
    yield from get_session()


# ---------------------------------------------------------------- V1 runs

@app.get("/api/runs")
def list_runs(s: Session = Depends(session_dep)):
    return analysis.list_runs(s)


# ---------------------------------------------------------------- V2 scorecard

@app.get("/api/scorecard/{run_id}")
def scorecard(run_id: int, s: Session = Depends(session_dep)):
    out = analysis.scorecard(s, run_id)
    if not out:
        raise HTTPException(404, f"run {run_id} not found")
    return out


# ---------------------------------------------------------------- V3 compare

@app.get("/api/compare")
def compare(run_ids: str, s: Session = Depends(session_dep)):
    ids = [int(x) for x in run_ids.split(",") if x.strip()]
    if len(ids) < 2:
        raise HTTPException(400, "run_ids must list at least two runs")
    return analysis.compare(s, ids)


# ---------------------------------------------------------------- V4 design space

@app.get("/api/design-space")
def design_space(x: str = "total_power_mw", y: str = "specint_score",
                 s: Session = Depends(session_dep)):
    return analysis.design_space(s, x, y)


# ---------------------------------------------------------------- V5/V6/V7/V8/V9

@app.get("/api/area/{run_id}")
def area(run_id: int, s: Session = Depends(session_dep)):
    return analysis.area_explorer(s, run_id)


@app.get("/api/power/{run_id}")
def power(run_id: int, s: Session = Depends(session_dep)):
    return analysis.power_explorer(s, run_id)


@app.get("/api/timing/{run_id}")
def timing(run_id: int, s: Session = Depends(session_dep)):
    return analysis.timing_explorer(s, run_id)


@app.get("/api/perf/{run_id}")
def perf(run_id: int, baseline_id: int | None = None,
         s: Session = Depends(session_dep)):
    return analysis.perf_explorer(s, run_id, baseline_id)


@app.get("/api/hotspot/{run_id}")
def hotspot(run_id: int, s: Session = Depends(session_dep)):
    return analysis.hotspot(s, run_id)


# ---------------------------------------------------------------- V10 findings

@app.get("/api/findings")
def findings(run_id: int | None = None, severity: str | None = None,
             category: str | None = None, status: str | None = None,
             s: Session = Depends(session_dep)):
    return analysis.findings(s, run_id, severity, category, status)


class FindingPatch(BaseModel):
    status: str | None = None
    ai_explanation: str | None = None
    ai_proposal: str | None = None


@app.patch("/api/findings/{finding_id}")
def patch_finding(finding_id: int, patch: FindingPatch,
                  s: Session = Depends(session_dep)):
    f = s.get(Finding, finding_id)
    if not f:
        raise HTTPException(404, "finding not found")
    if patch.status:
        if patch.status not in ("open", "acknowledged", "fixed", "wont_fix"):
            raise HTTPException(400, "invalid status")
        f.status = patch.status
    if patch.ai_explanation is not None:
        f.ai_explanation = patch.ai_explanation
    if patch.ai_proposal is not None:
        f.ai_proposal = patch.ai_proposal
    s.add(f)
    s.commit()
    s.refresh(f)
    return {"id": f.id, "status": f.status}


class FeedbackIn(BaseModel):
    verdict: str
    comment: str = ""
    author: str = "anonymous"


@app.post("/api/findings/{finding_id}/feedback")
def finding_feedback(finding_id: int, body: FeedbackIn,
                     s: Session = Depends(session_dep)):
    if body.verdict not in ("up", "down"):
        raise HTTPException(400, "verdict must be up|down")
    fb = RuleFeedback(finding_id=finding_id, verdict=body.verdict,
                      comment=body.comment, author=body.author)
    s.add(fb)
    s.commit()
    return {"ok": True}


# ---------------------------------------------------------------- V11 ingest/admin

@app.get("/api/ingest-status")
def ingest_status(s: Session = Depends(session_dep)):
    return analysis.ingest_status(s)


@app.get("/api/rules")
def get_rules():
    from .rules import load_rules
    return load_rules()


# ---------------------------------------------------------------- v2 version analysis

@app.get("/api/overview")
def overview(s: Session = Depends(session_dep)):
    """Release overview board payload: geomean/perf-area trends across the
    provenance series, benchmark trends, area stack, timing, PPA board."""
    return versioning.overview_board(s)


@app.get("/api/version-drill")
def version_drill(version: str = Query(...), s: Session = Depends(session_dep)):
    """Module/signal drill-down for one synthesis version."""
    return versioning.version_drill(s, version)


@app.get("/api/version-compare")
def version_compare(versions: str, s: Session = Depends(session_dep)):
    """Module area/power + IPC + signal slack matrices across versions."""
    vs = [v.strip() for v in versions.split(",") if v.strip()]
    if len(vs) < 2:
        raise HTTPException(400, "versions must list at least two versions")
    return versioning.version_compare_multi(s, vs)


@app.get("/api/versions")
def versions(s: Session = Depends(session_dep)):
    """Ordered version series with headline metrics and change notes."""
    return versioning.version_series(s)


@app.get("/api/change-points")
def change_points(s: Session = Depends(session_dep)):
    """Persisted change-point detection results (ChangeEvents)."""
    return versioning.change_points(s)


@app.get("/api/correlations")
def get_correlations(s: Session = Depends(session_dep)):
    """Perf x PPA correlations across the version series."""
    return versioning.correlations(s)


@app.get("/api/search")
def search(q: str = Query(..., min_length=2),
           s: Session = Depends(session_dep)):
    """Global search: modules, timing signals (slack history), report text."""
    return versioning.signal_search(s, q)


@app.get("/api/trace")
def trace(run_id: int, kind: str, scope_path: str | None = None,
          path_id: int | None = None, benchmark: str | None = None,
          line: int | None = None,
          s: Session = Depends(session_dep)):
    """Raw report lines backing one plotted value (src_line provenance)."""
    try:
        out = versioning.trace_to_source(s, run_id, kind, scope_path=scope_path,
                                         path_id=path_id, benchmark=benchmark,
                                         line=line)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not out.get("found"):
        raise HTTPException(404, out.get("error", "row or report not found"))
    return out


# ---------------------------------------------------------------- AI

@app.get("/api/ai/status")
def ai_status():
    return llm.probe()


class ChatIn(BaseModel):
    messages: list[dict]
    run_context: dict | None = None


@app.post("/api/ai/chat")
def ai_chat_endpoint(body: ChatIn, s: Session = Depends(session_dep)):
    result = ai_chat(s, body.messages, body.run_context)
    # persist lightweight session log (auditability, plan 6.3)
    sess = ChatSession(title=(body.messages[-1]["content"][:60]
                              if body.messages else "chat"),
                       context_json=body.run_context or {})
    s.add(sess)
    s.flush()
    s.add(ChatMessage(session_id=sess.id, role="user",
                      content=body.messages[-1]["content"] if body.messages else ""))
    s.add(ChatMessage(session_id=sess.id, role="assistant",
                      content=result.get("content", ""),
                      tool_trace=result.get("tool_trace", []),
                      citations=result.get("citations", []),
                      offline=result.get("offline", False)))
    s.commit()
    return result


# ---------------------------------------------------------------- static frontend

dist = Path(settings.frontend_dist)
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
else:
    @app.get("/")
    def _root():
        return {"app": "PPA-Profiler", "hint": "frontend not built; API at /docs"}
