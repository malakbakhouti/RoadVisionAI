# RoadVisionAI

AI-powered national road inspection & predictive maintenance platform — **Direction Générale des Routes, Maroc**.

Reference documents (single source of truth): CDC v5.0 · Schema v4.2 · SAD v1.1 · APISpec v1.0 · DataDictionary v1.0 · TechStack v1.0.

## Quick start

```bash
cp .env.example .env          # fill JWT_SECRET_KEY, POSTGRES_PASSWORD, MINIO keys
docker compose up -d --build
```

First start automatically: creates the database, executes **schema v4.2** (`01_schema_v4.2.sql`),
seeds the **8 CDC damage classes**, the 3 roles and the initial admin (`02_seed_data.sql`),
and provisions the 4 MinIO buckets.

| Service | URL |
|---|---|
| API (via Nginx) | http://localhost/api |
| OpenAPI docs | http://localhost:8000/docs |
| Liveness / readiness | `/api/health` · `/api/ready` |
| MinIO console | http://localhost:9001 |
| ChromaDB | http://localhost:8001 |

Initial admin: `admin@dgr.gov.ma` / `Admin@2026!` — **change at first login**.

## Backend development (without Docker)

```bash
cd backend
uv sync                        # deps from pyproject.toml (lockfile: uv.lock)
cp ../.env.example .env        # set POSTGRES_HOST=localhost
uv run uvicorn app.main:app --reload
uv run pytest                  # smoke tests (require a running PostgreSQL+PostGIS)
uv run ruff check . && uv run ruff format .
```

## Repository layout (TechStack §10)

```
backend/app/
  core/          settings (pydantic-settings), structlog, DI wiring
  db/            async engine/session, declarative Base   (models: Step 3)
  api/v1/        routers — 1:1 with APISpec v1.0          (auth: Step 2)
  schemas/       Pydantic v2 DTOs
  services/      business layer (owns transactions)
  repositories/  data access layer
  ai/            detection | engines | rag | agents | xai | reporting
  workers/       background dispatch (202 pattern), snapshot job
infrastructure/  nginx, postgres init (schema+seed), minio bucket init
```

## Implementation roadmap (Phase 1 — Week 2)

- [x] Step 1 — Skeleton, config, logging, DB connection, Docker
- [ ] Step 2 — Authentication (JWT, Argon2id, RBAC) — SD01
- [ ] Step 3 — SQLAlchemy models + Alembic + repositories — Schema v4.2
- [ ] Step 4 — Inspections + MinIO image upload — SD02
- [ ] Step 5 — Reports — SD06
- [ ] Step 6 — Dashboard (CQRS read) — SD08
