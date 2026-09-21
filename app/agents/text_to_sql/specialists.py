from __future__ import annotations

"""Provider-neutral specialist contracts and bounded OpenAI implementations."""

from dataclasses import dataclass, field
import json
from typing import Any, Protocol

from app.agents.text_to_sql.contracts import LinkedContext


@dataclass(frozen=True)
class DomainDecision:
    route: str
    reason_code: str
    sources: tuple[str, ...] = ("sql",)


@dataclass(frozen=True)
class TaskPlan:
    intent: str
    rationale: str
    resolved_filters: dict[str, str | int | float | bool | None] = field(default_factory=dict)


@dataclass(frozen=True)
class SqlProposal:
    sql: str | None
    clarification: str | None = None


@dataclass(frozen=True)
class DataAnalysis:
    summary: str
    insights: list[str]
    caveats: list[str]


@dataclass(frozen=True)
class GroundedAnswer:
    answer: str
    chart: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReviewDecision:
    approved: bool
    reason_code: str


class Specialists(Protocol):
    def domain_guard(self, question: str, facts: dict[str, str]) -> DomainDecision: ...
    def plan(self, question: str, facts: dict[str, str]) -> TaskPlan: ...
    def schema_link(self, question: str, catalog: Any) -> LinkedContext: ...
    def metric_resolution(self, question: str, catalog: Any) -> dict[str, str]: ...
    def generate_sql(self, question: str, linked: LinkedContext, facts: dict[str, str], repair_error: str | None) -> SqlProposal: ...
    def data_analysis(self, question: str, columns: list[str], rows: list[list[Any]]) -> DataAnalysis: ...
    def analyze(self, question: str, columns: list[str], rows: list[list[Any]], proposal: SqlProposal) -> GroundedAnswer: ...
    def review(self, question: str, columns: list[str], rows: list[list[Any]], answer: str, analysis: dict[str, Any] | None) -> ReviewDecision: ...
    def suggest(self, question: str, facts: dict[str, str], relations: tuple[str, ...]) -> list[str]: ...


class DeterministicSuggestedQuestionSpecialist:
    """Catalog-bounded fallbacks used for answered and clarification paths."""

    def suggest(self, question: str, facts: dict[str, str], relations: tuple[str, ...]) -> list[str]:
        lower = question.lower()
        filters = facts.get("resolved_filters", {}) if isinstance(facts.get("resolved_filters", {}), dict) else {}
        year = filters.get("year", facts.get("year", "the selected period"))
        suggestions: list[str] = []
        if relations and "transaction" in relations[0]:
            suggestions.append(f"Show monthly recorded transaction count for {year}.")
        if "spend" in lower or "amount" in lower:
            suggestions.append(f"Compare net signed recorded amount with positive recorded amounts for {year}.")
        if "main.mcc_codes" in relations or "category" in lower:
            suggestions.append("Break the recorded amounts down by merchant category.")
        if not suggestions:
            suggestions.append("Show recorded transaction count by transaction method.")
        return suggestions[:3]


class OpenAIResponsesSpecialists:
    """Initial provider adapter; other providers can implement ``Specialists``."""

    def __init__(self, client: Any, model: str, catalog: Any):
        self._client, self._model, self._catalog = client, model, catalog
        self._fallback_suggester = DeterministicSuggestedQuestionSpecialist()

    def _json(self, instructions: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.responses.create(
            model=self._model, instructions=instructions, input=json.dumps(payload), store=False
        )
        parsed = json.loads(response.output_text)
        if not isinstance(parsed, dict):
            raise ValueError("Specialist response must be a JSON object")
        return parsed

    @staticmethod
    def _text_list(value: Any, maximum: int = 5) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()][:maximum]

    _VALID_SOURCES = frozenset({"sql", "rag"})

    def domain_guard(self, question: str, facts: dict[str, str]) -> DomainDecision:
        data = self._json(
            "Return JSON with route, reason_code, and sources. Use in_scope, clarify, or abstain for route. "
            "sources is an array containing sql and/or rag, for whether the question needs financial-transaction "
            "analysis, consumer-complaint narratives, or both.",
            {"question": question, "facts": facts},
        )
        raw_sources = data.get("sources")
        valid_sources = (
            tuple(dict.fromkeys(item for item in raw_sources if item in self._VALID_SOURCES))
            if isinstance(raw_sources, list)
            else ()
        )
        return DomainDecision(
            route=data.get("route", "clarify"),
            reason_code=data.get("reason_code", "unclear_request"),
            sources=valid_sources or ("sql",),
        )

    def plan(self, question: str, facts: dict[str, str]) -> TaskPlan:
        data = self._json("Return JSON with intent and rationale for a safe aggregate financial analysis. Do not write SQL.", {"question": question, "facts": facts})
        filters = data.get("resolved_filters")
        safe_filters = {
            str(key): value
            for key, value in (filters.items() if isinstance(filters, dict) else ())
            if isinstance(value, (str, int, float, bool, type(None)))
        }
        return TaskPlan(
            intent=str(data.get("intent", "aggregate_query")),
            rationale=str(data.get("rationale", "approved financial exploration")),
            resolved_filters=safe_filters,
        )

    def schema_link(self, question: str, catalog: Any) -> LinkedContext:
        return catalog.link(question)

    def metric_resolution(self, question: str, catalog: Any) -> dict[str, str]:
        lower = question.lower()
        matches = [metric["label"] for metric in catalog.semantics.get("metrics", {}).values() if any(word in lower for word in metric["label"].lower().split())]
        return {"resolved_metric": matches[0]} if matches else {}

    def generate_sql(self, question: str, linked: LinkedContext, facts: dict[str, str], repair_error: str | None) -> SqlProposal:
        data = self._json("Return JSON with sql or clarification. Use only the supplied linked context.", {"question": question, "context": linked.prompt, "facts": facts, "repair_error": repair_error})
        return SqlProposal(sql=data.get("sql"), clarification=data.get("clarification"))

    def data_analysis(self, question: str, columns: list[str], rows: list[list[Any]]) -> DataAnalysis:
        data = self._json("Return JSON with summary, insights, and caveats. Ground each item only in the supplied rows. Return at most five insights and five caveats.", {"question": question, "columns": columns, "rows": rows})
        return DataAnalysis(summary=str(data.get("summary", "No data analysis was produced.")).strip(), insights=self._text_list(data.get("insights")), caveats=self._text_list(data.get("caveats")))

    def analyze(self, question: str, columns: list[str], rows: list[list[Any]], proposal: SqlProposal) -> GroundedAnswer:
        data = self._json("Return JSON with answer and optional chart. Ground every claim in rows.", {"question": question, "columns": columns, "rows": rows, "sql": proposal.sql})
        chart = data.get("chart") if isinstance(data.get("chart"), dict) else None
        return GroundedAnswer(answer=str(data.get("answer", "No grounded answer was produced.")).strip(), chart=chart)

    def review(self, question: str, columns: list[str], rows: list[list[Any]], answer: str, analysis: dict[str, Any] | None) -> ReviewDecision:
        data = self._json("Return JSON with approved boolean and reason_code. Approve only if answer and analysis remain grounded in supplied rows.", {"question": question, "columns": columns, "rows": rows, "answer": answer, "analysis": analysis})
        return ReviewDecision(approved=bool(data.get("approved", False)), reason_code=str(data.get("reason_code", "grounding_review_failed")))

    def suggest(self, question: str, facts: dict[str, str], relations: tuple[str, ...]) -> list[str]:
        return self._fallback_suggester.suggest(question, facts, relations)