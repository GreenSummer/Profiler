---
kind: build_system
name: Build System for PPA Profiler — Vite/React Frontend + FastAPI Backend with Pytest
category: build_system
scope:
    - '**'
source_files:
    - frontend/package.json
    - frontend/vite.config.ts
    - backend/requirements.txt
    - backend/ppa/main.py
    - backend/tests/test_backend.py
---

## Build & Artifact Management

This repository is a full-stack Python/TypeScript application with no centralized build orchestration (no top-level Makefile, Dockerfile, or CI pipeline). Each side builds independently using its native toolchain.

### Frontend build (Vite + React + TypeScript)
- **Toolchain**: Vite 6 with the `@vitejs/plugin-react` and Tailwind CSS v4 (`@tailwindcss/vite`).
- **Entry**: `frontend/index.html` loaded via `frontend/src/main.tsx`.
- **Scripts** (from `frontend/package.json`):
  - `npm run dev` → runs Vite dev server on port **5173**.
  - `npm run build` → runs `tsc --noEmit` (type-check only) then `vite build` to emit static assets.
  - `npm run preview` → serves the built output locally.
- **Dev proxy**: `frontend/vite.config.ts` proxies `/api` requests to `http://127.0.0.1:8000`, so the frontend expects the backend to be running separately during development.
- **Dependencies**: pinned in `frontend/package-lock.json`; runtime deps include React 18, ECharts, TanStack Query/Table, Zustand; dev deps include TypeScript 5, Vite, Tailwind, and the React plugin.

### Backend build & runtime (Python + FastAPI + Uvicorn)
- **Dependency manifest**: `backend/requirements.txt` pins all packages (FastAPI 0.115.6, Uvicorn 0.34.0, SQLModel 0.0.22, Pydantic v2, PyYAML, httpx, Typer, Rich, pytest).
- **Runtime entry**: `backend/ppa/main.py` defines the FastAPI app (`PPA-Profiler`, version `0.1.0`) and mounts:
  - REST endpoints under `/api/*` (runs, scorecard, compare, design-space, area/power/timing/perf/hotspot explorers, findings, AI chat).
  - The built frontend as static files via `StaticFiles(settings.frontend_dist)` when the directory exists; otherwise returns a JSON hint that the frontend is not built.
- **Startup**: `init_db()` is called on FastAPI startup to create tables in the SQLite database.
- **Configuration**: read via `pydantic-settings` from `backend/ppa/config.py` (e.g., `settings.frontend_dist` controls where the built frontend is served from).
- **No packaging**: there is no `setup.py`, `pyproject.toml`, wheel/sdist, or Docker image definition — the backend is intended to be run directly from source (e.g., `uvicorn ppa.main:app`).

### Testing
- **Framework**: pytest 8.3.4, located at `backend/tests/test_backend.py`.
- **Scope**: tests cover canonicalization, parser outputs, figures-of-merit computation, Pareto front calculation, end-to-end ingest + rule evaluation, and an integration test over the FastAPI `TestClient` that boots the app against an in-memory SQLite DB.
- **Fixtures**: a module-scoped `db` fixture creates a temp directory, generates sample data via `ppa.sample_data.generate`, ingests it into a fresh engine, and yields the engine for reuse across tests.
- **AI offline fallback**: the API test asserts that when the LLM is unavailable, `/api/ai/chat` still returns content with citations and `offline=True`.

### Deployment / Serving model
- **Single-process serving**: the FastAPI process both serves the JSON API and optionally serves the prebuilt frontend SPA from `settings.frontend_dist`. If the dist directory does not exist, the root route returns a JSON hint rather than a 404.
- **CORS**: enabled for all origins/methods/headers (intended for local dev; may need tightening for production).
- **Database**: SQLite file (`backend/data/ppa.db` shipped with sample data); tests use a temporary in-memory/temp-file engine.

### Conventions observed
- Frontend and backend are developed in parallel: the Vite dev server proxies API calls to `localhost:8000`, implying the backend must be started separately before `npm run dev`.
- Versioning is minimal: the FastAPI app declares `version="0.1.0"`; the frontend package declares `"version": "0.1.0"`; no semantic-release or changelog automation was found.
- There is no containerization, no GitHub Actions/GitLab CI, no Makefile, no shell-based build script, and no cross-compilation step — the repo is intended to be built by running the native tools directly in each subdirectory.