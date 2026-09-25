"""Retrieval contract for the document (RAG) branch: any corpus plugs in by implementing `Retriever`."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RetrievedDocument:
    text: str
    payload: dict[str, object]
    citation: str


class Retriever(Protocol):
    def retrieve(self, question: str) -> list[RetrievedDocument]: ...
