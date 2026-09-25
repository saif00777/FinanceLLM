import unittest

from app.helpers.config import AppConfig, ConfigurationError


BASE_ENV = {
    "OPEN_AI_KEY": "project-key",
    "OPEN_AI_MODEL": "gpt-4o",
    "MOTHERDUCK_TOKEN": "motherduck-key",
}


class SupabaseRemovedTests(unittest.TestCase):
    def test_leftover_supabase_settings_are_ignored_not_an_error(self):
        # Supabase support was removed; an old .env that still sets one of the pair must not break startup.
        for leftovers in ({"SUPABASE_URL": "https://example.supabase.co"}, {"SUPABASE_KEY": "k"},
                          {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_KEY": "k"}):
            with self.subTest(leftovers=sorted(leftovers)):
                config = AppConfig.from_environment({**BASE_ENV, **leftovers})
                self.assertFalse(hasattr(config, "supabase_url"))
                self.assertFalse(hasattr(config, "supabase_enabled"))


class ServerKeyOptionalTests(unittest.TestCase):
    # Users bring their own OpenAI key through the landing page, so the server's own key is only a fallback.
    def test_the_server_openai_key_is_optional(self):
        values = {k: v for k, v in BASE_ENV.items() if k != "OPEN_AI_KEY"}
        self.assertIsNone(AppConfig.from_environment(values).openai_api_key)

    def test_a_blank_server_key_counts_as_absent(self):
        self.assertIsNone(AppConfig.from_environment({**BASE_ENV, "OPEN_AI_KEY": "   "}).openai_api_key)

    def test_the_generic_openai_api_key_variable_is_never_used(self):
        values = {k: v for k, v in BASE_ENV.items() if k != "OPEN_AI_KEY"}
        self.assertIsNone(AppConfig.from_environment({**values, "OPENAI_API_KEY": "system-wide"}).openai_api_key)

    def test_the_model_and_database_settings_are_still_required(self):
        for missing in ("OPEN_AI_MODEL", "MOTHERDUCK_TOKEN"):
            with self.subTest(missing=missing):
                with self.assertRaisesRegex(ConfigurationError, missing):
                    AppConfig.from_environment({k: v for k, v in BASE_ENV.items() if k != missing})

    def test_admin_scripts_that_call_openai_themselves_get_a_clear_error_without_it(self):
        values = {k: v for k, v in BASE_ENV.items() if k != "OPEN_AI_KEY"}
        with self.assertRaisesRegex(ConfigurationError, "OPEN_AI_KEY"):
            AppConfig.from_environment(values).require_openai_api_key()
        self.assertEqual(AppConfig.from_environment(BASE_ENV).require_openai_api_key(), "project-key")


class OptionalServiceConfigurationTests(unittest.TestCase):
    def test_optional_durable_services_are_disabled_when_both_values_are_absent(self):
        config = AppConfig.from_environment(BASE_ENV)

        self.assertFalse(config.qdrant_enabled)
        self.assertFalse(config.langfuse_enabled)

    def test_qdrant_runtime_requires_an_embedding_model(self):
        with self.assertRaisesRegex(ConfigurationError, "OPEN_AI_EMBEDDING_MODEL"):
            AppConfig.from_environment({
                **BASE_ENV,
                "QDRANT_API_URL": "https://example.qdrant.io",
                "QDRANT_API_KEY": "qdrant-key",
            })

    def test_langfuse_base_url_is_read_when_configured(self):
        config = AppConfig.from_environment({
            **BASE_ENV,
            "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
            "LANGFUSE_SECRET_KEY": "sk-lf-test",
            "LANGFUSE_BASE_URL": "https://jp.cloud.langfuse.com",
        })

        self.assertTrue(config.langfuse_enabled)
        self.assertEqual(config.langfuse_host, "https://jp.cloud.langfuse.com")

    def test_langfuse_host_defaults_to_none_when_unset(self):
        config = AppConfig.from_environment({
            **BASE_ENV,
            "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
            "LANGFUSE_SECRET_KEY": "sk-lf-test",
        })

        self.assertIsNone(config.langfuse_host)

    def test_langfuse_verbose_tracing_defaults_to_false(self):
        config = AppConfig.from_environment({
            **BASE_ENV,
            "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
            "LANGFUSE_SECRET_KEY": "sk-lf-test",
        })

        self.assertFalse(config.langfuse_verbose_tracing)

    def test_langfuse_verbose_tracing_reads_a_truthy_env_value(self):
        for truthy in ("true", "True", "1", "yes"):
            config = AppConfig.from_environment({
                **BASE_ENV,
                "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
                "LANGFUSE_SECRET_KEY": "sk-lf-test",
                "LANGFUSE_VERBOSE_TRACING": truthy,
            })
            self.assertTrue(config.langfuse_verbose_tracing, f"expected {truthy!r} to be truthy")

    def test_langfuse_verbose_tracing_reads_a_falsy_env_value(self):
        for falsy in ("false", "False", "0", "no", ""):
            config = AppConfig.from_environment({
                **BASE_ENV,
                "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
                "LANGFUSE_SECRET_KEY": "sk-lf-test",
                "LANGFUSE_VERBOSE_TRACING": falsy,
            })
            self.assertFalse(config.langfuse_verbose_tracing, f"expected {falsy!r} to be falsy")


if __name__ == "__main__":
    unittest.main()