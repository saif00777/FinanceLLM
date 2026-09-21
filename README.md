# Financial Multi-Agent Text-to-SQL Backend

A backend-only student demo for safe, conversational analysis of the MotherDuck `financial_transactions` database.

## Agent graph

FastAPI sends each request through a bounded LangGraph workflow:

1. Deterministic hard guards block secret, private-source, file, PII, and instruction-bypass requests.
2. A domain guard routes supported questions, clarification requests, and abstentions.
3. The schema-link and metric roles select compact context from `context/schema.yaml` and `context/semantics.yaml`.
4. SQL generation may repair a policy failure twice. SQLGlot then enforces the canonical `main` views, one read-only statement, and result limits.
5. One approved query can execute against MotherDuck. The data-analysis and answer/chart roles run in parallel, then a reviewer verifies grounding before suggested questions are generated.
6. A separate complaint router runs only after domain guards. It embeds the question, retrieves redacted public narratives from Qdrant, returns source-hash citations, and never executes SQL.

Database access, SQL policy, execution limits, and response serialization stay in application code. The LLM never receives a MotherDuck token.

## Configuration

Create `.env` from `.env.example`. Required server-side values are:

- `OPEN_AI_KEY` and `OPEN_AI_MODEL`
- `MOTHERDUCK_TOKEN`

`SUPABASE_URL` and `SUPABASE_KEY` are optional as a pair. When configured, sessions use Supabase; otherwise the process uses a 30-minute in-memory store. Apply [0001_conversations.sql](supabase/migrations/0001_conversations.sql) before enabling Supabase.

`LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are reserved for optional redacted observability. The consented consumer-complaints RAG ingestion branch also requires `QDRANT_API_URL`, `QDRANT_API_KEY`, and `OPEN_AI_EMBEDDING_MODEL`.

## Run locally

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.api.main:app --reload
```

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/chat `
  -ContentType 'application/json' `
  -Body '{"question":"Which merchant categories have the largest total positive recorded amounts?"}'
```

The response includes `conversation_id`, `answer`, `sql`, `columns`, `rows`, `chart`, `analysis`, `citations`, `suggested_questions`, and `route`. Send the returned `conversation_id` on the next request to continue the session.

## Standalone ingestion modules

`ingestion/motherduck.py` contains the financial dataset preparation and upload workflow, with `ingestion/motherduck_cli.py` as its command-line entry point. Complaint RAG ingestion is self-contained in `ingestion/complaints/`; run a local safety check with `python -m ingestion.complaints.cli --limit 10`, or append `--upload` to embed and upsert consented, redacted documents to Qdrant. Uploads checkpoint after each batch in `.complaints-rag-checkpoint.json`; use `--restart` only to deliberately reprocess the corpus.

## Testing and evaluation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\run_evals.py
```

Tests use fake specialists and fake database clients; they make no OpenAI, MotherDuck, Supabase, Qdrant, or Langfuse request. The deterministic release gate runs 17 public, redacted, versioned fixtures in `evals/` through a network-free fake workflow. It checks routes, execution and repair budgets, declared specialist paths, approved suggestions, result digests/grounding, and supplied RAG citation metadata. See `evals/README.md` for the fixture counts and its limits. Expand this compact baseline with held-out, reviewed SQL, safety, multi-turn, and grounding cases before making a quality claim or publicly deploying the demo.

## Deployment boundary

The current MotherDuck token is suitable for local work only. Before public hosting, use a restricted read-only serving credential that cannot access `source` tables, system tables, or filesystem/network extensions. Keep all secrets as server-side hosting variables.