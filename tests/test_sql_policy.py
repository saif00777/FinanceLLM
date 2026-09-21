from pathlib import Path
import unittest

import yaml

from app.helpers.sql_policy import SqlPolicy, SqlPolicyError


ROOT = Path(__file__).resolve().parents[1]
VALID_SQL = (
    "SELECT t.mcc, SUM(t.amount) AS total "
    "FROM main.transactions AS t "
    "GROUP BY t.mcc ORDER BY total DESC LIMIT 10"
)


class SqlPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = SqlPolicy()

    def test_allows_canonical_aggregate_query(self):
        normalized = self.policy.validate(VALID_SQL)

        self.assertIn("main.transactions", normalized)
        self.assertIn("LIMIT 10", normalized)

    def test_allows_count_star_but_not_wildcard_projection(self):
        allowed = "SELECT COUNT(*) AS transaction_count FROM main.transactions AS t LIMIT 1"
        self.assertIn("COUNT(*)", self.policy.validate(allowed))

        with self.assertRaisesRegex(SqlPolicyError, "wildcard"):
            self.policy.validate("SELECT * FROM main.transactions AS t LIMIT 1")

    def test_rejects_source_schema_before_query_execution(self):
        with self.assertRaisesRegex(SqlPolicyError, "allowed relation"):
            self.policy.validate("SELECT card_number FROM source.cards LIMIT 1")

    def test_rejects_unqualified_relation(self):
        with self.assertRaisesRegex(SqlPolicyError, "fully qualified"):
            self.policy.validate("SELECT t.mcc FROM transactions AS t LIMIT 1")

    def test_rejects_column_outside_canonical_schema(self):
        with self.assertRaisesRegex(SqlPolicyError, "allowed column"):
            self.policy.validate("SELECT t.card_number FROM main.transactions AS t LIMIT 1")

    def test_rejects_non_select_multiple_and_file_sql(self):
        statements = (
            "DELETE FROM main.transactions",
            "SELECT t.mcc FROM main.transactions AS t LIMIT 1; SELECT 1",
            "SELECT * FROM read_csv_auto('transactions.csv') LIMIT 1",
        )
        for sql in statements:
            with self.subTest(sql=sql):
                with self.assertRaises(SqlPolicyError):
                    self.policy.validate(sql)

    def test_requires_bounded_limit(self):
        for sql in (
            "SELECT t.mcc FROM main.transactions AS t",
            "SELECT t.mcc FROM main.transactions AS t LIMIT 101",
        ):
            with self.subTest(sql=sql):
                with self.assertRaisesRegex(SqlPolicyError, "LIMIT"):
                    self.policy.validate(sql)

    def test_all_reviewed_semantic_examples_satisfy_the_policy(self):
        with (ROOT / "context" / "semantics.yaml").open(encoding="utf-8") as stream:
            examples = yaml.safe_load(stream)["examples"]

        for example in examples:
            with self.subTest(example=example["id"]):
                self.policy.validate(example["sql"])


if __name__ == "__main__":
    unittest.main()
