import unittest

from app.helpers.config import AppConfig, ConfigurationError


BASE_ENV = {
    "OPEN_AI_KEY": "project-key",
    "OPEN_AI_MODEL": "gpt-4o",
    "MOTHERDUCK_TOKEN": "motherduck-key",
}


class OptionalServiceConfigurationTests(unittest.TestCase):
    def test_optional_durable_services_are_disabled_when_both_values_are_absent(self):
        config = AppConfig.from_environment(BASE_ENV)

        self.assertFalse(config.supabase_enabled)
        self.assertFalse(config.qdrant_enabled)
        self.assertFalse(config.langfuse_enabled)

    def test_qdrant_runtime_requires_an_embedding_model(self):
        with self.assertRaisesRegex(ConfigurationError, "OPEN_AI_EMBEDDING_MODEL"):
            AppConfig.from_environment({
                **BASE_ENV,
                "QDRANT_API_URL": "https://example.qdrant.io",
                "QDRANT_API_KEY": "qdrant-key",
            })

    def test_partial_supabase_configuration_is_rejected(self):
        with self.assertRaisesRegex(ConfigurationError, "SUPABASE"):
            AppConfig.from_environment(
                {**BASE_ENV, "SUPABASE_URL": "https://example.supabase.co"}
            )


if __name__ == "__main__":
    unittest.main()