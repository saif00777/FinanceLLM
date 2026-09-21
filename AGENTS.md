## superpowers workflow

Before responding to substantial tasks, check for relevant Superpowers skills.
Use explicit `$skill-name` references when a specific workflow is needed.

Pipeline: `$brainstorming` -> `$writing-plans` -> `$using-git-worktrees` ->
`$subagent-driven-development` -> `$test-driven-development` ->
`$requesting-code-review` -> `$verification-before-completion` ->
`$finishing-a-development-branch`

Iron laws:
1. No production code without a failing test first.
2. No fixes without root cause investigation.
3. No completion claims without running verification fresh.

## Token-efficient execution

- Use the smallest workflow that fits the request. The full pipeline is for
  architectural work or substantive implementation, not routine documentation,
  configuration, status, or one-file maintenance changes.
- Do not repeat an inspection, test suite, database validation, review, or
  progress update unless a change or new evidence makes it necessary.
- Prefer one focused verification command over broad suites for a localized
  change; run the full suite only when the affected contract or behavior needs it.
- Keep commentary and final responses concise. Report decisions, material
  findings, changed files, and verification evidence; omit routine narration.
- Do not delegate or create review work solely for ceremony. Use an independent
  review when the change is substantial, security-sensitive, or difficult to
  validate locally.

