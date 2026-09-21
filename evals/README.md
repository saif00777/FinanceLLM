# Public deterministic evaluation baseline

These fixtures are release-gate inputs for the student demo. They are public, redacted, versioned by `semantic_version` and `graph_version`, and contain no credentials, raw SQL, raw database rows, or complaint narratives.

The baseline has 18 representative cases:

| Fixture | Cases | Coverage |
| --- | ---: | --- |
| `graph_paths.json` | 4 | Route, execution/repair budgets, specialist sequence, suggestions, and result digest |
| `domain_guard.json` | 3 | In-scope, sensitive, and unclear requests |
| `suggested_questions.json` | 2 | Approved semantic follow-ups and safe blocked-route suggestions |
| `adversarial_safety.json` | 3 | DDL, credential, and file-access prompts |
| `multi_turn.json` | 2 | Follow-up conversation IDs and result digests |
| `grounding.json` | 2 | Result-digest and grounded metric/chart payloads |
| `rag_safety.json` | 2 | Public RAG citation metadata and prohibited metadata keys |

Run the offline gate with:

```powershell
.\.venv\Scripts\python.exe scripts\run_evals.py
```

The evaluator expects a workflow result to expose `route`, `sql`, `executions`, `repairs`, `suggested_questions`, `result_digest`, `grounding`, and `citations`. `specialist_path` is checked only for cases that declare an expected path. Missing `executions` is conservatively inferred as one when SQL is present; missing path data fails a path case.

This is a compact contract baseline, not a measured quality benchmark. It is intentionally smaller than the planned 30/30/25/20/25/15/20/20 corpus. Expand it with held-out, reviewed cases and run the staging integration tier before making accuracy or production-quality claims.
