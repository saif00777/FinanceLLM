import json
import unittest

from app.agents.text_to_sql.specialists import OpenAIResponsesSpecialists


class FakeResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("Response", (), {"output_text": json.dumps({"summary": "The returned rows contain one category.", "insights": ["5411 is present."], "caveats": ["The result is limited."]})})()


class FakeDomainGuardResponses:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("Response", (), {"output_text": json.dumps(self._payload)})()


class ProductionSpecialistTests(unittest.TestCase):
    def test_openai_adapter_returns_structured_data_analysis(self):
        responses = FakeResponses()
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        analysis = specialist.data_analysis("Summarize", ["mcc", "total"], [["5411", 100]])

        self.assertEqual(analysis.summary, "The returned rows contain one category.")
        self.assertEqual(analysis.insights, ["5411 is present."])
        self.assertEqual(analysis.caveats, ["The result is limited."])
        self.assertFalse(responses.calls[0]["store"])

    def test_domain_guard_parses_sources_from_the_model_response(self):
        responses = FakeDomainGuardResponses({"route": "in_scope", "reason_code": "allowed", "sources": ["sql", "rag"]})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        decision = specialist.domain_guard("Spending and complaints about it", {})

        self.assertEqual(decision.route, "in_scope")
        self.assertEqual(decision.sources, ("sql", "rag"))

    def test_domain_guard_defaults_sources_to_sql_when_missing_or_invalid(self):
        responses = FakeDomainGuardResponses({"route": "in_scope", "reason_code": "allowed", "sources": ["bogus", 42]})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        decision = specialist.domain_guard("Total spending", {})

        self.assertEqual(decision.sources, ("sql",))

    def test_domain_guard_defaults_sources_to_sql_when_key_is_missing(self):
        responses = FakeDomainGuardResponses({"route": "in_scope", "reason_code": "allowed"})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        decision = specialist.domain_guard("Total spending", {})

        self.assertEqual(decision.sources, ("sql",))


if __name__ == "__main__":
    unittest.main()