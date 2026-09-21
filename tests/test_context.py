"""Exercise the context's declared SQL with synthetic data, never cardholder samples.

Run: python -m unittest discover -s tests -v
The optional .context-tools directory contains local validation dependencies.
"""

import csv
import datetime as dt
from decimal import Decimal
import json
import hashlib
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = ROOT / ".context-tools"
# Reuse bundled extensions only when compatible with this interpreter.
# Installed environment packages take precedence over this optional fallback.
if any((LOCAL_DEPS / f"_duckdb{suffix}").is_file() for suffix in EXTENSION_SUFFIXES):
    sys.path.append(str(LOCAL_DEPS))
import duckdb
import yaml


def load_contract(test, name):
    path = ROOT / "context" / name
    test.assertTrue(path.is_file(), f"Missing approved context artifact: {name}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def make_fixture(connection, schema):
    """Independent source-shaped fixtures with one deliberately unmatched MCC."""
    fixtures = {
        "users": [
            {"id": "1", "current_age": "40", "yearly_income": "$60000", "total_debt": "$12000"},
            {"id": "2", "current_age": "60", "yearly_income": "$40000", "total_debt": "$8000"},
        ],
        "cards": [
            {"id": "10", "client_id": "1", "card_brand": "Visa", "card_type": "Credit",
             "has_chip": "YES", "credit_limit": "$1,234.50", "acct_open_date": "09/2002", "card_on_dark_web": "No"},
            {"id": "11", "client_id": "1", "card_brand": "Visa", "card_type": "Debit", "has_chip": "NO"},
            {"id": "20", "client_id": "2", "card_brand": "Amex", "card_type": "Credit", "has_chip": "YES"},
        ],
        "transactions": [
            {"id": "101", "date": "2019-01-01 00:00:00", "client_id": "1", "card_id": "10", "amount": "$100.00",
             "use_chip": "Chip Transaction", "mcc": "5411", "merchant_id": "5", "zip": "1234.0"},
            {"id": "102", "date": "2019-01-02 12:00:00", "client_id": "1", "card_id": "11", "amount": "$-20.00",
             "use_chip": "Swipe Transaction", "mcc": "5411", "merchant_id": "5", "zip": "01234"},
            {"id": "103", "date": "2019-01-31 23:59:59", "client_id": "2", "card_id": "20", "amount": "$40.00",
             "use_chip": "Online Transaction", "mcc": "9999", "merchant_id": "6", "errors": "Bad PIN"},
            {"id": "104", "date": "2019-02-01 00:00:00", "client_id": "1", "card_id": "10", "amount": "$0.00",
             "use_chip": "Swipe Transaction", "mcc": "5411", "merchant_id": "5", "errors": "  "},
        ],
        "mcc_codes": [{"mcc": "5411", "description": "Grocery Stores, Supermarkets"}],
    }
    for name, table in schema["tables"].items():
        columns = list(table["columns"])
        definition = ", ".join(f'"{col}" VARCHAR' for col in columns)
        connection.execute(f'CREATE TABLE raw_{name} ({definition})')
        marks = ", ".join("?" for _ in columns)
        connection.executemany(f'INSERT INTO raw_{name} VALUES ({marks})',
                               [[row.get(col) for col in columns] for row in fixtures[name]])
        projections = [f'{field["expression_sql"]} AS "{field["canonical_name"]}"'
                       for field in table["columns"].values() if field["expose_to_llm"]]
        connection.execute(f'CREATE VIEW {name} AS SELECT {", ".join(projections)} FROM raw_{name} src')


class ContextBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.schema = load_contract(self, "schema.yaml")
        self.import_schema = load_contract(self, "import_schema.yaml")
        self.semantics = load_contract(self, "semantics.yaml")
        self.db = duckdb.connect()
        self.addCleanup(self.db.close)
        make_fixture(self.db, self.import_schema)

    def test_exact_money_sign_and_postal_normalization(self):
        self.assertEqual(self.db.execute("SELECT amount, merchant_postal_code FROM transactions ORDER BY transaction_id").fetchall(),
                         [(Decimal("100.00"), "01234"), (Decimal("-20.00"), "01234"),
                          (Decimal("40.00"), None), (Decimal("0.00"), None)])

    def test_card_month_precision_and_boolean_values(self):
        self.assertEqual(self.db.execute("SELECT credit_limit, account_open_month, has_chip, card_on_dark_web FROM cards WHERE card_id=10").fetchone(),
                         (Decimal("1234.50"), dt.date(2002, 9, 1), True, False))
        self.assertIs(self.db.execute("SELECT has_chip FROM cards WHERE card_id=11").fetchone()[0], False)

    def test_malformed_amount_fails_instead_of_disappearing_from_totals(self):
        self.db.execute("UPDATE raw_transactions SET amount='broken' WHERE id='101'")
        with self.assertRaises(duckdb.Error):
            self.db.execute("SELECT sum(amount) FROM transactions").fetchall()

    def test_invalid_money_tokens_and_extra_fractional_cents_are_rejected(self):
        for table in self.import_schema["tables"].values():
            for raw_name, field in table["columns"].items():
                if field["duckdb_type"] != "DECIMAL(18,2)":
                    continue
                for token in ("$1$2", "$1,2", "$1.005"):
                    with self.subTest(field=raw_name, value=token):
                        sql = f'SELECT {field["expression_sql"]} FROM (SELECT ?::VARCHAR AS "{raw_name}") src'
                        with self.assertRaises(duckdb.Error):
                            self.db.execute(sql, [token]).fetchall()

    def test_whitespace_only_typed_values_are_null(self):
        for table in self.import_schema["tables"].values():
            for raw_name, field in table["columns"].items():
                if not field["expose_to_llm"] or field["duckdb_type"] == "VARCHAR":
                    continue
                with self.subTest(field=raw_name, type=field["duckdb_type"]):
                    sql = f'SELECT {field["expression_sql"]} FROM (SELECT ?::VARCHAR AS "{raw_name}") src'
                    self.assertIsNone(self.db.execute(sql, ["   "]).fetchone()[0])

    def test_fractional_integer_tokens_are_rejected_instead_of_rounded(self):
        for table in self.import_schema["tables"].values():
            for raw_name, field in table["columns"].items():
                if not field["expose_to_llm"] or field["duckdb_type"] not in ("BIGINT", "INTEGER"):
                    continue
                with self.subTest(field=raw_name, type=field["duckdb_type"]):
                    sql = f'SELECT {field["expression_sql"]} FROM (SELECT ?::VARCHAR AS "{raw_name}") src'
                    with self.assertRaises(duckdb.Error):
                        self.db.execute(sql, ["1.6"]).fetchall()

    def test_unknown_boolean_does_not_become_false(self):
        self.db.execute("UPDATE raw_cards SET has_chip='MAYBE' WHERE id='10'")
        with self.assertRaises(duckdb.Error):
            self.db.execute("SELECT has_chip FROM cards WHERE card_id=10").fetchall()

    def test_blank_error_and_missing_location_stay_unknown(self):
        self.assertEqual(self.db.execute("SELECT errors, merchant_state FROM transactions WHERE transaction_id=104").fetchone(), (None, None))

    def test_restricted_source_fields_are_absent_from_canonical_views(self):
        for table, forbidden in {"cards": {"card_number", "cvv", "expires"},
                                 "users": {"address", "latitude", "longitude", "birth_month"}}.items():
            exposed = {row[0] for row in self.db.execute(f"DESCRIBE {table}").fetchall()}
            self.assertFalse(exposed & forbidden)

    def test_declared_metric_results_include_negative_zero_and_error_rows(self):
        expected = {"transaction_count": 4, "positive_amount_total": Decimal("140.00"),
                    "negative_amount_magnitude": Decimal("20.00"), "net_amount": Decimal("120.00"),
                    "average_positive_amount": Decimal("70.00"), "negative_transaction_count": 1,
                    "error_recorded_count": 1, "error_recorded_rate": 0.25,
                    "transacting_customer_count": 2}
        for name, want in expected.items():
            with self.subTest(metric=name):
                metric = self.semantics["metrics"][name]
                got = self.db.execute(f'SELECT {metric["expression_sql"]} FROM transactions t').fetchone()[0]
                self.assertEqual(got, want)

    def test_empty_population_rate_and_average_are_undefined(self):
        for name in ("average_positive_amount", "error_recorded_rate"):
            expr = self.semantics["metrics"][name]["expression_sql"]
            self.assertIsNone(self.db.execute(f"SELECT {expr} FROM transactions t WHERE FALSE").fetchone()[0])

    def test_join_paths_preserve_transactions_and_unknown_categories(self):
        for relation in self.schema["relationships"]:
            sql = (f'SELECT count(*) FROM {relation["from_table"]} {relation["from_alias"]} '
                   f'LEFT JOIN {relation["to_table"]} {relation["to_alias"]} ON {relation["join_sql"]}')
            expected = 3 if relation["from_table"] == "cards" else 4
            self.assertEqual(self.db.execute(sql).fetchone()[0], expected)
        self.assertEqual(self.db.execute("SELECT count(*) FROM transactions t LEFT JOIN mcc_codes m ON t.mcc=m.mcc WHERE m.mcc IS NULL").fetchone()[0], 1)

    def test_declared_types_match_actual_projection_results(self):
        for name, table in self.schema["tables"].items():
            actual = {row[0]: row[1] for row in self.db.execute(f"DESCRIBE {name}").fetchall()}
            expected = {name: field["duckdb_type"] for name, field in table["columns"].items()}
            self.assertEqual(actual, expected)

    def test_examples_return_hand_checked_answers(self):
        expected = {
            "monthly_net_amount": [(dt.date(2019, 1, 1), Decimal("120.00")), (dt.date(2019, 2, 1), Decimal("0.00"))],
            "category_positive_amount": [("5411", "Grocery Stores, Supermarkets", Decimal("100.00")), ("9999", "Unknown MCC", Decimal("40.00"))],
            "card_type_positive_amount": [("Credit", Decimal("140.00"))],
            "customer_net_amount": [(1, Decimal("80.00")), (2, Decimal("40.00"))],
            "january_error_rate": [(3, 1, 1 / 3)],
            "average_income_of_transacting_customers": [(50000.0,)],
        }
        examples = {e["id"]: e for e in self.semantics["examples"]}
        self.assertEqual(set(examples), set(expected))
        for name, want in expected.items():
            with self.subTest(example=name):
                self.assertEqual(self.db.execute(examples[name]["sql"]).fetchall(), want)


class SourceContractTests(unittest.TestCase):
    def test_runtime_context_uses_motherduck_and_isolated_import_lineage(self):
        schema = load_contract(self, "schema.yaml")
        semantics = load_contract(self, "semantics.yaml")
        import_schema = load_contract(self, "import_schema.yaml")
        profile = json.loads((ROOT / "context" / "profile.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["contract_version"], "2.0.0")
        self.assertEqual(semantics["contract_version"], "2.0.0")
        self.assertEqual(profile["contract_version"], "2.0.0")
        self.assertEqual(schema["source_of_truth"]["kind"], "motherduck_database")
        self.assertEqual(schema["source_of_truth"]["database"], "financial_transactions")
        self.assertEqual(profile["source_of_truth"]["kind"], "motherduck_database")
        self.assertEqual(schema["lineage"]["import_contract"], "context/import_schema.yaml")
        self.assertEqual(profile["lineage"]["import_profile"], "context/import_profile.json")
        self.assertEqual(semantics["access_policy"]["credential_status"], "temporary_owner_token")
        for name, table in schema["tables"].items():
            self.assertEqual(table["relation"]["qualified_name"], f"main.{name}")
            self.assertEqual(table["relation"]["object_type"], "VIEW")
            self.assertTrue(all("expression_sql" not in column for column in table["columns"].values()))
            self.assertTrue(all("expression_sql" not in column for column in table["columns"].values()))
        self.assertIn("card_number", import_schema["tables"]["cards"]["columns"])
        self.assertNotIn("card_number", schema["tables"]["cards"]["columns"])

    def test_runtime_profile_does_not_expose_private_catalog_details_or_mask_owner_mismatches(self):
        semantics = load_contract(self, "semantics.yaml")
        profile = json.loads((ROOT / "context" / "profile.json").read_text(encoding="utf-8"))
        self.assertNotIn("private_source_relations", profile)
        self.assertEqual(profile["private_source_boundary"]["schema"], "source")
        self.assertEqual(semantics["access_policy"]["field_policy"], "Only columns declared in context/schema.yaml are model-visible; private source columns are never model-visible.")
        ownership_query = next(query for query in profile["reproduction_queries"] if "transaction_card_owner_mismatches" not in query and "t.client_id IS DISTINCT FROM c.client_id" in query)
        self.assertIn("LEFT JOIN main.cards c ON t.card_id=c.card_id", ownership_query)
        self.assertNotIn("t.card_id=c.card_id AND t.client_id=c.client_id", ownership_query)

    def test_runtime_context_directory_has_no_detailed_private_import_report(self):
        self.assertFalse((ROOT / "context" / "motherduck_import_report.json").exists())
        semantics = load_contract(self, "semantics.yaml")
        self.assertNotIn("private_source_relations", semantics["source_of_truth"])
        self.assertNotIn("motherduck_import_report.json", (ROOT / "context" / "README.md").read_text(encoding="utf-8"))

    def test_motherduck_deployment_metadata_matches_verified_import(self):
        schema = load_contract(self, "schema.yaml")
        semantics = load_contract(self, "semantics.yaml")
        profile = json.loads((ROOT / "context" / "profile.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["contract_version"], "2.0.0")
        self.assertEqual(semantics["contract_version"], "2.0.0")
        deployment = schema["source_of_truth"]
        self.assertEqual(deployment["provider"], "motherduck")
        self.assertEqual(deployment["database"], profile["source_of_truth"]["database"])
        self.assertEqual(deployment["canonical_schema"], "main")
        self.assertEqual(deployment["snapshot_report"], "context/profile.json")
        for name, table in schema["tables"].items():
            self.assertEqual(table["relation"]["qualified_name"], f"main.{name}")
            self.assertEqual(table["relation"]["object_type"], "VIEW")
            self.assertTrue(table["relation"]["backing_relation"].startswith("source."))
        self.assertEqual(schema["tables"]["cards"]["columns"]["account_open_month"]["duckdb_type"], "DATE")
        policy = semantics["access_policy"]
        self.assertEqual(policy["database"], profile["source_of_truth"]["database"])
        self.assertEqual(policy["default_schema"], "main")
        self.assertEqual(policy["allowed_relations"], [f"main.{name}" for name in schema["tables"]])
        self.assertEqual(policy["source_relation_access"], "denied_for_generated_sql")
        self.assertEqual(semantics["source_of_truth"]["verification_status"], "verified_post_upload")

    def test_profile_fingerprints_match_current_files(self):
        profile = json.loads((ROOT / "context" / "import_profile.json").read_text(encoding="utf-8"))
        for source in profile["sources"].values():
            path = ROOT / source["path"]
            with self.subTest(source=source["path"]):
                self.assertEqual(path.stat().st_size, source["bytes"], "Profile is stale: source size changed")
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                self.assertEqual(digest, source["sha256"], "Profile is stale: source content changed")

    def test_contract_covers_actual_headers_and_mcc_object_shape(self):
        schema = load_contract(self, "import_schema.yaml")
        for table in schema["tables"].values():
            source = table["source"]
            path = ROOT / source["path"]
            if source["format"] == "csv":
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    self.assertEqual(next(csv.reader(stream)), list(table["columns"]))
            else:
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertIsInstance(value, dict)
                self.assertTrue(all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()))


if __name__ == "__main__":
    unittest.main()
