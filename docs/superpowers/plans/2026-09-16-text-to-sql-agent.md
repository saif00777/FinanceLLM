# Text-to-SQL Agent Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a backend-only agent that can safely answer natural-language financial-data questions using controlled OpenAI tool calls and MotherDuck’s canonical views.

**Architecture:** A FastAPI route invokes a bounded `TextToSqlAgent`. The agent controls tool selection, while a compact contract tool and SQL policy are deterministic application code. Only a policy-approved query runner can reach MotherDuck.

**Tech Stack:** Python 3.12, FastAPI, OpenAI Python SDK Responses API, DuckDB/MotherDuck, SQLGlot, PyYAML, python-dotenv, unittest.

**Spec:** `docs/superpowers/specs/2026-09-16-text-to-sql-agent-design.md`

## Global Constraints

- Use `OPEN_AI_KEY`, `OPEN_AI_MODEL`, and `MOTHERDUCK_TOKEN` from `.env`; never read, log, return, or commit their values.
- Generated SQL may access only fully qualified `main.transactions`, `main.cards`, `main.users`, and `main.mcc_codes`.
- Require a single DuckDB `SELECT` or `WITH` ending in `SELECT`, explicit projection, and a `LIMIT` from 1 through 100.
- Use `store=False` for Responses API requests and perform no live OpenAI/MotherDuck call in automated tests.
- Keep the current owner token local-only; a restricted serving credential is required before public deployment.
- Keep every new production behavior covered by a test that is observed failing before implementation.

---

### Task 1: Configuration and Runtime Contract

**Files:**
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/contracts.py`
- Create: `tests/test_agent_contracts.py`
- Create: `requirements.txt`
- Modify: `.gitignore`

**Interfaces:**
- Produces `AppConfig.from_environment(environ: Mapping[str, str]) -> AppConfig`.
- Produces `RuntimeContract.from_files(root: Path) -> RuntimeContract` and `RuntimeContract.as_prompt() -> str`.

- [ ] **Step 1: Write failing configuration and contract tests**

```python
def test_configuration_prefers_project_open_ai_key():
    config = AppConfig.from_environment({
        "OPEN_AI_KEY": "project-key", "OPENAI_API_KEY": "fallback-key",
        "OPEN_AI_MODEL": "gpt-4o", "MOTHERDUCK_TOKEN": "motherduck-key",
    })
    self.assertEqual(config.openai_api_key, "project-key")

def test_runtime_contract_excludes_private_source_details():
    prompt = RuntimeContract.from_files(ROOT).as_prompt()
    self.assertIn("main.transactions", prompt)
    self.assertNotIn("source.cards", prompt)
    self.assertNotIn("card_number", prompt)
```

- [ ] **Step 2: Run the new tests and confirm they fail because `app` does not exist**

Run: `& .\\.venv\\Scripts\\python.exe -m unittest tests.test_agent_contracts -v`

Expected: import failure for `app`.

- [ ] **Step 3: Add pinned runtime dependencies and minimal implementations**

```python
@dataclass(frozen=True)
class AppConfig:
    openai_api_key: str
    openai_model: str
    motherduck_token: str

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "AppConfig":
        return cls(
            openai_api_key=_required(environ, "OPEN_AI_KEY", fallback="OPENAI_API_KEY"),
            openai_model=_required(environ, "OPEN_AI_MODEL"),
            motherduck_token=_required(environ, "MOTHERDUCK_TOKEN"),
        )
