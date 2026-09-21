# MotherDuck dataset import

The importer creates the private database `financial_transactions` from the
fingerprinted files in `FinancialTransactionsDataset`. Existing local or remote
destinations are never overwritten by the importer.

The implementation is in `ingestion/motherduck.py`. The
`ingestion/motherduck_cli.py` file is only the command-line entry point.

## Tables and views

| Physical table | Source rows | Canonical view |
|---|---:|---|
| `source.transactions_data` | 13,305,915 | `main.transactions` |
| `source.cards_data` | 6,146 | `main.cards` |
| `source.users_data` | 2,000 | `main.users` |
| `source.mcc_codes` | 109 | `main.mcc_codes` |

Physical tables preserve all source columns and their names, with explicit
conversions. The JSON object's keys and values become `mcc VARCHAR` and
`description VARCHAR` in a physical table. Canonical views select the names and
fields defined in the operator-only `context/import_schema.yaml`; they read stored tables and do not
depend on the original CSV files.

## Types and conversions

- Money: `DECIMAL(18,2)`, removing dollar signs and valid grouping commas while
  preserving negative amounts. Malformed tokens or fractional cents fail import.
- Transaction date/time: `TIMESTAMP`, with no inferred timezone.
- Account opening and expiry: `DATE`. Source `MM/YYYY` values use day 01 as a
  storage convention; the actual day is unknown.
- IDs: `BIGINT`; whole-number attributes such as age and credit score: `INTEGER`.
- Yes/no flags: `BOOLEAN`; unrecognized nonempty values fail import.
- Card number, CVV and MCC: `VARCHAR`, preserving leading zeros.
- Postal codes: `VARCHAR`; US-shaped numeric tokens such as `1234.0` become
  `01234`, while other formats are retained.
- Latitude and longitude: `DOUBLE`. Other descriptive fields stay `VARCHAR`.
- Empty fields become SQL `NULL`; no records are dropped for conversion errors.

The validation report contains the complete column/type mapping, row counts,
content signatures, null counts, relationship checks and transaction aggregates.

## Commands

From the project root, with Python and `requirements-context.txt` installed:

```powershell
python -m unittest discover -s tests -v
python -m ingestion.motherduck_cli prepare
python -m ingestion.motherduck_cli upload
python -m ingestion.motherduck_cli verify
```

Set `MOTHERDUCK_TOKEN` in the environment or the ignored project `.env` file.
Never pass a token on the command line. Preparation uses no cloud connection;
upload and verify use the configured MotherDuck account. The optional
`--database` argument chooses a new remote name and `--local-db` chooses a local
staging file.

Preparation checks file SHA-256 fingerprints against `context/import_profile.json`,
converts every row, checks column types and source keys, validates joins and
compares counts with the profile. Upload requires that successful preparation
report and checks it against the current local database and approved source
profile before connecting. Upload compares local and remote content
signatures, schema, null counts and totals using a new connection after copying.
Standalone `verify` checks the remote schema and integrity; the upload operation
also compares the remote result with the local database.

Local staging and machine-generated reports are in ignored `.motherduck-staging/`.
If an upload fails, inspect the remote database before retrying: an interrupted
request can leave a destination behind, and the importer will refuse to replace
it. A completed preparation also remains intact for investigation.

## Querying

Select `financial_transactions` in MotherDuck, then use the canonical views:

```sql
SELECT m.description, COUNT(*) AS transaction_count, SUM(t.amount) AS net_amount
FROM main.transactions AS t
JOIN main.mcc_codes AS m ON t.mcc = m.mcc
GROUP BY m.description
ORDER BY transaction_count DESC
LIMIT 10;
```

The amount is a signed net total and includes rows carrying error text, matching
the context contract. It is not a verified settled-spending measure.

The private `source` tables include all original fields, including card numbers
and CVVs. Canonical views exclude the restricted fields identified in the context
contract. Views and schemas organize access but do not enforce a read-only LLM
boundary; the future application needs separately restricted credentials and SQL
execution controls. No public share is created by this import.
