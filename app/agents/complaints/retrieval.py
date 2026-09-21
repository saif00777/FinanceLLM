"""Safe, mockable retrieval contract for public consumer-complaint narratives."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ingestion.complaints.documents import redact_text

_SAFE_RESULT_FIELDS = frozenset(
    {"source_hash", "product", "sub_product", "issue", "company", "state", "received_year"}
)


class QueryEmbedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class ComplaintRetriever(Protocol):
    def retrieve(self, question: str) -> list["ComplaintRetrievalResult"]: ...


class ComplaintVectorStore(Protocol):
    def search(self, query_vector: list[float], top_k: int = 5) -> list[Mapping[str, object]]: ...


@dataclass(frozen=True)
class ComplaintRetrievalResult:
    text: str
    payload: dict[str, object]
    citation: str


class ComplaintRetrievalAdapter:
    """Filters Qdrant results before they can be passed to an agent response."""

    def __init__(self, store: ComplaintVectorStore, vector_size: int):
        if vector_size <= 0:
            raise ValueError("vector_size must be positive")
        self._store = store
        self._vector_size = vector_size

    def retrieve(self, query_vector: list[float], top_k: int = 5) -> list[ComplaintRetrievalResult]:
        self._validate_vector(query_vector)
        limit = self._validated_top_k(top_k)
        results: list[ComplaintRetrievalResult] = []
        for item in self._store.search(query_vector, top_k=limit):
            result = self._safe_result(item)
            if result is not None:
                results.append(result)
        return results

    def _validate_vector(self, vector: Sequence[float]) -> None:
        if len(vector) != self._vector_size:
            raise ValueError(f"query vector must have length {self._vector_size}")

    @staticmethod
    def _validated_top_k(top_k: int) -> int:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            raise ValueError("top_k must be a positive integer")
        return min(top_k, 5)

    @staticmethod
    def _safe_result(item: Mapping[str, object]) -> ComplaintRetrievalResult | None:
        payload = item.get("payload")
        text = item.get("text")
        if not isinstance(payload, Mapping) or not isinstance(text, str):
            return None
        if payload.get("visibility") not in (None, "public"):
            return None
        source_hash = payload.get("source_hash")
        if not isinstance(source_hash, str) or not source_hash:
            return None
        safe_payload = {
            key: value
            for key, value in payload.items()
            if key in _SAFE_RESULT_FIELDS
            and ((key == "received_year" and isinstance(value, int)) or (key != "received_year" and isinstance(value, str)))
        }
        safe_payload["source_hash"] = source_hash
        return ComplaintRetrievalResult(
            text=redact_text(text),
            payload=safe_payload,
            citation=source_hash,
        )


class ComplaintRagRetriever:
    """Embeds a complaint-domain question and retrieves only safe public results."""

    def __init__(self, embedder: QueryEmbedder, adapter: ComplaintRetrievalAdapter):
        self._embedder = embedder
        self._adapter = adapter

    def retrieve(self, question: str) -> list[ComplaintRetrievalResult]:
        vectors = self._embedder.embed([question])
        if len(vectors) != 1:
            raise ValueError("query embedder must return exactly one vector")
        candidates = self._adapter.retrieve(vectors[0], top_k=5)
        query_terms = {term for term in question.lower().split() if len(term) > 2}
        return sorted(
            candidates,
            key=lambda item: -len(query_terms.intersection(set((item.text + " " + " ".join(str(value) for value in item.payload.values())).lower().split()))),
        )[:3]