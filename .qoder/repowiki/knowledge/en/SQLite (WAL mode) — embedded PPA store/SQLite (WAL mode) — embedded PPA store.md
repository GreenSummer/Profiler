---
kind: external_dependency
name: SQLite (WAL mode) — embedded PPA store
slug: sqlite
category: external_dependency
scope:
    - '**'
source_files:
    - backend/ppa/models.py
    - backend/ppa/db.py
    - backend/ppa/analysis.py
---

### Identity + role
Embedded relational database backing the entire PPA Profiler data layer. Chosen for single-core, tens-of-runs scale; WAL mode is enabled for concurrent reads during ingestion.

### Integration points
- Schema and typed models live in `backend/ppa/models.py` (SQLModel/SQLAlchemy ORM).
- DB file lives under `backend/data/ppa.db`.
- Full-text search over report text uses SQLite's built-in FTS5 (no vector DB).

### Durable usage model
- All writes go through the ingest pipeline; queries are read-only Python functions that join area/power/timing/perf tables via canonicalized tool paths. No raw SQL is exposed to the frontend or the AI layer.