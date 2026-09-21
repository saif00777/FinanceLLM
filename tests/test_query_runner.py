import datetime as dt
from decimal import Decimal
import unittest

from app.helpers.query_runner import MotherDuckQueryRunner, QueryExecutionError
from app.helpers.sql_policy import SqlPolicyError


VALID_SQL = "SELECT t.amount FROM main.transactions AS t LIMIT 1"


class FakeConnection:
    description = [("amount",), ("recorded_at",), ("metadata",)]

    def __init__(self):
        self.executed_sql = None
        self.closed = False

    def execute(self, sql):
        self.executed_sql = sql
        return self

    def fetchall(self):
        return [(Decimal("12.30"), dt.datetime(2019, 1, 2, 3, 4, 5), None)]

    def close(self):
        self.closed = True


class QueryRunnerTests(unittest.TestCase):
    def test_runner_serializes_rows_and_closes_connection(self):
        connection = FakeConnection()
        runner = MotherDuckQueryRunner(
            token="test-token", connect=lambda token: connection
        )

        result = runner.run(VALID_SQL)

        self.assertEqual(result.columns, ["amount", "recorded_at", "metadata"])
        self.assertEqual(result.rows, [[12.3, "2019-01-02T03:04:05", None]])
        self.assertIn("main.transactions", connection.executed_sql)
        self.assertTrue(connection.closed)

    def test_runner_rejects_unsafe_sql_before_connecting(self):
        connection_attempts = []
        runner = MotherDuckQueryRunner(
            token="test-token", connect=lambda token: connection_attempts.append(token)
        )

        with self.assertRaises(SqlPolicyError):
            runner.run("SELECT * FROM source.cards LIMIT 1")

        self.assertEqual(connection_attempts, [])

    def test_runner_hides_database_exception_details(self):
        class FailingConnection(FakeConnection):
            def execute(self, sql):
                raise RuntimeError("token=test-token customer-sensitive-value")

        runner = MotherDuckQueryRunner(
            token="test-token", connect=lambda token: FailingConnection()
        )

        with self.assertRaisesRegex(QueryExecutionError, "could not be completed") as caught:
            runner.run(VALID_SQL)

        self.assertNotIn("test-token", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
