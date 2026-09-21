# Hybrid SQL + Complaints-RAG Design

## Goal

Let a single chat request answer a question that needs both the financial-transactions SQL branch and the consumer-complaints RAG branch, when the question genuinely asks for both — without implying any relationship between the two datasets that the data doesn't support.

## Constraint that shapes everything below

The two datasets share no join key. `main.transactions.merchant_id` is an anonymous identifier with, per `context/schema.yaml`, "no merchant-name lookup or merchant dimension supplied." The complaints payload keys on `company` (a name string), `product`, `issue`, `state`, `received_year` — nothing overlapping a transaction, card, or user ID. The only overlaps are loose, non-key text (`mcc_codes.description` vs. complaint `product`/`issue`; `merchant_state` vs. complaint `state`).

**Decision:** hybrid means *two logically independent, safety-isolated lookups presented together in one answer* — never a literal join or an LLM-synthesized connection between them. (Independence here is about the data and logic never cross-informing each other, not execution concurrency — see §2: they run sequentially, not in parallel, for reasons discovered during planning.) This was confirmed directly by the user and drives every choice below, especially the "no implied relation" wording rule.

## Scope

In scope: routing a question to both branches when warranted, running them independently, combining their outputs into one response without implying a relationship, and the graph/state changes needed to do that safely. Out of scope: any cross-dataset join or fuzzy matching, any new LLM call to synthesize a combined narrative, and the restricted MotherDuck serving credential (explicitly deferred by the user this session — current owner token stays in use).

## Approaches considered (routing detection)

1. Extend the existing binary keyword scan in `document_router` to a three-way heuristic. Rejected: cheapest, but keyword heuristics are already the weakest part of the current router, and three-way classification is a harder problem than the binary case it currently gets wrong-ish.
2. **Extend the domain-guard specialist's existing LLM call to also classify sources needed. (Chosen.)** Reuses a call that already runs on every request instead of adding a new one; domain guard already reasons over the full semantic catalog.
3. Add a dedicated routing specialist as a new graph node. Rejected: correct in principle, but an extra model call on every request for marginal benefit over option 2.

## Architecture

### 1. Domain guard gains a `sources` classification

`DomainDecision` ([app/agents/text_to_sql/specialists.py:12-15](app/agents/text_to_sql/specialists.py)) gains a field:

```python
@dataclass(frozen=True)
class DomainDecision:
    route: str
    reason_code: str
    sources: tuple[str, ...] = ("sql",)
```

Default `("sql",)` preserves current behavior for every existing caller/fake that doesn't populate it. Values are drawn from `{"sql", "rag"}`; `sources` is only meaningful when `route == "in_scope"`.

`OpenAIResponsesSpecialists.domain_guard` ([app/agents/text_to_sql/specialists.py:103-105](app/agents/text_to_sql/specialists.py)) prompt instructions gain one clause: return `sources`, an array containing `sql` and/or `rag`, for whether the question needs financial-transaction analysis, consumer-complaint narratives, or both. Parsed defensively — the same pattern `_text_list` already uses elsewhere: invalid/missing/unrecognized values fall back to `("sql",)`.

### 2. `document_router` becomes a thin translator, not a classifier — and routing is sequential, not parallel fan-out

Today it runs its own keyword scan of the question text. It stops doing that. It instead reads `state["sources"]` (set by `_domain_guard_node`), with the same defensive drop of `rag` when no complaint retriever is configured.

**Revised from the original draft of this section** (see "Verified technical risk" below for why): the two branches are **not** run as true parallel fan-out converging on a shared join. RAG runs first as a sequential prefix step when needed — whether RAG-only or hybrid — and its own conditional edge either chains into the SQL branch (hybrid) or goes straight to the merge step (RAG-only). This means a hybrid request's total latency is RAG-latency-plus-SQL-latency rather than the max of the two; given RAG is one embedding call plus one Qdrant search versus the SQL branch's multi-LLM-call chain, this should be a small fraction of total latency, but it is a real, deliberate trade-off, not free.

```python
def _document_router_node(self, state):
    sources = set(state.get("sources", ("sql",)))
    if "rag" in sources and self._complaint_retriever is None:
        sources.discard("rag")   # never schedule a branch that can't run
    return {"active_sources": tuple(sorted(sources)) or ("sql",)}

def _after_document_router(self, state):
    return ["complaint_retrieval"] if "rag" in state["active_sources"] else ["planner"]

def _after_complaint_retrieval_routing(self, state):
    return "planner" if "sql" in state["active_sources"] else "merge_results"
```

