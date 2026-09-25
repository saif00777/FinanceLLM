import json
import unittest

from fastapi.testclient import TestClient

from app.api.main import create_app
from tests.test_api_key_flow import StubWorkflow


class StatusEndpointTests(unittest.TestCase):
    def test_reports_that_the_backend_is_active(self):
        response = TestClient(create_app(StubWorkflow())).get("/api/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["service"], "Financial Multi-Agent Text-to-SQL")
        self.assertRegex(body["version"], r"^\d+\.\d+\.\d+$")
        self.assertRegex(body["server_time"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*(Z|\+00:00)$")

    def test_the_root_url_shows_the_same_status_instead_of_not_found(self):
        client = TestClient(create_app(StubWorkflow()))
        root = client.get("/")
        self.assertEqual(root.status_code, 200)
        self.assertEqual(root.json()["status"], "ok")
        self.assertEqual(set(root.json()), set(client.get("/api/status").json()))

    def test_uptime_counts_seconds_since_the_app_started(self):
        now = [100.0]
        client = TestClient(create_app(StubWorkflow(), clock=lambda: now[0]))
        self.assertEqual(client.get("/api/status").json()["uptime_seconds"], 0)
        now[0] = 187.4
        self.assertEqual(client.get("/api/status").json()["uptime_seconds"], 87)

    def test_says_whether_the_agent_workflow_has_been_loaded(self):
        # The workflow is built lazily on the first chat request; an injected one counts as loaded.
        self.assertTrue(TestClient(create_app(StubWorkflow())).get("/api/status").json()["workflow_ready"])
        self.assertFalse(TestClient(create_app()).get("/api/status").json()["workflow_ready"])

    def test_the_status_check_is_cheap_and_leaks_nothing(self):
        # Must answer without building the workflow (no database/OpenAI calls) and expose no configuration.
        client = TestClient(create_app())
        text = client.get("/api/status").text
        self.assertFalse(client.get("/api/status").json()["workflow_ready"])
        for forbidden in ("key", "token", "secret", "password", "MOTHERDUCK", "sk-"):
            self.assertNotIn(forbidden.lower(), text.lower())
        self.assertEqual(sorted(json.loads(text)), sorted(["status", "service", "version", "uptime_seconds", "server_time", "workflow_ready"]))

    def test_health_is_unchanged(self):
        response = TestClient(create_app(StubWorkflow())).get("/health")
        self.assertEqual(response.json(), {"status": "ok"})

    def test_a_browser_on_the_frontend_origin_may_read_it(self):
        response = TestClient(create_app(StubWorkflow())).get("/api/status", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://localhost:5173")


if __name__ == "__main__":
    unittest.main()
