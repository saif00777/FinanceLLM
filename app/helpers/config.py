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

    openai_api_key: str
    openai_model: str
    motherduck_token: str
    supabase_url: str | None = None
    supabase_key: str | None = None
    qdrant_api_url: str | None = None
    qdrant_api_key: str | None = None
    openai_embedding_model: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    @property
    def supabase_enabled(self) -> bool:
        return self.supabase_url is not None

    @property
    def qdrant_enabled(self) -> bool:
        return self.qdrant_api_url is not None

    @property
    def langfuse_enabled(self) -> bool:
        return self.langfuse_public_key is not None

    @classmethod
    def from_environment(cls, values: Mapping[str, str] | None = None) -> "AppConfig":
        values = environ if values is None else values
        supabase_url, supabase_key = _optional_pair(values, "SUPABASE_URL", "SUPABASE_KEY")
        qdrant_api_url, qdrant_api_key = _optional_pair(values, "QDRANT_API_URL", "QDRANT_API_KEY")
        langfuse_public_key, langfuse_secret_key = _optional_pair(values, "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
        embedding_model = (values.get("OPEN_AI_EMBEDDING_MODEL") or "").strip() or None
        if qdrant_api_url and not embedding_model:
            raise ConfigurationError("OPEN_AI_EMBEDDING_MODEL is required when Qdrant is configured")
        return cls(
            openai_api_key=_required(values, "OPEN_AI_KEY", fallback="OPENAI_API_KEY"),
            openai_model=_required(values, "OPEN_AI_MODEL"),
            motherduck_token=_required(values, "MOTHERDUCK_TOKEN"),
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            qdrant_api_url=qdrant_api_url,
            qdrant_api_key=qdrant_api_key,
            openai_embedding_model=embedding_model,
            langfuse_public_key=langfuse_public_key,
            langfuse_secret_key=langfuse_secret_key,
        )