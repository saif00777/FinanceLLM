"""Embeds corpus documents in batches and upserts them into the vector store."""

from collections.abc import Callable, Iterable
from typing import Any

from ingestion.documents.corpus import CorpusDocument


def ingest_documents(
    documents: Iterable[CorpusDocument],
    embedder: Any,
    store: Any,
    batch_size: int = 16,
    on_batch: Callable[[int], None] | None = None,
) -> int:
    """Returns the number of documents upserted; `on_batch` receives the running total after each batch."""
    store.ensure_collection()
    total, batch = 0, []

    def flush() -> None:
        nonlocal total, batch
        vectors = embedder.embed([document.embedding_text for document in batch])
        store.upsert((document.doc_id, vector, document.payload) for document, vector in zip(batch, vectors, strict=True))
        total += len(batch)
        batch = []
        if on_batch is not None:
            on_batch(total)

    for document in documents:
        batch.append(document)
        if len(batch) == batch_size:
            flush()
    if batch:
        flush()
    return total
