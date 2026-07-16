# RoadVisionAI 🛣️

**AI-powered national road inspection & predictive maintenance platform**
*Direction Générale des Routes — Royaume du Maroc · PFE DDSIR, EMSI Rabat*

RoadVisionAI automates road-surface damage detection from field images (YOLOv11), computes the Pavement Condition Index per **ASTM D6433**, and generates engineer-validated, RAG-grounded maintenance plans with full XAI decision transparency.

> **Status: Backend MVP v1.0** — design phase 100% complete, backend complete (30/30 integration tests), AI pipeline in progress (Week 3).

---

## Architecture

```
Angular 20 (Week 6) ──► Nginx ──► FastAPI (async) ──► PostgreSQL 17 + PostGIS 3.5
                                      │                    ▲ schema v4.2 — 24 tables,
                                      ├──► MinIO           │ 16 triggers, 14 ENUMs
                                      ├──► ChromaDB (RAG)  │
                                      └──► AI pipeline: YOLOv11 → PCIEngine (ASTM D6433)
                                           → LangGraph (6 agents) → Gemini 2.5 Pro
```

**Layered backend** (SAD v1.1): routers → services (own transactions) → repositories → async session. Errors follow **RFC 7807**. Every mutation is traced in an immutable `audit_logs` table.

## Tech stack

| Layer | Technologies |
|---|---|
| API | FastAPI · Python 3.13 · Pydantic v2 · uv |
| Data | PostgreSQL 17 + PostGIS 3.5 · SQLAlchemy 2 async · Alembic |
| Security | JWT (30 min / 7 d) · Argon2id · RBAC (3 roles) |
| Storage | MinIO (road-images, annotated-images, reports, models) |
| AI (Week 3+) | YOLOv11s · PyTorch · LangGraph · Gemini 2.5 Pro · ChromaDB + multilingual-e5-small |
| Infra | Docker Compose (6 services) · Nginx |
| Quality | pytest (30 integration tests vs real DB) · Ruff · pre-commit |

## Quick start

```bash
cp .env.example .env      # set JWT_SECRET_KEY (openssl rand -hex 32), passwords
docker compose up -d --build
```

First boot auto-provisions everything: schema v4.2, seed data (8 CDC damage classes with PCI weights, 3 roles, initial admin), and the 4 MinIO buckets.

| Service | URL |
|---|---|
| API (Nginx) | http://localhost/api |
| OpenAPI docs | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 |

> **Apple Silicon:** replace `postgis/postgis:17-3.5` with `imresamu/postgis:17-3.5` in `docker-compose.yml` (functionally identical multi-arch build; the official image remains valid for x86 production).

## API surface (19 endpoints)

| Group | Endpoints |
|---|---|
| Infrastructure | `GET /health` · `GET /ready` |
| Auth (SD01) | `POST /auth/login` · `/refresh` · `/logout` · `GET /auth/me` |
| Inspections (SD02) | `POST\|GET /inspections` · `GET\|PATCH\|DELETE /inspections/{id}` · `POST .../images` · `POST .../analyse` (202) |
| Reports (SD06) | `POST /plans/{id}/report` · `GET /reports` · `GET /reports/{id}` · `.../download` |
| Dashboard (SD08, CQRS) | `GET /dashboard/summary` · `GET /dashboard/pci-trends` · `POST /dashboard/snapshots` |

## Critical business rules (enforced & tested)

1. **Human-in-the-Loop** — no recommendation is ever auto-validated (`chk_rec_validation`, DB-level).
2. **Single active AI model** — `uq_one_active_model` partial unique index.
3. **Async 202** — analysis never blocks HTTP; state machine SM1 drives status.
4. **Optimistic locking** — every PATCH carries `version`; stale → HTTP 409 (DB trigger increments).
5. **Soft delete only** — `deleted_at`, filtered on every read.
6. **RAG grounding** — every AI recommendation must cite ≥ 1 normative reference (Week 4).

## Development

```bash
cd backend
uv sync
uv run pytest -v          # 30 passed — requires a running PostgreSQL+PostGIS
uv run ruff check . && uv run ruff format .
uv run alembic current    # 0001_baseline (head)
```

## Repository layout

```
backend/
  app/{core, db, api/v1, schemas, services, repositories, ai, workers}
  alembic/   # 0001_baseline executes the verified v4.2 SQL
  tests/     # 30 integration tests against the real schema
infrastructure/{nginx, postgres/init, minio}
ai/          # offline ML: datasets (immutable raw), training, evaluation, exports
```

## Roadmap

- [x] **W1** — Design: CDC v5.0, schema v4.2, SAD v1.1, APISpec v1.0, 27 UML diagrams
- [x] **W2** — Backend MVP v1.0 *(you are here)*
- [ ] **W3** — AI pipeline: YOLOv11 inference, PCIEngine (ASTM D6433), analysis worker
- [ ] **W4** — LangGraph 6-agent orchestration, RAG (ChromaDB), Gemini recommendations
- [ ] **W5** — HITL validation, 12-section XAI reports, notifications
- [ ] **W6** — Angular 20 frontend (dashboard, GIS map, validation UI)
- [ ] **W7-8** — Tests, deployment, thesis & defense

## License & context

Final-year engineering project (PFE) — EMSI Rabat, DDSIR program, in partnership with the Direction Générale des Routes (Morocco). Not licensed for redistribution.
