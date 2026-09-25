from pathlib import Path
import unittest

from app.helpers.config import AppConfig, ConfigurationError
from app.agents.text_to_sql.contracts import RuntimeContract


ROOT = Path(__file__).resolve().parents[1]


class ConfigurationTests(unittest.TestCase):
    def test_configuration_uses_only_the_project_open_ai_key(self):
        config = AppConfig.from_environment(
            {
                "OPEN_AI_KEY": "project-key",
                "OPENAI_API_KEY": "system-wide-key",
                "OPEN_AI_MODEL": "gpt-4o",
                "MOTHERDUCK_TOKEN": "motherduck-key",
            }
        )

        self.assertEqual(config.openai_api_key, "project-key")

    def test_the_generic_openai_api_key_variable_is_ignored(self):
        # A machine-wide OPENAI_API_KEY (used by other tools) must never become this server's key: users bring
        # their own key, and a stale system variable silently used instead is worse than a clear 401.
        config = AppConfig.from_environment(
            {
                "OPENAI_API_KEY": "system-wide-key",
                "OPEN_AI_MODEL": "gpt-4o",
                "MOTHERDUCK_TOKEN": "motherduck-key",
            }
        )

        self.assertIsNone(config.openai_api_key)

    def test_configuration_rejects_missing_required_value(self):
        with self.assertRaisesRegex(ConfigurationError, "OPEN_AI_MODEL"):
            AppConfig.from_environment(
                {"OPEN_AI_KEY": "project-key", "MOTHERDUCK_TOKEN": "motherduck-key"}
            )


class RuntimeContractTests(unittest.TestCase):
    def test_runtime_contract_excludes_private_source_details(self):
        prompt = RuntimeContract.from_files(ROOT).as_prompt()

        self.assertIn("main.transactions", prompt)
        self.assertIn("main.mcc_codes", prompt)
        self.assertNotIn("source.cards", prompt)
        self.assertNotIn("card_number", prompt)

    def test_runtime_contract_includes_semantic_boundaries(self):
        prompt = RuntimeContract.from_files(ROOT).as_prompt()

        self.assertIn("unsupported", prompt.lower())
        self.assertIn("No transaction fraud label", prompt)


if __name__ == "__main__":
    unittest.main()
