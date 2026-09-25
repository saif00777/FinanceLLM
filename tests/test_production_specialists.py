import json
import unittest

from app.agents.text_to_sql.contracts import LinkedContext
from app.agents.text_to_sql.specialists import OpenAIResponsesSpecialists, SqlProposal


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


class FakeFencedResponses:
    """Reproduces a real, observed failure mode: the model wraps JSON in a markdown code fence."""

    def __init__(self, payload, fence="```json\n{body}\n```"):
        self._text = fence.format(body=json.dumps(payload))
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("Response", (), {"output_text": self._text})()


class FakeAnalyzeResponses:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("Response", (), {"output_text": json.dumps(self._payload)})()


class _SequenceResponses:
    """Returns each queued raw model output in turn (repeating the last one)."""

    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self._texts[min(len(self.calls) - 1, len(self._texts) - 1)]
        return type("Response", (), {"output_text": text})()


class _SpyRecorder:
    def __init__(self):
        self.outputs = []

    def record_output(self, output):
        self.outputs.append(output)


class _SpyGenerationTelemetry:
    def __init__(self):
        self.generations = []
        self.recorder = _SpyRecorder()

    def generation(self, name, model, instructions, payload):
        from contextlib import nullcontext
        self.generations.append((name, model, instructions, payload))
        return nullcontext(self.recorder)


