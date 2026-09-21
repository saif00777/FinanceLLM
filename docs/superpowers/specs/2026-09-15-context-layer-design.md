# Financial transactions context layer

Approved scope: machine-readable schema and semantic contracts plus a human guide,
for a future read-only DuckDB chat-to-SQL system. This delivery is the context
package; application orchestration and a database service are future work.

## Design

- `context/schema.yaml` owns source paths, field-level raw-to-canonical mappings,
  DuckDB projection expressions, grains, candidate keys, joins and sensitivity.
- `context/semantics.yaml` owns glossary, explicit metric formulas, query policy,
  ambiguity handling and representative DuckDB SELECT examples.
- `context/profile.json` records measured source facts and the coverage of checks.
- `context/README.md` explains consumption, relationships, assumptions and limits.
- `tests/test_context.py` exercises the declared conversions, joins, metrics and
  examples against small deterministic DuckDB fixtures. Source checks compare the
  real file headers with the contract without exposing sensitive example values.

Use four canonical tables: transactions, cards, users, mcc_codes. Store money as
DECIMAL; preserve identifiers and postal codes deliberately; date/time values have
no verified time zone. Customer and card attributes are undated snapshots.

Negative transaction amounts are negative-value entries. Refund/reversal is a
possible interpretation requiring an explicitly labeled proxy or clarification.
Blank errors do not prove settlement. There is no transaction fraud label.

All source fields remain documented, including sensitive fields. Fields such as
card numbers, CVV, addresses and precise coordinates are excluded from canonical
LLM-facing projections. Read-only rules are an integration contract: enforcement
requires a future SQL validator and restricted database execution environment.

## Acceptance

YAML parses; every source column is accounted for; foreign-key paths resolve;
monetary/date/boolean parsing and metric calculations pass fixture checks; example
queries bind and run against declared tables; profile facts have stated coverage.
Do not infer source guarantees from field names or samples.

This folder is not a Git repository. Files are versionable; no commit or worktree
can be created without first establishing a repository.
