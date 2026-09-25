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

    def test_a_cards_question_is_not_dragged_towards_transactions_by_stopwords_in_metric_labels(self):
        # Regression: the word "of" in the label "Magnitude of negative recorded amounts" matched
        # "credit limit of cards", scoring the transactions table for a pure cards question.
        linked = RuntimeContract.from_files(ROOT).link("what is the credit limit of cards?")

        self.assertEqual(linked.relations, ("main.cards",))

    def test_a_follow_up_with_no_table_signal_keeps_the_previous_turns_relations(self):
        linked = RuntimeContract.from_files(ROOT).link("tell me the average", prior_relations=("main.cards",))

        self.assertEqual(linked.relations, ("main.cards",))
        self.assertIn("main.cards", linked.prompt)

    def test_a_question_with_its_own_table_signal_ignores_the_previous_relations(self):
        linked = RuntimeContract.from_files(ROOT).link("Show spending by merchant category", prior_relations=("main.cards",))

        self.assertEqual(linked.relations, ("main.transactions", "main.mcc_codes"))

    def test_a_signal_free_question_with_no_history_still_defaults_to_transactions(self):
        linked = RuntimeContract.from_files(ROOT).link("tell me the average")

        self.assertEqual(linked.relations, ("main.transactions",))

    def test_prompt_gives_explicit_limit_and_date_part_guidance(self):
        linked = RuntimeContract.from_files(ROOT).link("Show spending by merchant category")

        self.assertIn("LIMIT", linked.prompt)
        self.assertIn("EXTRACT", linked.prompt)


if __name__ == "__main__":
    unittest.main()