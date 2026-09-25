"""TTL-bound, in-memory conversation state with safe fact handling."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Callable, Literal, Mapping, Protocol
from uuid import uuid4

_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE_OR_ACCOUNT = re.compile(r"\b\d[\d -]{7,}\d\b")
_HASH = re.compile(r"^[a-f0-9]{64}$")
_FORBIDDEN_FILTER_KEYS = {"rows", "row", "sql", "raw_sql", "prompt", "question", "answer", "content", "narrative"}


@dataclass(frozen=True)
class ConversationTurn:
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime | None = None

    @classmethod
    def user(cls, content: str) -> "ConversationTurn":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str) -> "ConversationTurn":
        return cls(role="assistant", content=content)


class ConversationFacts(dict[str, Any]):
    """A JSON-safe, redacted summary of resolved conversation state.

    This is deliberately a dictionary subclass so existing specialists may use
    it as ordinary JSON-compatible context. Raw prompts, SQL and result rows
    have no representable fields in this contract.
    """

    def __init__(
        self,
        *,
        resolved_metric: str | None = None,
        resolved_filters: Mapping[str, str | int | float | bool | None] | None = None,
        selected_relation_ids: tuple[str, ...] | list[str] = (),
        last_sql_hash: str | None = None,
        result_digest: str | None = None,
        semantic_version: str | None = None,
    ):
        super().__init__(
            resolved_metric=resolved_metric,
            resolved_filters=dict(resolved_filters or {}),
            selected_relation_ids=tuple(selected_relation_ids),
            last_sql_hash=last_sql_hash,
            result_digest=result_digest,
            semantic_version=semantic_version,
        )

    @property
    def resolved_metric(self) -> str | None:
        return self["resolved_metric"]

    @property
    def resolved_filters(self) -> dict[str, str | int | float | bool | None]:
        return self["resolved_filters"]

    @property
    def selected_relation_ids(self) -> tuple[str, ...]:
        return self["selected_relation_ids"]

    @property
    def last_sql_hash(self) -> str | None:
        return self["last_sql_hash"]

    @property
    def result_digest(self) -> str | None:
        return self["result_digest"]

    @property
    def semantic_version(self) -> str | None:
        return self["semantic_version"]

    def sanitized(self) -> "ConversationFacts":
        # Drop rather than raise on an unsafe entry: resolved_filters keys/values originate
        # from plan() (LLM output that only type-checks values, never key names), so a filter
        # key that happens to collide with a forbidden name must not crash an otherwise
        # successfully-computed answer at this last, purely-persistence step.
        filters: dict[str, str | int | float | bool | None] = {}
        for key, value in self.resolved_filters.items():
            if key.lower() in _FORBIDDEN_FILTER_KEYS:
                continue
            if not isinstance(value, (str, int, float, bool, type(None))):
                continue
            filters[str(key)] = _redact_scalar(value)
        relations = tuple(_safe_text(value, "relation") for value in self.selected_relation_ids)
        return ConversationFacts(
            resolved_metric=_safe_optional_text(self.resolved_metric, "metric"),
            resolved_filters=filters,
            selected_relation_ids=relations,
            last_sql_hash=_safe_hash(self.last_sql_hash, "last_sql_hash"),
            result_digest=_safe_hash(self.result_digest, "result_digest"),
            semantic_version=_safe_optional_text(self.semantic_version, "semantic_version"),
        )



def _safe_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError(f"Invalid {label} conversation fact")
    return value.strip()


def _safe_optional_text(value: Any, label: str) -> str | None:
    return None if value is None else _safe_text(value, label)


def _safe_hash(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError(f"Invalid {label}; store only a SHA-256 digest")
    return value


def _redact_turn_text(value: str) -> str:
    value = _EMAIL.sub("[redacted email]", value)
    return _PHONE_OR_ACCOUNT.sub("[redacted number]", value)


def _redact_scalar(value: str | int | float | bool | None) -> str | int | float | bool | None:
    if not isinstance(value, str):
        return value
    if len(value) > 160 or _EMAIL.search(value) or _PHONE_OR_ACCOUNT.search(value):
        return "[redacted]"
    return value.strip()


@dataclass(frozen=True)
class ConversationContext:
    id: str
    turns: tuple[ConversationTurn, ...]
    expires_at: datetime
    facts: ConversationFacts


class ConversationStore(Protocol):
    def load(self, conversation_id: str | None) -> ConversationContext: ...
    def append(self, context: ConversationContext, turn: ConversationTurn) -> ConversationContext: ...
    def update_facts(self, context: ConversationContext, facts: ConversationFacts) -> ConversationContext: ...


class InMemoryConversationStore:
    """Bounded development/test store; process restarts clear its contents."""

    def __init__(self, ttl_seconds: int = 1800, clock: Callable[[], datetime] | None = None):
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._contexts: dict[str, ConversationContext] = {}

    def _new(self, conversation_id: str | None = None) -> ConversationContext:
        return ConversationContext(
            id=conversation_id or str(uuid4()),
            turns=(),
            expires_at=self._clock() + self._ttl,
            facts=ConversationFacts(),
        )

    def load(self, conversation_id: str | None) -> ConversationContext:
        if not conversation_id:
            return self._new()
        context = self._contexts.get(conversation_id)
        if context is None or context.expires_at <= self._clock():
            self._contexts.pop(conversation_id, None)
            return self._new(conversation_id)
        return context

    def append(self, context: ConversationContext, turn: ConversationTurn) -> ConversationContext:
        stamped = replace(turn, content=_redact_turn_text(turn.content), created_at=turn.created_at or self._clock())
        updated = replace(
            context,
            turns=(*context.turns, stamped)[-6:],
            expires_at=self._clock() + self._ttl,
        )
        self._contexts[updated.id] = updated
        return updated

    def update_facts(self, context: ConversationContext, facts: ConversationFacts) -> ConversationContext:
        updated = replace(context, facts=facts.sanitized(), expires_at=self._clock() + self._ttl)
        self._contexts[updated.id] = updated
        return updated
