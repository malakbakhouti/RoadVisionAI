"""ORM models — generated from the LIVE schema v4.2 database (sqlacodegen),
then reviewed and organised by domain. The database remains the single source
of truth; do not edit columns here without a schema-level ADR.
"""

import datetime
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.user import User

from app.db.models.enums import (
    DocType,
)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint(
            "deleted_at IS NULL OR deleted_at >= uploaded_at", name="chk_docs_deleted_at"
        ),
        CheckConstraint("embedding_count >= 0", name="chk_docs_embedding_count"),
        CheckConstraint("page_count > 0", name="knowledge_documents_page_count_check"),
        CheckConstraint(
            "status::text = ANY (ARRAY['PENDING'::character varying, 'INDEXING'::character varying, 'INDEXED'::character varying, 'ERROR'::character varying]::text[])",
            name="knowledge_documents_status_check",
        ),
        CheckConstraint("updated_at >= uploaded_at", name="chk_docs_updated_at"),
        ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            ondelete="SET NULL",
            name="knowledge_documents_uploaded_by_fkey",
        ),
        PrimaryKeyConstraint("id", name="knowledge_documents_pkey"),
        Index("idx_doc_content_fts", postgresql_using="gin"),
        Index("idx_doc_deleted", "deleted_at", postgresql_where="(deleted_at IS NULL)"),
        Index("idx_doc_indexed", "doc_type", postgresql_where="((status)::text = 'INDEXED'::text)"),
        Index(
            "idx_doc_pending_idx",
            "uploaded_at",
            postgresql_where="((status)::text = 'PENDING'::text)",
        ),
        Index("idx_doc_status", "status"),
        Index(
            "idx_doc_title_trgm",
            "title",
            postgresql_ops={"title": "gin_trgm_ops"},
            postgresql_using="gin",
        ),
        Index("idx_doc_type", "doc_type"),
        Index("idx_doc_uploaded_by", "uploaded_by", postgresql_where="(uploaded_by IS NOT NULL)"),
        {
            "comment": "Normative documents (DGR, ASTM, AASHTO, PCI Manual). Source for "
            "RAG pipeline."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    doc_type: Mapped[DocType] = mapped_column(
        Enum(
            DocType, values_callable=lambda cls: [member.value for member in cls], name="doc_type"
        ),
        nullable=False,
    )
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'fr'::character varying")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default=text("'PENDING'::character varying"),
        comment="Indexing lifecycle: PENDING → INDEXING → INDEXED | ERROR.",
    )
    embedding_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        comment="Number of chunks indexed into ChromaDB. Updated after successful indexing.",
    )
    uploaded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    lock_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
        comment="Optimistic locking counter. Prevents concurrent update conflicts between admin UI and background indexing job.",
    )
    source: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[str | None] = mapped_column(String(50))
    page_count: Mapped[int | None] = mapped_column(Integer)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(True), comment="Soft delete — NULL means active."
    )

    uploader: Mapped[Optional["User"]] = relationship("User", back_populates="knowledge_documents")
    embeddings: Mapped[list["Embedding"]] = relationship("Embedding", back_populates="document")


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="embeddings_chunk_index_check"),
        CheckConstraint("token_count > 0", name="embeddings_token_count_check"),
        ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            ondelete="CASCADE",
            name="embeddings_document_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="embeddings_pkey"),
        UniqueConstraint("document_id", "chunk_index", name="uq_embedding_doc_chunk"),
        Index("idx_emb_chroma_id", "chroma_id"),
        Index("idx_emb_document", "document_id"),
        {
            "comment": "Chunk metadata persisted in PostgreSQL. Actual vectors live in "
            "ChromaDB; chroma_id enables sync."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Zero-based position of this chunk within the parent document.",
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    token_count: Mapped[int | None] = mapped_column(Integer)
    chroma_id: Mapped[str | None] = mapped_column(
        String(500),
        comment="ChromaDB internal record ID. Used to synchronise updates and deletions.",
    )

    document: Mapped["KnowledgeDocument"] = relationship(
        "KnowledgeDocument", back_populates="embeddings"
    )
