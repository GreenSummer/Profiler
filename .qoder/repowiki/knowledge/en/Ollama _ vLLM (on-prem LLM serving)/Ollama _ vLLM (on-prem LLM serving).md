---
kind: external_dependency
name: Ollama / vLLM (on-prem LLM serving)
slug: ollama
category: external_dependency
scope:
    - '**'
source_files:
    - backend/ppa/ai/llm.py
    - backend/ppa/config.py
---

### Identity + role
On-prem large-language-model serving backend used by the AI assistant layer. The project ships a thin OpenAI-compatible HTTP client (`backend/ppa/ai/llm.py`) that calls `/chat/completions` and `/models` against a configurable base URL; Ollama is the default target, vLLM is an equivalent alternative.

### Integration points
- `backend/ppa/ai/llm.py::chat_completion` — POSTs messages/tools to `<base_url>/chat/completions`; auth via `Authorization: Bearer <api_key>` from `settings.ai_api_key`.
- Configured through `pydantic-settings` fields `ai_base_url`, `ai_model`, `ai_api_key`, `ai_timeout_s`.

### Durable usage model
- The client is provider-agnostic: any server exposing the OpenAI chat-completions protocol works (Ollama at `http://localhost:11434/v1` out of the box).
- If the endpoint is unreachable the agent falls back to a deterministic offline analyst that answers from context packs with full citations — no hard dependency on the model being online.
- Tools are passed as OpenAI function-calling schema; the agent never executes arbitrary code.