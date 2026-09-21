"""MotherDuck ingestion, validation and administration operations.

Prepare, upload and verify the financial dataset with explicit DuckDB types.

This trusted administration utility preserves sensitive source columns in the
private source schema. Its main views expose only context-approved fields.
"""
import argparse
import csv
import hashlib
from importlib.machinery import EXTENSION_SUFFIXES
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = ROOT / '.context-tools'
if any((LOCAL_DEPS / f'_duckdb{s}').is_file() for s in EXTENSION_SUFFIXES):
    sys.path.append(str(LOCAL_DEPS))
import duckdb
import yaml

IMPORT_SCHEMA_PATH = ROOT / 'context' / 'import_schema.yaml'
IMPORT_PROFILE_PATH = ROOT / 'context' / 'import_profile.json'
STAGING = ROOT / '.motherduck-staging'
DEFAULT_LOCAL = STAGING / 'financial_transactions_local.duckdb'

# Excluded fields still belong in the user's complete, private source import.
# Every exposed field reuses the already-tested context conversion expression.
EXTRA_FIELDS = {
    ('cards', 'card_number'): ('VARCHAR', "NULLIF(trim(src.card_number), '')"),
    ('cards', 'cvv'): ('VARCHAR', "NULLIF(trim(src.cvv), '')"),
    ('cards', 'expires'): ('DATE', "CAST(strptime(NULLIF(trim(src.expires), ''), '%m/%Y') AS DATE)"),
    ('users', 'birth_month'): ('INTEGER', "CASE WHEN NULLIF(trim(src.birth_month), '') IS NULL THEN NULL WHEN regexp_full_match(trim(src.birth_month), '[0-9]+') THEN CAST(src.birth_month AS INTEGER) ELSE error('Invalid birth_month integer') END"),
    ('users', 'address'): ('VARCHAR', "NULLIF(trim(src.address), '')"),
    ('users', 'latitude'): ('DOUBLE', "CAST(NULLIF(trim(src.latitude), '') AS DOUBLE)"),
    ('users', 'longitude'): ('DOUBLE', "CAST(NULLIF(trim(src.longitude), '') AS DOUBLE)"),
}


def identifier(name):
    return '"' + name.replace('"', '""') + '"'


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def checked_database_name(name):
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', name):
        raise ValueError('Database name must contain lowercase letters, digits and underscores, starting with a letter')
    return name


def load_token(env_path, environment=None):
    environment = os.environ if environment is None else environment
    for name in ('motherduck_token', 'MOTHERDUCK_TOKEN'):
        if environment.get(name, '').strip():
            return environment[name].strip()
    path = Path(env_path)
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            key, sep, value = line.strip().partition('=')
            if sep and key.strip() in ('motherduck_token', 'MOTHERDUCK_TOKEN'):
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                if value:
                    return value
    raise ValueError('MotherDuck token missing: set MOTHERDUCK_TOKEN in .env or the environment')


def redact(message, token):
    message = str(message)
    if token:
        message = message.replace(token, '[redacted]')
    return re.sub(r'eyJ[A-Za-z0-9_.-]+', '[redacted]', message)


def safe_error_message(exc, token):
    if isinstance(exc, duckdb.Error):
        return (f'{type(exc).__name__}: Database operation failed. Check source formatting, '
                'declared types and connection settings. Raw database diagnostics are '
                'suppressed because they may include source values.')
    return f'{type(exc).__name__}: {redact(exc, token)}'


def load_schema(path=IMPORT_SCHEMA_PATH):
    return yaml.safe_load(Path(path).read_text(encoding='utf-8'))


def source_name(table):
    return Path(table['source']['path']).stem


def field_conversion(table_name, raw_name, field):
    if field['expose_to_llm']:
        return field['duckdb_type'], field['expression_sql']
    return EXTRA_FIELDS[(table_name, raw_name)]