`_after_document_router` replaces today's binary `_after_document_router`. `_after_complaint_retrieval_routing` is a **new** conditional-edge function (registered on the `complaint_retrieval` node, not a graph node itself) deciding what runs after RAG completes.

If `sources` says `rag` is needed but no complaint retriever is configured (Qdrant not set up in this environment), that branch is dropped at the router rather than scheduled to fail — the request degrades to SQL-only rather than showing a broken RAG section.

### 3. Per-branch state keys replace the shared `answer`/`route`

Verified empirically (see "Verified technical risk" below): the two existing shared keys, `answer` and `route`, are each written by both branches. If both branches run in the same request, that's a genuine collision — LangGraph raises `InvalidUpdateError` for concurrent writes to a plain (non-reducer) key in the same superstep, and would otherwise silently let whichever branch finishes later overwrite the other's contribution.

Fix: each branch writes to its own keys instead of the shared ones.

- Every SQL-branch node from `_sql_policy_node` onward — `_sql_policy_node`, `_executor_node`, `_reviewer_node`, and `_analyst_node` — writes `sql_route` and, where it currently sets a message (repair-exhausted clarify, budget-exceeded clarify, grounding-rejected clarify, or the analyst's grounded success answer), `sql_answer`. None of them write the shared `route`/`answer` keys anymore. (`route` *before* the policy check — hard_guard, domain_guard — is unaffected; that part of the graph is still single-writer/sequential and unrelated to this collision.)
- `_complaint_retrieval_node` writes `rag_message` and `rag_route` (was `answer`/`route`).
- `citations`, `documents`, `sql`, `columns`, `rows`, `chart`, `analysis` are untouched — each is written by only one branch today, so there's no collision there.

This makes `sql_answer`/`sql_route` the single, consistent source for "whatever the SQL branch produced, success or failure" — the merge node never has to know which specific SQL node produced the message.

### 4. New `merge_results` node

Sits after whichever branch(es) actually ran, before `suggestions`. Because routing is now sequential (§2) rather than true parallel fan-out, `merge_results` always has exactly one real incoming edge per request — never two racing to the same target — so there is no join-cardinality problem to solve. Graph edges: `reviewer -> merge_results` (unconditional, unchanged shape from today's `reviewer -> suggestions`), `complaint_retrieval -> merge_results` (only taken when RAG-only, via `_after_complaint_retrieval_routing`), `merge_results -> suggestions`. It is plain Python, no LLM call. This is the actual shipped code (`app/agents/text_to_sql/workflow.py`'s `_merge_results_node`); it differs from the version originally drafted here in two ways, both made during Task 2's review fix round: a crash guard on a missing/falsy `sql_answer` (the original unconditionally indexed `state["sql_answer"]`, which crashed on SQL repair-exhaustion), and the `"Consumer complaint narratives found:"` prefix now only applies when the SQL branch also ran, so a RAG-only answer isn't incorrectly prefixed:

```python
def _merge_results_node(self, state: AgentState) -> dict[str, Any]:
    sql_route = state.get("sql_route")
    rag_route = state.get("rag_route")
    parts = []
    if sql_route is not None:
        sql_answer = state.get("sql_answer")
        if sql_answer:
            parts.append(sql_answer)
    if rag_route is not None:
        rag_message = state["rag_message"]
        parts.append(f"Consumer complaint narratives found: {rag_message}" if sql_route is not None else rag_message)
    route = "answered" if "answered" in (sql_route, rag_route) else (sql_route or rag_route)
    return {"answer": "\n\n".join(parts), "route": route}
```

**Combined-answer template** (confirmed with the user — no "related" wording, since nothing establishes a relationship):

```
{sql_answer}

Consumer complaint narratives found: {rag_message}
```

When only one branch ran, the output is exactly that branch's own answer — unchanged from today's behavior for SQL-only and RAG-only requests.

**"Show whatever succeeded" (confirmed with the user):** overall `route` is `"answered"` if *either* branch reached `answered`. Each section reflects its own branch's real outcome — if the SQL branch couldn't produce a grounded answer (repairs exhausted, or the reviewer rejected grounding), that section says so plainly while a successful RAG section still shows its citations alongside it. Since `_complaint_retrieval_node` is effectively always `"answered"` once scheduled (whether or not it finds matching narratives — "not configured" is now filtered out at the router, per §2), the only realistic partial-failure case in practice is: hybrid request, SQL fails, RAG succeeds → overall route `"answered"`, SQL section shows its own clarification text, RAG section shows its results.

### 5. Safety invariant — preserved, not loosened

The existing test `test_complaint_request_routes_to_retrieval_without_sql_execution` (asserts the SQL runner is never called on a complaint-*only*-classified request) is unchanged and must keep passing exactly as written. Hybrid adds a third classification where *both* are deliberately invoked — it does not weaken the guarantee that a complaint-only request never touches SQL.

### 6. Budgets

Unchanged per branch: SQL still gets at most 2 repairs and 1 execution; RAG still caps at 5 Qdrant hits, re-ranked down to 3. Hybrid mode doesn't relax either budget — it just means both bounded branches can be invoked for the same request instead of at most one.

## Verified technical risk

Before committing to this design, three throwaway spikes (not part of the app) were run against the exact installed `langgraph==1.2.11` (per `requirements.txt`):

1. **First spike** (equal-length branches, one step each): a conditional edge fanning out to one-or-two single-step nodes, joined by plain `add_edge` calls to a shared downstream node, correctly fired the join exactly once in all three cases (both/either-only) — no deadlock, no double-fire. This also independently reproduced the `answer`/`route` collision (`InvalidUpdateError` on a shared non-reducer key written by two nodes in the same superstep) when a test field wasn't given per-branch keys, confirming §3's key-split is a real, necessary fix.
2. **Second spike** (topology matching the real graph shape: a 1-step RAG branch and an 8-step SQL branch, both fanned out from the router): with plain `add_edge` calls into a shared `merge_results`, **the join fired twice** — once prematurely right after the fast RAG branch alone completed, again after the slow SQL branch finished — because each plain edge triggers independently rather than waiting for siblings. This silently double-invoked `suggestions` (a real specialist/LLM call) on every hybrid request, based on incomplete state the first time.
3. Switching to the bundled list-form join (`add_edge(["reviewer", "complaint_retrieval"], "merge_results")` — the same pattern already used for `schema_link`+`metric_resolver`) fixed the double-fire but **deadlocked** SQL-only and RAG-only requests instead: the bundled form unconditionally requires every listed predecessor, so when only one branch is actually scheduled, the join waits forever for a predecessor that never runs, and neither `merge_results` nor anything after it ever executes.
4. **Third spike, adopted**: restructuring routing to be sequential rather than parallel fan-out (§2 — RAG runs first when needed, chains into the SQL branch or straight to `merge_results`) means `merge_results` only ever has one real predecessor firing per request. Verified exactly one `merge_results` and one `suggestions` firing, with the correct node sequence, for all three cases (`sql`-only, `rag`-only, `sql`+`rag`).

This directly overturns the original draft of this section, which assumed true parallel fan-out with a dual-predecessor join would work — it doesn't, for branches of unequal length, under either edge form LangGraph offers for this. The sequential design is the one carried into the implementation plan.

## Testing and eval impact

- Existing isolation test stays as-is (§5).
- New unit test: a hybrid-classified request asserts both the SQL runner *and* the complaint retriever are each called exactly once, and that `route == "answered"` with both a SQL-shaped and a RAG-shaped fragment in `answer`.
- New unit tests for each partial-failure combination: SQL fails/RAG succeeds → overall `answered`, SQL section shows its own failure text, RAG section shows citations; (RAG realistically can't fail once scheduled, so the reverse case reduces to today's existing SQL-only-fails behavior, unaffected by this change).
- New `graph_paths`-style eval case(s) for the hybrid specialist path (`sql` and `rag` both present in `specialist_path`).
- New `domain_guard.json` case(s) exercising `sources` classification itself (SQL-only, RAG-only, hybrid).

## Acceptance criteria

- A question needing only SQL or only complaints behaves identically to today (same routes, same response shape) — this is a strict regression check, not just a new-feature check.
- A question needing both produces one response with `route: "answered"` (when either branch succeeds), a combined `answer` with no language implying the two datasets are related, and citations sourced only from the RAG branch.
- The existing complaint-only SQL-isolation test passes unchanged.
- `sources` requesting `rag` when no complaint retriever is configured degrades to SQL-only rather than exposing a broken branch.
- Full unit suite and the deterministic eval gate both pass; no live OpenAI/MotherDuck/Qdrant call required for tests.
