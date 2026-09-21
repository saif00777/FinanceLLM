"""Bounded LangGraph orchestration for the read-only financial assistant."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from operator import add
from typing import Annotated, Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.agents.complaints.retrieval import ComplaintRetriever
from app.agents.text_to_sql.contracts import LinkedContext, RuntimeContract
from app.agents.text_to_sql.domain_guard import HardGuard
from app.agents.text_to_sql.specialists import Specialists
from app.helpers.conversation import ConversationFacts, ConversationStore, ConversationTurn
from app.helpers.query_runner import QueryRunner
from app.helpers.sql_policy import SqlPolicy, SqlPolicyError
from app.helpers.telemetry import NoopTelemetry, Telemetry


class AgentState(TypedDict, total=False):
    question: str
    conversation_id: str
    facts: ConversationFacts
    route: str
    reason_code: str
    sources: tuple[str, ...]
    active_sources: tuple[str, ...]
    plan: Any
    linked: LinkedContext
    metric_context: dict[str, str]
    proposal: Any
    sql: str
    sql_route: str
    sql_answer: str
    repair_error: str
    repairs: int
    executions: int
    result: Any
    answer: str
    chart: dict[str, Any] | None
    analysis: dict[str, Any] | None
    grounding: str
    rag_route: str
    rag_message: str
    suggested_questions: list[str]
    specialist_path: Annotated[list[str], add]
    citations: list[dict[str, object]]
    documents: list[Any]


@dataclass(frozen=True)
class WorkflowAnswer:
    request_id: str
    conversation_id: str
    answer: str
    sql: str | None
    columns: list[str]
    rows: list[list[Any]]
    chart: dict[str, Any] | None
    analysis: dict[str, Any] | None
    suggested_questions: list[str]
    route: str
    executions: int = 0
    repairs: int = 0
    specialist_path: list[str] | None = None
    result_digest: str | None = None
    grounding: str | None = None
    citations: list[dict[str, object]] | None = None


class MultiAgentWorkflow:
    """Explicitly bounded agent graph; application code retains all tool authority."""

    def __init__(
        self,
        contract: RuntimeContract,
        runner: QueryRunner,
        specialists: Specialists,
        store: ConversationStore,
        hard_guard: HardGuard,
        policy: SqlPolicy | None = None,
        telemetry: Telemetry | None = None,
        complaint_retriever: ComplaintRetriever | None = None,
    ):
        self._contract = contract
        self._runner = runner
        self._specialists = specialists
        self._store = store
        self._hard_guard = hard_guard
        self._policy = policy or SqlPolicy()
        self._telemetry = telemetry or NoopTelemetry()
        self._complaint_retriever = complaint_retriever
        self._graph = self._build_graph()

    def _traced(self, name: str, handler):
        def run(state: AgentState) -> dict[str, Any]:
            attributes = self._telemetry.safe_attributes(
                question=state.get("question", ""),
                route=state.get("route", "pending"),
                node=name,
                repair_count=state.get("repairs", 0),
                execution_count=state.get("executions", 0),
                rows=getattr(state.get("result"), "rows", []),
            )
            with self._telemetry.span(name, attributes):
                output = handler(state)
            return {**output, "specialist_path": [name]}
        return run

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("hard_guard", self._traced("hard_guard", self._hard_guard_node))
        graph.add_node("domain_guard", self._traced("domain_guard", self._domain_guard_node))
        graph.add_node("document_router", self._traced("document_router", self._document_router_node))
        graph.add_node("complaint_retrieval", self._traced("complaint_retrieval", self._complaint_retrieval_node))
        graph.add_node("planner", self._traced("planner", self._planner_node))
        graph.add_node("schema_link", self._traced("schema_link", self._schema_link_node))
        graph.add_node("metric_resolver", self._traced("metric_resolver", self._metric_resolver_node))
        graph.add_node("sql_generator", self._traced("sql_generator", self._sql_generator_node))
        graph.add_node("sql_policy", self._traced("sql_policy", self._sql_policy_node))
        graph.add_node("executor", self._traced("executor", self._executor_node))
        graph.add_node("data_analysis", self._traced("data_analysis", self._data_analysis_node))
        graph.add_node("analyst", self._traced("analyst", self._analyst_node))
        graph.add_node("reviewer", self._traced("reviewer", self._reviewer_node))
        graph.add_node("suggestions", self._traced("suggestions", self._suggestions_node))
        graph.add_node("merge_results", self._traced("merge_results", self._merge_results_node))
        graph.add_edge(START, "hard_guard")
        graph.add_conditional_edges("hard_guard", self._after_hard_guard, {"domain_guard": "domain_guard", "suggestions": "suggestions"})
        graph.add_conditional_edges("domain_guard", self._after_domain_guard, {"document_router": "document_router", "suggestions": "suggestions"})
        graph.add_conditional_edges("document_router", self._after_document_router, {"planner": "planner", "complaint_retrieval": "complaint_retrieval"})
        graph.add_conditional_edges("complaint_retrieval", self._after_complaint_retrieval_routing, {"planner": "planner", "merge_results": "merge_results"})
        graph.add_edge("planner", "schema_link")
        graph.add_edge("planner", "metric_resolver")
        graph.add_edge(["schema_link", "metric_resolver"], "sql_generator")
        graph.add_edge("sql_generator", "sql_policy")
        graph.add_conditional_edges("sql_policy", self._after_policy, {"executor": "executor", "sql_generator": "sql_generator", "merge_results": "merge_results"})
        graph.add_edge("executor", "data_analysis")
        graph.add_edge("executor", "analyst")
        graph.add_edge(["data_analysis", "analyst"], "reviewer")
        graph.add_edge("reviewer", "merge_results")
        graph.add_edge("merge_results", "suggestions")
        graph.add_edge("suggestions", END)
        return graph.compile()

    def answer(self, question: str, conversation_id: str | None = None) -> WorkflowAnswer:
        context = self._store.load(conversation_id)
        context = self._store.append(context, ConversationTurn.user(question.strip()))
        state = self._graph.invoke({
            "question": question.strip(),
            "conversation_id": context.id,
            "facts": context.facts,
            "repairs": 0,
            "executions": 0,
            "specialist_path": [],
        })
        route = state.get("route", "clarify")
        answer = state.get("answer") or self._message_for_route(route)
        context = self._store.append(context, ConversationTurn.assistant(answer))
        result = state.get("result")
        result_digest = self._result_digest(result.columns, result.rows) if result else None
        context = self._store.update_facts(context, self._conversation_facts(state, result_digest))
        return WorkflowAnswer(
            request_id=str(uuid4()),
            conversation_id=context.id,
            answer=answer,
            sql=state.get("sql"),
            columns=result.columns if result else [],
            rows=result.rows if result else [],
            chart=state.get("chart"),
            analysis=state.get("analysis"),
            suggested_questions=state.get("suggested_questions", []),
            route=route,
            executions=state.get("executions", 0),
            repairs=state.get("repairs", 0),
            specialist_path=state.get("specialist_path", []),
            result_digest=result_digest,
            grounding=state.get("grounding"),
            citations=state.get("citations", []),
        )

    def _conversation_facts(self, state: AgentState, result_digest: str | None) -> ConversationFacts:
        linked = state.get("linked")
        metric_context = state.get("metric_context", {})
        plan = state.get("plan")
        sql = state.get("sql")
        prior_filters = dict(state["facts"].resolved_filters)
        planned_filters = getattr(plan, "resolved_filters", {})
        if isinstance(planned_filters, dict):
            prior_filters.update(planned_filters)
        return ConversationFacts(
            resolved_metric=metric_context.get("resolved_metric") or metric_context.get("metric"),
            resolved_filters=prior_filters,
            selected_relation_ids=linked.relations if linked else (),
            last_sql_hash=sha256(sql.encode("utf-8")).hexdigest() if sql else None,
            result_digest=result_digest,
            semantic_version=str(self._contract.semantics.get("version", "2.0.0")),
        )

    @staticmethod
    def _result_digest(columns: list[str], rows: list[list[Any]]) -> str:
        canonical = json.dumps({"columns": columns, "rows": rows}, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(canonical.encode("utf-8")).hexdigest()

    def _hard_guard_node(self, state: AgentState) -> dict[str, Any]:
        verdict = self._hard_guard.evaluate(state["question"])
        return {"route": "pending" if verdict.route == "allow" else verdict.route, "reason_code": verdict.reason_code}

    @staticmethod
    def _after_hard_guard(state: AgentState) -> str:
        return "domain_guard" if state["route"] == "pending" else "suggestions"

    def _domain_guard_node(self, state: AgentState) -> dict[str, Any]:
        decision = self._specialists.domain_guard(state["question"], state["facts"])
        return {
            "route": "in_scope" if decision.route == "in_scope" else decision.route,
            "reason_code": decision.reason_code,
            "sources": decision.sources,
        }

    @staticmethod
    def _after_domain_guard(state: AgentState) -> str:
        return "document_router" if state["route"] == "in_scope" else "suggestions"

    def _document_router_node(self, state: AgentState) -> dict[str, Any]:
        sources = set(state.get("sources", ("sql",)))
        if "rag" in sources and self._complaint_retriever is None:
            sources.discard("rag")
        return {"active_sources": tuple(sorted(sources)) or ("sql",)}

    @staticmethod
    def _after_document_router(state: AgentState) -> str:
        return "complaint_retrieval" if "rag" in state["active_sources"] else "planner"

    @staticmethod
    def _after_complaint_retrieval_routing(state: AgentState) -> str:
        return "planner" if "sql" in state["active_sources"] else "merge_results"

    def _complaint_retrieval_node(self, state: AgentState) -> dict[str, Any]:
        if self._complaint_retriever is None:
            return {"rag_route": "clarify", "rag_message": "Complaint retrieval is not configured."}
        documents = self._complaint_retriever.retrieve(state["question"])
        citations = [{"source_hash": document.citation} for document in documents]
        if not documents:
            return {"rag_route": "answered", "rag_message": "I could not find a matching consented complaint narrative.", "documents": [], "citations": [], "grounding": "approved"}
        return {
            "rag_route": "answered",
            "rag_message": f"I found {len(documents)} relevant consented complaint narrative(s). The cited excerpts are redacted and the complaint branch did not query financial transactions.",
            "documents": documents,
            "citations": citations,
            "grounding": "approved",
        }

    def _planner_node(self, state: AgentState) -> dict[str, Any]:
        return {"plan": self._specialists.plan(state["question"], state["facts"])}

    def _schema_link_node(self, state: AgentState) -> dict[str, Any]:
        return {"linked": self._specialists.schema_link(state["question"], self._contract)}

    def _metric_resolver_node(self, state: AgentState) -> dict[str, Any]:
        return {"metric_context": self._specialists.metric_resolution(state["question"], self._contract)}

    def _sql_generator_node(self, state: AgentState) -> dict[str, Any]:
        linked = state["linked"]
        metric_context = state.get("metric_context", {})
        if metric_context:
            resolved = "; ".join(
                f"{key.replace('_', ' ').title()}: {value}"
                for key, value in metric_context.items()
            )
            linked = LinkedContext(
                relations=linked.relations,
                prompt=f"{linked.prompt}\nResolved metric context: {resolved}",
            )
        return {"proposal": self._specialists.generate_sql(state["question"], linked, state["facts"], state.get("repair_error"))}

    def _sql_policy_node(self, state: AgentState) -> dict[str, Any]:
        proposal = state["proposal"]
        if not proposal.sql:
            return {"sql_route": "clarify", "sql_answer": proposal.clarification or "Please clarify the requested analysis."}
        try:
            return {"sql": self._policy.validate(proposal.sql), "sql_route": "approved"}
        except SqlPolicyError as error:
            return {"sql_route": "repair", "repair_error": str(error), "repairs": state["repairs"] + 1}

    @staticmethod
    def _after_policy(state: AgentState) -> str:
        if state["sql_route"] == "approved":
            return "executor"
        if state["sql_route"] == "repair" and state["repairs"] <= 2:
            return "sql_generator"
        return "merge_results"

    def _executor_node(self, state: AgentState) -> dict[str, Any]:
        if state["executions"] >= 1:
            return {"sql_route": "clarify", "sql_answer": "The request exceeded its query budget."}
        result = self._runner.run(state["sql"])
        return {"result": result, "executions": state["executions"] + 1, "sql_route": "answered"}

    def _data_analysis_node(self, state: AgentState) -> dict[str, Any]:
        result = state["result"]
        analysis = self._specialists.data_analysis(state["question"], result.columns, result.rows)
        return {"analysis": {"summary": analysis.summary, "insights": analysis.insights, "caveats": analysis.caveats}}

    def _analyst_node(self, state: AgentState) -> dict[str, Any]:
        result = state["result"]
        grounded = self._specialists.analyze(state["question"], result.columns, result.rows, state["proposal"])
        return {"sql_answer": grounded.answer, "chart": grounded.chart}

    def _reviewer_node(self, state: AgentState) -> dict[str, Any]:
        result = state["result"]
        decision = self._specialists.review(state["question"], result.columns, result.rows, state.get("sql_answer", ""), state.get("analysis"))
        if decision.approved:
            return {"sql_route": "answered", "reason_code": decision.reason_code, "grounding": "approved"}
        return {
            "sql_route": "clarify",
            "reason_code": decision.reason_code,
            "grounding": decision.reason_code,
            "sql_answer": "The returned result needs a narrower question before I can give a grounded answer.",
        }

    def _merge_results_node(self, state: AgentState) -> dict[str, Any]:
        sql_route = state.get("sql_route")
        rag_route = state.get("rag_route")
        parts = []
        if sql_route is not None:
            sql_answer = state.get("sql_answer")
            if sql_answer:
                parts.append(sql_answer)
        if rag_route is not None:
            rag_message = state["rag_message"]
            parts.append(f"Consumer complaint narratives found: {rag_message}" if sql_route is not None else rag_message)
        route = "answered" if "answered" in (sql_route, rag_route) else (sql_route or rag_route)
        return {"answer": "\n\n".join(parts), "route": route}

    def _suggestions_node(self, state: AgentState) -> dict[str, Any]:
        linked = state.get("linked")
        relations = linked.relations if linked else ()
        return {"suggested_questions": self._specialists.suggest(state["question"], state["facts"], relations)}

    @staticmethod
    def _message_for_route(route: str) -> str:
        if route == "abstain":
            return "I can help with approved aggregate exploration of the financial dataset, but not that request."
        return "Please clarify the metric, time period, or approved dataset dimension you want to explore."