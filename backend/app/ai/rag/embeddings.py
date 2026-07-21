"""Embedding providers for the normative RAG (SD07, TechStack §5).

Production: intfloat/multilingual-e5-small via sentence-transformers — chosen
for its French performance (DGR corpus) at CPU-friendly size (118 MB, 384 d).
E5 requires asymmetric prefixes: "passage: " for indexed chunks, "query: "
for search queries; both are normalised so cosine similarity is the dot product.

The provider is injected (DI): tests substitute a deterministic fake, so the
RAG pipeline is testable without downloading models.
"""

from typing import Protocol

import structlog

log = structlog.get_logger("app.ai.rag.embeddings")


class EmbeddingProvider(Protocol):
    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class E5Embedder:
    """Lazy-loading multilingual-e5-small embedder (CPU)."""

    def __init__(self, model_name: str = "intfloat/multilingual-e5-small") -> None:
        self._model_name = model_name
        self._model = None

    def _ensure(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy import

            log.info("loading_embedding_model", model=self._model_name)
            self._model = SentenceTransformer(self._model_name, device="cpu")
        return self._model

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure()
        vectors = model.encode(
            [f"passage: {t}" for t in texts],
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        model = self._ensure()
        return model.encode([f"query: {text}"], normalize_embeddings=True, show_progress_bar=False)[
            0
        ].tolist()
