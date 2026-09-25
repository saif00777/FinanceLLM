import os
import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import _DEFAULT_DEV_ORIGINS, _parse_cors_origins, create_app
from tests.test_api_key_flow import StubWorkflow

VERCEL = "https://finance-llm-puce.vercel.app"


def _preflight(origin: str, env: dict[str, str]):
    with patch.dict(os.environ, env, clear=False):
        client = TestClient(create_app(StubWorkflow()))
    return client.options(
        "/api/validate-key",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"},
    )


class ParseTests(unittest.TestCase):
    def test_empty_or_missing_falls_back_to_the_local_dev_origins(self):
        for raw in (None, "", "   ", " , ,"):
            with self.subTest(raw=raw):
                exact, pattern = _parse_cors_origins(raw)
                self.assertEqual(exact, list(_DEFAULT_DEV_ORIGINS))
                self.assertIsNone(pattern)

    def test_harmless_formatting_slips_are_forgiven(self):
        # The browser sends an origin with no trailing slash and no quotes, and matching is exact, so these
        # common copy-paste mistakes used to silently block every request.
        exact, _ = _parse_cors_origins(f' "{VERCEL}/" ,  \'https://other.example.com\' ,{VERCEL}/ ')
        self.assertEqual(exact, [VERCEL, "https://other.example.com"])

    def test_a_wildcard_pattern_matches_preview_urls_and_nothing_else(self):
        exact, pattern = _parse_cors_origins("https://finance-llm-*.vercel.app")
        self.assertEqual(exact, [])
        regex = re.compile(pattern)
        self.assertTrue(regex.fullmatch("https://finance-llm-git-main-saif.vercel.app"))
        self.assertTrue(regex.fullmatch("https://finance-llm-4kx9a2b-saif00777.vercel.app"))
        for hostile in (
            "http://finance-llm-abc.vercel.app",                    # wrong scheme
            "https://finance-llm-abc.vercel.app.evil.com",          # suffix trick
            "https://evil.com/https://finance-llm-abc.vercel.app",  # embedded
            "https://evilfinance-llm-abc.vercel.app",               # prefix trick
            "https://finance-llm-.evil.com",                        # different host entirely
            "https://finance-llm-abc.vercel.app:8443",              # unexpected port
        ):
            with self.subTest(origin=hostile):
                self.assertIsNone(regex.fullmatch(hostile))

    def test_exact_and_wildcard_entries_can_be_mixed(self):
        exact, pattern = _parse_cors_origins(f"{VERCEL}, https://*.example.com")
        self.assertEqual(exact, [VERCEL])
        self.assertTrue(re.fullmatch(pattern, "https://app.example.com"))

    def test_a_bare_star_is_not_accepted_as_allow_everything(self):
        exact, pattern = _parse_cors_origins("*")
        self.assertEqual(exact, list(_DEFAULT_DEV_ORIGINS))
        self.assertIsNone(pattern)


class PreflightTests(unittest.TestCase):
    """What the browser actually sends before POSTing: the failure reported from a Vercel-hosted frontend."""

    def test_the_configured_origin_is_allowed(self):
        response = _preflight(VERCEL, {"CORS_ALLOWED_ORIGINS": VERCEL})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], VERCEL)
        self.assertIn("x-openai-key", response.headers["access-control-allow-headers"].lower())

    def test_a_trailing_slash_in_the_setting_no_longer_blocks_the_origin(self):
        response = _preflight(VERCEL, {"CORS_ALLOWED_ORIGINS": VERCEL + "/"})
        self.assertEqual(response.headers.get("access-control-allow-origin"), VERCEL)

    def test_a_preview_deployment_is_allowed_by_a_wildcard(self):
        origin = "https://finance-llm-git-feature-saif.vercel.app"
        response = _preflight(origin, {"CORS_ALLOWED_ORIGINS": f"{VERCEL}, https://finance-llm-*.vercel.app"})
        self.assertEqual(response.headers.get("access-control-allow-origin"), origin)

    def test_an_origin_that_is_not_listed_is_still_refused(self):
        response = _preflight("https://evil.example.com", {"CORS_ALLOWED_ORIGINS": VERCEL})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_a_wildcard_does_not_admit_a_lookalike_host(self):
        response = _preflight("https://finance-llm-abc.vercel.app.evil.com", {"CORS_ALLOWED_ORIGINS": "https://finance-llm-*.vercel.app"})
        self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