```

Implement `RuntimeContract` by loading only `context/schema.yaml` and `context/semantics.yaml`, projecting approved table/column names, relationships, metrics, rules, ambiguities, and unsupported topics.

- [ ] **Step 4: Run the contract tests and confirm they pass**

Run: `& .\\.venv\\Scripts\\python.exe -m unittest tests.test_agent_contracts -v`

- [ ] **Step 5: Keep the virtual environment excluded from source control**

Add `.venv/` to `.gitignore` without changing the existing `.env` exclusions.

### Task 2: SQL Policy and Query Runner

**Files:**
- Create: `app/sql_policy.py`
- Create: `app/query_runner.py`
- Create: `tests/test_sql_policy.py`

**Interfaces:**
- Produces `SqlPolicy.validate(sql: str) -> str`, which returns normalized SQL or raises `SqlPolicyError`.
- Produces `QueryResult(columns: list[str], rows: list[list[JsonValue]])`.
- Produces `MotherDuckQueryRunner.run(sql: str) -> QueryResult`.

- [ ] **Step 1: Write failing SQL-policy tests**

```python
def test_allows_canonical_aggregate_query():
    sql = "SELECT t.mcc, SUM(t.amount) AS total FROM main.transactions AS t GROUP BY t.mcc ORDER BY total DESC LIMIT 10"
    self.assertIn("main.transactions", SqlPolicy().validate(sql))

def test_rejects_source_schema_before_runner():
    with self.assertRaisesRegex(SqlPolicyError, "allowed relation"):
        SqlPolicy().validate("SELECT card_number FROM source.cards LIMIT 1")

def test_rejects_unbounded_and_mutating_sql():
    for sql in ("SELECT t.mcc FROM main.transactions t", "DELETE FROM main.transactions"):
        with self.subTest(sql=sql):
            with self.assertRaises(SqlPolicyError):
                SqlPolicy().validate(sql)
```

- [ ] **Step 2: Run the new tests and confirm they fail because `SqlPolicy` does not exist**

Run: `& .\\.venv\\Scripts\\python.exe -m unittest tests.test_sql_policy -v`

- [ ] **Step 3: Implement AST-based validation and a JSON-safe runner**

```python
class SqlPolicy:
    allowed_relations = {("main", "transactions"), ("main", "cards"),
                         ("main", "users"), ("main", "mcc_codes")}

    def validate(self, sql: str) -> str:
        expression = sqlglot.parse_one(sql, read="duckdb")
        self._validate_select_shape(expression)
        self._validate_tables(expression)
        self._validate_projection(expression)
        self._validate_functions(expression)
        self._validate_limit(expression)
        return expression.sql(dialect="duckdb")
```

`MotherDuckQueryRunner` connects only with the token supplied through `AppConfig`, executes the already validated SQL, maps `Decimal`, `date`, and `datetime` values to JSON-compatible values, and closes its connection in `finally`.

- [ ] **Step 4: Run the SQL-policy tests and confirm they pass**

Run: `& .\\.venv\\Scripts\\python.exe -m unittest tests.test_sql_policy -v`

### Task 3: Bounded OpenAI Tool-Using Agent

**Files:**
- Create: `app/agent.py`
- Create: `tests/test_agent.py`

**Interfaces:**
- Produces `TextToSqlAgent.answer(question: str) -> AgentAnswer`.
- Consumes a client with `responses.create(**kwargs)` and a `QueryRunner` protocol, allowing tests to use deterministic fakes.
- `AgentAnswer` has `answer`, `sql`, `columns`, `rows`, and `request_id` fields.

- [ ] **Step 1: Write failing agent-loop tests**

```python
def test_agent_reads_contract_then_executes_one_query():
    client = ScriptedClient([
        function_call("get_data_contract", {}, "contract-call"),
        function_call("run_read_only_sql", {"sql": VALID_SQL}, "query-call"),
        final_text("The requested totals are shown in the result."),
    ])
    result = TextToSqlAgent(client, FakeRunner()).answer("Totals by MCC")
    self.assertEqual(result.sql, VALID_SQL)
    self.assertEqual(result.rows, [["5411", 100.0]])

def test_agent_refuses_query_tool_before_contract():
    client = ScriptedClient([function_call("run_read_only_sql", {"sql": VALID_SQL}, "query-call")])
    with self.assertRaisesRegex(AgentProtocolError, "contract"):
        TextToSqlAgent(client, FakeRunner()).answer("Totals by MCC")
