# Text-to-SQL Agent Backend Design

## Goal

Provide a backend-only, agentic HTTP service that answers natural-language questions against the deployed `financial_transactions` MotherDuck database without exposing credentials, private source relations, or arbitrary SQL execution.

## Scope

The first release is a student demo backend. It has no browser UI, authentication, session persistence, vector database, charts, exports, or write operations. It serves a JSON API that a future frontend can call.

## Users and questions

The user is a student demonstrating analytical questions over financial transactions. The initial evaluation questions are the six reviewed examples in `context/semantics.yaml`, including monthly net amount, merchant-category positive amounts, card-type totals, customer net amounts, January error rate, and average income of transacting customers. Wrong answers are acceptable only as a demo failure when the agent explains an ambiguity or refuses an unsupported question; unsafe queries and made-up facts are never acceptable.

## Data and security classification

The data contains financial activity and pseudonymous customer identifiers. The private `source` schema additionally contains fields that must never be available to the model. The model receives a compact projection of `context/schema.yaml` and `context/semantics.yaml`, never raw rows, tokens, import files, private source metadata, or server configuration. The agent may receive bounded SQL results only through its query tool to write its final answer. Requests use the OpenAI Responses API with `store=False`.

The current MotherDuck token is an owner token. It is permitted for local development only. Before public deployment it must be replaced with a restricted, read-only serving credential that can access only the `main` views, as required by `context/semantics.yaml`.

## Architecture

`FastAPI` exposes `GET /health` and `POST /api/chat`. `POST /api/chat` accepts one question and returns an answer, generated SQL when a query ran, column names, bounded rows, and a request identifier. It never returns a token or an internal exception.

`TextToSqlAgent` uses the OpenAI Responses API with two application-owned function tools:

1. `get_data_contract` returns a compact runtime-only schema, relationship, metric, ambiguity, and unsupported-topic contract.
2. `run_read_only_sql` accepts one SQL statement. It first uses `SqlPolicy` to parse and validate the statement, then uses `MotherDuckQueryRunner` to execute it and returns at most 100 JSON-safe rows.

The agent loop accepts a maximum of four tool rounds. It must call `get_data_contract` before `run_read_only_sql`; it may use `run_read_only_sql` at most once. If a question is unsupported or ambiguous, it returns a plain-language clarification instead of querying.

`SqlPolicy` is the security boundary. It uses SQLGlot’s DuckDB parser and rejects syntax that does not parse to a single `SELECT` or `WITH … SELECT`. It permits fully qualified relations only in `main`: `transactions`, `cards`, `users`, and `mcc_codes`; rejects wildcard projection (except `COUNT(*)`), non-allowlisted functions, source/catalog/file/table-function access, unqualified tables, mutations, multiple statements, and output limits over 100. SQL validation is never delegated to an LLM.

## Configuration

`.env` remains excluded from Git. The backend loads these values via `python-dotenv`:

- `OPEN_AI_KEY` — required; passed explicitly to `OpenAI(api_key=...)`.
- `OPEN_AI_MODEL` — required; model supplied by the user.
- `MOTHERDUCK_TOKEN` — required; passed only to DuckDB’s MotherDuck connection.

The application accepts the conventional `OPENAI_API_KEY` only as a fallback for hosting platforms. `OPEN_AI_KEY` remains the documented project setting.

## Dependencies

The backend adds `fastapi`, `uvicorn`, `openai`, `python-dotenv`, and `sqlglot` alongside the existing `duckdb` and `PyYAML` dependencies. Dependencies are pinned in a new `requirements.txt`; `requirements-context.txt` remains a focused context-validation file.

## API contract

`POST /api/chat` request:

```json
{"question": "Which merchant categories have the largest total positive recorded amounts?"}
```

Successful query response:

```json
{
  "request_id": "uuid",
  "answer": "...",
  "sql": "SELECT ...",
  "columns": ["mcc", "category", "positive_amount_total"],
  "rows": [["5411", "Grocery Stores, Supermarkets", 100.0]],
  "row_count": 1
}
```

Clarification or unsupported-topic response has `sql: null`, empty `columns` and `rows`, and a plain-language `answer`. Invalid requests return HTTP 422. Model, validation, database, and tool-loop failures return HTTP 502 with a safe message and the request identifier.

## Acceptance criteria

- A valid canonical `SELECT` succeeds through the policy and returns JSON-safe, no-more-than-100 rows.
- `source.*`, unqualified relations, DDL/DML, file scans, multiple statements, wildcard projections, and excessive or missing `LIMIT` are rejected before the runner is invoked.
- The agent requires contract retrieval before a query, caps tool rounds, and includes final query results only in its tool continuation.
- The API validates its request and does not disclose secrets or raw exceptions.
- Existing context/import tests remain green and new tests run without a live OpenAI or MotherDuck call.
