from pathlib import Path
import unittest

from app.agents.text_to_sql.contracts import RuntimeContract

ROOT = Path(__file__).resolve().parents[1]


class BusinessContextTests(unittest.TestCase):
    def setUp(self):
        self.text = RuntimeContract.from_files(ROOT).business_context()

    def test_describes_every_table_with_its_columns_and_meaning(self):
        for relation in ("main.transactions", "main.cards", "main.users", "main.mcc_codes"):
            self.assertIn(relation, self.text)
        # column name AND its business description, not just the name
        self.assertIn("credit_limit", self.text)
        self.assertIn("has_chip", self.text)

    def test_includes_how_tables_relate(self):
        self.assertIn("Relationships", self.text)
        self.assertIn("transactions", self.text)
        self.assertIn("users", self.text)

    def test_includes_business_terms_metrics_and_what_cannot_be_answered(self):
        self.assertIn("Net signed recorded amount", self.text)  # a governed metric
        self.assertIn("chip", self.text.lower())  # glossary term
        self.assertIn("Confirmed fraud", self.text)  # an unsupported topic, with its reason

    def test_describes_the_document_corpus_so_agents_know_rag_exists(self):
        # Without this the domain guard refuses document questions as unrelated to the SQL tables.
        lowered = self.text.lower()
        self.assertIn("larkspur ridge", lowered)
        self.assertIn('source "rag"', lowered)
        self.assertNotIn("complaint narratives", lowered)

    def test_never_exposes_private_source_tables(self):
        self.assertNotIn("source.", self.text)

    def test_is_compact_enough_to_send_with_a_request(self):
        self.assertLess(len(self.text), 30_000)


if __name__ == "__main__":
    unittest.main()
