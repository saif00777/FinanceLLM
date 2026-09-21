"""Read-only MotherDuck execution behind the SQL policy boundary."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Protocol

from ingestion.motherduck import connect_motherduck

from app.helpers.sql_policy import SqlPolicy


class QueryExecutionError(RuntimeError):
    """A database failure safe to return from the service boundary."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]


class QueryRunner(Protocol):
    def run(self, sql: str) -> QueryResult:
        """Execute a policy-approved read-only query."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


class MotherDuckQueryRunner:
    """Execute only validated SQL against the configured canonical database."""

    def __init__(
        self,
        token: str,
        database: str = "financial_transactions",
        policy: SqlPolicy | None = None,
        connect: Callable[[str], Any] | None = None,
    ):
        self._token = token
        self._database = database
        self._policy = policy or SqlPolicy()
        self._connect = connect or self._connect_to_database

    def _connect_to_database(self, token: str) -> Any:
        connection = connect_motherduck(token)
        connection.execute(f"USE {self._database}")
        return connection

    def run(self, sql: str) -> QueryResult:
        approved_sql = self._policy.validate(sql)
        connection = None
        try:
            connection = self._connect(self._token)
            cursor = connection.execute(approved_sql)
            columns = [column[0] for column in cursor.description]
            rows = [[_json_safe(value) for value in row] for row in cursor.fetchall()]
            return QueryResult(columns=columns, rows=rows)
        except QueryExecutionError:
            raise
        except Exception as error:
            raise QueryExecutionError("The database query could not be completed") from error
        finally:
            if connection is not None:
                connection.close()
