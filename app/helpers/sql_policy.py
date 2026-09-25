"""AST-based policy for model-generated DuckDB SQL."""

from pathlib import Path

import sqlglot
from sqlglot import exp
import yaml


ROOT = Path(__file__).resolve().parents[2]


class SqlPolicyError(ValueError):
    """Raised when generated SQL falls outside the application allowlist."""


class SqlPolicy:
    """Allow one bounded read-only query over the canonical MotherDuck views."""

    allowed_relations = {
        ("main", "transactions"),
        ("main", "cards"),
        ("main", "users"),
        ("main", "mcc_codes"),
    }
    allowed_functions = {
        "ABS",
        "AVG",
        "CASE",
        "CAST",
        "CEIL",
        "COALESCE",
        "COUNT",
        "EXTRACT",
        "FLOOR",
        "IF",
        "LOWER",
        "MAX",
        "MIN",
        "NULLIF",
        "ROUND",
        "SUM",
        "TIMESTAMP_TRUNC",
        "UPPER",
    }
    non_function_nodes = (exp.And, exp.Exists)
    maximum_limit = 100

    def __init__(self, relation_columns: dict[tuple[str, str], set[str]] | None = None):
        self._relation_columns = relation_columns or self._load_relation_columns()

    @staticmethod
    def _load_relation_columns() -> dict[tuple[str, str], set[str]]:
        with (ROOT / "context" / "schema.yaml").open(encoding="utf-8") as stream:
            schema = yaml.safe_load(stream)
        return {
            ("main", table_name): set(table["columns"])
            for table_name, table in schema["tables"].items()
        }

    def validate(self, sql: str) -> str:
        """Validate and normalize a single canonical, bounded read query."""
        if not isinstance(sql, str) or not sql.strip():
            raise SqlPolicyError("SQL must be a non-empty string")
        try:
            statements = sqlglot.parse(sql, read="duckdb")
        except sqlglot.errors.ParseError as error:
            raise SqlPolicyError("SQL could not be parsed") from error
        if len(statements) != 1:
            raise SqlPolicyError("Exactly one SQL statement is allowed")

        expression = statements[0]
        if not isinstance(expression, exp.Select):
            raise SqlPolicyError("Only SELECT queries are allowed")

        aliases, cte_names = self._validate_tables(expression)
        self._validate_columns(expression, aliases, cte_names)
        self._validate_projection(expression)
        self._validate_functions(expression)
        self._validate_limit(expression)
        return expression.sql(dialect="duckdb")

    @staticmethod
    def relations_used(sql: str) -> tuple[str, ...]:
        """Schema-qualified relations a query references (CTE names excluded), each once, in no guaranteed order.

        Lets conversation memory record what an answer was actually about rather than every
        table the schema linker merely considered."""
        try:
            expression = sqlglot.parse_one(sql, read="duckdb")
        except sqlglot.errors.ParseError:
            return ()
        cte_names = {cte.alias_or_name.lower() for cte in expression.find_all(exp.CTE) if cte.alias_or_name}
        used: list[str] = []
        for table in expression.find_all(exp.Table):
            if not table.db and table.name.lower() in cte_names:
                continue
            relation = f"{table.db}.{table.name}".lower() if table.db else table.name.lower()
            if relation not in used:
                used.append(relation)
        return tuple(used)

    def _validate_tables(self, expression: exp.Expression) -> tuple[dict[str, set[str]], set[str]]:
        cte_names = {
            cte.alias_or_name.lower()
            for cte in expression.find_all(exp.CTE)
            if cte.alias_or_name
        }
        aliases: dict[str, set[str]] = {}
        for table in expression.find_all(exp.Table):
            table_name = table.name.lower()
            schema_name = (table.db or "").lower()
            catalog_name = (table.catalog or "").lower()
            if not schema_name and not catalog_name and table_name in cte_names:
                continue
            if not schema_name:
                raise SqlPolicyError("Every relation must be fully qualified with main")
            relation = (schema_name, table_name)
            if catalog_name or relation not in self.allowed_relations:
                raise SqlPolicyError(f"Relation is not in the allowed relation list: {table.sql()}")
            columns = self._relation_columns[relation]
            aliases[table_name] = columns
            aliases[table.alias_or_name.lower()] = columns
        return aliases, cte_names

    @staticmethod
    def _validate_columns(
        expression: exp.Expression, aliases: dict[str, set[str]], cte_names: set[str]
    ) -> None:
        # A column written without a table alias must still be an allowlisted column of a table in the query, or
        # an alias the query itself defines (e.g. `GROUP BY year ORDER BY total`). Skipping unqualified columns
        # would let a non-allowlisted one (cvv, card_number) through just by leaving off the alias.
        defined_aliases = {alias.alias.lower() for alias in expression.find_all(exp.Alias) if alias.alias}
        table_columns = {name.lower() for columns in aliases.values() for name in columns}
        for column in expression.find_all(exp.Column):
            if isinstance(column.this, exp.Star):
                continue
            if not column.table:
                name = column.name.lower()
                if name not in defined_aliases and name not in table_columns:
                    raise SqlPolicyError(f"Column is not in the allowed column list: {column.sql()}")
                continue
            table_alias = column.table.lower()
            if table_alias in cte_names:
                continue
            allowed_columns = aliases.get(table_alias)
            if allowed_columns is None or column.name not in allowed_columns:
                raise SqlPolicyError(f"Column is not in the allowed column list: {column.sql()}")

    @staticmethod
    def _validate_projection(expression: exp.Expression) -> None:
        for star in expression.find_all(exp.Star):
            if not isinstance(star.parent, exp.Count):
                raise SqlPolicyError("wildcard projections are not allowed")

    def _validate_functions(self, expression: exp.Expression) -> None:
        for function in expression.find_all(exp.Func):
            if isinstance(function, self.non_function_nodes):
                continue
            function_name = function.sql_name().upper()
            if function_name not in self.allowed_functions:
                raise SqlPolicyError(f"Function is not allowed: {function_name}")

    @staticmethod
    def _is_scalar_aggregate(expression: exp.Select) -> bool:
        if expression.args.get("group") is not None:
            return False
        return any(projection.find(exp.AggFunc) is not None for projection in expression.expressions)

    def _validate_limit(self, expression: exp.Select) -> None:
        limit = expression.args.get("limit")
        if limit is None:
            if not self._is_scalar_aggregate(expression):
                # A missing limit can only be bounded, never widened, so it is normalized instead of rejected: the
                # model often omitted it on GROUP BY queries and repeated the same SQL on every repair.
                expression.limit(self.maximum_limit, copy=False)
            return
        value = limit.expression
        if not isinstance(value, exp.Literal) or not value.is_int:
            raise SqlPolicyError(f"A numeric LIMIT between 1 and {self.maximum_limit} is required")
        row_limit = int(value.this)
        if row_limit < 1 or row_limit > self.maximum_limit:
            raise SqlPolicyError(f"A LIMIT between 1 and {self.maximum_limit} is required")