```

- [ ] **Step 2: Run the new tests and confirm they fail because `TextToSqlAgent` does not exist**

Run: `& .\\.venv\\Scripts\\python.exe -m unittest tests.test_agent -v`

- [ ] **Step 3: Implement the tool definitions and loop**

```python
for _ in range(MAX_TOOL_ROUNDS):
    response = client.responses.create(model=model, input=input_items, tools=TOOLS, store=False)
    calls = [item for item in response.output if item.type == "function_call"]
    if not calls:
        return AgentAnswer(answer=response.output_text, **last_query_result)
    input_items = [_execute_call(call) for call in calls]
```

`_execute_call` must require contract retrieval before the sole query, serialize tool outputs as JSON, validate every SQL request through `SqlPolicy`, and return safe error text for policy/database failures. Exceeding four rounds raises `AgentProtocolError`.

- [ ] **Step 4: Run the agent tests and confirm they pass**

Run: `& .\\.venv\\Scripts\\python.exe -m unittest tests.test_agent -v`

### Task 4: FastAPI Surface and Operations Documentation

**Files:**
- Create: `app/main.py`
- Create: `tests/test_api.py`
- Create: `README.md`
- Modify: `.env.example`

**Interfaces:**
- Produces `app.api.main.create_app(agent: TextToSqlAgent | None = None) -> FastAPI`.
- `GET /health` returns `{"status": "ok"}`.
- `POST /api/chat` accepts `{"question": str}` and returns the `AgentAnswer` shape.

- [ ] **Step 1: Write failing API tests**

```python
def test_health_is_available_without_credentials():
    response = TestClient(create_app(FakeAgent())).get("/health")
    self.assertEqual(response.json(), {"status": "ok"})

def test_chat_returns_agent_result():
    response = TestClient(create_app(FakeAgent())).post("/api/chat", json={"question": "Totals by MCC"})
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.json()["sql"], VALID_SQL)
```

- [ ] **Step 2: Run the new tests and confirm they fail because `create_app` does not exist**

Run: `& .\\.venv\\Scripts\\python.exe -m unittest tests.test_api -v`

- [ ] **Step 3: Implement the FastAPI app and documentation**

```python
def create_app(agent: TextToSqlAgent | None = None) -> FastAPI:
    app = FastAPI(title="Financial Text-to-SQL Agent")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        return ChatResponse.from_agent_answer((agent or build_agent()).answer(request.question))

    return app
```

Document local installation, `.env` variable names, `uvicorn app.api.main:app --reload`, example `curl` request, the backend-only scope, and the mandatory restricted serving credential before public deployment. Add comments to `.env.example` distinguishing project configuration from hosting fallback.

- [ ] **Step 4: Run the API tests and confirm they pass**

Run: `& .\\.venv\\Scripts\\python.exe -m unittest tests.test_api -v`

### Task 5: Full Verification

**Files:**
- Verify: `tests/test_context.py`
- Verify: `tests/test_motherduck_import.py`
- Verify: `tests/test_agent_contracts.py`
- Verify: `tests/test_sql_policy.py`
- Verify: `tests/test_agent.py`
- Verify: `tests/test_api.py`

- [ ] **Step 1: Run the complete automated suite**

Run: `& .\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v`

Expected: every test passes without a live API or database request.

- [ ] **Step 2: Validate the importable ASGI app**

Run: `& .\\.venv\\Scripts\\python.exe -c "from app.api.main import app; print(app.title)"`

Expected: `Financial Text-to-SQL Agent`.

- [ ] **Step 3: Inspect tracked-sensitive-file protections**

Run: `Select-String -Path .gitignore -Pattern '^\\.env$|^\\.venv/$'`

Expected: entries for `.env` and `.venv/`.
