import importlib
from pathlib import Path
import unittest


class ModuleLayoutTests(unittest.TestCase):
    def test_public_backend_modules_follow_layered_structure(self):
        for module in (
            "app.api.main", "app.agents.text_to_sql.workflow", "app.helpers.config",
            "ingestion.complaints.documents", "ingestion.complaints.pipeline",
        ):
            with self.subTest(module=module):
                self.assertIsNotNone(importlib.import_module(module))

    def test_entry_points_resolve_the_repository_root(self):
        from app.api.main import ROOT as api_root
        from ingestion.complaints.cli import ROOT as complaints_root

        root = Path(__file__).resolve().parents[1]
        self.assertEqual(api_root, root)
        self.assertEqual(complaints_root, root)


if __name__ == "__main__":
    unittest.main()