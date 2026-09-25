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

    def stream_answer(self, question, conversation_id=None):
        yield ("progress", "hard_guard")
        yield ("progress", "domain_guard")
        yield ("result", self.answer(question, conversation_id))


class FailingWorkflow:
    def answer(self, question, conversation_id=None):
        raise RuntimeError("token=secret-value private database failure")

    def stream_answer(self, question, conversation_id=None):
        yield ("progress", "hard_guard")
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

    def test_chat_allows_cross_origin_requests_from_a_default_dev_frontend_origin(self):
        response = TestClient(create_app(FakeWorkflow())).post(
            "/api/chat", json={"question": "Totals by MCC"}, headers={"Origin": "http://localhost:5173"},
        )
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://localhost:5173")

    def test_chat_preflight_is_approved_for_a_default_dev_frontend_origin(self):
        response = TestClient(create_app(FakeWorkflow())).options(
            "/api/chat",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://localhost:5173")

    def test_chat_stream_emits_progress_events_then_a_result_event(self):
        response = TestClient(create_app(FakeWorkflow())).post("/api/chat/stream", json={"question": "Totals by MCC"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("content-type"), "text/event-stream; charset=utf-8")

        events = [block for block in response.text.split("\n\n") if block.strip()]
        self.assertEqual(len(events), 3)
        self.assertIn("event: progress", events[0])
        self.assertIn('"node": "hard_guard"', events[0])
        self.assertIn("event: progress", events[1])
        self.assertIn('"node": "domain_guard"', events[1])
        self.assertIn("event: result", events[2])
        self.assertIn('"conversation_id": "conversation-123"', events[2])
        self.assertIn('"route": "answered"', events[2])

    def test_chat_stream_hides_exception_details_in_an_error_event(self):
        response = TestClient(create_app(FailingWorkflow())).post("/api/chat/stream", json={"question": "Totals by MCC"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("secret-value", response.text)
        self.assertIn("event: error", response.text)
        self.assertIn("could not be completed", response.text)


if __name__ == "__main__":
    unittest.main()