---
kind: dependency_management
name: Dual-Stack Dependency Management (Python requirements.txt + npm package.json with lockfiles)
category: dependency_management
scope:
    - '**'
source_files:
    - backend/requirements.txt
    - frontend/package.json
    - frontend/package-lock.json
    - frontend/tsconfig.json
---

## What system/approach is used

The repository manages dependencies for two independent stacks using their native package managers:

- **Backend (Python)**: Dependencies are pinned via `backend/requirements.txt`, which lists every runtime and test dependency with an exact version (`==`). The project uses a local virtual environment located at `.venv/` in the repository root.
- **Frontend (TypeScript/React/Vite)**: Dependencies are declared in `frontend/package.json` under `dependencies` and `devDependencies`. A `frontend/package-lock.json` lockfile is present, pinning transitive resolutions. The frontend also has a `node_modules/` directory (currently empty in this snapshot).

There is no shared monorepo tool (e.g., pnpm workspace, Lerna, Turborepo); each stack is self-contained.

## Key files and packages

- `backend/requirements.txt` — single source of truth for Python dependencies; all entries use exact pins (e.g. `fastapi==0.115.6`, `uvicorn[standard]==0.34.0`, `sqlmodel==0.0.22`, `pydantic==2.10.4`, `pydantic-settings==2.7.0`, `PyYAML==6.0.2`, `httpx==0.28.1`, `typer==0.15.1`, `rich==13.9.4`, `pytest==8.3.4`).
- `frontend/package.json` — declares runtime deps (`react`, `react-dom`, `@tanstack/react-query`, `@tanstack/react-table`, `echarts`, `echarts-for-react`, `zustand`) and dev deps (`typescript`, `vite`, `@vitejs/plugin-react`, `tailwindcss`, `@tailwindcss/vite`, `@types/*`). All versions use caret ranges (`^`).
- `frontend/package-lock.json` — deterministic lockfile for reproducible frontend installs.
- `frontend/tsconfig.json` — TypeScript configuration that constrains module resolution but does not manage third-party packages.
- `.venv/` — Python virtual environment directory at repo root (used to isolate backend dependencies from the host Python installation).
- `.npm-cache/` — npm cache directory at repo root, indicating npm was invoked from the repository root or configured to cache here.

## Architecture and conventions

- **Exact pinning on the backend**: Every Python dependency in `requirements.txt` is pinned to an exact version with `==`. This enforces deterministic builds and avoids accidental upgrades.
- **Caret ranges on the frontend**: Frontend dependencies use `^` version specifiers, allowing minor/patch updates within the major version range while still being locked by `package-lock.json`.
- **No vendoring**: Neither stack vendors third-party code into the repository. Python packages are installed into `.venv/`; Node packages are installed into `frontend/node_modules/`.
- **No private registry / proxy configuration**: There is no `.npmrc`, `pip.conf`, `~/.netrc`, or equivalent file visible in the repository. Dependencies are resolved against the default PyPI and npm registries.
- **No global/shared lockfile**: Each stack maintains its own lockfile (`package-lock.json` for Node). There is no `Pipfile.lock`, `poetry.lock`, or `requirements.lock` for Python — `requirements.txt` itself acts as the manifest.
- **Isolated environments**: The presence of both `.venv/` and `.npm-cache/` at the repository root suggests developers install dependencies per-repo rather than relying on system-wide installations.

## Conventions and constraints

- Backend dependencies must be added to `backend/requirements.txt` with an explicit `==` version pin; there is no dynamic version resolution or constraint file.
- Frontend dependencies should be added to `frontend/package.json` under the appropriate `dependencies` or `devDependencies` section; changes should be committed alongside the updated `package-lock.json` to keep the lockfile in sync.
- No cross-stack dependency sharing exists; the backend and frontend are treated as independent projects with separate manifests and lockfiles.
- There is no documented policy for updating dependencies (no automated bot, no scheduled PRs), so updates appear to be manual based on the absence of automation scripts.