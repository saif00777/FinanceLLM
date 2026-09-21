# Hybrid SQL + Complaints-RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one chat request answer a question that needs both the SQL branch and the consumer-complaints RAG branch, combining both results into one answer with no implied relationship between the two datasets.

**Architecture:** Extend the domain-guard specialist's existing LLM call to classify `sources` needed (`sql`, `rag`, or both). Restructure `document_router` so RAG runs first as a sequential prefix step when needed (not true parallel fan-out — that was tried and proven broken during planning, see below), chaining into the SQL branch for hybrid requests or straight to a new `merge_results` node for RAG-only. Rename the SQL and RAG branches' state-key writes so they never collide, and let `merge_results` combine whichever ran via template concatenation.

**Tech Stack:** Python, FastAPI, LangGraph 1.2.11, unittest (no pytest in this repo — verify with `grep -r pytest requirements.txt` if unsure; it uses `unittest.TestCase`).

**Spec:** [docs/superpowers/specs/2026-09-21-hybrid-sql-rag-design.md](../specs/2026-09-21-hybrid-sql-rag-design.md) — read it before starting; it has the full rationale, including the "Verified technical risk" section explaining why the graph topology below is sequential, not parallel (a true parallel design was tried and empirically disproven during planning — do not "fix" this plan back to parallel fan-out without re-reading that section).

## Global Constraints

- This repository now has git history, starting from an initial baseline commit made 2026-09-21 (it had none before). Every task below ends with a real "Commit" step — commit only the files that task touched, not a blanket `git add -A`.
- Test runner: `./.venv/Scripts/python.exe -m unittest <module> -v` (Windows venv; the path works from both PowerShell and the Bash tool in this environment). Full suite: `./.venv/Scripts/python.exe -m unittest discover -s tests -v`. Eval gate: `./.venv/Scripts/python.exe scripts/run_evals.py`.
- No task may touch the MotherDuck credential, add rate limiting, or add a kill switch — explicitly out of scope per the spec.
- No task may make a live OpenAI, MotherDuck, Supabase, or Qdrant call from a test. Every existing test in this repo uses fakes; follow that pattern exactly (see `tests/test_workflow.py`'s `FakeSpecialists`/`FakeRunner`/`FakeComplaintRetriever` and `tests/test_production_specialists.py`'s `FakeResponses`).
- The existing test `tests/test_workflow.py::WorkflowTests::test_complaint_request_routes_to_retrieval_without_sql_execution` must keep passing **unchanged** (do not edit it) after every task — it is the safety-isolation guarantee this feature must not weaken.
- Run the full unit suite (not just the file you touched) at the end of every task. A task is not done if it introduces any regression elsewhere.

---

## Task 1: `DomainDecision` gains a `sources` classification

**Files:**
- Modify: `app/agents/text_to_sql/specialists.py:12-15` (the `DomainDecision` dataclass), `app/agents/text_to_sql/specialists.py:103-105` (the `domain_guard` method)
- Test: `tests/test_production_specialists.py`

