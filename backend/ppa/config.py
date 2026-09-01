"""Application settings. All values overridable via PPA_* environment variables."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"


class Settings(BaseSettings):
    # Storage
    db_path: Path = BACKEND_DIR / "data" / "ppa.db"
    sample_dir: Path = REPO_ROOT / "sample_runs"

    # AI (on-prem, OpenAI-compatible endpoint: Ollama or vLLM)
    ai_base_url: str = "http://localhost:11434/v1"
    ai_model: str = "qwen2.5:32b-instruct"
    ai_api_key: str = "ollama"  # placeholder; Ollama ignores it
    ai_timeout_s: float = 120.0
    ai_max_tool_rounds: int = 6
    # models below this size cannot drive the tool loop reliably; the agent
    # answers deterministically instead of burning minutes on failed rounds
    ai_min_model_b: float = 4.0

    # Server
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"

    model_config = {"env_prefix": "PPA_"}


settings = Settings()
