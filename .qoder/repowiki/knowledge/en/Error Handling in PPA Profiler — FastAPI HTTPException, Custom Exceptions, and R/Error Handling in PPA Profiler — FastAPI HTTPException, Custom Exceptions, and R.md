---
kind: error_handling
name: Error Handling in PPA Profiler — FastAPI HTTPException, Custom Exceptions, and Resilient Ingestion
category: error_handling
scope:
    - '**'
source_files:
    - backend/ppa/main.py
    - backend/ppa/ai/llm.py
    - backend/ppa/ai/agent.py
    - backend/ppa/ingest.py
    - backend/ppa/cli.py
    - backend/ppa/parsers/base.py
---

## Overview

The PPA Profiler backend (FastAPI + SQLModel) uses a small set of explicit error-handling patterns rather than a centralized exception hierarchy. Errors are raised as standard Python exceptions or FastAPI `HTTPException`s at API boundaries, while the ingestion pipeline tolerates per-report failures so that one bad EDA report does not abort an entire run.

## System / Approach

- **FastAPI `HTTPException`** is the sole HTTP error type used by the API layer (`backend/ppa/main.py`). Endpoints raise it for client errors such as missing runs, invalid parameters, unknown findings, and invalid status/verdict values. FastAPI converts these into JSON responses with the appropriate HTTP status code; no custom exception handler middleware is registered.
- **Custom domain exception**: `LLMUnavailable(Exception)` in `backend/ppa/ai/llm.py` wraps `httpx.ConnectError`, `httpx.ConnectTimeout`, and `httpx.HTTPError` from the OpenAI-compatible LLM client. Callers catch this specific exception to fall back gracefully when the local Ollama/vLLM endpoint is down.
- **Standard built-in exceptions**: `FileNotFoundError` is raised directly from `ingest_directory` when the required `manifest.json` is absent. This propagates up to the CLI `ingest` command, which lets Typer surface it as a normal process exit.
- **No global logging framework**: The backend does not configure Python's `logging` module. User-facing output goes through `rich.console.Console` in the CLI (`cli.py`) and through HTTP responses. There is no structured log sink for errors.
- **No `try`/`except` around request handlers**: Each FastAPI route is short and raises `HTTPException` directly; there is no middleware-level try/catch block.

## Key Files and Packages

| File | Role |
|---|---|
| `backend/ppa/main.py` | FastAPI app; all API endpoints raise `HTTPException` for validation / not-found cases |
| `backend/ppa/ai/llm.py` | Defines `LLMUnavailable`; catches `httpx.*` errors and re-raises as the domain exception |
| `backend/ppa/ai/agent.py` | Catches `LLMUnavailable` to return offline chat results; also catches `json.JSONDecodeError` / `TypeError` when parsing tool responses |
| `backend/ppa/ingest.py` | Resilient ingestion: per-report `try`/`except Exception` records parse failures as `RawReport.parse_status="error"` and continues processing other reports |
| `backend/ppa/cli.py` | CLI entry points; uses `typer` for argument validation and `rich` for console output; swallows parser exceptions in `check-format` |
| `backend/ppa/parsers/base.py` | Parser result dataclasses carry a `warnings: list[str]` field; parsers surface non-fatal issues via warnings rather than exceptions |

## Architecture and Conventions

### API Layer — Fail-Fast with `HTTPException`
Every public endpoint validates inputs before delegating to business logic:
- `/api/scorecard/{run_id}` raises 404 when the run is missing.
- `/api/compare` raises 400 when fewer than two `run_ids` are supplied.
- `/api/findings/{finding_id}` raises 404 on missing finding and 400 on invalid `status` values (`open`, `acknowledged`, `fixed`, `wont_fix`).
- `/api/findings/{finding_id}/feedback` raises 400 when `verdict` is not `up` or `down`.

These are the only places where user-facing errors are produced; the underlying `analysis.*` functions return `None` or empty collections instead of raising, letting the route decide the response shape.

### AI Subsystem — Explicit Unavailability
The LLM client isolates network failures behind `LLMUnavailable`. The agent (`ai/agent.py`) catches this exception in two places: during tool execution and during fallback chat, returning an "offline" result instead of failing the whole request. The `probe()` endpoint returns `{available: False, error: str(e)}` for any exception, giving the frontend a way to show whether the AI is reachable.

### Ingestion Pipeline — Per-Report Failure Isolation
`ingest_run` iterates over `REPORT_SPECS` and wraps each parser call in `try`/`except Exception`. On failure it:
1. Records a `RawReport` row with `parse_status="error"` and `parse_log=str(e)`.
2. Continues to the next report kind.

This means a malformed RTLA area report does not prevent primepower/specint reports from being ingested. Non-fatal parsing issues are surfaced via the `warnings` list on the returned report dataclass (defined in `parsers/base.py`), not via exceptions.

### CLI — Console Output and Swallowed Parser Errors
The CLI uses `rich` `Console` for colored output. The `check-format` command tries each parser in turn and silently skips those that raise, printing `[red]no parser matched this file[/red]` only if none succeed. The `ingest` command relies on Typer to display uncaught exceptions (e.g., missing `manifest.json`).

## Conventions and Constraints Observed

- **API routes never return `None` for missing resources** — they explicitly raise `HTTPException(404, ...)`.
- **Input validation happens at the route boundary**, not deep inside analysis functions; invalid payloads produce 400 responses.
- **Parser failures are treated as recoverable**: ingestion records them but never aborts the run. Fatal ingestion errors (missing manifest) use plain `FileNotFoundError`.
- **Warnings vs errors distinction**: parsers populate `report.warnings` for known-but-non-fatal conditions; only unexpected exceptions become `parse_status="error"`.
- **No global exception handler middleware** is registered in `main.py`; FastAPI's default exception handling is relied upon to serialize `HTTPException` responses.
- **No `print`/`logging` calls in library code** under `ppa/` except `sample_data.py` (which writes files and prints paths); all user-visible messages go through `rich` or HTTP responses.