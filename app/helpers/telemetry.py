"""Payload-minimised telemetry interfaces."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
import hashlib
from typing import Any, Iterator, Mapping, Protocol


class Telemetry(Protocol):
    def safe_attributes(self, **values: Any) -> dict[str, Any]: ...
    def span(self, name: str, attributes: Mapping[str, Any]) -> Iterator[None]: ...


class NoopTelemetry:
    """Trace-compatible no-op that still exposes the redaction contract for tests."""

    _HASHED_FIELDS = frozenset({"sql", "prompt", "question", "answer", "conversation_id", "request_id"})
    _PASSTHROUGH_FIELDS = frozenset({
        "route", "reason_code", "semantic_version", "graph_version", "node", "provider", "model",
        "latency_ms", "execution_count", "repair_count", "token_count", "cost_micros",
    })

    def safe_attributes(self, **values: Any) -> dict[str, Any]:
        attributes: dict[str, Any] = {}
        for name, value in values.items():
            if name in self._HASHED_FIELDS:
                attributes[f"{name}_hash"] = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
            elif name == "rows":
                attributes["row_count"] = len(value)
            elif name in self._PASSTHROUGH_FIELDS and isinstance(value, (str, int, float, bool)):
                attributes[name] = value
        return attributes

    def span(self, _name: str, _attributes: Mapping[str, Any]):
        return nullcontext()


class LangfuseTelemetry(NoopTelemetry):
    """Injectable adapter for Langfuse's current-observation API.

    Only ``safe_attributes`` output is passed as metadata. Inputs and outputs
    are intentionally omitted to prevent accidental prompt, SQL, or row export.
    """

    def __init__(self, client: Any):
        self._client = client

    @contextmanager
    def span(self, name: str, attributes: Mapping[str, Any]) -> Iterator[None]:
        metadata = self.safe_attributes(**dict(attributes))
        with self._client.start_as_current_observation(name=name, as_type="span", metadata=metadata):
            yield
