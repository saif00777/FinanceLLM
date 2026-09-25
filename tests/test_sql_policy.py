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

    def test_rejects_unqualified_columns_that_are_not_allowlisted(self):
        # The validator used to skip any column written without a table alias, so an unqualified sensitive column
        # (cvv, card_number) passed while `c.cvv` was rejected. Also `state` on main.users crashed the database.
        for sql in (
            "SELECT cvv FROM main.cards LIMIT 5",
            "SELECT card_number FROM main.cards LIMIT 5",
            "SELECT state, COUNT(client_id) AS n FROM main.users GROUP BY state LIMIT 5",
            "SELECT c.credit_limit FROM main.cards AS c WHERE cvv = 1 LIMIT 5",
        ):
            with self.subTest(sql=sql):
                with self.assertRaisesRegex(SqlPolicyError, "allowed column"):
                    self.policy.validate(sql)

    def test_allows_unqualified_allowlisted_columns_and_select_aliases(self):
        for sql in (
            "SELECT has_chip FROM main.cards LIMIT 5",
            "SELECT EXTRACT(YEAR FROM t.transaction_at) AS year, COUNT(*) AS n FROM main.transactions AS t GROUP BY year ORDER BY year LIMIT 10",
            "SELECT t.mcc, SUM(t.amount) AS total FROM main.transactions AS t GROUP BY t.mcc ORDER BY total DESC LIMIT 10",
            "WITH x AS (SELECT t.mcc AS code, COUNT(*) AS n FROM main.transactions AS t GROUP BY t.mcc) SELECT code, n FROM x ORDER BY n DESC LIMIT 5",
        ):
            with self.subTest(sql=sql):
                self.assertIn("LIMIT", self.policy.validate(sql))

    def test_rejects_an_explicit_limit_that_is_too_large_or_not_a_number(self):
        for sql in (
            "SELECT t.mcc FROM main.transactions AS t LIMIT 101",
            "SELECT t.mcc FROM main.transactions AS t LIMIT 0",
        ):
            with self.subTest(sql=sql):
                with self.assertRaisesRegex(SqlPolicyError, "LIMIT"):
                    self.policy.validate(sql)

    def test_adds_the_maximum_limit_when_a_row_returning_query_has_none(self):
        # Live: the model omitted LIMIT on GROUP BY queries and repeated the identical SQL on all 3 repairs, so
        # the user got "Couldn't validate a query". A missing limit can only be bounded, never widened, so it is
        # normalized rather than rejected.
        for sql in (
            "SELECT t.mcc FROM main.transactions AS t",
            "SELECT EXTRACT(YEAR FROM t.transaction_at) AS year, COUNT(*) AS n FROM main.transactions AS t GROUP BY year ORDER BY year",
        ):
            with self.subTest(sql=sql):
                self.assertTrue(self.policy.validate(sql).endswith("LIMIT 100"))

    def test_leaves_a_scalar_aggregate_unbounded(self):
        self.assertNotIn("LIMIT", self.policy.validate("SELECT COUNT(*) AS n FROM main.transactions AS t"))

    def test_allows_case_expressions_used_by_canonical_metrics(self):
        # Mirrors context/semantics.yaml's positive_amount_total expression_sql, which is
        # injected verbatim into the SQL-generation prompt — the policy must accept it.
        sql = (
            "SELECT COALESCE(SUM(CASE WHEN t.amount > 0 THEN t.amount ELSE 0 END), 0) AS total "
            "FROM main.transactions AS t"
        )
        normalized = self.policy.validate(sql)
        self.assertIn("CASE", normalized)

    def test_all_reviewed_semantic_examples_satisfy_the_policy(self):
        with (ROOT / "context" / "semantics.yaml").open(encoding="utf-8") as stream:
            examples = yaml.safe_load(stream)["examples"]

        for example in examples:
            with self.subTest(example=example["id"]):
                self.policy.validate(example["sql"])

    def test_relations_used_lists_only_the_tables_the_sql_actually_references(self):
        sql = "SELECT c.credit_limit FROM main.cards AS c WHERE c.has_chip = true LIMIT 10"

        self.assertEqual(SqlPolicy.relations_used(sql), ("main.cards",))

    def test_relations_used_reports_joins_once_each_and_skips_ctes(self):
        sql = (
            "WITH t AS (SELECT * FROM main.transactions) "
            "SELECT m.description, COUNT(*) FROM t JOIN main.mcc_codes AS m ON t.mcc = m.mcc "
            "JOIN main.transactions AS x ON x.mcc = m.mcc GROUP BY m.description LIMIT 5"
        )

        self.assertCountEqual(SqlPolicy.relations_used(sql), ("main.transactions", "main.mcc_codes"))

    def test_relations_used_is_empty_for_unparseable_sql(self):
        self.assertEqual(SqlPolicy.relations_used("SELEC nonsense ((("), ())


if __name__ == "__main__":
    unittest.main()
