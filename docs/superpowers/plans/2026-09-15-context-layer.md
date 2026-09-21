# Context Layer Implementation Plan

> **For agentic workers:** Execute this focused metadata delivery in the current
> session, with a separate read-only review once the package is ready.

**Goal:** Deliver the approved context contract for read-only DuckDB text-to-SQL.

**Architecture:** Raw source mappings and safe canonical projections in schema
YAML; definitions, metrics and examples in semantic YAML; observed facts in JSON.
Tests consume these declarations in an in-memory DuckDB database.

**Tech Stack:** YAML-compatible mappings, JSON, Markdown, Python unittest,
DuckDB and PyYAML for validation only.

**Spec:** `docs/superpowers/specs/2026-09-15-context-layer-design.md`

## Global Constraints

- Dataset access is read-only; no application or SQL execution service.
- Preserve the source data and document every source column.
- Separate verified data facts, conventional interpretations and unknowns.
- No card credentials or direct personal data in canonical LLM tables.
- No Git initialization, worktree or commits in this non-repository directory.

## Work

- [x] Profile all four sources with strict parsing; measure keys and join coverage.
- [x] Write fixture checks for money signs, nulls, month dates, zip codes, joined
      aggregations and example queries; verify failure while contract is absent.
- [x] Write schema and semantics declarations and measured profile.
- [x] Explain future materialization and enforcement requirements in README.
- [x] Run fixture and source-header validation, request read-only review, address
      actionable findings, and rerun affected checks before delivery.

Verification: `python -m unittest discover -s tests -v`, using DuckDB 1.5.5 and
PyYAML 6.0.3, passes 16 tests. Fixture expectations are independently calculated.
Source checks read headers and verify full-file SHA-256 fingerprints.

Independent review found integer-cast rounding and inconsistent whitespace-null
handling. A local regression also exposed malformed money acceptance/rounding.
All three were reproduced before fixes, corrected in declared expressions and
covered by regression checks. The revised projections were then evaluated on all
13,305,915 transactions and every dimension record; row/null counts still match
the saved profile and categorical/count distributions reconcile.

No persistent database, application, Git repository or commit was created.
