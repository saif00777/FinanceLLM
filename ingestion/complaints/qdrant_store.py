"""Qdrant adapter for redacted consumer-complaint documents."""
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from ingestion.complaints.documents import redact_text

SAFE_PAYLOAD_FIELDS = frozenset(
    {
        "source_hash",
        "product",
        "sub_product",
        "issue",
        "company",
        "state",
        "received_year",
        "text",
        "visibility",
    }
)


class ComplaintQdrantStore:
    def __init__(self, client: Any, collection_name: str = "complaints_v1", vector_size: int = 1536):
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
        for source_hash, vector, payload in records:
            self._validate_vector(vector)
            safe_payload = self._safe_payload(payload)
            safe_payload["source_hash"] = source_hash
            points.append(
                PointStruct(
                    id=uuid5(NAMESPACE_URL, source_hash),
                    vector=vector,
                    payload=safe_payload,
                )
            )
        if points:
            self._upsert_with_retry(points)

    def _upsert_with_retry(self, points: list) -> None:
        """Retry once on a transient write failure; upsert is idempotent (point IDs are deterministic)."""
        from qdrant_client.http.exceptions import ResponseHandlingException

        try:
            self._client.upsert(collection_name=self._collection_name, points=points)
        except (TimeoutError, ResponseHandlingException):
            self._client.upsert(collection_name=self._collection_name, points=points)

    def search(self, query_vector: list[float], top_k: int = 5) -> list[dict[str, object]]:
        """Return stored redacted text and payload from at most five Qdrant hits."""
        self._validate_vector(query_vector)
        limit = self._validated_top_k(top_k)
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        response = self._client.query_points(
            collection_name=self._collection_name,
            query=query_vector,
            limit=limit,
            query_filter=Filter(must=[FieldCondition(key="visibility", match=MatchValue(value="public"))]),
            with_payload=True,
            with_vectors=False,
        )
        points = getattr(response, "points", response)
        return [
            {"text": self._point_text(point), "payload": self._safe_payload(self._point_payload(point))}
            for point in points
        ]

    def _validate_vector(self, vector: list[float]) -> None:
        if len(vector) != self._vector_size:
            raise ValueError(f"vector must have length {self._vector_size}")

    @staticmethod
    def _validated_top_k(top_k: int) -> int:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            raise ValueError("top_k must be a positive integer")
        return min(top_k, 5)

    @staticmethod
    def _point_payload(point: Any) -> Mapping[str, object]:
        if isinstance(point, Mapping):
            payload = point.get("payload", {})
        else:
            payload = getattr(point, "payload", {})
        return payload if isinstance(payload, Mapping) else {}

    @staticmethod
    def _point_text(point: Any) -> str:
        payload = ComplaintQdrantStore._point_payload(point)
        text = payload.get("text", "")
        return redact_text(text) if isinstance(text, str) else ""

    @staticmethod
    def _safe_payload(payload: Mapping[str, object]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key in SAFE_PAYLOAD_FIELDS:
            value = payload.get(key)
            if key == "received_year" and isinstance(value, int):
                result[key] = value
            elif key in {"text", "visibility"} and isinstance(value, str):
                result[key] = redact_text(value) if key == "text" else value
            elif key not in {"text", "visibility", "received_year"} and isinstance(value, str):
                result[key] = value
        return result
