"""Qdrant adapter for the document corpus (one point per document, deterministic ids so re-ingestion is idempotent)."""

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

DEFAULT_COLLECTION = "larkspur_ridge_bank_v1"
MAX_TOP_K = 10


class DocumentQdrantStore:
    def __init__(self, client: Any, collection_name: str = DEFAULT_COLLECTION, vector_size: int = 1536):
        if vector_size <= 0:
            raise ValueError("vector_size must be positive")
        self._client = client
        self._collection_name = collection_name
        self._vector_size = vector_size

    def ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        if not self._client.collection_exists(self._collection_name):
            self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=VectorParams(size=self._vector_size, distance=Distance.COSINE),
            )

    def upsert(self, records: Iterable[tuple[str, list[float], Mapping[str, object]]]) -> None:
        from qdrant_client.models import PointStruct

        points = []
        for doc_id, vector, payload in records:
            self._validate_vector(vector)
            points.append(PointStruct(id=str(uuid5(NAMESPACE_URL, doc_id)), vector=vector, payload=dict(payload)))
        if points:
            self._upsert_with_retry(points)

    def _upsert_with_retry(self, points: list) -> None:
        """Retry once on a transient write failure; safe because point ids are deterministic."""
        from qdrant_client.http.exceptions import ResponseHandlingException

        try:
            self._client.upsert(collection_name=self._collection_name, points=points)
        except (TimeoutError, ResponseHandlingException):
            self._client.upsert(collection_name=self._collection_name, points=points)

    def search(self, query_vector: list[float], top_k: int = 5) -> list[dict[str, object]]:
        self._validate_vector(query_vector)
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            raise ValueError("top_k must be a positive integer")
        response = self._client.query_points(
            collection_name=self._collection_name,
            query=query_vector,
            limit=min(top_k, MAX_TOP_K),
            with_payload=True,
            with_vectors=False,
        )
        points = getattr(response, "points", response)
        return [dict(getattr(point, "payload", None) or {}) for point in points]

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self._vector_size:
            raise ValueError(f"vector must have length {self._vector_size}")
