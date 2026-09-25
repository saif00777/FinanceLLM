"""Retriever for the Larkspur Ridge document corpus (implements `app.agents.rag.Retriever`)."""

from collections.abc import Mapping
from typing import Any, Protocol

from app.agents.rag import RetrievedDocument

# Only these stored fields may reach an agent response; everything else in a payload is dropped.
_SAFE_FIELDS = ("doc_id", "title", "category", "doc_type", "date", "summary")


class QueryEmbedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class DocumentRetriever:
    def __init__(self, embedder: QueryEmbedder, store: Any, top_k: int = 8):
        self._embedder = embedder
        self._store = store
        self._top_k = top_k

    def retrieve(self, question: str) -> list[RetrievedDocument]:
        vectors = self._embedder.embed([question])
        if len(vectors) != 1:
            raise ValueError("query embedder must return exactly one vector")
        documents = []
        for hit in self._store.search(vectors[0], top_k=self._top_k):
            document = self._to_document(hit)
            if document is not None:
                documents.append(document)
        return documents

    @staticmethod
    def _to_document(hit: Mapping[str, object]) -> RetrievedDocument | None:
        doc_id, text = hit.get("doc_id"), hit.get("text")
        if not isinstance(doc_id, str) or not doc_id or not isinstance(text, str):
            return None
        payload = {key: hit[key] for key in _SAFE_FIELDS if isinstance(hit.get(key), str)}
        return RetrievedDocument(text=text, payload=payload, citation=doc_id)
