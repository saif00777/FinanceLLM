import unittest

from app.helpers.telemetry import LangfuseTelemetry, NoopTelemetry


class TelemetryTests(unittest.TestCase):
    def test_telemetry_replaces_raw_sql_and_rows_with_hashes_and_counts(self):
        attributes = NoopTelemetry().safe_attributes(
            sql="SELECT secret", rows=[[1], [2]], question="What did Alice spend?",
            answer="Alice spent 100.", route="answered", reason_code="ok", latency_ms=12,
        )

        self.assertNotIn("SELECT secret", repr(attributes))
        self.assertNotIn("Alice", repr(attributes))
        self.assertEqual(attributes["row_count"], 2)
        self.assertIn("sql_hash", attributes)
        self.assertEqual(attributes["route"], "answered")
        self.assertEqual(attributes["latency_ms"], 12)

    def test_langfuse_adapter_emits_only_safe_metadata(self):
        client = _FakeLangfuse()
        telemetry = LangfuseTelemetry(client)

        with telemetry.span(
            "executor",
            {"sql": "SELECT secret", "rows": [["sensitive"]], "question": "private question", "route": "answered"},
        ):
            pass

        self.assertEqual(client.observation.name, "executor")
        self.assertEqual(client.observation.metadata["row_count"], 1)
        self.assertEqual(client.observation.metadata["route"], "answered")
        self.assertNotIn("SELECT secret", repr(client.observation.metadata))
        self.assertNotIn("sensitive", repr(client.observation.metadata))
        self.assertNotIn("private question", repr(client.observation.metadata))

    def test_langfuse_adapter_groups_the_span_under_the_given_trace_id(self):
        client = _FakeLangfuse()
        telemetry = LangfuseTelemetry(client)

        with telemetry.span("executor", {}, trace_id="a" * 32):
            pass

        self.assertEqual(client.trace_context, {"trace_id": "a" * 32})

    def test_langfuse_adapter_omits_trace_context_when_no_trace_id_given(self):
        client = _FakeLangfuse()
        telemetry = LangfuseTelemetry(client)

        with telemetry.span("executor", {}):
            pass

        self.assertIsNone(client.trace_context)

    def test_langfuse_adapter_sets_session_id_so_a_conversation_groups_its_traces(self):
        # Langfuse groups traces into a "session" via the session.id span attribute, which
        # is per-observation, not automatically inherited by sibling spans in the same
        # trace (confirmed against the real API) — so every node's span needs it set
        # explicitly for a whole conversation (many turns, each its own trace) to group.
        client = _FakeLangfuse()
        telemetry = LangfuseTelemetry(client)

        with telemetry.span("executor", {}, session_id="conversation-abc"):
            pass

        self.assertEqual(client.observation._otel_span.attributes.get("session.id"), "conversation-abc")

    def test_langfuse_adapter_does_not_set_session_id_when_none_given(self):
        client = _FakeLangfuse()
        telemetry = LangfuseTelemetry(client)

        with telemetry.span("executor", {}):
            pass

        self.assertNotIn("session.id", client.observation._otel_span.attributes)

    def test_default_langfuse_adapter_omits_input_and_output(self):
        # Default posture: never send raw question/SQL/row/answer text to a third party.
        client = _FakeLangfuse()
        telemetry = LangfuseTelemetry(client)

        with telemetry.span("sql_generator", {"question": "What did Alice spend?"}) as recorder:
            recorder.record_output({"sql": "SELECT t.amount FROM main.transactions AS t"})

        self.assertIsNone(client.observation.input)
        self.assertIsNone(client.observation.output)

    def test_verbose_langfuse_adapter_sets_raw_input_and_records_raw_output(self):
        client = _FakeLangfuse()
        telemetry = LangfuseTelemetry(client, verbose=True)

        with telemetry.span("sql_generator", {"question": "What did Alice spend?"}) as recorder:
            recorder.record_output({"sql": "SELECT t.amount FROM main.transactions AS t"})

        self.assertEqual(client.observation.input, "What did Alice spend?")
        self.assertEqual(client.observation.output, {"sql": "SELECT t.amount FROM main.transactions AS t"})

    def test_verbose_langfuse_adapter_still_redacts_metadata(self):
        # Verbose mode only affects the dedicated input/output fields; the metadata
        # dict populated from safe_attributes() must stay redacted either way.
        client = _FakeLangfuse()
        telemetry = LangfuseTelemetry(client, verbose=True)

        with telemetry.span("executor", {"sql": "SELECT secret", "rows": [["sensitive"]], "question": "private"}) as recorder:
            recorder.record_output({})

        self.assertNotIn("SELECT secret", repr(client.observation.metadata))
        self.assertNotIn("sensitive", repr(client.observation.metadata))


class GenerationTelemetryTests(unittest.TestCase):
    def test_verbose_generation_records_instructions_payload_model_and_raw_output(self):
        client = _FakeLangfuse()
        telemetry = LangfuseTelemetry(client, verbose=True)

        with telemetry.generation("generate_sql", "gpt-4o", "Return JSON with sql.", {"question": "Total spending?"}) as recorder:
            recorder.record_output('{"sql": "SELECT 1"}')

        observation = client.observation
        self.assertEqual(client.as_type, "generation")
        self.assertEqual(observation.name, "generate_sql")
        self.assertEqual(client.model, "gpt-4o")
        self.assertEqual(observation.input, {"instructions": "Return JSON with sql.", "input": {"question": "Total spending?"}})
        self.assertEqual(observation.output, '{"sql": "SELECT 1"}')

    def test_default_generation_sends_nothing_to_langfuse(self):
        client = _FakeLangfuse()
        telemetry = LangfuseTelemetry(client)

        with telemetry.generation("generate_sql", "gpt-4o", "instructions", {"question": "private"}) as recorder:
            recorder.record_output("raw output")

        self.assertFalse(hasattr(client, "observation"))

    def test_noop_generation_is_a_harmless_context_manager(self):
        with NoopTelemetry().generation("generate_sql", "gpt-4o", "i", {}) as recorder:
            recorder.record_output("x")


class _FakeOtelSpan:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value


class _Observation:
    def __init__(self, name, metadata, input=None):
        self.name = name
        self.metadata = metadata
        self.input = input
        self.output = None
        self._otel_span = _FakeOtelSpan()

    def update(self, *, output=None, **_kwargs):
        self.output = output

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeLangfuse:
    def start_as_current_observation(self, *, name, as_type, metadata=None, trace_context=None, input=None, model=None):
        self.observation = _Observation(name, metadata, input=input)
        self.as_type = as_type
        self.model = model
        self.trace_context = trace_context
        return self.observation


if __name__ == "__main__":
    unittest.main()
