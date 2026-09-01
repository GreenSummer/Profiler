---
kind: configuration_system
name: Pydantic Settings-Based Configuration with Environment Overrides and YAML Rule Packs
category: configuration_system
scope:
    - '**'
source_files:
    - backend/ppa/config.py
    - backend/ppa/db.py
    - backend/ppa/main.py
    - backend/ppa/cli.py
    - backend/ppa/rules_pack.yaml
---

## What system/approach is used

The PPA Profiler uses a lightweight, code-first configuration system built on **`pydantic_settings.BaseSettings`** with environment-variable overrides via a `PPA_` prefix. Runtime behavior (database path, sample data directory, AI backend endpoint/model/keys/timeouts, and frontend build output location) is declared as typed fields in a single `Settings` class. There are no `.env` files checked in; defaults are embedded in Python and can be overridden at process start by exporting `PPA_*` variables.

Configuration is layered:
1. Hardcoded defaults inside `backend/ppa/config.py`.
2. Optional runtime overrides from environment variables prefixed with `PPA_` (e.g. `PPA_DB_PATH`, `PPA_AI_BASE_URL`).
3. A declarative YAML rule pack (`backend/ppa/rules_pack.yaml`) that defines diagnosis thresholds and titles — treated as *data* configuration rather than program logic.
4. CLI entry points in `cli.py` accept explicit arguments (e.g. `ingest <dir_path>`, `serve --host --port`) that shadow settings for one-shot commands.

## Key files and packages

- `backend/ppa/config.py` — sole source of application settings; exposes a module-level `settings = Settings()` singleton consumed everywhere else.
- `backend/ppa/db.py` — consumes `settings.db_path` to create the SQLite engine; also sets WAL mode and foreign keys on connect.
- `backend/ppa/main.py` — FastAPI app mounts the built frontend from `settings.frontend_dist`; falls back to a JSON health endpoint when the dist folder is absent.
- `backend/ppa/cli.py` — Typer CLI whose commands read `settings` for default paths but allow per-invocation overrides.
- `backend/ppa/rules_pack.yaml` — externalized rule definitions (severity, category, title templates, threshold parameters) loaded by `rules.py` at runtime.

## Architecture and conventions

- **Single source of truth**: All cross-cutting configuration lives in `config.Settings`. Modules import `from .config import settings` rather than reading env vars directly.
- **Environment variable convention**: Every setting is overridable by an uppercase `PPA_<FIELD>` env var. The pydantic model declares `model_config = {"env_prefix": "PPA_"}`, so e.g. `PPA_DB_PATH=/tmp/ppa.db` replaces the default `backend/data/ppa.db`.
- **Path resolution relative to repo root**: Defaults resolve against `REPO_ROOT = Path(__file__).resolve().parents[2]`, making the package relocatable without hardcoding absolute filesystem paths.
- **SQLite persistence defaults**: `db_path` defaults to `backend/data/ppa.db`; `db.make_engine` auto-creates the parent directory on first use.
- **AI backend defaults**: Default to Ollama on `http://localhost:11434/v1` with model `qwen2.5:32b-instruct`; these are intended to be swapped to vLLM or any OpenAI-compatible endpoint via env vars.
- **Frontend serving convention**: If `frontend/dist` exists it is mounted as static files under `/`; otherwise the root route returns a JSON hint pointing users to `/docs` (the generated OpenAPI schema).
- **Rule configuration as data**: Diagnosis rules live in `rules_pack.yaml` with fields `id`, `category`, `severity`, `title`, and optional `params`. Adding a new rule type requires both a YAML entry and a matching evaluator in `rules.py` (documented in the file header). Thresholds are tuned here without touching Python code.
- **CLI overrides**: Commands like `ppa ingest <dir>` and `ppa serve --host --port` accept positional/option arguments that take precedence over `settings` values for that invocation only.

## Conventions and constraints

- **All runtime configuration must go through `settings`** — modules do not call `os.environ.get` directly; they access typed attributes on the shared `settings` instance.
- **Environment variable naming**: Use `PPA_<UPPERCASE_FIELD_NAME>` to override any `Settings` field; the prefix is enforced by pydantic's `env_prefix` config.
- **Paths must be `pathlib.Path` objects**: The `Settings` class declares `db_path`, `sample_dir`, and `frontend_dist` as `Path`; consumers pass them directly to `create_engine` and `StaticFiles`.
- **Rule pack schema**: Each rule entry must include `id`, `category`, `severity`, and `title`; severity is restricted to `critical | high | medium | low | info`; adding a new `category` requires a corresponding evaluator in `rules.py`.
- **Database initialization**: The SQLite database is created lazily on first engine creation; WAL journaling and `PRAGMA foreign_keys=ON` are applied automatically on every connection.
- **No secrets in code**: `ai_api_key` defaults to the placeholder string `"ollama"` (noted as ignored by Ollama); real API keys should be supplied via `PPA_AI_API_KEY`.
- **Frontend build artifact contract**: The server expects a built Vite output at `frontend/dist`; absence triggers a fallback JSON response instead of a 404.