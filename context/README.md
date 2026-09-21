# Financial transactions context layer

Version **2.0.0** is the runtime context contract for the MotherDuck database
`financial_transactions`. The database, not the local CSV/JSON files, is the
source of truth for chat-to-SQL queries.

## Runtime contract

| File | Purpose |
|---|---|
| `schema.yaml` | Canonical model-visible schema for the four deployed `main` views |
| `semantics.yaml` | Business meaning, metrics, query rules, examples and SQL allowlist |
| `profile.json` | Verified MotherDuck catalog, aggregate snapshot and refresh rules |

The model may query only these canonical views:

| Relation | Rows at verified snapshot |
|---|---:|
| `main.transactions` | 13,305,915 |
| `main.cards` | 6,146 |
| `main.users` | 2,000 |
| `main.mcc_codes` | 109 |

The related physical tables are private operator data in `source`. In
particular, they contain card numbers, CVVs, addresses and exact coordinates.
They are excluded from the runtime schema and must never be included in model
prompts or result sets.

## Running queries

Connect to the MotherDuck database `financial_transactions`. Generated SQL
must use the fully-qualified `main.*` relations, for example:

```sql
SELECT m.description, SUM(t.amount) AS net_amount
FROM main.transactions AS t
LEFT JOIN main.mcc_codes AS m ON t.mcc = m.mcc
GROUP BY m.description
ORDER BY net_amount DESC
LIMIT 10;
```

The current token is an owner token used for development. It can reach
`source.*`; therefore the YAML allowlist is not a security boundary. Before
hosting the app publicly, create a separate read-only serving credential with
access limited to canonical `main` relations.

## Historical import lineage

The original files are retained only for reproducible administration:

| File | Purpose |
|---|---|
| `import_schema.yaml` | Raw CSV/JSON columns and trusted conversion rules |
| `import_profile.json` | Original file fingerprint and profiling evidence |
| `../ingestion/motherduck.py` | Prepare, upload and verify administration module |\n| `../scripts/motherduck_import.py` | Thin command-line entry point |

The importer uses these two `import_*` files, never the runtime schema or
runtime profile. A local file fingerprint changing does not alter the runtime
source of truth; it only means a new import requires validation.

## Validation and refresh

Run the full local contract suite:

```text
python -m unittest discover -s tests -v
```

To inspect the deployed database after an import or before a context refresh:

```text
python scripts/motherduck_import.py verify
```

Refresh `profile.json` only from a MotherDuck verification: compare canonical
view types and null counts, physical-table counts and checksums, key and join
checks, and transaction aggregates. Update the `import_*` lineage files only
when the local source files are re-imported.

The dataset's timestamps have unknown timezone. Monetary values are dataset
dollar units without verified ISO currency. Customer and card attributes are an
undated snapshot, so they are not historical values at transaction time.
