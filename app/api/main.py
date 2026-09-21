"""HTTP entry point for the multi-agent text-to-SQL and complaint-RAG backend."""

from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.agents.complaints.retrieval import ComplaintRagRetriever, ComplaintRetrievalAdapter
from app.agents.text_to_sql.contracts import RuntimeContract
from app.agents.text_to_sql.domain_guard import HardGuard
from app.agents.text_to_sql.specialists import OpenAIResponsesSpecialists
from app.agents.text_to_sql.workflow import MultiAgentWorkflow, WorkflowAnswer
from app.helpers.config import AppConfig
from app.helpers.conversation import InMemoryConversationStore, SupabaseConversationStore
from app.helpers.query_runner import MotherDuckQueryRunner
from app.helpers.telemetry import LangfuseTelemetry, NoopTelemetry
from ingestion.complaints.pipeline import OpenAIEmbedder
from ingestion.complaints.qdrant_store import ComplaintQdrantStore


ROOT = Path(__file__).resolve().parents[2]


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
        )


def build_workflow(root: Path = ROOT) -> MultiAgentWorkflow:
    """Build server-only dependencies lazily; no client receives credentials."""
    load_dotenv(root / ".env")
    config = AppConfig.from_environment()
    from openai import OpenAI

    openai_client = OpenAI(api_key=config.openai_api_key)
    store: Any = InMemoryConversationStore()
    if config.supabase_enabled:
        from supabase import create_client
        store = SupabaseConversationStore(create_client(config.supabase_url, config.supabase_key))

    telemetry: Any = NoopTelemetry()
    if config.langfuse_enabled:
        from langfuse import Langfuse
        telemetry = LangfuseTelemetry(Langfuse(public_key=config.langfuse_public_key, secret_key=config.langfuse_secret_key))

    complaint_retriever = None
    if config.qdrant_enabled:
        from qdrant_client import QdrantClient
        complaint_retriever = ComplaintRagRetriever(
            OpenAIEmbedder(openai_client, config.openai_embedding_model),
            ComplaintRetrievalAdapter(
                ComplaintQdrantStore(QdrantClient(url=config.qdrant_api_url, api_key=config.qdrant_api_key)),
                vector_size=1536,
            ),
        )

    contract = RuntimeContract.from_files(root)
    return MultiAgentWorkflow(
        contract=contract,
        runner=MotherDuckQueryRunner(token=config.motherduck_token),
        specialists=OpenAIResponsesSpecialists(openai_client, config.openai_model, contract),
        store=store,
        hard_guard=HardGuard(),
        telemetry=telemetry,
        complaint_retriever=complaint_retriever,
    )


def create_app(workflow: Any | None = None) -> FastAPI:
    app = FastAPI(title="Financial Multi-Agent Text-to-SQL", version="0.3.0")
    resolved_workflow = workflow

    def get_workflow() -> Any:
        nonlocal resolved_workflow
        if resolved_workflow is None:
            resolved_workflow = build_workflow()
        return resolved_workflow

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        try:
            result = get_workflow().answer(request.question, request.conversation_id)
        except Exception as error:
            request_id = str(uuid4())
            raise HTTPException(
                status_code=502,
                detail={"request_id": request_id, "message": "The analysis request could not be completed. Please try again."},
            ) from error
        return ChatResponse.from_workflow_answer(result)

    return app


app = create_app()