**Interfaces:**
- Produces: `DomainDecision(route: str, reason_code: str, sources: tuple[str, ...] = ("sql",))` — the new `sources` field, values drawn from `{"sql", "rag"}`, defaulting to `("sql",)` so every existing call site (e.g. `tests/test_workflow.py`'s `FakeSpecialists.domain_guard`, which calls `DomainDecision("in_scope", "allowed")` with two positional args) keeps working unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_production_specialists.py` (after the existing `FakeResponses` class, before `ProductionSpecialistTests`):

```python
class FakeDomainGuardResponses:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("Response", (), {"output_text": json.dumps(self._payload)})()
```

Add these two methods inside the existing `ProductionSpecialistTests` class:

```python
    def test_domain_guard_parses_sources_from_the_model_response(self):
        responses = FakeDomainGuardResponses({"route": "in_scope", "reason_code": "allowed", "sources": ["sql", "rag"]})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        decision = specialist.domain_guard("Spending and complaints about it", {})

        self.assertEqual(decision.route, "in_scope")
        self.assertEqual(decision.sources, ("sql", "rag"))

    def test_domain_guard_defaults_sources_to_sql_when_missing_or_invalid(self):
        responses = FakeDomainGuardResponses({"route": "in_scope", "reason_code": "allowed", "sources": ["bogus", 42]})
        client = type("Client", (), {"responses": responses})()
        specialist = OpenAIResponsesSpecialists(client, "demo-model", object())

        decision = specialist.domain_guard("Total spending", {})

        self.assertEqual(decision.sources, ("sql",))
```

Also add the import at the top of the file: change `from app.agents.text_to_sql.specialists import OpenAIResponsesSpecialists` to `from app.agents.text_to_sql.specialists import DomainDecision, OpenAIResponsesSpecialists` (only needed if you reference `DomainDecision` directly in a test; the two tests above don't construct it directly, so this import addition is optional — skip it unless you add an assertion that does).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_production_specialists -v`
Expected: both new tests FAIL — `test_domain_guard_parses_sources_from_the_model_response` fails on `AttributeError: 'DomainDecision' object has no attribute 'sources'` (or a `TypeError` if you also added a direct `DomainDecision(...)` construction elsewhere); the existing `test_openai_adapter_returns_structured_data_analysis` must still PASS (it's unrelated to this change).

- [ ] **Step 3: Add the `sources` field to `DomainDecision`**

In `app/agents/text_to_sql/specialists.py`, replace:

```python
@dataclass(frozen=True)
class DomainDecision:
    route: str
    reason_code: str
```

with:

```python
@dataclass(frozen=True)
class DomainDecision:
    route: str
    reason_code: str
    sources: tuple[str, ...] = ("sql",)
```

- [ ] **Step 4: Parse `sources` in `domain_guard`**

In the same file, replace:

```python
    def domain_guard(self, question: str, facts: dict[str, str]) -> DomainDecision:
        data = self._json("Return JSON with route and reason_code. Use in_scope, clarify, or abstain.", {"question": question, "facts": facts})
        return DomainDecision(route=data.get("route", "clarify"), reason_code=data.get("reason_code", "unclear_request"))
```

with:

```python
    _VALID_SOURCES = frozenset({"sql", "rag"})

    def domain_guard(self, question: str, facts: dict[str, str]) -> DomainDecision:
        data = self._json(
            "Return JSON with route, reason_code, and sources. Use in_scope, clarify, or abstain for route. "
            "sources is an array containing sql and/or rag, for whether the question needs financial-transaction "
            "analysis, consumer-complaint narratives, or both.",
            {"question": question, "facts": facts},
        )
        raw_sources = data.get("sources")
        valid_sources = (
            tuple(dict.fromkeys(item for item in raw_sources if item in self._VALID_SOURCES))
            if isinstance(raw_sources, list)
            else ()
        )
        return DomainDecision(
            route=data.get("route", "clarify"),
            reason_code=data.get("reason_code", "unclear_request"),
            sources=valid_sources or ("sql",),
        )
```

Note `_VALID_SOURCES` is defined as a class attribute right above the method it's used in (matches this class's existing style — `_text_list` is a `@staticmethod` a few lines up, this is a plain class constant). `dict.fromkeys(...)` dedupes while preserving order (a plain `set()` would not preserve order, and the "sources contains sql and rag" assertion in Step 1 depends on order `("sql", "rag")` matching the input list order).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_production_specialists -v`
Expected: PASS, 3/3 (the 2 new tests plus the pre-existing one).

- [ ] **Step 6: Run the full suite to confirm no regression**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -v`
Expected: all tests pass (94 pre-existing + 2 new = 96). The `DomainDecision("in_scope", "allowed")` two-positional-arg calls in `tests/test_workflow.py` must still work unchanged because of the new field's default.

- [ ] **Step 7: Commit**

```bash
git add app/agents/text_to_sql/specialists.py tests/test_production_specialists.py
git commit -m "feat: add sources classification to DomainDecision"
```

---

## Task 2: Sequential source-aware routing, per-branch state keys, and the `merge_results` node

This is one atomic task, not several — none of the following changes can be tested or reviewed in isolation from the others. Renaming `_executor_node`'s writes without also updating `_after_policy` to read the new key breaks the SQL branch's own control flow; adding `merge_results` without rewiring the edges leaves it unreachable; changing `document_router`'s fan-out without the sequential-chaining logic reintroduces the double-fire/deadlock bug documented in the spec's "Verified technical risk" section. All of it lands together, and the full test suite must be green at the end.

**Files:**
- Modify: `app/agents/text_to_sql/workflow.py` (extensively — see steps below for every touched section)
- Test: `tests/test_workflow.py`

**Interfaces:**
- Consumes: `DomainDecision.sources: tuple[str, ...]` from Task 1.
- Produces: `AgentState` gains `sources: tuple[str, ...]`, `active_sources: tuple[str, ...]`, `sql_route: str`, `sql_answer: str`, `rag_route: str`, `rag_message: str`. The graph gains one new node, `merge_results`. Final `state["route"]`/`state["answer"]` (consumed by `answer()`, unchanged) are now written **only** by `_merge_results_node` (for requests that pass `document_router`) or by the pre-existing `hard_guard`/`domain_guard` early-rejection paths (unchanged, still write `route`/`answer` directly, since those never reach `document_router` at all).

### Step-by-step

- [ ] **Step 1: Add the new `AgentState` fields**

In `app/agents/text_to_sql/workflow.py`, in the `AgentState` TypedDict (currently lines 24-47), add these fields (insert after the existing `route: str` and `reason_code: str` lines, before `plan: Any`):

```python
    sources: tuple[str, ...]
    active_sources: tuple[str, ...]
```

And add these fields after the existing `sql: str` line:

```python
    sql_route: str
    sql_answer: str
```

And add these fields after the existing `grounding: str` line:

```python
    rag_route: str
    rag_message: str
```

(Exact placement within the TypedDict doesn't affect behavior — TypedDict field order is cosmetic — but group them near their related existing fields for readability, matching this file's existing organization.)

- [ ] **Step 2: Make `_domain_guard_node` expose `sources`**

Replace (currently lines 208-210):

```python
    def _domain_guard_node(self, state: AgentState) -> dict[str, Any]:
        decision = self._specialists.domain_guard(state["question"], state["facts"])
        return {"route": "in_scope" if decision.route == "in_scope" else decision.route, "reason_code": decision.reason_code}
```

with:

```python
    def _domain_guard_node(self, state: AgentState) -> dict[str, Any]:
        decision = self._specialists.domain_guard(state["question"], state["facts"])
        return {
            "route": "in_scope" if decision.route == "in_scope" else decision.route,
            "reason_code": decision.reason_code,
            "sources": decision.sources,
        }
```

- [ ] **Step 3: Rewrite `_document_router_node` and its conditional-edge functions**

Replace (currently lines 216-223):

```python
    def _document_router_node(self, state: AgentState) -> dict[str, Any]:
        normalized = state["question"].lower()
        complaint_terms = ("complaint", "consumer complaint", "cfpb", "consumer narrative")
        return {"route": "complaint_request" if self._complaint_retriever and any(term in normalized for term in complaint_terms) else "sql_request"}

    @staticmethod
    def _after_document_router(state: AgentState) -> str:
        return "complaint_retrieval" if state["route"] == "complaint_request" else "planner"
```

with:

```python
    def _document_router_node(self, state: AgentState) -> dict[str, Any]:
        sources = set(state.get("sources", ("sql",)))
        if "rag" in sources and self._complaint_retriever is None:
            sources.discard("rag")
        return {"active_sources": tuple(sorted(sources)) or ("sql",)}

    @staticmethod
    def _after_document_router(state: AgentState) -> str:
        return "complaint_retrieval" if "rag" in state["active_sources"] else "planner"

    @staticmethod
    def _after_complaint_retrieval_routing(state: AgentState) -> str:
        return "planner" if "sql" in state["active_sources"] else "merge_results"
```

Note `_document_router_node` no longer sets `"route"` at all — it's a pure translator now, and nothing downstream reads a `route` value it used to set (the old `"complaint_request"`/`"sql_request"` values were only ever consumed by the old `_after_document_router`, which is being replaced in the same step). `_after_document_router` returns a plain `str`, same shape as its siblings (`_after_hard_guard`, `_after_domain_guard`, `_after_policy`) — routing is sequential now (RAG-first-if-needed, chaining into SQL via `_after_complaint_retrieval_routing`), so it only ever needs to name one target, never both at once; there's no true parallel fan-out left in this design (see the spec's "Verified technical risk" section for why that was tried and reverted).

- [ ] **Step 4: Rename `_complaint_retrieval_node`'s writes**

Replace (currently lines 225-238):

```python
    def _complaint_retrieval_node(self, state: AgentState) -> dict[str, Any]:
        if self._complaint_retriever is None:
            return {"route": "clarify", "answer": "Complaint retrieval is not configured."}
        documents = self._complaint_retriever.retrieve(state["question"])
        citations = [{"source_hash": document.citation} for document in documents]
        if not documents:
            return {"route": "answered", "answer": "I could not find a matching consented complaint narrative.", "documents": [], "citations": [], "grounding": "approved"}
        return {
            "route": "answered",
            "answer": f"I found {len(documents)} relevant consented complaint narrative(s). The cited excerpts are redacted and the complaint branch did not query financial transactions.",
            "documents": documents,
            "citations": citations,
            "grounding": "approved",
        }
```

with:

```python
    def _complaint_retrieval_node(self, state: AgentState) -> dict[str, Any]:
        if self._complaint_retriever is None:
            return {"rag_route": "clarify", "rag_message": "Complaint retrieval is not configured."}
        documents = self._complaint_retriever.retrieve(state["question"])
        citations = [{"source_hash": document.citation} for document in documents]
        if not documents:
            return {"rag_route": "answered", "rag_message": "I could not find a matching consented complaint narrative.", "documents": [], "citations": [], "grounding": "approved"}
        return {
            "rag_route": "answered",
            "rag_message": f"I found {len(documents)} relevant consented complaint narrative(s). The cited excerpts are redacted and the complaint branch did not query financial transactions.",
            "documents": documents,
            "citations": citations,
            "grounding": "approved",
        }
```

(The `self._complaint_retriever is None` branch is now unreachable in practice — `document_router` filters `rag` out of `active_sources` before this node would ever be scheduled without a configured retriever — but it's left in place as a defensive fallback, per the existing style of this codebase; not part of this change's scope to remove it.)

- [ ] **Step 5: Rename `_sql_policy_node`'s writes and update `_after_policy`**

Replace (currently lines 263-278):

```python
    def _sql_policy_node(self, state: AgentState) -> dict[str, Any]:
        proposal = state["proposal"]
        if not proposal.sql:
            return {"route": "clarify", "answer": proposal.clarification or "Please clarify the requested analysis."}
        try:
            return {"sql": self._policy.validate(proposal.sql), "route": "approved"}
        except SqlPolicyError as error:
            return {"route": "repair", "repair_error": str(error), "repairs": state["repairs"] + 1}

    @staticmethod
    def _after_policy(state: AgentState) -> str:
        if state["route"] == "approved":
            return "executor"
        if state["route"] == "repair" and state["repairs"] <= 2:
            return "sql_generator"
        return "suggestions"
```

with:

```python
    def _sql_policy_node(self, state: AgentState) -> dict[str, Any]:
        proposal = state["proposal"]
        if not proposal.sql:
            return {"sql_route": "clarify", "sql_answer": proposal.clarification or "Please clarify the requested analysis."}
        try:
            return {"sql": self._policy.validate(proposal.sql), "sql_route": "approved"}
        except SqlPolicyError as error:
            return {"sql_route": "repair", "repair_error": str(error), "repairs": state["repairs"] + 1}

    @staticmethod
    def _after_policy(state: AgentState) -> str:
        if state["sql_route"] == "approved":
            return "executor"
        if state["sql_route"] == "repair" and state["repairs"] <= 2:
            return "sql_generator"
        return "merge_results"
```

Note the repair-exhausted case still ends up with `sql_route` literally equal to `"repair"` (not rewritten to `"clarify"`) when it falls through to `merge_results` — this exactly preserves today's existing (slightly unusual) behavior where a repair-exhausted request's exposed `route` is `"repair"`, not `"clarify"`. Do not "fix" this as part of this task; it's out of scope and no existing test or eval fixture depends on changing it.

- [ ] **Step 6: Rename `_executor_node`'s writes**

Replace (currently lines 280-284):

```python
    def _executor_node(self, state: AgentState) -> dict[str, Any]:
        if state["executions"] >= 1:
            return {"route": "clarify", "answer": "The request exceeded its query budget."}
        result = self._runner.run(state["sql"])
        return {"result": result, "executions": state["executions"] + 1, "route": "answered"}
```

with:

```python
    def _executor_node(self, state: AgentState) -> dict[str, Any]:
        if state["executions"] >= 1:
            return {"sql_route": "clarify", "sql_answer": "The request exceeded its query budget."}
        result = self._runner.run(state["sql"])
        return {"result": result, "executions": state["executions"] + 1, "sql_route": "answered"}
```

- [ ] **Step 7: Rename `_analyst_node`'s write**

Replace (currently lines 291-294):

```python
    def _analyst_node(self, state: AgentState) -> dict[str, Any]:
        result = state["result"]
        grounded = self._specialists.analyze(state["question"], result.columns, result.rows, state["proposal"])
        return {"answer": grounded.answer, "chart": grounded.chart}
```

with:

```python
    def _analyst_node(self, state: AgentState) -> dict[str, Any]:
        result = state["result"]
        grounded = self._specialists.analyze(state["question"], result.columns, result.rows, state["proposal"])
        return {"sql_answer": grounded.answer, "chart": grounded.chart}
```

- [ ] **Step 8: Rename `_reviewer_node`'s writes**

Replace (currently lines 296-306):

```python
    def _reviewer_node(self, state: AgentState) -> dict[str, Any]:
        result = state["result"]
        decision = self._specialists.review(state["question"], result.columns, result.rows, state.get("answer", ""), state.get("analysis"))
        if decision.approved:
            return {"route": "answered", "reason_code": decision.reason_code, "grounding": "approved"}
        return {
            "route": "clarify",
            "reason_code": decision.reason_code,
            "grounding": decision.reason_code,
            "answer": "The returned result needs a narrower question before I can give a grounded answer.",
        }
```

with:

```python
    def _reviewer_node(self, state: AgentState) -> dict[str, Any]:
        result = state["result"]
        decision = self._specialists.review(state["question"], result.columns, result.rows, state.get("sql_answer", ""), state.get("analysis"))
        if decision.approved:
            return {"sql_route": "answered", "reason_code": decision.reason_code, "grounding": "approved"}
        return {
            "sql_route": "clarify",
            "reason_code": decision.reason_code,
            "grounding": decision.reason_code,
            "sql_answer": "The returned result needs a narrower question before I can give a grounded answer.",
        }
```

Note `state.get("answer", "")` becomes `state.get("sql_answer", "")` on the first line — this is the value passed to `self._specialists.review(...)` for grounding review, and must read the renamed key or it will always see an empty string.

- [ ] **Step 9: Add the new `_merge_results_node`**

Add this new method immediately after `_reviewer_node` (i.e., right before `_suggestions_node`, currently starting at line 308):

```python
    def _merge_results_node(self, state: AgentState) -> dict[str, Any]:
        sql_route = state.get("sql_route")
        rag_route = state.get("rag_route")
        parts = []
        if sql_route is not None:
            parts.append(state["sql_answer"])
        if rag_route is not None:
            parts.append(f"Consumer complaint narratives found: {state['rag_message']}")
        route = "answered" if "answered" in (sql_route, rag_route) else (sql_route or rag_route)
        return {"answer": "\n\n".join(parts), "route": route}
```

(Instance method, not `@staticmethod` — it doesn't need `self`, but every other actual graph-node handler in this file (`_hard_guard_node`, `_domain_guard_node`, etc.) is an instance method with this exact `(self, state)` signature; matching that convention keeps all node handlers uniform for whoever reads this file next. Only the `_after_*` routing functions and a couple of pure helpers are staticmethods.)

- [ ] **Step 10: Register the new node and rewire the graph edges**

In `_build_graph` (currently lines 108-139), add the new node registration. After the existing line:

```python
        graph.add_node("suggestions", self._traced("suggestions", self._suggestions_node))
```

add:

```python
        graph.add_node("merge_results", self._traced("merge_results", self._merge_results_node))
```

Then replace the routing edges. Find:

```python
        graph.add_conditional_edges("hard_guard", self._after_hard_guard, {"domain_guard": "domain_guard", "suggestions": "suggestions"})
        graph.add_conditional_edges("domain_guard", self._after_domain_guard, {"document_router": "document_router", "suggestions": "suggestions"})
        graph.add_conditional_edges("document_router", self._after_document_router, {"planner": "planner", "complaint_retrieval": "complaint_retrieval"})
        graph.add_edge("complaint_retrieval", "suggestions")
        graph.add_edge("planner", "schema_link")
```

Replace with:

```python
        graph.add_conditional_edges("hard_guard", self._after_hard_guard, {"domain_guard": "domain_guard", "suggestions": "suggestions"})
        graph.add_conditional_edges("domain_guard", self._after_domain_guard, {"document_router": "document_router", "suggestions": "suggestions"})
        graph.add_conditional_edges("document_router", self._after_document_router, {"planner": "planner", "complaint_retrieval": "complaint_retrieval"})
        graph.add_conditional_edges("complaint_retrieval", self._after_complaint_retrieval_routing, {"planner": "planner", "merge_results": "merge_results"})
        graph.add_edge("planner", "schema_link")
```

Then find:

```python
        graph.add_conditional_edges("sql_policy", self._after_policy, {"executor": "executor", "sql_generator": "sql_generator", "suggestions": "suggestions"})
        graph.add_edge("executor", "data_analysis")
        graph.add_edge("executor", "analyst")
        graph.add_edge(["data_analysis", "analyst"], "reviewer")
        graph.add_edge("reviewer", "suggestions")
        graph.add_edge("suggestions", END)
```

Replace with:

```python
        graph.add_conditional_edges("sql_policy", self._after_policy, {"executor": "executor", "sql_generator": "sql_generator", "merge_results": "merge_results"})
        graph.add_edge("executor", "data_analysis")
        graph.add_edge("executor", "analyst")
        graph.add_edge(["data_analysis", "analyst"], "reviewer")
        graph.add_edge("reviewer", "merge_results")
        graph.add_edge("merge_results", "suggestions")
        graph.add_edge("suggestions", END)
```

The `document_router` conditional edge's path map is unchanged from before (`{"planner": "planner", "complaint_retrieval": "complaint_retrieval"}`) — only `_after_document_router`'s internal logic changed (reads `active_sources` instead of scanning keywords), not its return shape.

- [ ] **Step 11: Run the full suite — expect regressions, fix them**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -v`

At this point every existing test should pass, because for the SQL-only and RAG-only cases, the new sequential routing produces the same externally-observable behavior as before (just through renamed internal keys and one extra pass-through node). If anything fails, it is almost certainly one of:
- A missed rename (grep the file for `"route"` and `"answer"` as dict keys below `_document_router_node` to make sure none remain among the SQL/RAG branch nodes).
- `_after_policy` or `_reviewer_node` reading the old `state["answer"]`/`state["route"]` instead of the renamed keys.

Do not proceed to Step 12 until this is fully green.

- [ ] **Step 12: Write the failing hybrid-path test**

Add this fake to `tests/test_workflow.py`, near `FakeComplaintRetriever` (after it):

```python
class HybridDomainGuardSpecialists(FakeSpecialists):
    def domain_guard(self, question, facts):
        return DomainDecision("in_scope", "allowed", sources=("sql", "rag"))
```

Add this test method to `WorkflowTests`:

```python
    def test_hybrid_request_runs_both_branches_and_combines_the_answer(self):
        retriever = FakeComplaintRetriever()
        specialists = HybridDomainGuardSpecialists()
        workflow = MultiAgentWorkflow(
            RuntimeContract.from_files(ROOT), self.runner, specialists, InMemoryConversationStore(), HardGuard(),
            complaint_retriever=retriever,
        )
        result = workflow.answer("Total spending by category and related consumer complaints")
        self.assertEqual(self.runner.calls, 1)
        self.assertEqual(retriever.calls, 1)
        self.assertEqual(result.route, "answered")
        self.assertIn("The total is 100.", result.answer)
        self.assertIn("Consumer complaint narratives found:", result.answer)
        self.assertNotIn("related", result.answer.lower())
        self.assertEqual(result.citations, [{"source_hash": "citation-a"}])
```

(`"The total is 100."` is `FakeSpecialists.analyze`'s hardcoded `GroundedAnswer` text — see line 30 of the existing test file — so this asserts the real SQL-branch output landed in the combined answer, not a stand-in.)

- [ ] **Step 13: Run it, verify it fails, then verify it passes**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_workflow.WorkflowTests.test_hybrid_request_runs_both_branches_and_combines_the_answer -v`

If Steps 1-11 above were done correctly, this should already **pass** the first time (there's no separate implementation step left — the graph changes were already made). If it fails, that's a real signal something in Steps 3-10 is wrong; debug against the actual failure rather than assuming the plan's code is correct as-is. Do not skip actually running this.

- [ ] **Step 14: Write and verify the "no complaint retriever configured" degrade-to-SQL test**

Add to `WorkflowTests`:

```python
    def test_hybrid_request_degrades_to_sql_only_when_rag_not_configured(self):
        specialists = HybridDomainGuardSpecialists()
        workflow = MultiAgentWorkflow(RuntimeContract.from_files(ROOT), self.runner, specialists, InMemoryConversationStore(), HardGuard())
        result = workflow.answer("Total spending and complaints")
        self.assertEqual(self.runner.calls, 1)
        self.assertEqual(result.route, "answered")
        self.assertNotIn("Consumer complaint narratives found:", result.answer)
```

Run: `./.venv/Scripts/python.exe -m unittest tests.test_workflow.WorkflowTests.test_hybrid_request_degrades_to_sql_only_when_rag_not_configured -v`
Expected: PASS (no `complaint_retriever` argument means `self._complaint_retriever is None`, so `_document_router_node` drops `"rag"` from `active_sources` per Step 3).

- [ ] **Step 15: Write and verify the partial-failure test (SQL fails, RAG succeeds)**

Add this fake near `HybridDomainGuardSpecialists`:

```python
class HybridSqlUngroundedSpecialists(HybridDomainGuardSpecialists):
    def review(self, question, columns, rows, answer, analysis):
        return ReviewDecision(False, "ungrounded_for_test")
```

Add to `WorkflowTests`:

```python
    def test_hybrid_request_shows_rag_results_when_sql_grounding_is_rejected(self):
        retriever = FakeComplaintRetriever()
        specialists = HybridSqlUngroundedSpecialists()
        workflow = MultiAgentWorkflow(
            RuntimeContract.from_files(ROOT), self.runner, specialists, InMemoryConversationStore(), HardGuard(),
            complaint_retriever=retriever,
        )
        result = workflow.answer("Total spending and related complaints")
        self.assertEqual(result.route, "answered")
        self.assertIn("narrower question", result.answer)
        self.assertIn("Consumer complaint narratives found:", result.answer)
        self.assertEqual(result.citations, [{"source_hash": "citation-a"}])
```

Run: `./.venv/Scripts/python.exe -m unittest tests.test_workflow.WorkflowTests.test_hybrid_request_shows_rag_results_when_sql_grounding_is_rejected -v`
Expected: PASS. `"narrower question"` is a substring of `_reviewer_node`'s rejection message (`"The returned result needs a narrower question before I can give a grounded answer."`) — this confirms the merge node's overall `route` is `"answered"` (from RAG) even though the SQL branch's own `sql_route` is `"clarify"`, and both text fragments are present.

There is no corresponding "RAG fails, SQL succeeds" test — per the spec, `_complaint_retrieval_node` is effectively always `rag_route == "answered"` once scheduled (the only failure case, "not configured," is filtered out before this node ever runs, per Step 3/14 above). Do not add a speculative test for a case that cannot actually occur; if you find yourself wanting to force one, that's a sign to re-read the spec's "show whatever succeeded" section rather than write a test around a fake that doesn't model real behavior.

- [ ] **Step 16: Run the full suite one more time**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -v`
Expected: all pass — 96 (end of Task 1) + 3 new tests from this task = 99 total. Confirm specifically that `test_complaint_request_routes_to_retrieval_without_sql_execution` (the pre-existing isolation test) is still in the passing set and was not modified.

- [ ] **Step 17: Run the eval gate**

Run: `./.venv/Scripts/python.exe scripts/run_evals.py`
Expected: `Passed 17/17 deterministic evaluation cases.` (unchanged — this task doesn't touch `evals/`, that's Task 3).

- [ ] **Step 18: Commit**

```bash
git add app/agents/text_to_sql/workflow.py tests/test_workflow.py
git commit -m "feat: sequential source-aware routing, per-branch state keys, and merge_results node"
```

---

## Task 3: Add the hybrid eval fixture case and update the fixture-count assertions

**Files:**
- Modify: `evals/graph_paths.json` (add one case), `tests/test_evaluations.py:28` (hardcoded case count), `tests/test_evaluations.py:72` (hardcoded "Passed N/N" string)

**Interfaces:**
- Consumes: the real graph topology from Task 2 (this task's fixture data must match what the real graph actually produces — see Step 1, which has you verify this directly rather than trust a guess).

Regarding the spec's other testing-impact bullet — "new `domain_guard.json` case(s) exercising `sources` classification" — this plan deliberately does **not** add one. `app/helpers/evaluation.py`'s evaluator has no field that checks `sources` or `active_sources` at all (it only checks `route`, `executions`, `repairs`, `specialist_path`, `suggested_questions`, `result_digest`, `grounding`, `citations` — see `_evaluate_case`), and the fixture-running harness (`FixtureWorkflow` in `scripts/run_evals.py`) is a dumb stub that echoes back whatever the fixture declares rather than exercising real classification logic. A `domain_guard.json` case for `sources` would not test anything beyond what it declares — the real functional coverage for `sources` classification already exists in Task 1's and Task 2's unit tests (which use real fakes and do exercise the real code paths). Adding an eval fixture that can't fail meaningfully would be pure busywork; skip it.

- [ ] **Step 1: Verify the real specialist_path order for a hybrid request**

This plan's spec was written using a structurally-accurate but simplified throwaway spike (not the real code) to determine node ordering. Verify it against the real implementation before hardcoding it into a fixture. Add this temporary block at the very end of `test_hybrid_request_runs_both_branches_and_combines_the_answer` in `tests/test_workflow.py` (temporarily — you will remove it in Step 2):

```python
        print("HYBRID PATH:", result.specialist_path)
```

Run: `./.venv/Scripts/python.exe -m unittest tests.test_workflow.WorkflowTests.test_hybrid_request_runs_both_branches_and_combines_the_answer -v -b 2>&1 | grep "HYBRID PATH"`

(The `-b` flag buffers normal test output but still lets explicit `print` through on failure/verbose paths in some unittest versions — if the print doesn't show, drop `-b` and just run without `-v` piping, or run the single test file directly without discovery and read its stdout.)

Record the exact printed list. It is expected to match (node names only — this repo's real registration order is identical to the spike's):

```
['hard_guard', 'domain_guard', 'document_router', 'complaint_retrieval', 'planner', 'metric_resolver', 'schema_link', 'sql_generator', 'sql_policy', 'executor', 'analyst', 'data_analysis', 'reviewer', 'merge_results', 'suggestions']
```

If it differs, use whatever the real run actually printed — that is the ground truth, not this plan.

- [ ] **Step 2: Remove the temporary print**

Delete the `print("HYBRID PATH:", result.specialist_path)` line added in Step 1. Re-run the test to confirm it still passes clean:

Run: `./.venv/Scripts/python.exe -m unittest tests.test_workflow.WorkflowTests.test_hybrid_request_runs_both_branches_and_combines_the_answer -v`
Expected: PASS, no stray output.

- [ ] **Step 3: Add the hybrid case to `evals/graph_paths.json`**

Read the current file first (it's a single-line-per-case JSON array; match that formatting). Add this case to the array (using the specialist_path confirmed in Step 1 — replace it below if your real run differed):

```json
{"id":"graph-hybrid","suite":"graph_paths","semantic_version":"financial-v1","graph_version":"multi-agent-v1","question":"Show total spending by merchant category and related consumer complaints","expected_route":"answered","max_executions":1,"max_repairs":2,"expected_specialist_path":["hard_guard","domain_guard","document_router","complaint_retrieval","planner","metric_resolver","schema_link","sql_generator","sql_policy","executor","analyst","data_analysis","reviewer","merge_results","suggestions"],"approved_suggested_questions":["Compare with the prior year","Break down spending by merchant category"],"expected_result_digest":"public-digest-category-v1","expected_grounding":{"metric":"positive_amount_total","rows":1},"expected_citations":[{"source_hash":"citation-a"}]}
```

Insert it as a new element in the existing JSON array (comma-separated, matching the file's existing style — do not reformat the whole file).

- [ ] **Step 4: Update the hardcoded fixture-count assertions**

In `tests/test_evaluations.py`, line 28, change:

```python
        self.assertEqual(len(cases), 17)
```

to:

```python
        self.assertEqual(len(cases), 18)
```

And line 72, change:

```python
        self.assertIn("Passed 17/17 deterministic evaluation cases.", result.stdout)
```

to:

```python
        self.assertIn("Passed 18/18 deterministic evaluation cases.", result.stdout)
```

- [ ] **Step 5: Run the evaluation tests**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_evaluations -v`
Expected: PASS, 4/4.

- [ ] **Step 6: Run the eval gate directly**

Run: `./.venv/Scripts/python.exe scripts/run_evals.py`
Expected: `Passed 18/18 deterministic evaluation cases.`

If it fails on the new `graph-hybrid` case specifically, the most likely cause is `expected_specialist_path` not matching what `FixtureWorkflow` echoes back — but since `FixtureWorkflow` just returns `case.get("expected_specialist_path")` verbatim (see `scripts/run_evals.py`), a self-consistent fixture cannot fail this specific check; if it fails, look at `REQUIRED_CASE_FIELDS` in `app/helpers/evaluation.py` for a missing required key instead (the new case must include `id`, `suite`, `semantic_version`, `graph_version`, `question`, `expected_route`, `max_executions`, `max_repairs` at minimum).

- [ ] **Step 7: Run the full suite one final time**

Run: `./.venv/Scripts/python.exe -m unittest discover -s tests -v`
Expected: all pass, 99/99.

- [ ] **Step 8: Commit**

```bash
git add evals/graph_paths.json tests/test_evaluations.py
git commit -m "test: add hybrid graph_paths eval case and update fixture count"
```

---

## Final acceptance check (run after Task 3)

Confirm every bullet in the spec's "Acceptance criteria" section:

- [ ] SQL-only and RAG-only requests behave identically to before this plan (verified by every pre-existing test still passing unchanged).
- [ ] A hybrid request produces one response, `route: "answered"`, a combined answer with no "related" language, citations from the RAG branch only (Task 2, Step 12-13's test).
- [ ] The pre-existing complaint-only SQL-isolation test passes unchanged (Task 2, Step 16).
- [ ] `sources` requesting `rag` with no complaint retriever configured degrades to SQL-only (Task 2, Step 14).
- [ ] Full unit suite (99 tests) and the eval gate (18/18) both pass with no live network calls anywhere in `tests/`.
