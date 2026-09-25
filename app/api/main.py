"""HTTP entry point for the multi-agent text-to-SQL (and optional document-RAG) backend."""

from datetime import datetime, timezone
import json
from os import environ
import time
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.agents.document_retrieval import DocumentRetriever
from app.agents.text_to_sql.contracts import RuntimeContract
from app.agents.text_to_sql.domain_guard import HardGuard
from app.agents.text_to_sql.specialists import OpenAIResponsesSpecialists
from app.agents.text_to_sql.workflow import MultiAgentWorkflow, WorkflowAnswer
from app.helpers.config import AppConfig
from app.helpers.conversation import InMemoryConversationStore
from app.helpers.embedder import OpenAIEmbedder
from app.helpers.key_validation import KeyCheck, SlidingWindowLimiter, validate_openai_key
from app.helpers.openai_scope import MissingApiKeyError, ScopedOpenAI, use_api_key
from app.helpers.mcc_resolver import MccResolver
from app.helpers.query_runner import MotherDuckQueryRunner
from app.helpers.telemetry import LangfuseTelemetry, NoopTelemetry
from ingestion.documents.store import DEFAULT_COLLECTION, DocumentQdrantStore


ROOT = Path(__file__).resolve().parents[2]

# No frontend origin is fixed yet; these cover the common local dev servers (CRA/Next, Vite).
# Set CORS_ALLOWED_ORIGINS (comma-separated) to override once a real frontend origin exists.
_DEFAULT_DEV_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173", "http://127.0.0.1:5173")


def _cors_origins() -> list[str]:
    configured = (environ.get("CORS_ALLOWED_ORIGINS") or "").strip()
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return list(_DEFAULT_DEV_ORIGINS)


SERVICE_NAME = "Financial Multi-Agent Text-to-SQL"
SERVICE_VERSION = "0.3.0"


def _sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class ChatRequest(BaseModel):
    question: str = Field(max_length=2_000)
    conversation_id: str | None = Field(default=None, max_length=64)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value


class ValidateKeyRequest(BaseModel):
    api_key: str = Field(max_length=600)


_GENERIC_FAILURE = "The analysis request could not be completed. Please try again."


def _failure_for(error: Exception) -> tuple[int, dict[str, Any]]:
    """HTTP status and body for a failed request. Never includes the error text: it can carry secrets."""
    request_id = str(uuid4())
    if isinstance(error, MissingApiKeyError):
        return 401, {"request_id": request_id, "code": "missing_api_key", "message": "Enter your OpenAI API key to continue."}
    try:
        from openai import AuthenticationError
    except ImportError:  # pragma: no cover - openai is a hard dependency
        AuthenticationError = ()  # type: ignore[assignment]
    if AuthenticationError and isinstance(error, AuthenticationError):
        return 401, {"request_id": request_id, "code": "invalid_api_key", "message": "OpenAI rejected your API key. Please enter it again."}
    return 502, {"request_id": request_id, "message": _GENERIC_FAILURE}


def _default_key_validator(key: str) -> KeyCheck:
    load_dotenv(ROOT / ".env")
    config = AppConfig.from_environment()
    return validate_openai_key(key, config.openai_model, config.openai_embedding_model)


class ChatResponse(BaseModel):
    request_id: str
    conversation_id: str
    answer: str
    sql: str | None
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    chart: dict[str, Any] | None
    analysis: dict[str, Any] | None
    suggested_questions: list[str]
    route: str
    citations: list[dict[str, object]]
    assumptions: list[str] = []

    @classmethod
    def from_workflow_answer(cls, result: WorkflowAnswer) -> "ChatResponse":
        return cls(
            request_id=result.request_id,
            conversation_id=result.conversation_id,
            answer=result.answer,
            sql=result.sql,
            columns=result.columns,
            rows=result.rows,
            row_count=len(result.rows),
            chart=result.chart,
            analysis=result.analysis,
            suggested_questions=result.suggested_questions,
            route=result.route,
            citations=result.citations or [],
            assumptions=result.assumptions or [],
        )


def build_document_retriever(config: Any, openai_client: Any) -> DocumentRetriever | None:
    """The RAG branch's retriever over the Larkspur Ridge corpus; None (branch off) without Qdrant + an embedding model."""
    if not config.qdrant_enabled or not config.openai_embedding_model:
        return None
    from qdrant_client import QdrantClient

    return DocumentRetriever(
        OpenAIEmbedder(openai_client, config.openai_embedding_model),
        DocumentQdrantStore(QdrantClient(url=config.qdrant_api_url, api_key=config.qdrant_api_key), DEFAULT_COLLECTION, 1536),
    )


