"""Proves a user-supplied OpenAI key works by making the same kinds of calls the chatbot will make."""

from collections import defaultdict, deque
from dataclasses import dataclass, field
import re
import time
from typing import Any, Callable

_KEY_SHAPE = re.compile(r"^sk-[A-Za-z0-9_\-]{16,400}$")


@dataclass(frozen=True)
class KeyCheck:
    valid: bool
    code: str
    message: str
    checks: list[dict[str, Any]] = field(default_factory=list)


def _failure(error: Exception) -> tuple[str, str]:
    """Maps an OpenAI error to a stable code plus a message for the person who typed the key."""
    import openai

    if isinstance(error, openai.AuthenticationError):
        return "invalid_key", "OpenAI rejected this key. Check that it was copied in full and has not been revoked."
    if isinstance(error, openai.RateLimitError):
        body = getattr(error, "body", None)
        if isinstance(body, dict) and body.get("code") == "insufficient_quota":
            return "no_quota", "The key is valid, but its OpenAI account has no remaining credit or quota."
        return "rate_limited", "OpenAI is rate limiting this key right now. Wait a moment and try again."
    if isinstance(error, (openai.PermissionDeniedError, openai.NotFoundError)):
        return "no_model_access", "The key is valid, but it cannot use the model this assistant needs."
    if isinstance(error, (openai.APIConnectionError, openai.APITimeoutError)):
        return "network", "Could not reach OpenAI to check the key. This is a connection problem, not the key."
    return "error", "OpenAI returned an unexpected error while checking the key."


def validate_openai_key(
    key: str,
    model: str,
    embedding_model: str | None,
    client_factory: Callable[[str], Any] | None = None,
) -> KeyCheck:
    """Format check first (no network), then one tiny real call per model the app uses."""
    key = (key or "").strip()
    if not _KEY_SHAPE.match(key):
        return KeyCheck(False, "bad_format", "That does not look like an OpenAI API key (it should start with sk-).")

    if client_factory is None:
        from openai import OpenAI

        client_factory = lambda value: OpenAI(api_key=value, timeout=20, max_retries=0)
    client = client_factory(key)

    checks: list[dict[str, Any]] = []
    calls = [("chat model", lambda: client.responses.create(model=model, input="ping", max_output_tokens=16, store=False))]
    if embedding_model:
        calls.append(("embedding model", lambda: client.embeddings.create(model=embedding_model, input="ping")))
    for name, call in calls:
        try:
            call()
        except Exception as error:  # noqa: BLE001 - every OpenAI failure maps to a user-facing code
            code, message = _failure(error)
            checks.append({"name": name, "ok": False})
            return KeyCheck(False, code, message, checks)
        checks.append({"name": name, "ok": True})
    return KeyCheck(True, "ok", "Key verified. You are ready to launch.", checks)


class SlidingWindowLimiter:
    """At most `max_calls` per `window_seconds` per caller; in-memory, so per server process."""

    def __init__(self, max_calls: int, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self._max, self._window, self._clock = max_calls, window_seconds, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, caller: str) -> bool:
        now = self._clock()
        hits = self._hits[caller]
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._max:
            return False
        hits.append(now)
        return True
