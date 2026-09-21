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


class _Observation:
    def __init__(self, name, metadata):
        self.name = name
        self.metadata = metadata

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeLangfuse:
    def start_as_current_observation(self, *, name, as_type, metadata):
        self.observation = _Observation(name, metadata)
        self.as_type = as_type
        return self.observation


if __name__ == "__main__":
    unittest.main()
