"""Payload-minimised telemetry interfaces."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
import hashlib
from typing import Any, Iterator, Mapping, Protocol


class SpanRecorder(Protocol):
    def record_output(self, output: Mapping[str, Any]) -> None: ...


class _NullRecorder:
    def record_output(self, output: Mapping[str, Any]) -> None:
        pass


_NULL_RECORDER = _NullRecorder()


class Telemetry(Protocol):
    def safe_attributes(self, **values: Any) -> dict[str, Any]: ...
    def generation(
        self, name: str, model: str, instructions: str, payload: Mapping[str, Any]
    ) -> Iterator[SpanRecorder]: ...
    def span(
        self, name: str, attributes: Mapping[str, Any], *, trace_id: str | None = None, session_id: str | None = None
    ) -> Iterator[SpanRecorder]: ...


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

    def span(
        self, _name: str, _attributes: Mapping[str, Any], *, trace_id: str | None = None, session_id: str | None = None
    ):
        return nullcontext(_NULL_RECORDER)

    def generation(self, _name: str, _model: str, _instructions: str, _payload: Mapping[str, Any]):
        return nullcontext(_NULL_RECORDER)


class LangfuseTelemetry(NoopTelemetry):
    """Injectable adapter for Langfuse's current-observation API.

    Only ``safe_attributes`` output is passed as metadata. Inputs and outputs
    are intentionally omitted to prevent accidental prompt, SQL, or row export.

    Each graph node opens and closes its own span independently (nodes run as
    separate calls, sometimes on separate threads for parallel branches), so
    there is never an ambient parent span for Langfuse to nest under. Without
    an explicit ``trace_id``, every node's span becomes its own root span --
    i.e. its own trace -- so one question produces a dozen unrelated traces
    instead of one. Passing the caller's per-request trace_id through
    ``trace_context`` groups every node's span under that same trace
    regardless of call order or thread.

    ``session_id`` groups traces themselves into Langfuse's conversation-level
    "session" view (one conversation = many turns = many traces). Langfuse
    treats ``session.id`` as a per-observation attribute, not something it
    infers or inherits across sibling spans in the same trace (confirmed
    against the real API), so it must be set on every node's span explicitly,
    the same way trace_id is -- there is no bulk "set once per trace" call.

    ``verbose``, off by default, opts into sending the *raw* question as this
    span's ``input`` and the node's own raw return dict as its ``output`` --
    real prompt/SQL/answer text, not hashes or counts. Dev-only debugging aid
    (``LANGFUSE_VERBOSE_TRACING`` in ``.env``, see AppConfig); the default
    (``verbose=False``) keeps the original posture of never sending raw
    question/SQL/row/answer content to Langfuse.
    """

    def __init__(self, client: Any, verbose: bool = False):
        self._client = client
        self._verbose = verbose

    @contextmanager
    def span(
        self, name: str, attributes: Mapping[str, Any], *, trace_id: str | None = None, session_id: str | None = None
    ) -> Iterator[SpanRecorder]:
        attributes = dict(attributes)
        metadata = self.safe_attributes(**attributes)
        trace_context = {"trace_id": trace_id} if trace_id else None
        input_value = attributes.get("question") if self._verbose else None
        with self._client.start_as_current_observation(
            name=name, as_type="span", metadata=metadata, trace_context=trace_context, input=input_value
        ) as observation:
            if session_id:
                from langfuse import LangfuseOtelSpanAttributes

                observation._otel_span.set_attribute(LangfuseOtelSpanAttributes.TRACE_SESSION_ID, session_id)
            yield _LangfuseSpanRecorder(observation, verbose=self._verbose)

    @contextmanager
    def generation(
        self, name: str, model: str, instructions: str, payload: Mapping[str, Any]
    ) -> Iterator[SpanRecorder]:
        """One LLM call, nested under the calling agent's span (same thread => current OTEL span).

        Verbose-only: instructions and payload carry the question, schema context, and result
        rows, so nothing is sent unless LANGFUSE_VERBOSE_TRACING is on."""
        if not self._verbose:
            yield _NULL_RECORDER
            return
        with self._client.start_as_current_observation(
            name=name, as_type="generation", model=model,
            input={"instructions": instructions, "input": dict(payload)},
        ) as observation:
            yield _LangfuseSpanRecorder(observation, verbose=True, wrap_output=False)


class _LangfuseSpanRecorder:
    def __init__(self, observation: Any, verbose: bool, wrap_output: bool = True):
        self._observation = observation
        self._verbose = verbose
        self._wrap_output = wrap_output

    def record_output(self, output: Any) -> None:
        if self._verbose:
            self._observation.update(output=dict(output) if self._wrap_output else output)
