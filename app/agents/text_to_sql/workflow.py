"""Bounded LangGraph orchestration for the read-only financial assistant."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from operator import add
from typing import Annotated, Any, Iterator, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.agents.rag import Retriever
from app.agents.text_to_sql.contracts import LinkedContext, RuntimeContract
from app.agents.text_to_sql.domain_guard import HardGuard
from app.agents.text_to_sql.specialists import NOT_FOUND_IN_DOCUMENTS, Specialists
from app.helpers.conversation import ConversationContext, ConversationFacts, ConversationStore, ConversationTurn
from app.helpers.mcc_resolver import MccResolver
from app.helpers.query_runner import QueryRunner
from app.helpers.sql_policy import SqlPolicy, SqlPolicyError
from app.helpers.telemetry import NoopTelemetry, Telemetry


class AgentState(TypedDict, total=False):
    question: str
    conversation_id: str
    trace_id: str
    recent_questions: list[str]
    facts: ConversationFacts
    route: str
    reason_code: str
    clarification: str
    sources: tuple[str, ...]
    active_sources: tuple[str, ...]
    plan: Any
    linked: LinkedContext
    metric_context: dict[str, str]
    mcc_context: dict[str, str]
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
    assumptions: list[str] | None = None


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
        retriever: Retriever | None = None,
        mcc_resolver: MccResolver | None = None,
    ):
        self._contract = contract
        self._runner = runner
        self._specialists = specialists
        self._store = store
        self._hard_guard = hard_guard
        self._policy = policy or SqlPolicy()
        self._telemetry = telemetry or NoopTelemetry()
        self._retriever = retriever
        self._mcc_resolver = mcc_resolver
        self._graph = self._build_graph()

    def _traced(self, name: str, handler):
        def run(state: AgentState) -> dict[str, Any]:
            # Raw, not pre-redacted: Telemetry.safe_attributes() is the single place
            # redaction happens (inside span()) -- passing already-redacted values here
            # would silently drop fields on a second pass (e.g. question_hash, row_count
            # match none of safe_attributes()'s three branches on their own field names).
            attributes = dict(
                question=state.get("question", ""),
                route=state.get("route", "pending"),
                node=name,
                repair_count=state.get("repairs", 0),
                execution_count=state.get("executions", 0),
                rows=getattr(state.get("result"), "rows", []),
            )
            with self._telemetry.span(
                name, attributes, trace_id=state.get("trace_id"), session_id=state.get("conversation_id")
            ) as recorder:
                output = handler(state)
                recorder.record_output(output)
            return {**output, "specialist_path": [name]}
        return run

    _CONTEXT_NODES = ("schema_link", "metric_resolver", "mcc_resolver")

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("hard_guard", self._traced("hard_guard", self._hard_guard_node))
        graph.add_node("domain_guard", self._traced("domain_guard", self._domain_guard_node))
        graph.add_node("document_router", self._traced("document_router", self._document_router_node))
        graph.add_node("document_retrieval", self._traced("document_retrieval", self._document_retrieval_node))
        graph.add_node("planner", self._traced("planner", self._planner_node))
        graph.add_node("schema_link", self._traced("schema_link", self._schema_link_node))
        graph.add_node("metric_resolver", self._traced("metric_resolver", self._metric_resolver_node))
        graph.add_node("mcc_resolver", self._traced("mcc_resolver", self._mcc_resolver_node))
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
        graph.add_conditional_edges("domain_guard", self._after_domain_guard, {"planner": "planner", "suggestions": "suggestions"})
        graph.add_edge("planner", "document_router")
        # A conditional edge may return several node names: the SQL context stage fans out to its three
        # parallel nodes, which the bundled join below waits for. (Spike-verified with this LangGraph:
        # every branch mix fires sql_generator, merge_results and suggestions exactly once.)
        context_targets = {name: name for name in self._CONTEXT_NODES}
        graph.add_conditional_edges("document_router", self._after_document_router, {"document_retrieval": "document_retrieval", **context_targets})
        graph.add_conditional_edges("document_retrieval", self._after_document_retrieval_routing, {"merge_results": "merge_results", **context_targets})
        graph.add_edge(list(self._CONTEXT_NODES), "sql_generator")
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
        recent_questions = self._recent_user_questions(context)
        context = self._store.append(context, ConversationTurn.user(question.strip()))
        request_uuid = uuid4()
        state = self._graph.invoke({
            "question": question.strip(),
            "conversation_id": context.id,
            "facts": context.facts,
            "repairs": 0,
            "executions": 0,
            "specialist_path": [],
            "trace_id": request_uuid.hex,
            "recent_questions": recent_questions,
        })
        return self._finalize(context, state, request_id=str(request_uuid))

    def stream_answer(self, question: str, conversation_id: str | None = None) -> Iterator[tuple[str, Any]]:
        """Yield ("progress", node_name) as each graph node completes, then ("result", WorkflowAnswer)."""
        context = self._store.load(conversation_id)
        recent_questions = self._recent_user_questions(context)
        context = self._store.append(context, ConversationTurn.user(question.strip()))
        request_uuid = uuid4()
        state: dict[str, Any] = {
            "question": question.strip(),
            "conversation_id": context.id,
            "facts": context.facts,
            "repairs": 0,
            "executions": 0,
            "specialist_path": [],
            "trace_id": request_uuid.hex,
            "recent_questions": recent_questions,
        }
        accumulated: dict[str, Any] = dict(state)
        for update in self._graph.stream(state, stream_mode="updates"):
            for node_name, output in update.items():
                # specialist_path uses an `add` reducer (Annotated[list[str], add]) inside the
                # graph; stream_mode="updates" reports each node's raw delta, not the reduced
                # value, so it must be concatenated here rather than overwritten.
                path_delta = output.get("specialist_path")
                prior_path = accumulated.get("specialist_path", [])
                accumulated.update(output)
                if path_delta is not None:
                    accumulated["specialist_path"] = prior_path + list(path_delta)
                yield ("progress", node_name)
                thought = self._thought(node_name, output, accumulated)
                if thought:
                    yield ("thought", {"node": node_name, "text": thought})
        yield ("result", self._finalize(context, accumulated, request_id=str(request_uuid)))

    _RECENT_QUESTION_LIMIT = 3

    @classmethod
    def _recent_user_questions(cls, context: ConversationContext) -> list[str]:
        """Earlier user questions (already PII-redacted by the store), oldest first, excluding the current turn."""
        return [turn.content for turn in context.turns if turn.role == "user"][-cls._RECENT_QUESTION_LIMIT:]

    @staticmethod
    def _facts_with_history(state: AgentState) -> dict[str, Any]:
        """Facts as the interpreting agents see them. The persisted ConversationFacts deliberately
        has no field for raw text, so recent questions are added to this per-call view only."""
        return {**state["facts"], "recent_user_questions": state.get("recent_questions", [])}

    @staticmethod
    def _question_for(state: AgentState) -> str:
        """The planner's self-contained rewrite when there is one, else what the user typed."""
        plan = state.get("plan")
        return (getattr(plan, "standalone_question", "") or state["question"]) if plan else state["question"]

    @classmethod
    def _facts_for_planner(cls, state: AgentState) -> dict[str, Any]:
        recent = state.get("recent_questions", [])
        return {
            **cls._facts_with_history(state),
            "most_recent_earlier_question": recent[-1] if recent else None,
            "sources": state.get("sources", ("sql",)),
        }

    def _finalize(self, context: ConversationContext, state: dict[str, Any], request_id: str) -> WorkflowAnswer:
        route = state.get("route", "clarify")
        clarification = state.get("clarification") if route == "clarify" else None
        answer = state.get("answer") or clarification or self._message_for_route(route, state.get("sources", ("sql",)))
        context = self._store.append(context, ConversationTurn.assistant(answer))
        result = state.get("result")
        result_digest = self._result_digest(result.columns, result.rows) if result else None
        context = self._store.update_facts(context, self._conversation_facts(state, result_digest))
        return WorkflowAnswer(
            request_id=request_id,
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
            assumptions=self._assumptions(state),
        )

    @staticmethod
    def _assumptions(state: dict[str, Any]) -> list[str]:
        """What the bot took for granted, in plain words: the planner's own list plus what the code resolved."""
        plan = state.get("plan")
        if plan is None:
            return []
        found = list(getattr(plan, "assumptions", ()) or ())
        rewrite = getattr(plan, "standalone_question", "")
        if rewrite and rewrite.strip().lower() != state["question"].strip().lower():
            found.append(f"Read your question as: {rewrite}")
        filters = getattr(plan, "resolved_filters", {}) or {}
        if filters:
            found.append("Applied filters: " + ", ".join(f"{key} = {value}" for key, value in filters.items()))
        metric_context = state.get("metric_context") or {}
        metric = metric_context.get("resolved_metric") or metric_context.get("metric")
        if metric:
            found.append(f"Used the governed metric: {metric}")
        mcc = (state.get("mcc_context") or {}).get("resolved_mcc_codes")
        if mcc:
            found.append(f"Matched merchant categories by meaning: {mcc}")
        return found

    @staticmethod
    def _thought(node: str, output: dict[str, Any], state: dict[str, Any]) -> str | None:
        """A short plain-language account of what an agent just decided. Never includes result rows."""
        if node == "hard_guard":
            return "Request passed the safety checks." if output.get("route") == "pending" else f"Blocked: {output.get('reason_code')}."
        if node == "domain_guard":
            sources = " and ".join(output.get("sources", ())) or "sql"
            return f"Route: {output.get('route')} ({output.get('reason_code')}). Data needed: {sources}."
        if node == "planner":
            plan = output["plan"]
            lines = [f"Plan: {plan.rationale}"]
            if plan.standalone_question:
                lines.append(f"Understood as: {plan.standalone_question}")
            if plan.sql_guidance:
                lines.append(f"Query guidance: {plan.sql_guidance}")
            return "\n".join(lines)
        if node == "document_router":
            return "Using: " + " and ".join(output.get("active_sources", ())) + "."
        if node == "document_retrieval":
            documents = output.get("documents") or []
            if not documents:
                return output.get("rag_message")
            return "Retrieved: " + "; ".join(f"{d.citation} {d.payload.get('title', '')}".strip() for d in documents) + "."
        if node == "schema_link":
            return "Relevant tables: " + (", ".join(output["linked"].relations) or "none") + "."
        if node == "metric_resolver":
            metric = output.get("metric_context") or {}
            name = metric.get("resolved_metric") or metric.get("metric")
            return f"Metric: {name}." if name else "No governed metric matched."
        if node == "mcc_resolver":
            return (output.get("mcc_context") or {}).get("resolved_mcc_codes") or "No merchant categories matched."
        if node == "sql_generator":
            return output["proposal"].sql or "No query was returned."
        if node == "sql_policy":
            if output.get("sql_route") == "approved":
                return "Approved: " + (", ".join(SqlPolicy.relations_used(output["sql"])) or "query") + " is allowed to run."
            return f"Rejected, rewriting (attempt {output.get('repairs')}): {output.get('repair_error')}"
        if node == "executor":
            result = output.get("result")
            if result is None:
                return output.get("sql_answer")
            count = len(result.rows)
            return f"Query returned {count} row{'s' if count != 1 else ''}."
        if node == "data_analysis":
            return (output.get("analysis") or {}).get("summary")
        if node == "analyst":
            return output.get("sql_answer")
        if node == "reviewer":
            return f"Answer checked against the rows: {output.get('reason_code')}."
        if node == "suggestions":
            count = len(output.get("suggested_questions", ()))
            return f"Prepared {count} follow-up question{'s' if count != 1 else ''}."
        return None

    def _conversation_facts(self, state: AgentState, result_digest: str | None) -> ConversationFacts:
        linked = state.get("linked")
        metric_context = state.get("metric_context", {})
        plan = state.get("plan")
        sql = state.get("sql")
        used_relations = SqlPolicy.relations_used(sql) if sql else ()
        prior_filters = dict(state["facts"].resolved_filters)
        planned_filters = getattr(plan, "resolved_filters", {})
        if isinstance(planned_filters, dict):
            prior_filters.update(planned_filters)
        return ConversationFacts(
            resolved_metric=metric_context.get("resolved_metric") or metric_context.get("metric"),
            resolved_filters=prior_filters,
            selected_relation_ids=used_relations or (linked.relations if linked else ()),
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
        decision = self._specialists.domain_guard(state["question"], self._facts_with_history(state))
        return {
            "route": "in_scope" if decision.route == "in_scope" else decision.route,
            "reason_code": decision.reason_code,
            "sources": decision.sources,
            "clarification": decision.clarification or "",
        }

    @staticmethod
    def _after_domain_guard(state: AgentState) -> str:
        return "planner" if state["route"] == "in_scope" else "suggestions"

    def _document_router_node(self, state: AgentState) -> dict[str, Any]:
        sources = set(state.get("sources", ("sql",)))
        if "rag" in sources and self._retriever is None:
            sources.discard("rag")
        return {"active_sources": tuple(sorted(sources)) or ("sql",)}

    @classmethod
    def _after_document_router(cls, state: AgentState) -> str | list[str]:
        return "document_retrieval" if "rag" in state["active_sources"] else list(cls._CONTEXT_NODES)

    @classmethod
    def _after_document_retrieval_routing(cls, state: AgentState) -> str | list[str]:
        return list(cls._CONTEXT_NODES) if "sql" in state["active_sources"] else "merge_results"

    _CITATION_FIELDS = ("title", "doc_type", "category", "date")
    _MAX_DOCUMENTS = 10

    def _retrieve_documents(self, rewrite: str, original: str) -> list[Any]:
        """Retrieve with the user's own wording as well as the planner's rewrite, then merge round-robin (original
        first) without duplicates. The rewrite can drift (e.g. it may add the bank's name, which every document
        matches), so the original wording is a second, independent query."""
        by_query = [self._retriever.retrieve(rewrite)]
        if original.strip().lower() != rewrite.strip().lower():
            by_query.insert(0, self._retriever.retrieve(original))
        merged: list[Any] = []
        seen: set[str] = set()
        for rank in range(max(len(docs) for docs in by_query)):
            for docs in by_query:
                if rank < len(docs) and docs[rank].citation not in seen:
                    seen.add(docs[rank].citation)
                    merged.append(docs[rank])
        return merged[: self._MAX_DOCUMENTS]

    def _document_retrieval_node(self, state: AgentState) -> dict[str, Any]:
        if self._retriever is None:
            return {"rag_route": "clarify", "rag_message": "Document retrieval is not configured."}
        question = self._question_for(state)
        documents = self._retrieve_documents(question, state["question"])
        if not documents:
            return {"rag_route": "answered", "rag_message": NOT_FOUND_IN_DOCUMENTS, "documents": [], "citations": [], "grounding": "approved"}
        answer = self._specialists.answer_documents(question, documents, plan=state.get("plan"))
        cited = set(answer.cited_doc_ids)
        citations = [
            {"source_hash": document.citation, **{key: document.payload[key] for key in self._CITATION_FIELDS if key in document.payload}}
            for document in documents
            if document.citation in cited
        ]
        return {"rag_route": "answered", "rag_message": answer.answer, "documents": documents, "citations": citations, "grounding": "approved"}

    def _planner_node(self, state: AgentState) -> dict[str, Any]:
        return {"plan": self._specialists.plan(state["question"], self._facts_for_planner(state))}

    def _schema_link_node(self, state: AgentState) -> dict[str, Any]:
        return {"linked": self._specialists.schema_link(self._question_for(state), self._contract, prior_relations=state["facts"].selected_relation_ids)}

    def _metric_resolver_node(self, state: AgentState) -> dict[str, Any]:
        return {"metric_context": self._specialists.metric_resolution(self._question_for(state), self._contract)}

    def _mcc_resolver_node(self, state: AgentState) -> dict[str, Any]:
        if self._mcc_resolver is None:
            return {"mcc_context": {}}
        matches = self._mcc_resolver.resolve(self._question_for(state))
        if not matches:
            return {"mcc_context": {}}
        resolved = "; ".join(f"{match.mcc} {match.description} (similarity {match.score:.2f})" for match in matches)
        return {"mcc_context": {"resolved_mcc_codes": resolved}}

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
        mcc_context = state.get("mcc_context", {})
        if mcc_context.get("resolved_mcc_codes"):
            linked = LinkedContext(
                relations=linked.relations,
                prompt=f"{linked.prompt}\nResolved MCC context: {mcc_context['resolved_mcc_codes']}",
            )
        return {"proposal": self._specialists.generate_sql(self._question_for(state), linked, dict(state["facts"]), state.get("repair_error"), plan=state.get("plan"))}

    _NO_SQL_ERROR = 'No SQL query was returned. Return a JSON object whose "sql" key holds one SELECT query.'

    def _sql_policy_node(self, state: AgentState) -> dict[str, Any]:
        proposal = state["proposal"]
        if not proposal.sql:
            # Only the domain guard may ask the user anything; a SQL agent that returns nothing is a failed attempt.
            return {"sql_route": "repair", "repair_error": self._NO_SQL_ERROR, "repairs": state["repairs"] + 1}
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
        analysis = self._specialists.data_analysis(self._question_for(state), result.columns, result.rows, plan=state.get("plan"))
        return {"analysis": {"summary": analysis.summary, "insights": analysis.insights, "caveats": analysis.caveats}}

    def _analyst_node(self, state: AgentState) -> dict[str, Any]:
        result = state["result"]
        grounded = self._specialists.analyze(self._question_for(state), result.columns, result.rows, state["proposal"], plan=state.get("plan"))
        return {"sql_answer": grounded.answer, "chart": grounded.chart}

    def _reviewer_node(self, state: AgentState) -> dict[str, Any]:
        result = state["result"]
        decision = self._specialists.review(self._question_for(state), result.columns, result.rows, state.get("sql_answer", ""), state.get("analysis"), plan=state.get("plan"))
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
            parts.append(f"From the documents: {rag_message}" if sql_route is not None else rag_message)
        route = "answered" if "answered" in (sql_route, rag_route) else (sql_route or rag_route)
        return {"answer": "\n\n".join(parts), "route": route}

    def _suggestions_node(self, state: AgentState) -> dict[str, Any]:
        linked = state.get("linked")
        relations = SqlPolicy.relations_used(state["sql"]) if state.get("sql") else (linked.relations if linked else ())
        result = state.get("result")
        return {
            "suggested_questions": self._specialists.suggest(
                state["question"], self._facts_with_history(state), relations,
                plan=state.get("plan"), route=state.get("route"), columns=result.columns if result else (),
            )
        }

    @staticmethod
    def _message_for_route(route: str, sources: tuple[str, ...] = ("sql",)) -> str:
        if route == "abstain":
            return "I can help with approved aggregate exploration of the financial dataset, but not that request."
        if route == "repair":
            return "I couldn't turn that into a valid query. Please try rephrasing your question."
        wants_sql = "sql" in sources
        wants_rag = "rag" in sources
        if wants_rag and not wants_sql:
            return "Please clarify what you'd like to look up in the documents."
        if wants_sql and wants_rag:
            return (
                "Please clarify what you'd like explored — the metric, time period, or dataset dimension for "
                "transaction data, and/or the topic to look up in the documents."
            )
        return "Please clarify the metric, time period, or approved dataset dimension you want to explore."