def read_mcc(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate MCC key in source JSON')
            result[key] = value
        return result
    mapping = json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=unique_pairs)
    if not isinstance(mapping, dict) or not all(
            isinstance(k, str) and re.fullmatch(r'[0-9]{4}', k)
            and isinstance(v, str) and v.strip() for k, v in mapping.items()):
        raise ValueError('MCC JSON must map four-digit string keys to nonempty string descriptions')
    return list(mapping.items())


def relation(schema_name, table_name, catalog=None):
    parts = [schema_name, table_name] if catalog is None else [catalog, schema_name, table_name]
    return '.'.join(identifier(part) for part in parts)


def create_canonical_views(db, schema, catalog=None):
    for name, table in schema['tables'].items():
        projections = [f'{identifier(raw)} AS {identifier(field["canonical_name"])}'
                       for raw, field in table['columns'].items() if field['expose_to_llm']]
        db.execute(f'CREATE VIEW {relation("main", name, catalog)} AS SELECT {", ".join(projections)} '
                   f'FROM {relation("source", source_name(table), catalog)}')


def validate_database(db, schema, catalog=None):
    """Validate types/keys/joins and return aggregate-only content signatures."""
    report = {'tables': {}, 'views': {}}
    for name, table in schema['tables'].items():
        source = relation('source', source_name(table), catalog)
        actual_types = [[row[0], row[1]] for row in db.execute(f'DESCRIBE {source}').fetchall()]
        expected_types = [[raw, field_conversion(name, raw, field)[0]] for raw, field in table['columns'].items()]
        if actual_types != expected_types:
            raise ValueError(f'Type mismatch in source.{source_name(table)}')
        key = 'mcc' if name == 'mcc_codes' else 'id'
        cols = ', '.join(identifier(raw) for raw in table['columns'])
        count, distinct_keys, null_keys, checksum = db.execute(
            f'SELECT COUNT(*), COUNT(DISTINCT {identifier(key)}), '
            f'COUNT(*) FILTER (WHERE {identifier(key)} IS NULL), BIT_XOR(hash({cols})) FROM {source}'
        ).fetchone()
        if count != distinct_keys or null_keys:
            raise ValueError(f'Duplicate or null primary keys in source.{source_name(table)}')
        report['tables'][source_name(table)] = {'row_count': count, 'columns': actual_types, 'row_hash_xor': str(checksum)}
        view = relation('main', name, catalog)
        view_types = [[r[0], r[1]] for r in db.execute(f'DESCRIBE {view}').fetchall()]
        expected_view_types = [[f['canonical_name'], f['duckdb_type']] for f in table['columns'].values() if f['expose_to_llm']]
        if view_types != expected_view_types:
            raise ValueError(f'Canonical view type mismatch: {name}')
        null_exprs = ', '.join(f'COUNT(*) FILTER (WHERE {identifier(f["canonical_name"])} IS NULL)'
                              for f in table['columns'].values() if f['expose_to_llm'])
        null_values = db.execute(f'SELECT {null_exprs} FROM {view}').fetchone()
        report['views'][name] = {'columns': view_types, 'null_counts': dict(zip([x[0] for x in view_types], null_values))}

    tx = relation('main', 'transactions', catalog)
    cards = relation('main', 'cards', catalog)
    users = relation('main', 'users', catalog)
    mcc = relation('main', 'mcc_codes', catalog)
    missing_users, missing_cards, mismatched_owners, missing_mcc = db.execute(
        f'SELECT COUNT(*) FILTER (WHERE u.client_id IS NULL), '
        f'COUNT(*) FILTER (WHERE c.card_id IS NULL), '
        f'COUNT(*) FILTER (WHERE c.card_id IS NOT NULL AND t.client_id IS DISTINCT FROM c.client_id), '
        f'COUNT(*) FILTER (WHERE m.mcc IS NULL) FROM {tx} t '
        f'LEFT JOIN {users} u ON t.client_id=u.client_id '
        f'LEFT JOIN {cards} c ON t.card_id=c.card_id '
        f'LEFT JOIN {mcc} m ON t.mcc=m.mcc').fetchone()
    orphan_cards = db.execute(f'SELECT COUNT(*) FROM {cards} c LEFT JOIN {users} u ON c.client_id=u.client_id WHERE u.client_id IS NULL').fetchone()[0]
    report['relationships'] = {'transactions_without_users': missing_users, 'transactions_without_cards': missing_cards,
                              'transaction_card_owner_mismatches': mismatched_owners, 'transactions_without_mcc_descriptions': missing_mcc,
                              'cards_without_users': orphan_cards}
    if any(report['relationships'].values()):
        raise ValueError('Invalid source reference or card owner mismatch')
    values = db.execute(f'SELECT MIN(transaction_at), MAX(transaction_at), SUM(amount), '
                        f'SUM(amount) FILTER(WHERE amount>0), SUM(-amount) FILTER(WHERE amount<0), '
                        f'COUNT(*) FILTER(WHERE amount<0), COUNT(*) FILTER(WHERE amount=0), '
                        f'COUNT(*) FILTER(WHERE errors IS NOT NULL) FROM {tx}').fetchone()
    report['transactions'] = dict(zip(['first_timestamp', 'last_timestamp', 'net_amount', 'positive_amount_total',
                                      'negative_amount_magnitude', 'negative_count', 'zero_count', 'error_count'],
                                     [str(v) if v is not None else None for v in values]))
    return report


