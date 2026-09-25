"""Application configuration loaded from environment variables."""

from dataclasses import dataclass
from os import environ
from typing import Mapping


class ConfigurationError(ValueError):
    """Raised when a required server-side setting is absent or incomplete."""


def _required(values: Mapping[str, str], name: str, fallback: str | None = None) -> str:
    value = values.get(name) or (values.get(fallback) if fallback else None)
    if not value or not value.strip():
        alternatives = f" or {fallback}" if fallback else ""
        raise ConfigurationError(f"Missing required environment variable: {name}{alternatives}")
    return value.strip()


def _optional_pair(values: Mapping[str, str], first: str, second: str) -> tuple[str | None, str | None]:
    first_value = (values.get(first) or "").strip() or None
    second_value = (values.get(second) or "").strip() or None
    if bool(first_value) != bool(second_value):
        raise ConfigurationError(f"{first} and {second} must be configured together")
    return first_value, second_value


@dataclass(frozen=True)
class AppConfig:
    """Secrets and model selection held by the backend process only."""

    openai_model: str
    motherduck_token: str
    # Only a fallback: chat users bring their own key (X-OpenAI-Key). None means requests without one get a 401.
    openai_api_key: str | None = None
    qdrant_api_url: str | None = None
    qdrant_api_key: str | None = None
    openai_embedding_model: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None
    langfuse_verbose_tracing: bool = False

    def require_openai_api_key(self) -> str:
        """For offline admin scripts that call OpenAI themselves (there is no request to bring a key)."""
        if not self.openai_api_key:
            raise ConfigurationError("OPEN_AI_KEY must be set to run this script")
        return self.openai_api_key

    @property
    def qdrant_enabled(self) -> bool:
        return self.qdrant_api_url is not None

    @property
    def langfuse_enabled(self) -> bool:
        return self.langfuse_public_key is not None

    @classmethod
    def from_environment(cls, values: Mapping[str, str] | None = None) -> "AppConfig":
        values = environ if values is None else values
        qdrant_api_url, qdrant_api_key = _optional_pair(values, "QDRANT_API_URL", "QDRANT_API_KEY")
        langfuse_public_key, langfuse_secret_key = _optional_pair(values, "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
        langfuse_host = (values.get("LANGFUSE_BASE_URL") or "").strip() or None
        langfuse_verbose_tracing = (values.get("LANGFUSE_VERBOSE_TRACING") or "").strip().lower() in ("true", "1", "yes")
        embedding_model = (values.get("OPEN_AI_EMBEDDING_MODEL") or "").strip() or None
        if qdrant_api_url and not embedding_model:
            raise ConfigurationError("OPEN_AI_EMBEDDING_MODEL is required when Qdrant is configured")
        return cls(
            # Only OPEN_AI_KEY. The generic OPENAI_API_KEY is deliberately ignored: it is often a machine-wide variable
            # for other tools, and silently using a stale one would replace a clear "enter your key" with an OpenAI 401.
            openai_api_key=(values.get("OPEN_AI_KEY") or "").strip() or None,
            openai_model=_required(values, "OPEN_AI_MODEL"),
            motherduck_token=_required(values, "MOTHERDUCK_TOKEN"),
            qdrant_api_url=qdrant_api_url,
            qdrant_api_key=qdrant_api_key,
            openai_embedding_model=embedding_model,
            langfuse_public_key=langfuse_public_key,
            langfuse_secret_key=langfuse_secret_key,
            langfuse_host=langfuse_host,
            langfuse_verbose_tracing=langfuse_verbose_tracing,
        )