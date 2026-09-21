import unittest

from app.agents.text_to_sql.specialists import DeterministicSuggestedQuestionSpecialist


class SpecialistTests(unittest.TestCase):
    def test_suggested_questions_are_limited_to_three_catalog_terms(self):
        questions = DeterministicSuggestedQuestionSpecialist().suggest(
            "spending by category", {"year": "2019"}, ("main.transactions", "main.mcc_codes")
        )

        self.assertLessEqual(len(questions), 3)
        self.assertTrue(questions)
        self.assertTrue(all("card_number" not in item.lower() for item in questions))


if __name__ == "__main__":
    unittest.main()