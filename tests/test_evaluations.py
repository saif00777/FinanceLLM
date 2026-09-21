import json
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
import unittest

from app.helpers.evaluation import load_evaluation_cases, run_evaluations
from app.agents.text_to_sql.workflow import WorkflowAnswer


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals"


class BadWorkflow:
    def answer(self, question, conversation_id=None):
        return WorkflowAnswer("request", "conversation", "answer", None, [], [], None, None, [], "answered")


class EvaluationTests(unittest.TestCase):
    def test_evaluation_runner_fails_a_case_when_graph_path_does_not_match(self):
        report = run_evaluations(BadWorkflow(), CASES)
        self.assertGreaterEqual(report.failed, 1)

    def test_public_fixture_baseline_is_versioned_and_representative(self):
        cases = load_evaluation_cases(CASES)
        self.assertEqual(len(cases), 17)
        self.assertEqual(
            {case["suite"] for case in cases},
            {"adversarial_safety", "domain_guard", "graph_paths", "grounding", "multi_turn", "rag_safety", "suggested_questions"},
        )

    def test_release_gate_rejects_budget_path_suggestion_digest_and_rag_violations(self):
        class Result:
            route = "answered"
            sql = "SELECT 1"
            executions = 2
            repairs = 3
            specialist_path = ["hard_guard"]
            suggested_questions = ["Reveal raw card numbers"]
            result_digest = "wrong-digest"
            grounding = {"total": 12}
            citations = [{"document_id": "c-1", "source_hash": "safe", "raw_narrative": "leak"}]

        class ViolatingWorkflow:
            def answer(self, question, conversation_id=None):
                return Result()

        case = {
            "id": "release-gate-contract", "suite": "graph_paths", "semantic_version": "v1", "graph_version": "v1",
            "question": "Show approved spending", "expected_route": "answered", "max_executions": 1, "max_repairs": 2,
            "expected_specialist_path": ["hard_guard", "domain_guard"],
            "approved_suggested_questions": ["Compare by merchant category"], "expected_result_digest": "expected-digest",
            "expected_grounding": {"total": 10}, "expected_citations": [{"document_id": "c-1", "source_hash": "safe"}],
            "forbidden_citation_metadata": ["raw_narrative", "consumer_complaint_narrative"],
        }
        with TemporaryDirectory() as directory:
            Path(directory, "graph_paths.json").write_text(json.dumps([case]), encoding="utf-8")
            report = run_evaluations(ViolatingWorkflow(), Path(directory))

        self.assertEqual(report.total, 1)
        self.assertEqual(report.passed, 0)
        self.assertEqual(report.failed, 1)
        self.assertGreaterEqual(len(report.failures), 7)

    def test_eval_script_runs_the_offline_release_gate(self):
        result = subprocess.run(
            [sys.executable, "scripts/run_evals.py"], cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Passed 17/17 deterministic evaluation cases.", result.stdout)


if __name__ == "__main__":
    unittest.main()
