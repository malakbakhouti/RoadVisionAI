"""Application settings — single source of configuration (TechStack §2: pydantic-settings + .env).

Every value can be overridden by an environment variable of the same name
(case-insensitive). Secrets NEVER have production defaults.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application -------------------------------------------------------
    app_name: str = "RoadVisionAI"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api"
    version: str = "0.1.0"

    # --- Security (SD01 — JWT access 30 min / refresh 7 days) --------------
    jwt_secret_key: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # --- Database (PostgreSQL 17 + PostGIS, schema v4.2) -------------------
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "roadvision"
    postgres_password: str
    postgres_db: str = "roadvisionai"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    # --- MinIO object storage (buckets per TechStack §7) --------------------
    minio_endpoint: str = "minio:9000"
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool = False
    # Endpoint used ONLY to sign browser-facing presigned URLs. Inside Docker
    # the SDK talks to minio:9000, but that hostname does not resolve outside
    # the compose network — so URLs are signed against this public endpoint.
    minio_public_endpoint: str = "localhost:9000"
    minio_bucket_road_images: str = "road-images"
    minio_bucket_annotated: str = "annotated-images"
    minio_bucket_reports: str = "reports"
    minio_bucket_models: str = "models"

    # --- ChromaDB (RAG — CDC: topK=5, threshold=0.75) ----------------------
    chroma_host: str = "chromadb"
    chroma_port: int = 8001
    chroma_collection: str = "road_knowledge_base"

    # --- Gemini (CDC: temperature 0.2) --------------------------------------
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-pro"
    gemini_temperature: float = 0.2

    # --- CORS / logging ------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:4200"]
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — inject via Depends(get_settings)."""
    return Settings()  # type: ignore[call-arg]
