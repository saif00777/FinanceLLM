import importlib
from pathlib import Path
import unittest


class ModuleLayoutTests(unittest.TestCase):
    def test_public_backend_modules_follow_layered_structure(self):
        for module in (
            "app.api.main", "app.agents.text_to_sql.workflow", "app.helpers.config",
            "app.helpers.embedder", "app.agents.rag",
        ):
            with self.subTest(module=module):
                self.assertIsNotNone(importlib.import_module(module))

    def test_entry_points_resolve_the_repository_root(self):
        from app.api.main import ROOT as api_root

        self.assertEqual(api_root, Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    unittest.main()