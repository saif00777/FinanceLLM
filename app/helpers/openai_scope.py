"""Per-request OpenAI credentials.

The chat UI sends the user's own OpenAI key with each request. It is held in a context variable for the duration of
that request only (never written to disk, a store or a log) and `ScopedOpenAI` resolves the right client from it, so
the agents keep using one long-lived `client.responses` / `client.embeddings` interface.
"""

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from typing import Any, Callable, Iterator

_api_key: ContextVar[str | None] = ContextVar("openai_api_key", default=None)


class MissingApiKeyError(RuntimeError):
    """No key was supplied with the request and the server has no default key."""

    def __init__(self) -> None:
        super().__init__("An OpenAI API key is required.")


def current_api_key() -> str | None:
    return _api_key.get()


@contextmanager
def use_api_key(key: str | None) -> Iterator[None]:
    token = _api_key.set(key)
    try:
        yield
    finally:
        _api_key.reset(token)


class ScopedOpenAI:
    """Looks like an OpenAI client; each call uses the request's key, else the server default, else fails loudly."""

    _MAX_CLIENTS = 16

    def __init__(self, default_client: Any | None, client_factory: Callable[[str], Any] | None = None):
        self._default = default_client
        self._factory = client_factory or self._openai
        self._clients: OrderedDict[str, Any] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def _openai(key: str) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=key)

    def _client(self) -> Any:
        key = _api_key.get()
        if not key:
            if self._default is None:
                raise MissingApiKeyError()
            return self._default
        with self._lock:
            client = self._clients.get(key)
            if client is None:
                client = self._factory(key)
                self._clients[key] = client
                while len(self._clients) > self._MAX_CLIENTS:
                    self._clients.popitem(last=False)
            else:
                self._clients.move_to_end(key)
            return client

    @property
    def responses(self) -> Any:
        return self._client().responses

    @property
    def embeddings(self) -> Any:
        return self._client().embeddings

    def __repr__(self) -> str:
        return "ScopedOpenAI(<request-scoped credentials>)"
