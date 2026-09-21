import unittest

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.agents.text_to_sql.workflow import WorkflowAnswer


class FakeWorkflow:
    def answer(self, question, conversation_id=None):
        return WorkflowAnswer(
            request_id="request-123", conversation_id=conversation_id or "conversation-123",
            answer=f"Answer for: {question}", sql="SELECT t.mcc FROM main.transactions AS t LIMIT 10",
            columns=["mcc"], rows=[["5411"]], chart={"type": "bar", "x": "mcc"},
            suggested_questions=["Compare with the prior year"], route="answered",
            analysis={"summary": "One category is present.", "insights": ["5411 has the returned total."], "caveats": ["Result is limited."]},
            citations=[{"source_hash": "citation-a"}],
        )


class FailingWorkflow:
    def answer(self, question, conversation_id=None):
        raise RuntimeError("token=secret-value private database failure")


class ApiTests(unittest.TestCase):
    def test_health_is_available_without_credentials(self):
        response = TestClient(create_app(FakeWorkflow())).get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_chat_returns_analysis_and_contextual_suggestions(self):
        response = TestClient(create_app(FakeWorkflow())).post("/api/chat", json={"question": "Totals by MCC"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["conversation_id"], "conversation-123")
        self.assertEqual(response.json()["analysis"]["insights"], ["5411 has the returned total."])
        self.assertEqual(response.json()["suggested_questions"], ["Compare with the prior year"])
        self.assertEqual(response.json()["citations"], [{"source_hash": "citation-a"}])

    def test_chat_hides_workflow_exception_details(self):
        response = TestClient(create_app(FailingWorkflow())).post("/api/chat", json={"question": "Totals by MCC"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("secret-value", response.text)


if __name__ == "__main__":
    unittest.main()