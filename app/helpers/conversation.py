"""Durable, TTL-bound conversation state with safe fact persistence."""

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

    @classmethod
    def from_storage(cls, row: Mapping[str, Any] | None, semantic_version: str | None) -> "ConversationFacts":
        row = row or {}
        return cls(
            resolved_metric=row.get("resolved_metric"),
            resolved_filters=row.get("filters") or {},
            selected_relation_ids=row.get("selected_relations") or (),
            last_sql_hash=row.get("last_sql_hash"),
            result_digest=row.get("result_digest"),
            semantic_version=semantic_version,
        ).sanitized()

    def sanitized(self) -> "ConversationFacts":
        filters: dict[str, str | int | float | bool | None] = {}
        for key, value in self.resolved_filters.items():
            if key.lower() in _FORBIDDEN_FILTER_KEYS:
                raise ValueError(f"Unsafe conversation fact key: {key}")
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise ValueError(f"Conversation fact values must be scalar: {key}")
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

    def storage_payload(self, conversation_id: str, expires_at: datetime) -> dict[str, Any]:
        safe = self.sanitized()
        return {
            "conversation_id": conversation_id,
            "resolved_metric": safe.resolved_metric,
            "filters": safe.resolved_filters,
            "selected_relations": list(safe.selected_relation_ids),
            "last_sql_hash": safe.last_sql_hash,
            "result_digest": safe.result_digest,
            "expires_at": expires_at.isoformat(),
        }


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


class SupabaseConversationStore:
    """Supabase-backed store. The caller supplies a server-only authenticated client."""

    def __init__(self, client: Any, ttl_seconds: int = 1800):
        self._client = client
        self._ttl = timedelta(seconds=ttl_seconds)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _new(self, conversation_id: str | None = None) -> ConversationContext:
        return ConversationContext(
            id=conversation_id or str(uuid4()),
            turns=(),
            expires_at=self._now() + self._ttl,
            facts=ConversationFacts(),
        )

    def load(self, conversation_id: str | None) -> ConversationContext:
        if not conversation_id:
            return self._new()
        response = self._client.table("conversations").select("id, expires_at, semantic_version").eq("id", conversation_id).execute()
        rows = getattr(response, "data", []) or []
        if not rows:
            return self._new(conversation_id)
        expires_at = datetime.fromisoformat(rows[0]["expires_at"].replace("Z", "+00:00"))
        if expires_at <= self._now():
            return self._new(conversation_id)
        message_response = (
            self._client.table("messages")
            .select("role, content, created_at")
            .eq("conversation_id", conversation_id)
            .order("created_at")
            .limit(6)
            .execute()
        )
        turns = tuple(
            ConversationTurn(
                role=row["role"], content=row["content"],
                created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
            )
            for row in (getattr(message_response, "data", []) or [])
        )
        facts_response = (
            self._client.table("conversation_facts")
            .select("resolved_metric, filters, selected_relations, last_sql_hash, result_digest")
            .eq("conversation_id", conversation_id)
            .execute()
        )
        fact_rows = getattr(facts_response, "data", []) or []
        facts = ConversationFacts.from_storage(fact_rows[0] if fact_rows else None, rows[0].get("semantic_version"))
        return ConversationContext(id=conversation_id, turns=turns, expires_at=expires_at, facts=facts)

    def append(self, context: ConversationContext, turn: ConversationTurn) -> ConversationContext:
        now = self._now()
        expires_at = now + self._ttl
        self._client.table("conversations").upsert(
            {"id": context.id, "expires_at": expires_at.isoformat()}
        ).execute()
        self._client.table("messages").insert(
            {"conversation_id": context.id, "role": turn.role, "content": _redact_turn_text(turn.content), "created_at": now.isoformat()}
        ).execute()
        safe_turn = replace(turn, content=_redact_turn_text(turn.content), created_at=now)
        return replace(context, turns=(*context.turns, safe_turn)[-6:], expires_at=expires_at)

    def update_facts(self, context: ConversationContext, facts: ConversationFacts) -> ConversationContext:
        now = self._now()
        expires_at = now + self._ttl
        safe = facts.sanitized()
        conversation_payload = {"id": context.id, "expires_at": expires_at.isoformat()}
        if safe.semantic_version:
            conversation_payload["semantic_version"] = safe.semantic_version
        self._client.table("conversations").upsert(conversation_payload).execute()
        self._client.table("conversation_facts").upsert(safe.storage_payload(context.id, expires_at)).execute()
        return replace(context, facts=safe, expires_at=expires_at)