class ProductionSpecialistTests(unittest.TestCase):
    def test_each_llm_call_reports_its_instructions_payload_and_raw_output_to_telemetry(self):
        responses = FakeAnalyzeResponses({"summary": "s", "insights": [], "caveats": []})
        client = type("Client", (), {"responses": responses})()
        telemetry = _SpyGenerationTelemetry()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object(), telemetry=telemetry)

        specialist.data_analysis("Summarize", ["mcc", "total"], [["5411", 100]])

        (name, model, instructions, payload), = telemetry.generations
        self.assertEqual(name, "data_analysis")
        self.assertEqual(model, "demo-model")
        self.assertEqual(instructions, responses.calls[0]["instructions"])
        self.assertEqual(payload["question"], "Summarize")
        self.assertIn('"summary"', telemetry.recorder.outputs[0])

    def test_every_llm_backed_specialist_names_its_generation(self):
        payloads = {"route": "in_scope", "reason_code": "ok", "sources": ["sql"], "intent": "i", "rationale": "r",
                    "sql": "SELECT 1", "summary": "s", "answer": "a", "approved": True}
        responses = FakeAnalyzeResponses(payloads)
        client = type("Client", (), {"responses": responses})()
        telemetry = _SpyGenerationTelemetry()
        specialist = OpenAIResponsesSpecialists(client, "m", object(), telemetry=telemetry)

        specialist.domain_guard("q", {})
        specialist.plan("q", {})
        specialist.generate_sql("q", LinkedContext(relations=(), prompt="p"), {}, None)
        specialist.data_analysis("q", ["c"], [[1]])
        specialist.analyze("q", ["c"], [[1]], SqlProposal("SELECT 1"))
        specialist.review("q", ["c"], [[1]], "a", None)

        self.assertEqual(
            [name for name, *_ in telemetry.generations],
            ["domain_guard", "plan", "generate_sql", "data_analysis", "analyze", "review"],
        )

    def test_domain_guard_instructions_define_each_route_and_forbid_clarifying_a_resolvable_follow_up(self):
        # Reproduced live: "I need for the cards with chips" (after two questions about card credit
        # limits) got route=clarify 10 times out of 12 because the instruction never said that a
        # missing metric/period is not a reason to clarify when earlier questions supply it.
        responses = FakeAnalyzeResponses({"route": "in_scope", "reason_code": "ok", "sources": ["sql"]})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "m", object())

        specialist.domain_guard("I need for the cards with chips", {"recent_user_questions": ["total credit limit?"]})

        instructions = responses.calls[0]["instructions"]
        for route in ("in_scope", "clarify", "abstain"):
            self.assertIn(route + ":", instructions)
        self.assertIn("NOT a reason to clarify", instructions)
        self.assertIn("even after reading facts.recent_user_questions", instructions)

    def test_an_unparseable_model_response_is_retried_once(self):
        responses = _SequenceResponses(['{"intent": "broken', '{"intent": "aggregate_query", "rationale": "ok"}'])
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "m", object())

        plan = specialist.plan("q", {})

        self.assertEqual(plan.intent, "aggregate_query")
        self.assertEqual(len(responses.calls), 2)

    def test_a_second_unparseable_response_still_raises(self):
        responses = _SequenceResponses(['{"intent": "broken', 'not json at all'])
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "m", object())

        with self.assertRaises(ValueError):
            specialist.plan("q", {})
        self.assertEqual(len(responses.calls), 2)

    def test_a_valid_response_is_not_retried(self):
        responses = _SequenceResponses(['{"intent": "aggregate_query", "rationale": "ok"}'])
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "m", object())

        specialist.plan("q", {})

        self.assertEqual(len(responses.calls), 1)

    def test_generate_sql_accepts_the_query_under_a_common_alias_key(self):
        # Reproduces a real, live-observed failure: the model returns valid SQL as {"query": "..."}
        # instead of {"sql": "..."}; reading only "sql" discarded it and the user got a clarify answer.
        for key in ("query", "sql_query"):
            responses = FakeAnalyzeResponses({key: "SELECT c.credit_limit FROM main.cards AS c LIMIT 10"})
            client = type("Client", (), {"responses": responses})()
            specialist = OpenAIResponsesSpecialists(client, "m", object())

            proposal = specialist.generate_sql("q", LinkedContext(relations=(), prompt="p"), {}, None)

            self.assertEqual(proposal.sql, "SELECT c.credit_limit FROM main.cards AS c LIMIT 10", key)

    def test_generate_sql_prefers_the_sql_key_and_ignores_blank_values(self):
        responses = FakeAnalyzeResponses({"sql": "  ", "query": "SELECT 1"})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "m", object())

        proposal = specialist.generate_sql("q", LinkedContext(relations=(), prompt="p"), {}, None)

        self.assertEqual(proposal.sql, "SELECT 1")

    def test_generate_sql_instructions_name_the_exact_json_keys(self):
        responses = FakeAnalyzeResponses({"sql": "SELECT 1"})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "m", object())

        specialist.generate_sql("q", LinkedContext(relations=(), prompt="p"), {}, None)

        instructions = responses.calls[0]["instructions"]
        self.assertIn('"sql"', instructions)

    def test_metric_resolution_ignores_stopwords_in_metric_labels(self):
        from pathlib import Path
        from app.agents.text_to_sql.contracts import RuntimeContract

        contract = RuntimeContract.from_files(Path(__file__).resolve().parents[1])
        specialist = OpenAIResponsesSpecialists(object(), "m", contract)

        self.assertEqual(specialist.metric_resolution("what is the credit limit of cards that have chips?", contract), {})
        self.assertEqual(specialist.metric_resolution("tell me the average", contract), {})

    def test_metric_resolution_still_matches_real_metric_words(self):
        from pathlib import Path
        from app.agents.text_to_sql.contracts import RuntimeContract

        contract = RuntimeContract.from_files(Path(__file__).resolve().parents[1])
        specialist = OpenAIResponsesSpecialists(object(), "m", contract)

        self.assertIn("resolved_metric", specialist.metric_resolution("what is the net signed amount by year?", contract))

    def test_the_agents_that_interpret_context_are_told_how_to_use_recent_user_questions(self):
        # domain_guard decides scope and the planner rewrites the question; the SQL agent then works from the plan.
        responses = FakeAnalyzeResponses({"route": "in_scope", "reason_code": "ok", "sources": ["sql"], "intent": "i", "rationale": "r", "sql": "SELECT 1"})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "m", object())

        specialist.domain_guard("q", {})
        specialist.plan("q", {})

        for call in responses.calls:
            self.assertIn("recent_user_questions", call["instructions"])

    def test_specialists_work_without_any_telemetry(self):
        responses = FakeAnalyzeResponses({"summary": "s"})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "m", object())

        self.assertEqual(specialist.data_analysis("q", ["c"], [[1]]).summary, "s")

    def test_openai_adapter_returns_structured_data_analysis(self):
        responses = FakeResponses()
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        analysis = specialist.data_analysis("Summarize", ["mcc", "total"], [["5411", 100]])

        self.assertEqual(analysis.summary, "The returned rows contain one category.")
        self.assertEqual(analysis.insights, ["5411 is present."])
        self.assertEqual(analysis.caveats, ["The result is limited."])
        self.assertFalse(responses.calls[0]["store"])

    def test_specialist_instructions_forbid_markdown_formatting(self):
        responses = FakeResponses()
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        specialist.data_analysis("Summarize", ["mcc", "total"], [["5411", 100]])

        self.assertIn("no markdown", responses.calls[0]["instructions"].lower())

    def test_json_response_tolerates_literal_newlines_inside_string_values(self):
        raw = '{"sql": "SELECT 1\nFROM main.transactions"}'
        responses = FakeResponses()
        responses.create = lambda **kwargs: type("Response", (), {"output_text": raw})()
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        proposal = specialist.generate_sql("Total spending", LinkedContext(relations=(), prompt="context"), {}, None)

        self.assertEqual(proposal.sql, "SELECT 1\nFROM main.transactions")

    def test_domain_guard_parses_sources_from_the_model_response(self):
        responses = FakeDomainGuardResponses({"route": "in_scope", "reason_code": "allowed", "sources": ["sql", "rag"]})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        decision = specialist.domain_guard("Spending and documents about it", {})

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

    def test_json_response_tolerates_a_markdown_json_code_fence(self):
        responses = FakeFencedResponses({"route": "in_scope", "reason_code": "allowed", "sources": ["sql"]}, fence="```json\n{body}\n```")
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        decision = specialist.domain_guard("Total spending", {})

        self.assertEqual(decision.route, "in_scope")

    def test_json_response_tolerates_a_bare_code_fence_without_a_language_tag(self):
        responses = FakeFencedResponses({"route": "clarify", "reason_code": "unclear", "sources": ["sql"]}, fence="```\n{body}\n```")
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        decision = specialist.domain_guard("Total spending", {})

        self.assertEqual(decision.route, "clarify")

    def test_analyze_passes_through_a_well_formed_chart(self):
        responses = FakeAnalyzeResponses({"answer": "5411 leads.", "chart": {"type": "bar", "x": "mcc", "y": "total"}})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        result = specialist.analyze("Totals by mcc", ["mcc", "total"], [["5411", 100]], SqlProposal("SELECT 1"))

        self.assertEqual(result.chart, {"type": "bar", "x": "mcc", "y": "total"})

    def test_analyze_drops_a_chart_shaped_like_a_charting_library_config(self):
        # Reproduces a real, observed failure: the model sometimes emits a Chart.js-style
        # config ({data: {labels, datasets}}) instead of the requested {type, x, y} shape.
        responses = FakeAnalyzeResponses({
            "answer": "5411 leads.",
            "chart": {"type": "bar", "data": {"labels": ["5411"], "datasets": [{"label": "Total", "data": [100]}]}},
        })
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        result = specialist.analyze("Totals by mcc", ["mcc", "total"], [["5411", 100]], SqlProposal("SELECT 1"))

        self.assertIsNone(result.chart)

    def test_analyze_drops_a_chart_referencing_an_unsupplied_column(self):
        responses = FakeAnalyzeResponses({"answer": "5411 leads.", "chart": {"type": "bar", "x": "mcc", "y": "not_a_real_column"}})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        result = specialist.analyze("Totals by mcc", ["mcc", "total"], [["5411", 100]], SqlProposal("SELECT 1"))

        self.assertIsNone(result.chart)

    def test_analyze_drops_a_chart_with_an_unsupported_type(self):
        responses = FakeAnalyzeResponses({"answer": "5411 leads.", "chart": {"type": "pie", "x": "mcc", "y": "total"}})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        result = specialist.analyze("Totals by mcc", ["mcc", "total"], [["5411", 100]], SqlProposal("SELECT 1"))

        self.assertIsNone(result.chart)

    def test_analyze_instructions_specify_the_exact_required_chart_shape(self):
        responses = FakeAnalyzeResponses({"answer": "5411 leads."})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        specialist.analyze("Totals by mcc", ["mcc", "total"], [["5411", 100]], SqlProposal("SELECT 1"))

        instructions = responses.calls[0]["instructions"]
        self.assertIn('"type"', instructions)
        self.assertIn('"x"', instructions)
        self.assertIn('"y"', instructions)

    def test_analyze_replaces_a_raw_list_of_dicts_answer_with_a_fallback_message(self):
        # Reproduces a real, live-observed failure: the model sometimes serializes the row
        # data it was given instead of summarizing it, e.g. a hundred rows concatenated as
        # "[{'description': 'Postal Services', 'total_spending': 1484483.89}, {...}, ...]".
        raw_dump = "[{'description': 'Postal Services', 'total_spending': 1484483.89}, {'description': 'Medical Services', 'total_spending': 1632299.99}]"
        responses = FakeAnalyzeResponses({"answer": raw_dump})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        result = specialist.analyze("Spending by category", ["description", "total_spending"], [["Postal Services", 1484483.89]], SqlProposal("SELECT 1"))

        self.assertNotIn("Postal Services", result.answer)
        self.assertNotIn("{", result.answer)

    def test_analyze_replaces_a_raw_dict_answer_with_a_fallback_message(self):
        raw_dump = "{'year': 2019, 'total': 55316451.39}"
        responses = FakeAnalyzeResponses({"answer": raw_dump})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        result = specialist.analyze("Total by year", ["year", "total"], [[2019, 55316451.39]], SqlProposal("SELECT 1"))

        self.assertNotIn("{", result.answer)

    def test_analyze_passes_through_a_normal_prose_answer_unchanged(self):
        responses = FakeAnalyzeResponses({"answer": "5411 leads with $100 in total spending."})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        result = specialist.analyze("Totals by mcc", ["mcc", "total"], [["5411", 100]], SqlProposal("SELECT 1"))

        self.assertEqual(result.answer, "5411 leads with $100 in total spending.")

    def test_analyze_instructions_require_prose_not_a_data_dump(self):
        responses = FakeAnalyzeResponses({"answer": "5411 leads."})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        specialist.analyze("Totals by mcc", ["mcc", "total"], [["5411", 100]], SqlProposal("SELECT 1"))

        instructions = responses.calls[0]["instructions"].lower()
        self.assertIn("sentence", instructions)

    def test_data_analysis_reformats_a_structured_insight_into_readable_text_instead_of_a_python_repr(self):
        # Reproduces a real, live-observed failure: the model sometimes returns insights/caveats
        # as objects instead of plain sentences, e.g. {"observation": "...", "categories": [...]}.
        # str()'ing that raw gives the user a literal "{'observation': ...}" dict repr on screen.
        payload = {
            "summary": "Money Transfer leads spending.",
            "insights": [{"observation": "Top three categories by spending", "categories": ["Money Transfer", "Service Stations"]}],
            "caveats": [{"note": "Categories vary widely", "impact": "Comparison may not be meaningful"}],
        }
        responses = FakeAnalyzeResponses(payload)
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        analysis = specialist.data_analysis("Spending by category", ["description", "total"], [["Money Transfer", 100]])

        self.assertNotIn("{", analysis.insights[0])
        self.assertNotIn("'observation':", analysis.insights[0])
        self.assertIn("Top three categories by spending", analysis.insights[0])
        self.assertIn("Money Transfer", analysis.insights[0])
        self.assertNotIn("{", analysis.caveats[0])

    def test_data_analysis_passes_through_plain_string_insights_unchanged(self):
        responses = FakeAnalyzeResponses({"summary": "s", "insights": ["5411 is present."], "caveats": ["Limited data."]})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        analysis = specialist.data_analysis("Summarize", ["mcc", "total"], [["5411", 100]])

        self.assertEqual(analysis.insights, ["5411 is present."])
        self.assertEqual(analysis.caveats, ["Limited data."])

    def test_data_analysis_instructions_require_plain_sentences(self):
        responses = FakeAnalyzeResponses({"summary": "s"})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        specialist.data_analysis("Summarize", ["mcc", "total"], [["5411", 100]])

        instructions = responses.calls[0]["instructions"].lower()
        self.assertIn("plain sentence", instructions)


if __name__ == "__main__":
    unittest.main()