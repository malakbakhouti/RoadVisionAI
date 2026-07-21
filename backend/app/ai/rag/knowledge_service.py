"""KnowledgeService — normative corpus ingestion & retrieval (SD07).

Division of labour (TechStack §5):
  * PostgreSQL (knowledge_documents) — source of truth: full text (with French
    FTS index), metadata, lifecycle PENDING -> INDEXED, embedding_count.
  * ChromaDB (collection `normative_corpus`) — vectors only, one entry per
    chunk, metadata (document_id, title, doc_type, pages) for citation.

Retrieval contract (CDC): top_k = 5, cosine similarity threshold = 0.75.
Every hit is citable as (title, pages, similarity) — the raw material of
business rule #6 (every AI recommendation cites >= 1 normative reference).
"""

import uuid

import anyio
import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.chunking import chunk_pages
from app.ai.rag.embeddings import EmbeddingProvider
from app.core.config import Settings
from app.db.models.knowledge import KnowledgeDocument
from app.db.models.user import User
from app.repositories.audit_repository import AuditRepository

log = structlog.get_logger("app.ai.rag.knowledge")

COLLECTION = "normative_corpus"


def _extract_pdf_pages(pdf_bytes: bytes) -> list[str]:
    """PyMuPDF text extraction, one string per page (worker-thread material)."""
    import fitz  # PyMuPDF

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return [page.get_text("text") for page in doc]


class KnowledgeService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        chroma_client,
        embedder: EmbeddingProvider,
    ) -> None:
        self._session = session
        self._settings = settings
        self._chroma = chroma_client
        self._embedder = embedder
        self._audit = AuditRepository(session)

    def _collection(self):
        return self._chroma.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})

    # --- Ingestion (SD07: upload -> extract -> chunk -> embed -> index) --------
    async def ingest_pdf(
        self,
        *,
        pdf_bytes: bytes,
        title: str,
        doc_type: str,
        source: str | None,
        version: str | None,
        actor: User,
    ) -> KnowledgeDocument:
        try:
            pages = await anyio.to_thread.run_sync(_extract_pdf_pages, pdf_bytes)
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unreadable PDF: {exc}") from exc
        full_text = "\n\n".join(pages).strip()
        if not full_text:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "PDF contains no extractable text (scanned document?)",
            )

        document = KnowledgeDocument(
            title=title,
            source=source,
            doc_type=doc_type,
            version=version,
            content=full_text,
            page_count=len(pages),
            status="PENDING",
            uploaded_by=actor.id,
        )
        self._session.add(document)
        await self._session.flush()

        chunks = chunk_pages(
            pages,
            chunk_size=self._settings.rag_chunk_size,
            overlap=self._settings.rag_chunk_overlap,
        )
        if not chunks:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No content to index")

        texts = [c.text for c in chunks]
        vectors = await anyio.to_thread.run_sync(self._embedder.embed_passages, texts)

        collection = self._collection()

        def _upsert() -> None:
            collection.upsert(
                ids=[f"{document.id}:{c.index}" for c in chunks],
                embeddings=vectors,
                documents=texts,
                metadatas=[
                    {
                        "document_id": str(document.id),
                        "title": title,
                        "doc_type": doc_type,
                        "page_start": c.page_start,
                        "page_end": c.page_end,
                    }
                    for c in chunks
                ],
            )

        await anyio.to_thread.run_sync(_upsert)

        document.status = "INDEXED"
        document.embedding_count = len(chunks)
        await self._audit.log(
            action="DOCUMENT_INDEXED",
            entity_type="knowledge_documents",
            entity_id=document.id,
            user_id=actor.id,
            new_value={"title": title, "chunks": len(chunks), "pages": len(pages)},
        )
        await self._session.commit()
        await self._session.refresh(document)
        log.info(
            "document_indexed",
            document_id=str(document.id),
            chunks=len(chunks),
            pages=len(pages),
        )
        return document

    # --- Retrieval (top_k=5, threshold=0.75) -----------------------------------
    async def search(
        self, query: str, *, top_k: int | None = None, threshold: float | None = None
    ) -> list[dict]:
        top_k = top_k or self._settings.rag_top_k
        threshold = threshold if threshold is not None else self._settings.rag_similarity_threshold

        query_vector = await anyio.to_thread.run_sync(self._embedder.embed_query, query)
        collection = self._collection()

        def _query():
            return collection.query(
                query_embeddings=[query_vector],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )

        result = await anyio.to_thread.run_sync(_query)
        hits: list[dict] = []
        for text, meta, distance in zip(
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
            strict=True,
        ):
            similarity = 1.0 - float(distance)  # cosine space
            if similarity < threshold:
                continue  # below CDC threshold: not citable
            hits.append(
                {
                    "text": text,
                    "similarity": round(similarity, 4),
                    "document_id": meta["document_id"],
                    "title": meta["title"],
                    "doc_type": meta["doc_type"],
                    "page_start": meta["page_start"],
                    "page_end": meta["page_end"],
                }
            )
        log.info("rag_search", query=query[:80], hits=len(hits), top_k=top_k)
        return hits

    # --- Listing / lifecycle ----------------------------------------------------
    async def list(self) -> list[KnowledgeDocument]:
        stmt = (
            select(KnowledgeDocument)
            .where(KnowledgeDocument.deleted_at.is_(None))
            .order_by(KnowledgeDocument.uploaded_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get(self, document_id: uuid.UUID) -> KnowledgeDocument:
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id, KnowledgeDocument.deleted_at.is_(None)
        )
        doc = (await self._session.execute(stmt)).scalar_one_or_none()
        if doc is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Document {document_id} not found")
        return doc