def prepare_database(dataset_dir, destination, schema_path=IMPORT_SCHEMA_PATH, progress=None):
    dataset_dir, destination = Path(dataset_dir), Path(destination)
    if destination.exists():
        raise FileExistsError(f'Local destination already exists: {destination.name}')
    schema = load_schema(schema_path)
    mcc_rows = None
    # Reject structural drift before creating a database.
    for table in schema['tables'].values():
        path = dataset_dir / Path(table['source']['path']).name
        if table['source']['format'] == 'csv':
            with path.open(encoding='utf-8-sig', newline='') as stream:
                if next(csv.reader(stream)) != list(table['columns']):
                    raise ValueError(f'Unexpected CSV header: {path.name}')
        else:
            mcc_rows = read_mcc(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(destination)) as db:
        db.execute("SET threads=4")
        db.execute("SET memory_limit='1GB'")
        db.execute("SET enable_progress_bar=false")
        db.execute(f'SET temp_directory={literal(destination.parent / "spill")}')
        db.execute('BEGIN TRANSACTION')
        try:
            db.execute('CREATE SCHEMA source')
            for name, table in schema['tables'].items():
                target = relation('source', source_name(table))
                if table['source']['format'] == 'csv':
                    projections = [f'{field_conversion(name, raw, f)[1]} AS {identifier(raw)}'
                                   for raw, f in table['columns'].items()]
                    source = str(dataset_dir / Path(table['source']['path']).name)
                    db.execute(f'CREATE TABLE {target} AS SELECT {", ".join(projections)} '
                               "FROM read_csv(?, header=true, all_varchar=true, delim=',', quote='\"', "
                               "escape='\"', nullstr='', strict_mode=true, ignore_errors=false) src", [source])
                else:
                    db.execute(f'CREATE TABLE {target} (mcc VARCHAR, description VARCHAR)')
                    if mcc_rows:
                        db.executemany(f'INSERT INTO {target} VALUES (?, ?)', mcc_rows)
                if progress:
                    progress(f'Materialized source.{source_name(table)} with explicit types', flush=True)
            create_canonical_views(db, schema)
            report = validate_database(db, schema)
            db.execute('COMMIT')
            db.execute('CHECKPOINT')
        except Exception:
            db.execute('ROLLBACK')
            raise
    return report


