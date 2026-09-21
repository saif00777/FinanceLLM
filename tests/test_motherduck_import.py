"""Real DuckDB ingestion tests; synthetic credentials only, no network calls."""
import csv
import datetime as dt
from decimal import Decimal
from importlib.machinery import EXTENSION_SUFFIXES
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = ROOT / '.context-tools'
if any((LOCAL_DEPS / f'_duckdb{s}').is_file() for s in EXTENSION_SUFFIXES):
    sys.path.append(str(LOCAL_DEPS))
import duckdb
import yaml


class ImportTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / 'ingestion' / 'motherduck.py'
        self.assertTrue(path.is_file(), 'MotherDuck ingestion module does not exist yet')
        spec = importlib.util.spec_from_file_location('ingestion.motherduck', path)
        self.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.app)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.schema = yaml.safe_load((ROOT / 'context' / 'import_schema.yaml').read_text())
        self.records = {
            'users': [{'id': '1', 'current_age': '40', 'retirement_age': '65', 'birth_year': '1979',
                       'birth_month': '01', 'gender': 'Female', 'address': 'Synthetic Test Address',
                       'latitude': '34.15', 'longitude': '-117.76', 'per_capita_income': '$20000',
                       'yearly_income': '$60000', 'total_debt': '$12000', 'credit_score': '720', 'num_credit_cards': '1'}],
            'cards': [{'id': '10', 'client_id': '1', 'card_brand': 'Visa', 'card_type': 'Debit',
                       'card_number': '0000000000000001', 'expires': '12/2022', 'cvv': '007',
                       'has_chip': 'YES', 'num_cards_issued': '1', 'credit_limit': '$1,234.50',
                       'acct_open_date': '09/2002', 'year_pin_last_changed': '2018', 'card_on_dark_web': 'No'}],
            'transactions': [
                {'id': '101', 'date': '2019-01-01 00:01:00', 'client_id': '1', 'card_id': '10',
                 'amount': '$100.25', 'use_chip': 'Chip Transaction', 'merchant_id': '-9',
                 'merchant_city': 'Test City', 'merchant_state': 'MA', 'zip': '1234.0', 'mcc': '0001', 'errors': ''},
                {'id': '102', 'date': '2019-01-02 23:59:00', 'client_id': '1', 'card_id': '10',
                 'amount': '$-20.10', 'use_chip': 'Online Transaction', 'merchant_id': '5',
                 'merchant_city': 'ONLINE', 'merchant_state': '', 'zip': '', 'mcc': '0001', 'errors': 'Bad PIN,Technical Glitch'},
            ],
        }
        self.write_fixture()
        self.destination = self.folder / 'staged.duckdb'

    def write_fixture(self):
        for name, rows in self.records.items():
            path = self.folder / f'{name}_data.csv'
            with path.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(self.schema['tables'][name]['columns']))
                writer.writeheader()
                writer.writerows(rows)
        (self.folder / 'mcc_codes.json').write_text(json.dumps({'0001': 'Test category'}))

    def prepare(self):
        return self.app.prepare_database(self.folder, self.destination, ROOT / 'context' / 'import_schema.yaml')

    def test_ingestion_logic_lives_in_module_and_cli_delegates(self):
        module_path = ROOT / 'ingestion' / 'motherduck.py'
        self.assertTrue(module_path.is_file(), 'MotherDuck ingestion module does not exist yet')
        self.assertTrue(callable(self.app.prepare_database))
        self.assertTrue(callable(self.app.upload_database))
        wrapper = (ROOT / 'ingestion' / 'motherduck_cli.py').read_text(encoding='utf-8')
        self.assertIn('from ingestion.motherduck import main', wrapper)
        self.assertNotIn('def prepare_database(', wrapper)

    def test_all_source_columns_are_preserved_and_typed(self):
        self.prepare()
        with duckdb.connect(str(self.destination), read_only=True) as db:
            for name in ('transactions', 'cards', 'users'):
                actual = db.execute(f'DESCRIBE source.{name}_data').fetchall()
                self.assertEqual([r[0] for r in actual], list(self.schema['tables'][name]['columns']))
            card = db.execute('SELECT card_number, cvv, expires, acct_open_date, has_chip, credit_limit FROM source.cards_data').fetchone()
            self.assertEqual(card, ('0000000000000001', '007', dt.date(2022, 12, 1), dt.date(2002, 9, 1), True, Decimal('1234.50')))
            user = db.execute('SELECT birth_month, latitude, longitude FROM source.users_data').fetchone()
            self.assertEqual(user, (1, 34.15, -117.76))
            self.assertEqual(db.execute('SELECT SUM(amount) FROM source.transactions_data').fetchone()[0], Decimal('80.15'))
            self.assertEqual(db.execute('SELECT zip, errors FROM source.transactions_data ORDER BY id').fetchall(), [('01234', None), (None, 'Bad PIN,Technical Glitch')])

    def test_mcc_json_is_a_physical_two_column_table(self):
        self.prepare()
        with duckdb.connect(str(self.destination), read_only=True) as db:
            self.assertEqual(db.execute("SELECT table_type FROM information_schema.tables WHERE table_schema='source' AND table_name='mcc_codes'").fetchone()[0], 'BASE TABLE')
            self.assertEqual(db.execute('SELECT mcc, description FROM source.mcc_codes').fetchall(), [('0001', 'Test category')])

    def test_canonical_views_join_and_exclude_restricted_columns(self):
        self.prepare()
        with duckdb.connect(str(self.destination), read_only=True) as db:
            result = db.execute('SELECT m.description, SUM(t.amount) FROM transactions t JOIN cards c ON t.card_id=c.card_id AND t.client_id=c.client_id JOIN users u ON t.client_id=u.client_id JOIN mcc_codes m ON t.mcc=m.mcc GROUP BY 1').fetchall()
            self.assertEqual(result, [('Test category', Decimal('80.15'))])
            self.assertNotIn('cvv', [r[0] for r in db.execute('DESCRIBE cards').fetchall()])

    def test_existing_destination_is_not_overwritten(self):
        self.destination.write_bytes(b'keep-me')
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(self.destination.read_bytes(), b'keep-me')

    def test_malformed_money_is_rejected_before_upload(self):
        self.records['transactions'][0]['amount'] = '$1.005'
        self.write_fixture()
        with self.assertRaises((ValueError, duckdb.Error)):
            self.prepare()

    def test_orphan_references_are_rejected(self):
        self.records['transactions'][0]['client_id'] = '999'
        self.write_fixture()
        with self.assertRaisesRegex(ValueError, 'reference|owner'):
            self.prepare()

    def test_duplicate_mcc_keys_are_not_silently_discarded(self):
        (self.folder / 'mcc_codes.json').write_text('{"0001":"first","0001":"second"}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.prepare()

    def test_header_drift_fails_before_materialization(self):
        path = self.folder / 'users_data.csv'
        path.write_text(path.read_text().replace('current_age', 'renamed_age', 1))
        with self.assertRaisesRegex(ValueError, 'header'):
            self.prepare()

    def test_duplicate_source_ids_are_rejected(self):
        self.records['transactions'][1]['id'] = '101'
        self.write_fixture()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.prepare()

    def test_upload_requires_successful_matching_preparation_manifest(self):
        actual = self.prepare()
        hashes = self.app.source_fingerprints(self.folder, self.schema)
        profile = {'sources': {
            name: {'sha256': hashes[name], 'row_count': actual['tables'][self.app.source_name(table)]['row_count']}
            for name, table in self.schema['tables'].items()
        }}
        manifest = self.destination.with_suffix('.validation.json')
        with self.assertRaisesRegex(ValueError, 'preparation'):
            self.app.validate_preparation_manifest(self.destination, actual, profile, self.schema)
        manifest.write_text(json.dumps({**actual, 'source_sha256': hashes}))
        self.app.validate_preparation_manifest(self.destination, actual, profile, self.schema)
        changed = json.loads(json.dumps(actual))
        changed['tables']['transactions_data']['row_hash_xor'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'manifest'):
            self.app.validate_preparation_manifest(self.destination, changed, profile, self.schema)
        manifest.write_text(json.dumps({**actual, 'source_sha256': {}}))
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            self.app.validate_preparation_manifest(self.destination, actual, profile, self.schema)
        manifest.write_text(json.dumps({**actual, 'source_sha256': hashes}))
        profile['sources']['transactions']['row_count'] = 999
        with self.assertRaisesRegex(ValueError, 'count'):
            self.app.validate_preparation_manifest(self.destination, actual, profile, self.schema)

    def test_database_errors_do_not_print_source_values(self):
        private_value = 'synthetic-private-location'
        with duckdb.connect() as db:
            try:
                db.execute('SELECT CAST(? AS DOUBLE)', [private_value])
            except duckdb.Error as exc:
                self.assertIn(private_value, str(exc))
                message = self.app.safe_error_message(exc, '')
                self.assertNotIn(private_value, message)
                self.assertIn(type(exc).__name__, message)
            else:
                self.fail('Invalid numeric input must fail')

    def test_token_loading_and_redaction(self):
        secret = 'synthetic-secret-token'
        path = self.folder / '.env'
        path.write_text('# example\nMOTHERDUCK_TOKEN="synthetic-secret-token"\n')
        self.assertEqual(self.app.load_token(path, {}), secret)
        self.assertEqual(self.app.load_token(path, {'motherduck_token': 'env-secret'}), 'env-secret')
        self.assertNotIn(secret, self.app.redact(f'failed with {secret}', secret))
        path.write_text('MOTHERDUCK_TOKEN=\n')
        with self.assertRaisesRegex(ValueError, 'token'):
            self.app.load_token(path, {})

    def test_remote_target_name_is_validated_without_network(self):
        for name in ('financial_transactions', 'student_data_1'):
            self.assertEqual(self.app.checked_database_name(name), name)
        with self.assertRaises(ValueError):
            self.app.checked_database_name('bad; DROP DATABASE x')


if __name__ == '__main__':
    unittest.main()
