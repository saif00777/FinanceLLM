"""Reusable ingestion pipeline for consented, redacted complaint RAG documents."""

from collections.abc import Callable, Iterable
from typing import Any


class OpenAIEmbedder:
    def __init__(self, client: Any, model: str):
        self._client, self._model = client, model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [item.embedding for item in self._client.embeddings.create(model=self._model, input=texts).data]


class ComplaintRagPipeline:
    def __init__(self, embedder: Any, store: Any, batch_size: int = 32):
        self._embedder, self._store, self._batch_size = embedder, store, batch_size

    def ingest_documents(self, documents: Iterable[Any], on_batch: Callable[[int], None] | None = None) -> int:
        self._store.ensure_collection()
        batch, total = [], 0
        for document in documents:
            batch.append(document)
            if len(batch) == self._batch_size:
                total += self._ingest_batch(batch)
                batch = []
                if on_batch is not None:
                    on_batch(total)
        if batch:
            total += self._ingest_batch(batch)
            if on_batch is not None:
                on_batch(total)
        return total

    def _ingest_batch(self, documents: list[Any]) -> int:
        vectors = self._embedder.embed([document.text for document in documents])
        self._store.upsert(
            (
                document.source_hash,
                vector,
                {**document.payload, "text": document.text, "visibility": "public"},
            )
            for document, vector in zip(documents, vectors, strict=True)
        )
        return len(documents)