def source_fingerprints(dataset_dir, schema):
    result = {}
    for name, table in schema['tables'].items():
        path = Path(dataset_dir) / Path(table['source']['path']).name
        with path.open('rb') as stream:
            result[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def validate_preparation_manifest(local_path, actual, profile, schema):
    """Require successful preparation evidence matching this exact staged content."""
    path = Path(local_path).with_suffix('.validation.json')
    if not path.is_file():
        raise ValueError('Successful preparation manifest missing; run prepare before upload')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    expected_hashes = {name: source['sha256'] for name, source in profile['sources'].items()}
    if manifest.get('source_sha256') != expected_hashes:
        raise ValueError('Preparation source fingerprints differ from the approved profile')
    if {key: manifest.get(key) for key in actual} != actual:
        raise ValueError('Local database differs from its successful preparation manifest')
    for name, source in profile['sources'].items():
        table_name = source_name(schema['tables'][name])
        if actual['tables'][table_name]['row_count'] != source['row_count']:
            raise ValueError(f'Prepared row count differs from source profile: {name}')


def connect_motherduck(token):
    os.environ['motherduck_token'] = token
    extensions = STAGING / 'extensions'
    extensions.mkdir(parents=True, exist_ok=True)
    return duckdb.connect('md:', config={'extension_directory': str(extensions)})


def upload_database(local_path, database, token, schema_path=IMPORT_SCHEMA_PATH):
    database = checked_database_name(database)
    local_path = Path(local_path).resolve()
    if not local_path.is_file():
        raise FileNotFoundError('Prepare the local database before uploading')
    schema = load_schema(schema_path)
    with duckdb.connect(str(local_path), read_only=True) as local:
        expected = validate_database(local, schema)
    profile = json.loads(IMPORT_PROFILE_PATH.read_text(encoding='utf-8'))
    validate_preparation_manifest(local_path, expected, profile, schema)
    with connect_motherduck(token) as cloud:
        existing = {row[0] for row in cloud.execute('SHOW DATABASES').fetchall()}
        if database in existing:
            raise FileExistsError(f'MotherDuck database {database} already exists; refusing to overwrite it')
        cloud.execute(f'ATTACH {literal(local_path)} AS upload_source (READ_ONLY)')
        # Native database upload preserves physical table types and stored data.
        cloud.execute(f'CREATE DATABASE {identifier(database)} FROM upload_source')
    # A new connection proves that verification reads persisted cloud state.
    with connect_motherduck(token) as cloud:
        actual = validate_database(cloud, schema, database)
    if actual != expected:
        raise ValueError('Remote data differs from local validation; preserve destination for investigation')
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'upload', 'verify'])
    parser.add_argument('--local-db', type=Path, default=DEFAULT_LOCAL)
    parser.add_argument('--database', default='financial_transactions')
    args = parser.parse_args()
    token = ''
    try:
        schema = load_schema()
        profile = json.loads(IMPORT_PROFILE_PATH.read_text())
        if args.action == 'prepare':
            expected_hashes = {k: v['sha256'] for k, v in profile['sources'].items()}
            before = source_fingerprints(ROOT / 'FinancialTransactionsDataset', schema)
            if before != expected_hashes:
                raise ValueError('Source files differ from the profiled snapshot; refresh the context before import')
            report = prepare_database(ROOT / 'FinancialTransactionsDataset', args.local_db, progress=print)
            if source_fingerprints(ROOT / 'FinancialTransactionsDataset', schema) != before:
                raise ValueError('Source files changed during preparation; do not upload this staging database')
            for name, source in profile['sources'].items():
                table_name = source_name(schema['tables'][name])
                if report['tables'][table_name]['row_count'] != source['row_count']:
                    raise ValueError(f'Row count differs from source profile: {name}')
            report['source_sha256'] = before
            output = args.local_db.with_suffix('.validation.json')
        else:
            token = load_token(ROOT / '.env')
            checked_database_name(args.database)
            if args.action == 'upload':
                print(f'Uploading validated database to MotherDuck: {args.database}', flush=True)
                report = upload_database(args.local_db, args.database, token)
            else:
                with connect_motherduck(token) as cloud:
                    report = validate_database(cloud, schema, args.database)
            report['database'] = args.database
            report['duckdb_version'] = duckdb.__version__
            output = STAGING / f'{args.database}.remote-validation.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8')
        print(json.dumps({'status': 'verified', 'action': args.action,
                          'tables': {k: v['row_count'] for k, v in report['tables'].items()},
                          'report': str(output)}, indent=2), flush=True)
    except Exception as exc:
        print(safe_error_message(exc, token), file=sys.stderr, flush=True)
        return 1
    return 0
