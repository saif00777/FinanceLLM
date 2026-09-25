"""Cosine-similarity resolution of merchant-category (MCC) descriptions into SQL-generation context."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Protocol


class QuestionEmbedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class MccMatch:
    mcc: str
    description: str
    score: float


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class MccResolver:
    """Resolves a question to candidate MCC codes against a small cached embedding catalog."""

    # text-embedding-3-small cosine similarities run low: genuine matches score ~0.4-0.6,
    # unrelated pairs ~0.05-0.15. Re-check this default against real scores if the
    # embedding model (OPEN_AI_EMBEDDING_MODEL) ever changes.
    def __init__(self, embedder: QuestionEmbedder, entries: list[dict[str, object]], top_k: int = 5, threshold: float = 0.35):
        if top_k < 1:
            raise ValueError("top_k must be at least one")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        self._embedder = embedder
        self._entries = entries
        self._top_k = top_k
        self._threshold = threshold

    @classmethod
    def from_cache_file(cls, embedder: QuestionEmbedder, path: Path, top_k: int = 5, threshold: float = 0.35) -> "MccResolver":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(embedder, payload["entries"], top_k=top_k, threshold=threshold)

    def resolve(self, question: str) -> list[MccMatch]:
        if not self._entries:
            return []
        vectors = self._embedder.embed([question])
        if len(vectors) != 1:
            raise ValueError("question embedder must return exactly one vector")
        query_vector = vectors[0]
        matches = sorted(
            (
                MccMatch(mcc=str(entry["mcc"]), description=str(entry["description"]), score=_cosine_similarity(query_vector, entry["vector"]))
                for entry in self._entries
            ),
            key=lambda match: -match.score,
        )
        return [match for match in matches[: self._top_k] if match.score >= self._threshold]
