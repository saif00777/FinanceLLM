import threading
import unittest

import httpx
import openai
from fastapi.testclient import TestClient

from app.agents.text_to_sql.contracts import RuntimeContract
from app.agents.text_to_sql.domain_guard import HardGuard
from app.agents.text_to_sql.workflow import MultiAgentWorkflow, WorkflowAnswer
from app.api.main import create_app
from app.helpers.conversation import InMemoryConversationStore
from app.helpers.key_validation import KeyCheck, SlidingWindowLimiter, validate_openai_key
from app.helpers.openai_scope import MissingApiKeyError, ScopedOpenAI, current_api_key, use_api_key
from tests.test_workflow import FakeRunner, FakeSpecialists, ROOT

GOOD_KEY = "sk-test-" + "a1B2c3D4" * 4


def _error(cls, status, body=None):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    return cls("boom", response=response, body=body)


class FakeClient:
    def __init__(self, key, fail=None, embed_fail=None):
        self.key = key
        self.calls = []
        self.responses = self
        self.embeddings = self
        self._fail, self._embed_fail = fail, embed_fail

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if "input" in kwargs and "max_output_tokens" in kwargs:
            if self._fail:
                raise self._fail
        elif self._embed_fail:
            raise self._embed_fail
        return object()


class ScopedClientTests(unittest.TestCase):
    def test_uses_the_default_client_when_no_key_is_in_scope(self):
        default = FakeClient("server")
        scoped = ScopedOpenAI(default, client_factory=lambda key: FakeClient(key))
        self.assertIs(scoped.responses, default)

    def test_uses_a_client_built_from_the_scoped_key(self):
        scoped = ScopedOpenAI(FakeClient("server"), client_factory=lambda key: FakeClient(key))
        with use_api_key(GOOD_KEY):
            self.assertEqual(scoped.responses.key, GOOD_KEY)
            self.assertEqual(scoped.embeddings.key, GOOD_KEY)
        self.assertEqual(scoped.responses.key, "server")

    def test_the_same_key_reuses_one_client(self):
        built = []
        scoped = ScopedOpenAI(None, client_factory=lambda key: built.append(key) or FakeClient(key))
        with use_api_key(GOOD_KEY):
            scoped.responses, scoped.responses
        with use_api_key(GOOD_KEY):
            scoped.responses
        self.assertEqual(built, [GOOD_KEY])

    def test_no_default_and_no_key_is_an_explicit_error(self):
        with self.assertRaises(MissingApiKeyError):
            ScopedOpenAI(None, client_factory=lambda key: FakeClient(key)).responses

    def test_the_key_is_not_in_the_repr_or_leaked_after_the_scope_ends(self):
        scoped = ScopedOpenAI(None, client_factory=lambda key: FakeClient(key))
        with use_api_key(GOOD_KEY):
            self.assertEqual(current_api_key(), GOOD_KEY)
            self.assertNotIn(GOOD_KEY, repr(scoped))
        self.assertIsNone(current_api_key())


