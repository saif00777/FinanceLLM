"""Deterministic, offline release-gate evaluation helpers.

Fixture cases are public and must never contain credentials, raw SQL, raw result rows,
or unredacted complaint narratives. The evaluator accepts workflow result objects or
mappings so it can exercise deterministic fakes without network access.
"""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable


REQUIRED_CASE_FIELDS = frozenset({
    "id", "suite", "semantic_version", "graph_version", "question", "expected_route",
    "max_executions", "max_repairs",
})


@dataclass(frozen=True)
class EvaluationReport:
    total: int
    passed: int
    failed: int
    failures: tuple[str, ...]


def load_evaluation_cases(cases_dir: Path) -> list[dict[str, Any]]:
    """Load all versioned JSON case sets in a deterministic filename order."""
    cases: list[dict[str, Any]] = []
    for fixture in sorted(cases_dir.glob("*.json")):
        loaded = json.loads(fixture.read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            raise ValueError(f"{fixture.name}: fixture root must be a JSON list")
        for case in loaded:
            if not isinstance(case, dict):
                raise ValueError(f"{fixture.name}: every case must be an object")
            missing = REQUIRED_CASE_FIELDS - case.keys()
            if missing:
                raise ValueError(f"{fixture.name}: {case.get('id', 'unknown')} missing {', '.join(sorted(missing))}")
            cases.append(case)
    return cases


def _value(result: Any, name: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(name, default)
    return getattr(result, name, default)


def _execution_count(result: Any) -> int:
    value = _value(result, "executions")
    if value is not None:
        return int(value)
    return 1 if _value(result, "sql") is not None else 0


def _repairs(result: Any) -> int:
    value = _value(result, "repairs", 0)
    return int(value or 0)


def _matches_subset(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def _evaluate_case(workflow: Any, case: dict[str, Any]) -> list[str]:
    result = workflow.answer(case["question"], conversation_id=case.get("conversation_id", f"eval-{case['id']}"))
    prefix = f"{case['id']}:"
    failures: list[str] = []
    if _value(result, "route") != case["expected_route"]:
        failures.append(f"{prefix} expected route {case['expected_route']}, got {_value(result, 'route')}")

    executions = _execution_count(result)
    if executions > int(case["max_executions"]):
        failures.append(f"{prefix} execution budget exceeded ({executions}>{case['max_executions']})")
    if int(case["max_executions"]) == 0 and _value(result, "sql") is not None:
        failures.append(f"{prefix} blocked route returned SQL")

    repairs = _repairs(result)
    if repairs > int(case["max_repairs"]):
        failures.append(f"{prefix} repair budget exceeded ({repairs}>{case['max_repairs']})")

    expected_path = case.get("expected_specialist_path")
    if expected_path is not None:
        actual_path = _value(result, "specialist_path")
        if actual_path is None:
            failures.append(f"{prefix} specialist path was not exposed")
        elif list(actual_path) != expected_path:
            failures.append(f"{prefix} expected specialist path {expected_path}, got {list(actual_path)}")

    approved_questions = case.get("approved_suggested_questions")
    if approved_questions is not None:
        suggested = _value(result, "suggested_questions", []) or []
        unapproved = [question for question in suggested if question not in approved_questions]
        if unapproved:
            failures.append(f"{prefix} unapproved suggested questions: {unapproved}")
        if len(suggested) > 3:
            failures.append(f"{prefix} more than three suggested questions")

    if "expected_result_digest" in case and _value(result, "result_digest") != case["expected_result_digest"]:
        failures.append(f"{prefix} result digest did not match")
    if "expected_grounding" in case and _value(result, "grounding") != case["expected_grounding"]:
        failures.append(f"{prefix} grounding did not match")

    if "expected_citations" in case:
        actual_citations = _value(result, "citations", []) or []
        expected_citations = case["expected_citations"]
        if len(actual_citations) != len(expected_citations):
            failures.append(f"{prefix} expected {len(expected_citations)} citations, got {len(actual_citations)}")
        elif any(not _matches_subset(actual, expected) for actual, expected in zip(actual_citations, expected_citations)):
            failures.append(f"{prefix} citation metadata did not match approved metadata")
    forbidden_keys = set(case.get("forbidden_citation_metadata", []))
    if forbidden_keys:
        for citation in _value(result, "citations", []) or []:
            leaked = forbidden_keys.intersection(citation.keys())
            if leaked:
                failures.append(f"{prefix} citation exposed forbidden metadata: {', '.join(sorted(leaked))}")
    return failures


def run_evaluations(workflow: Any, cases_dir: Path) -> EvaluationReport:
    """Run every local fixture and return a release-gate report without network I/O."""
    cases = load_evaluation_cases(cases_dir)
    failures = [failure for case in cases for failure in _evaluate_case(workflow, case)]
    failed_case_ids = {failure.split(":", 1)[0] for failure in failures}
    return EvaluationReport(
        total=len(cases), passed=len(cases) - len(failed_case_ids),
        failed=len(failed_case_ids), failures=tuple(failures),
    )
