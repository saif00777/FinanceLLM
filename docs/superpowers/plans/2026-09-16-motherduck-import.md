# MotherDuck typed import

## Approved goal

Upload FinancialTransactionsDataset to the user's MotherDuck account, turning
mcc_codes.json into a table and assigning verified types rather than retaining
all CSV values as text. Preserve source columns in private typed source tables.

## Design and boundaries

- Target database: `financial_transactions`; never replace an existing database.
- Four physical tables in `source`: `transactions_data`, `cards_data`,
  `users_data`, `mcc_codes`. CSV column names are retained.
- Four views in `main`: `transactions`, `cards`, `users`, `mcc_codes`. They expose
  the canonical names and approved fields already defined in context/schema.yaml.
- Reuse the schema's checked conversion expressions. Add explicit typed handling
  for the seven excluded source fields: preserve card number/CVV as text, expiry
  as a month-precision DATE, birth month as INTEGER, address as text and
  latitude/longitude as DOUBLE.
- Source and main schemas organize data; schemas alone do not enforce access.
  Credentials/raw personal columns are in the private database by the user's
  request. Future LLM credentials need separately restricted access.
- Build a local staging DuckDB database, verify it, upload only that database to
  MotherDuck, and verify remote table types/counts/joins/totals. Do not create a
  public share or send data to an LLM service.
- Read the token from the environment or ignored `.env`, never from CLI arguments
  or hardcoded source; redact exceptions before printing. Do not print records.
- The workspace is not a Git repository; work in place with scoped new files.

## Sequence

- [x] Write failing fixture tests for full source preservation, exact types,
  canonical views, MCC JSON shape, malformed input and token handling.
- [x] Implement a local preparation/validation module and a narrowly scoped
  MotherDuck upload command. Existing destinations fail safely.
- [x] Run tests, stage all source rows and verify profile/fingerprints and totals.
- [x] Perform independent read-only code review and address material findings.
- [x] Use the user's configured token, upload to the named private database and
  reconnect to verify persisted contents. Record a non-sensitive import report.

Token setup is the only initial dependency on user input. The task authorizes the
upload; no additional publishing confirmation is required for this private import.


## Verified outcome — 2026-09-16

All 29 context/import tests passed. Independent review findings were addressed
and re-reviewed. The private cloud copy completed and matched fresh local
validation after reconnect: 13,305,915 transactions, 6,146 cards, 2,000 users and
109 MCC codes. Cloud catalog inspection confirmed four physical source tables
and four canonical views. See `.motherduck-staging/financial_transactions.remote-validation.json` and
`docs/motherduck-import.md`. No source file was modified.