class ValidationTests(unittest.TestCase):
    def _validate(self, key=GOOD_KEY, fail=None, embed_fail=None, embedding_model="emb"):
        made = []

        def factory(k):
            made.append(FakeClient(k, fail, embed_fail))
            return made[-1]

        result = validate_openai_key(key, "gpt-x", embedding_model, client_factory=factory)
        return result, made

    def test_a_working_key_passes_both_real_calls(self):
        result, made = self._validate()
        self.assertTrue(result.valid)
        self.assertEqual([c["name"] for c in result.checks], ["chat model", "embedding model"])
        self.assertTrue(all(c["ok"] for c in result.checks))
        self.assertEqual(made[0].calls[0]["model"], "gpt-x")
        self.assertEqual(made[0].calls[1]["model"], "emb")

    def test_the_embedding_check_is_skipped_when_none_is_configured(self):
        result, _ = self._validate(embedding_model=None)
        self.assertEqual([c["name"] for c in result.checks], ["chat model"])

    def test_a_malformed_key_is_rejected_without_calling_openai(self):
        for key in ("", "   ", "not-a-key", "sk-short", "sk-has space in it 123456789012345678", "sk-" + "x" * 500):
            with self.subTest(key=key[:12]):
                result, made = self._validate(key=key)
                self.assertFalse(result.valid)
                self.assertEqual(result.code, "bad_format")
                self.assertEqual(made, [])

    def test_a_rejected_key_says_so(self):
        result, _ = self._validate(fail=_error(openai.AuthenticationError, 401))
        self.assertEqual((result.valid, result.code), (False, "invalid_key"))

    def test_an_account_without_credit_is_reported_as_valid_but_unusable(self):
        result, _ = self._validate(fail=_error(openai.RateLimitError, 429, body={"code": "insufficient_quota"}))
        self.assertEqual((result.valid, result.code), (False, "no_quota"))

    def test_a_plain_rate_limit_is_its_own_code(self):
        result, _ = self._validate(fail=_error(openai.RateLimitError, 429, body={"code": "rate_limit_exceeded"}))
        self.assertEqual(result.code, "rate_limited")

    def test_missing_model_access_is_reported(self):
        for cls, status in ((openai.PermissionDeniedError, 403), (openai.NotFoundError, 404)):
            with self.subTest(cls=cls.__name__):
                result, _ = self._validate(fail=_error(cls, status))
                self.assertEqual((result.valid, result.code), (False, "no_model_access"))

    def test_a_key_without_embedding_access_fails_validation(self):
        result, _ = self._validate(embed_fail=_error(openai.PermissionDeniedError, 403))
        self.assertFalse(result.valid)
        self.assertEqual(result.code, "no_model_access")
        self.assertEqual([c["ok"] for c in result.checks], [True, False])

    def test_a_network_failure_is_not_blamed_on_the_key(self):
        result, _ = self._validate(fail=openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com")))
        self.assertEqual(result.code, "network")

    def test_the_result_never_contains_the_key(self):
        result, _ = self._validate(fail=_error(openai.AuthenticationError, 401))
        self.assertNotIn(GOOD_KEY, repr(result))


class LimiterTests(unittest.TestCase):
    def test_allows_up_to_the_limit_then_blocks_until_the_window_passes(self):
        now = [0.0]
        limiter = SlidingWindowLimiter(3, 60, clock=lambda: now[0])
        self.assertEqual([limiter.allow("ip") for _ in range(4)], [True, True, True, False])
        self.assertTrue(limiter.allow("other"))
        now[0] = 61
        self.assertTrue(limiter.allow("ip"))


class StubWorkflow:
    def __init__(self, error=None):
        self.error = error

    def answer(self, question, conversation_id=None):
        if self.error:
            raise self.error
        return WorkflowAnswer("r", "c", "hello", None, [], [], None, None, [], "answered")

    def stream_answer(self, question, conversation_id=None):
        if self.error:
            raise self.error
        yield ("progress", "hard_guard")
        yield ("result", self.answer(question))


def _validator(result):
    calls = []

    def validate(key):
        calls.append(key)
        return result

    validate.calls = calls
    return validate


class ValidateEndpointTests(unittest.TestCase):
    def test_returns_the_check_result_and_never_echoes_the_key(self):
        validator = _validator(KeyCheck(True, "ok", "Key works.", [{"name": "chat model", "ok": True}]))
        client = TestClient(create_app(StubWorkflow(), key_validator=validator))
        response = client.post("/api/validate-key", json={"api_key": GOOD_KEY})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["valid"], True)
        self.assertEqual(response.json()["checks"], [{"name": "chat model", "ok": True}])
        self.assertNotIn(GOOD_KEY, response.text)
        self.assertEqual(validator.calls, [GOOD_KEY])

    def test_an_invalid_key_is_a_normal_response_not_a_server_error(self):
        client = TestClient(create_app(StubWorkflow(), key_validator=_validator(KeyCheck(False, "invalid_key", "Rejected.", []))))
        response = client.post("/api/validate-key", json={"api_key": GOOD_KEY})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json()["valid"], response.json()["code"]), (False, "invalid_key"))

    def test_attempts_are_rate_limited_per_client(self):
        client = TestClient(create_app(StubWorkflow(), key_validator=_validator(KeyCheck(False, "invalid_key", "x", [])), validate_limit=(2, 60)))
        statuses = [client.post("/api/validate-key", json={"api_key": GOOD_KEY}).status_code for _ in range(3)]
        self.assertEqual(statuses, [200, 200, 429])

    def test_the_key_header_is_allowed_cross_origin(self):
        client = TestClient(create_app(StubWorkflow()))
        response = client.options("/api/chat/stream", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-openai-key"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("x-openai-key", response.headers["access-control-allow-headers"].lower())


class KeyReachesTheWorkflowTests(unittest.TestCase):
    class Spy(FakeSpecialists):
        """Records the scoped key seen inside every agent, including the two that run in parallel threads."""

        def __init__(self):
            super().__init__()
            self.seen = {}

        def _see(self, name):
            self.seen[name] = (current_api_key(), threading.current_thread().name)

        def domain_guard(self, question, facts):
            self._see("domain_guard")
            return super().domain_guard(question, facts)

        def generate_sql(self, *args, **kwargs):
            self._see("generate_sql")
            return super().generate_sql(*args, **kwargs)

        def data_analysis(self, *args, **kwargs):
            self._see("data_analysis")
            return super().data_analysis(*args, **kwargs)

        def analyze(self, *args, **kwargs):
            self._see("analyze")
            return super().analyze(*args, **kwargs)

        def suggest(self, *args, **kwargs):
            self._see("suggest")
            return super().suggest(*args, **kwargs)

    def _run(self, path, headers):
        spy = self.Spy()
        workflow = MultiAgentWorkflow(RuntimeContract.from_files(ROOT), FakeRunner(), spy, InMemoryConversationStore(), HardGuard())
        response = TestClient(create_app(workflow)).post(path, json={"question": "Total spending by category"}, headers=headers)
        return spy, response

    def test_the_streaming_endpoint_scopes_the_key_to_every_agent_across_steps_and_threads(self):
        spy, response = self._run("/api/chat/stream", {"X-OpenAI-Key": GOOD_KEY})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({name: key for name, (key, _) in spy.seen.items()},
                         {n: GOOD_KEY for n in ("domain_guard", "generate_sql", "data_analysis", "analyze", "suggest")})

    def test_the_blocking_endpoint_scopes_the_key_too(self):
        spy, response = self._run("/api/chat", {"X-OpenAI-Key": GOOD_KEY})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(key == GOOD_KEY for key, _ in spy.seen.values()))

    def test_without_a_header_no_key_is_scoped(self):
        spy, _ = self._run("/api/chat", {})
        self.assertTrue(all(key is None for key, _ in spy.seen.values()))

    def test_the_key_does_not_leak_between_requests(self):
        self._run("/api/chat", {"X-OpenAI-Key": GOOD_KEY})
        self.assertIsNone(current_api_key())


class RejectedKeyTests(unittest.TestCase):
    def test_a_key_openai_rejects_mid_session_is_a_401_with_a_code_the_ui_can_act_on(self):
        client = TestClient(create_app(StubWorkflow(error=_error(openai.AuthenticationError, 401))))
        response = client.post("/api/chat", json={"question": "q"}, headers={"X-OpenAI-Key": GOOD_KEY})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "invalid_api_key")
        self.assertNotIn(GOOD_KEY, response.text)

    def test_the_stream_reports_the_same_code_in_an_error_event(self):
        client = TestClient(create_app(StubWorkflow(error=_error(openai.AuthenticationError, 401))))
        response = client.post("/api/chat/stream", json={"question": "q"}, headers={"X-OpenAI-Key": GOOD_KEY})
        self.assertIn("event: error", response.text)
        self.assertIn('"code": "invalid_api_key"', response.text)
        self.assertNotIn(GOOD_KEY, response.text)

    def test_a_missing_key_with_no_server_default_is_a_401(self):
        client = TestClient(create_app(StubWorkflow(error=MissingApiKeyError())))
        response = client.post("/api/chat", json={"question": "q"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "missing_api_key")


if __name__ == "__main__":
    unittest.main()
