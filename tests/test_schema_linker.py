from pathlib import Path
import unittest

from app.agents.text_to_sql.contracts import RuntimeContract


ROOT = Path(__file__).resolve().parents[1]


class SchemaLinkerTests(unittest.TestCase):
    def test_linker_returns_transactions_and_mcc_for_category_spending(self):
        linked = RuntimeContract.from_files(ROOT).link("Show spending by merchant category")

        self.assertEqual(linked.relations, ("main.transactions", "main.mcc_codes"))
        self.assertIn("main.transactions", linked.prompt)
        self.assertIn("main.mcc_codes", linked.prompt)
        self.assertNotIn("source.cards", linked.prompt)
        self.assertNotIn("card_number", linked.prompt)


if __name__ == "__main__":
    unittest.main()