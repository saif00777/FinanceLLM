# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A backend-only FastAPI service that answers natural-language questions about a MotherDuck financial-transactions database via a bounded LangGraph multi-agent workflow, plus a separate consented/redacted consumer-complaints RAG branch (Qdrant). The LLM never receives database credentials and never writes SQL that isn't AST-validated first.

## Commands

Activate the venv first (PowerShell):

```powershell
.\.venv\Scripts\Activate.ps1
```

Run the API locally:

```powershell
uvicorn app.api.main:app --reload
```

Run the full test suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Run a single test module / case:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_workflow -v
.\.venv\Scripts\python.exe -m unittest tests.test_workflow.WorkflowTests.test_some_case -v
```

Run the deterministic offline eval gate (17 versioned fixtures in `evals/`, no network calls):

```powershell
.\.venv\Scripts\python.exe scripts\run_evals.py
```

MotherDuck dataset administration (`prepare`, `upload`, `verify`):

```powershell
.\.venv\Scripts\python.exe ingestion\motherduck_cli.py verify
```

Consumer-complaints RAG ingestion (dry run by default; `--upload` embeds and upserts to Qdrant):

```powershell
.\.venv\Scripts\python.exe -m ingestion.complaints.cli --limit 10
```

Uploads checkpoint to `.complaints-rag-checkpoint.json` after each batch; pass `--restart` only to deliberately reprocess the whole corpus.

Tests use fake specialists/database clients and make no OpenAI, MotherDuck, Supabase, Qdrant, or Langfuse calls — never gate on live credentials being present.

## Configuration

Copy `.env.example` to `.env`. Required: `OPEN_AI_KEY` (or `OPENAI_API_KEY` fallback), `OPEN_AI_MODEL`, `MOTHERDUCK_TOKEN`. Optional pairs, each must be configured together or not at all: `SUPABASE_URL`/`SUPABASE_KEY` (durable conversation store; falls back to a 30-minute in-memory store), `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` (observability), `QDRANT_API_URL`/`QDRANT_API_KEY` (complaint RAG retrieval — also requires `OPEN_AI_EMBEDDING_MODEL`). `AppConfig.from_environment()` in [app/helpers/config.py](app/helpers/config.py) enforces these pairing rules and raises `ConfigurationError` early.

The current MotherDuck token is an owner token for local development only — it can reach `source.*` private tables, so the schema allowlist is an application convention, not a security boundary, until a restricted read-only serving credential is used in production.

## Architecture

### Request flow (`app/agents/text_to_sql/workflow.py`)

`MultiAgentWorkflow` compiles a bounded `langgraph.StateGraph` (`AgentState`) with a fixed node sequence — nothing here is open-ended agent looping:

1. **hard_guard** — deterministic regex checks ([app/agents/text_to_sql/domain_guard.py](app/agents/text_to_sql/domain_guard.py)) block credential/secret requests, `source.*` table references, file/URL fetches, instruction-bypass phrasing, and raw PII asks, before any model call.
2. **domain_guard** — an LLM specialist classifies the question as `in_scope`, `clarify`, or `abstain` against `context/semantics.yaml`.
3. **document_router** — keyword-routes to either the complaint-RAG branch or the SQL branch.
4. **complaint_retrieval** (RAG branch only) — embeds the question, retrieves via `ComplaintRetrievalAdapter` ([app/agents/complaints/retrieval.py](app/agents/complaints/retrieval.py)), which filters to `visibility: public` payloads, allowlists a fixed safe-field set, and redacts text before it ever reaches a response. Never touches SQL/MotherDuck.
5. **planner** → **schema_link** + **metric_resolver** (parallel) — `RuntimeContract.link()` ([app/agents/text_to_sql/contracts.py](app/agents/text_to_sql/contracts.py)) scores `context/schema.yaml` tables/synonyms and `context/semantics.yaml` glossary/metrics against the question to project only relevant relations into the prompt (keeps context compact and canonical).
6. **sql_generator** → **sql_policy** — `SqlPolicy.validate()` ([app/helpers/sql_policy.py](app/helpers/sql_policy.py)) parses generated SQL with `sqlglot` (dialect `duckdb`) and enforces: exactly one statement, `SELECT` only, every table fully qualified as `main.{transactions,cards,users,mcc_codes}`, every column in that table's allowlisted set from `schema.yaml`, no wildcard projections (except inside `COUNT`), only an explicit allowed-function set, and a `LIMIT` between 1–100 (waived only for scalar aggregates with no `GROUP BY`). A policy failure routes back to `sql_generator` for at most **2 repairs** before falling through to `suggestions`.
7. **executor** — runs at most **1** approved query per request (`QueryRunner`); a second attempt is rejected as over budget.
8. **data_analysis** + **analyst** (parallel) → **reviewer** — the reviewer re-checks the answer is grounded in the actual result rows before approving; otherwise the route becomes `clarify`.
9. **suggestions** — always runs last (every path converges here), producing contextual follow-up questions.

Routing state (`route`, `reason_code`, `repairs`, `executions`, `specialist_path`) flows through `AgentState`; `specialist_path` accumulates node names via `Annotated[list[str], add]` for audit/eval purposes. Every node is wrapped in `_traced()` for telemetry spans (Langfuse, or a no-op).

### Context layer (`context/`)

`schema.yaml` and `semantics.yaml` are the **runtime contract** — the only schema/business-meaning information ever projected into prompts — versioned (`semantic_version`) and validated by `tests/test_context.py`. `profile.json` holds a verified MotherDuck catalog snapshot. The `import_*.yaml`/`.json` files are separate historical lineage for the CSV/JSON-to-MotherDuck import (`ingestion/motherduck.py`) and are never read by the runtime agent path — don't conflate the two. See [context/README.md](context/README.md) for the full contract description and refresh procedure.

### Conversation state (`app/helpers/conversation.py`)

`ConversationStore` persists `ConversationFacts` (resolved metric, resolved filters, selected relations, last SQL hash, result digest, semantic version) across turns, backed by `InMemoryConversationStore` (default) or `SupabaseConversationStore` (when `SUPABASE_*` is set — apply [supabase/migrations/0001_conversations.sql](supabase/migrations/0001_conversations.sql) first).

### Consumer-complaints RAG ingestion (`ingestion/complaints/`)

Self-contained and independent of the MotherDuck path: `documents.py` builds consented+redacted `ComplaintDocument`s from `consumerComplaints/consumer_complaints.csv`, `pipeline.py` embeds and batch-upserts them via `ComplaintRagPipeline`/`OpenAIEmbedder`, `qdrant_store.py` wraps the Qdrant client, `cli.py` is the resumable, checkpointed command-line driver. The retrieval-time safety filtering (public-only, redacted, safe-field allowlist) lives separately in `app/agents/complaints/retrieval.py` — treat ingestion-time and retrieval-time filtering as two independent layers, both required.

### Module layout convention

`tests/test_module_layout.py` pins that `app.api.main` and `ingestion.complaints.cli` each resolve `ROOT` as the repository root two/three parents up from their file — keep entry points at their current nesting depth or update that test deliberately.

### Evals vs. tests

`tests/` is unit-level (mocked specialists/DB clients, fast, run on every change). `evals/*.json` + `scripts/run_evals.py` is a small (17-case), deterministic, network-free release gate checking end-to-end route/budget/grounding/citation behavior against fixed fixtures — described in [evals/README.md](evals/README.md). Both are non-negotiable before claiming a change to the workflow, guards, or policy is correct; neither is a substitute for the other.

## Progress log

[PROGRESS.md](PROGRESS.md) is the cross-session memory for this repo (there's no git history to fall back on — see below). Read its "Current state" section at the start of a session, and update it — in place for state, appended for the session log — before finishing significant work.

A `Stop` hook ([.claude/settings.json](.claude/settings.json)) enforces this: if any file changed more recently than `PROGRESS.md`, it blocks once with a reminder before letting the turn end. It fires at most once per turn (guarded by `stop_hook_active`) — if the change genuinely didn't warrant a log entry, say so and stop again.

## Workflow

This repo follows the Superpowers skill pipeline (see [AGENTS.md](AGENTS.md)): `$brainstorming` → `$writing-plans` → `$using-git-worktrees` → `$subagent-driven-development` → `$test-driven-development` → `$requesting-code-review` → `$verification-before-completion` → `$finishing-a-development-branch`. Iron laws: no production code without a failing test first; no fixes without root-cause investigation; no completion claims without freshly rerunning verification. Use the smallest workflow that fits — the full pipeline is for architectural work, not one-file maintenance changes.

Design decisions and specs are recorded under `docs/architecture/` and `docs/superpowers/{plans,specs}/`, dated `YYYY-MM-DD-*.md` — check there before re-deriving a rationale that may already be written down.

Note: this directory is not currently a git repository.
