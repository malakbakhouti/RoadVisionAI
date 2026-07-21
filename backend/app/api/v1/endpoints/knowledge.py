"""Knowledge base endpoints — SD07 (corpus normatif du RAG)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.ai.rag.knowledge_service import KnowledgeService
from app.core.dependencies import (
    CurrentUserDep,
    DbSessionDep,
    SettingsDep,
    get_chroma_client,
    get_embedder,
    require_roles,
)
from app.db.models.user import User, UserRole
from app.schemas.knowledge import (
    KnowledgeDocumentResponse,
    RagSearchRequest,
    RagSearchResponse,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

ChromaDep = Annotated[object, Depends(get_chroma_client)]
EmbedderDep = Annotated[object, Depends(get_embedder)]
EngineerOrAdminDep = Annotated[
    User, Depends(require_roles(UserRole.ROAD_ENGINEER, UserRole.ADMINISTRATOR))
]

ALLOWED_DOC_TYPES = {
    "NORME_DGR",
    "GUIDE_TECHNIQUE",
    "PCI_MANUAL",
    "AASHTO",
    "ASTM",
    "HISTORIQUE",
    "BONNE_PRATIQUE",
}
MAX_PDF_BYTES = 50 * 1024 * 1024


def _service(db, settings, chroma, embedder) -> KnowledgeService:
    return KnowledgeService(db, settings, chroma, embedder)


@router.post(
    "/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a normative PDF (extract -> chunk 512/50 -> embed -> index)",
)
async def ingest_document(
    actor: EngineerOrAdminDep,
    db: DbSessionDep,
    settings: SettingsDep,
    chroma: ChromaDep,
    embedder: EmbedderDep,
    file: Annotated[UploadFile, File(description="PDF document")],
    title: Annotated[str, Form(min_length=3, max_length=500)],
    doc_type: Annotated[str, Form()],
    source: Annotated[str | None, Form(max_length=500)] = None,
    version: Annotated[str | None, Form(max_length=50)] = None,
) -> KnowledgeDocumentResponse:
    if doc_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"doc_type must be one of {sorted(ALLOWED_DOC_TYPES)}",
        )
    if (file.content_type or "").lower() not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "PDF required")
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "PDF exceeds 50 MB")

    document = await _service(db, settings, chroma, embedder).ingest_pdf(
        pdf_bytes=data,
        title=title,
        doc_type=doc_type,
        source=source,
        version=version,
        actor=actor,
    )
    return KnowledgeDocumentResponse.model_validate(document)


@router.get(
    "/documents", response_model=list[KnowledgeDocumentResponse], summary="List indexed documents"
)
async def list_documents(
    user: CurrentUserDep,
    db: DbSessionDep,
    settings: SettingsDep,
    chroma: ChromaDep,
    embedder: EmbedderDep,
) -> list[KnowledgeDocumentResponse]:
    docs = await _service(db, settings, chroma, embedder).list()
    return [KnowledgeDocumentResponse.model_validate(d) for d in docs]


@router.get(
    "/documents/{document_id}", response_model=KnowledgeDocumentResponse, summary="Document detail"
)
async def get_document(
    document_id: uuid.UUID,
    user: CurrentUserDep,
    db: DbSessionDep,
    settings: SettingsDep,
    chroma: ChromaDep,
    embedder: EmbedderDep,
) -> KnowledgeDocumentResponse:
    doc = await _service(db, settings, chroma, embedder).get(document_id)
    return KnowledgeDocumentResponse.model_validate(doc)


@router.post(
    "/search",
    response_model=RagSearchResponse,
    summary="Semantic search over the normative corpus (top_k=5, threshold=0.75)",
)
async def search(
    body: RagSearchRequest,
    user: CurrentUserDep,
    db: DbSessionDep,
    settings: SettingsDep,
    chroma: ChromaDep,
    embedder: EmbedderDep,
) -> RagSearchResponse:
    hits = await _service(db, settings, chroma, embedder).search(
        body.query, top_k=body.top_k, threshold=body.threshold
    )
    return RagSearchResponse(query=body.query, hits=hits)
