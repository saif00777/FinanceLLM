import json
import unittest

from app.agents.text_to_sql.specialists import OpenAIResponsesSpecialists


class FakeResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("Response", (), {"output_text": json.dumps({"summary": "The returned rows contain one category.", "insights": ["5411 is present."], "caveats": ["The result is limited."]})})()


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


if __name__ == "__main__":
    unittest.main()