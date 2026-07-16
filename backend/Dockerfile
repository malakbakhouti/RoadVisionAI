# RoadVisionAI backend — uv-based multi-stage build (TechStack §2)
# Stage 1: resolve & install dependencies into a self-contained venv
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/srv/venv

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --frozen --no-install-project 2>/dev/null \
 || uv sync --no-dev --no-install-project

# Stage 2: minimal runtime image
FROM python:3.13-slim-bookworm AS runtime

RUN groupadd -r roadvision && useradd -r -g roadvision roadvision
WORKDIR /srv/app

COPY --from=builder /srv/venv /srv/venv
ENV PATH="/srv/venv/bin:$PATH" PYTHONUNBUFFERED=1

COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

USER roadvision
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; \
  sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
