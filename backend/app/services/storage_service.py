"""StorageService — MinIO object storage (TechStack §7, buckets per Deployment Diagram).

The minio SDK is synchronous; every call is pushed to a worker thread
(anyio.to_thread) so the event loop never blocks (ASYNC rule of the stack).
Injected via DI so tests can substitute an in-memory fake.
"""

import io
import uuid
from dataclasses import dataclass
from datetime import timedelta

import anyio
import structlog
from minio import Minio

from app.core.config import Settings

log = structlog.get_logger("app.services.storage")


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    object_name: str

    @property
    def storage_path(self) -> str:
        return f"{self.bucket}/{self.object_name}"


class StorageService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
            region="us-east-1",
        )
        # Presigned URLs are consumed by the person's browser, outside the
        # compose network: sign them against the public endpoint.
        self._public_client = Minio(
            settings.minio_public_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
            region="us-east-1",
        )

    async def put_image(
        self, *, inspection_id: uuid.UUID, filename: str, data: bytes, content_type: str
    ) -> StoredObject:
        """Store a road image under road-images/{inspection_id}/{uuid}_{filename}."""
        bucket = self._settings.minio_bucket_road_images
        object_name = f"{inspection_id}/{uuid.uuid4().hex}_{filename}"

        def _put() -> None:
            self._client.put_object(
                bucket,
                object_name,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )

        await anyio.to_thread.run_sync(_put)
        log.info("image_stored", bucket=bucket, object=object_name, size=len(data))
        return StoredObject(bucket=bucket, object_name=object_name)

    async def put_object(
        self, *, bucket: str, object_name: str, data: bytes, content_type: str
    ) -> StoredObject:
        """Generic object upload (reports, models, annotated images)."""

        def _put() -> None:
            self._client.put_object(
                bucket, object_name, io.BytesIO(data), length=len(data),
                content_type=content_type,
            )

        await anyio.to_thread.run_sync(_put)
        log.info("object_stored", bucket=bucket, object=object_name, size=len(data))
        return StoredObject(bucket=bucket, object_name=object_name)

    async def get_object(self, bucket: str, object_name: str) -> bytes:
        """Download an object's bytes (model weights, configs)."""

        def _get() -> bytes:
            resp = self._client.get_object(bucket, object_name)
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()

        return await anyio.to_thread.run_sync(_get)

    async def presigned_get_url(self, bucket: str, object_name: str) -> str:
        """Temporary download URL (1 h) — used by detail endpoints."""

        def _sign() -> str:
            return self._public_client.presigned_get_object(
                bucket, object_name, expires=timedelta(hours=1)
            )

        return await anyio.to_thread.run_sync(_sign)
