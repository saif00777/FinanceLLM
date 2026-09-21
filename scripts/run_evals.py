"""Run public, deterministic release-gate cases without network calls."""

from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.helpers.evaluation import load_evaluation_cases, run_evaluations


class FixtureWorkflow:
    """Deterministic fake exposing the public result fields consumed by the evaluator."""

    def __init__(self, cases):
        self._cases = {
            (case["question"], case.get("conversation_id", f"eval-{case['id']}")): case
            for case in cases
        }

    def answer(self, question, conversation_id=None):
        case = self._cases[(question, conversation_id)]
        executions = int(case["max_executions"])
        return SimpleNamespace(
            route=case["expected_route"],
            sql="SELECT 1" if executions else None,
            executions=executions,
            repairs=int(case["max_repairs"]),
            specialist_path=case.get("expected_specialist_path"),
            suggested_questions=case.get("approved_suggested_questions", []),
            result_digest=case.get("expected_result_digest"),
            grounding=case.get("expected_grounding"),
            citations=case.get("expected_citations", []),
        )


def main() -> int:
    cases_dir = ROOT / "evals"
    cases = load_evaluation_cases(cases_dir)
    report = run_evaluations(FixtureWorkflow(cases), cases_dir)
    if report.failed:
        print(f"FAILED {report.failed}/{report.total} deterministic evaluation cases.")
        for failure in report.failures:
            print(f"- {failure}")
        return 1
    print(f"Passed {report.passed}/{report.total} deterministic evaluation cases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