def build_workflow(root: Path = ROOT) -> MultiAgentWorkflow:
    """Build server-only dependencies lazily; no client receives credentials."""
    load_dotenv(root / ".env")
    config = AppConfig.from_environment()
    from openai import OpenAI

    # Each request may bring its own key (X-OpenAI-Key); the server's key is only the fallback for requests without one.
    openai_client = ScopedOpenAI(OpenAI(api_key=config.openai_api_key) if config.openai_api_key else None)
    store = InMemoryConversationStore()

    telemetry: Any = NoopTelemetry()
    if config.langfuse_enabled:
        from langfuse import Langfuse
        telemetry = LangfuseTelemetry(
            Langfuse(
                public_key=config.langfuse_public_key,
                secret_key=config.langfuse_secret_key,
                base_url=config.langfuse_host,
            ),
            verbose=config.langfuse_verbose_tracing,
        )

    retriever = build_document_retriever(config, openai_client)

    mcc_resolver = None
    mcc_embeddings_path = root / "context" / "mcc_embeddings.json"
    if config.openai_embedding_model and mcc_embeddings_path.is_file():
        mcc_resolver = MccResolver.from_cache_file(
            OpenAIEmbedder(openai_client, config.openai_embedding_model),
            mcc_embeddings_path,
        )

    contract = RuntimeContract.from_files(root)
    return MultiAgentWorkflow(
        contract=contract,
        runner=MotherDuckQueryRunner(token=config.motherduck_token),
        specialists=OpenAIResponsesSpecialists(openai_client, config.openai_model, contract, telemetry=telemetry),
        store=store,
        hard_guard=HardGuard(),
        telemetry=telemetry,
        retriever=retriever,
        mcc_resolver=mcc_resolver,
    )


def create_app(
    workflow: Any | None = None,
    key_validator: Callable[[str], KeyCheck] | None = None,
    validate_limit: tuple[int, float] = (10, 60),
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    app = FastAPI(title=SERVICE_NAME, version=SERVICE_VERSION)
    started_at = clock()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-OpenAI-Key"],
    )
    resolved_workflow = workflow
    validate_key = key_validator or _default_key_validator
    limiter = SlidingWindowLimiter(*validate_limit)

    def get_workflow() -> Any:
        nonlocal resolved_workflow
        if resolved_workflow is None:
            resolved_workflow = build_workflow()
        return resolved_workflow

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    @app.get("/api/status")
    def status() -> dict[str, Any]:
        """Shows the backend is up. Cheap by design: no database, OpenAI or configuration access, so it never fails
        or leaks settings. `workflow_ready` is False until the first chat request builds the agent workflow."""
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "uptime_seconds": int(clock() - started_at),
            "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "workflow_ready": resolved_workflow is not None,
        }

    @app.post("/api/validate-key")
    def validate_api_key(body: ValidateKeyRequest, request: Request) -> dict[str, Any]:
        """Tests the key with real (tiny) OpenAI calls. The key is used for this call only and is never echoed or stored."""
        caller = request.client.host if request.client else "unknown"
        if not limiter.allow(caller):
            raise HTTPException(status_code=429, detail={"code": "too_many_attempts", "message": "Too many attempts. Wait a minute and try again."}, headers={"Retry-After": "60"})
        result = validate_key(body.api_key)
        return {"valid": result.valid, "code": result.code, "message": result.message, "checks": result.checks}

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(request: ChatRequest, x_openai_key: str | None = Header(default=None)) -> ChatResponse:
        try:
            with use_api_key((x_openai_key or "").strip() or None):
                result = get_workflow().answer(request.question, request.conversation_id)
        except Exception as error:
            status, detail = _failure_for(error)
            raise HTTPException(status_code=status, detail=detail) from error
        return ChatResponse.from_workflow_answer(result)

    @app.post("/api/chat/stream")
    def chat_stream(request: ChatRequest, x_openai_key: str | None = Header(default=None)) -> StreamingResponse:
        key = (x_openai_key or "").strip() or None

        def events() -> Iterator[str]:
            try:
                stream = iter(get_workflow().stream_answer(request.question, request.conversation_id))
                while True:
                    # The key is scoped around each step, not the whole generator: the server advances this generator
                    # from a different worker thread per step and a context variable does not survive between them.
                    with use_api_key(key):
                        try:
                            kind, payload = next(stream)
                        except StopIteration:
                            break
                    if kind == "progress":
                        yield _sse_event("progress", {"node": payload})
                    elif kind == "thought":
                        yield _sse_event("thought", payload)
                    else:
                        yield _sse_event("result", ChatResponse.from_workflow_answer(payload).model_dump())
            except Exception as error:
                _, detail = _failure_for(error)
                yield _sse_event("error", detail)

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


app = create_app()