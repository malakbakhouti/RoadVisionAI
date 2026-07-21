"""Deterministic word-window chunker — CDC parameters: 512 tokens, 50 overlap.

Token = whitespace-separated word (fast, dependency-free approximation of the
e5 tokenizer; conservative because e5 subwords >= words). Page numbers are
tracked so every chunk can be cited as (document, page) — the currency of
normative references (business rule #6).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    text: str
    index: int
    page_start: int
    page_end: int


def chunk_pages(pages: list[str], *, chunk_size: int = 512, overlap: int = 50) -> list[Chunk]:
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be greater than overlap")
    # Flatten to (word, page) pairs to keep page attribution through windows
    words: list[tuple[str, int]] = []
    for page_num, page_text in enumerate(pages, start=1):
        words.extend((w, page_num) for w in page_text.split())
    if not words:
        return []

    chunks: list[Chunk] = []
    step = chunk_size - overlap
    start = 0
    index = 0
    while start < len(words):
        window = words[start : start + chunk_size]
        chunks.append(
            Chunk(
                text=" ".join(w for w, _ in window),
                index=index,
                page_start=window[0][1],
                page_end=window[-1][1],
            )
        )
        index += 1
        if start + chunk_size >= len(words):
            break
        start += step
    return chunks
