"""Stop hook: remind Claude to update PROGRESS.md when files changed since it was last touched.

Reads the Stop hook's JSON payload on stdin. If `stop_hook_active` is true, this is
already a continuation of a previously-blocked stop for the same turn, so it exits
immediately to avoid looping. Otherwise it walks the repository (skipping build/venv/
log noise) for files with a newer mtime than PROGRESS.md. If any exist, it prints a
`decision: block` response whose `reason` is fed back to Claude, asking it to update
PROGRESS.md's "Current state" and append a "Session log" entry, or to explain why this
turn does not need one and stop anyway.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROGRESS_FILE = os.path.join(ROOT, "PROGRESS.md")

EXCLUDE_DIRS = {
    ".git", ".venv", "__pycache__", ".claude", "node_modules",
    ".context-tools", ".motherduck-staging", "tmp",
}
EXCLUDE_FILES = {
    ".complaints-rag-checkpoint.json",
    ".complaints-rag-upload.log",
    ".complaints-rag-upload.error.log",
}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, TypeError):
        payload = {}

    if payload.get("stop_hook_active"):
        return 0

    if not os.path.isfile(PROGRESS_FILE):
        return 0

    progress_mtime = os.path.getmtime(PROGRESS_FILE)

    newer = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            if name == "PROGRESS.md" or name in EXCLUDE_FILES:
                continue
            path = os.path.join(dirpath, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime > progress_mtime:
                newer.append(os.path.relpath(path, ROOT).replace(os.sep, "/"))

    if not newer:
        return 0

    newer.sort()
    sample = ", ".join(newer[:8])
    if len(newer) > 8:
        sample += f", and {len(newer) - 8} more"

    reason = (
        "Files changed since PROGRESS.md was last updated ("
        f"{sample}). If this turn completed a task (code change, investigation "
        "finding, completed run, or decision), update PROGRESS.md now: refresh "
        "'Current state' in place and append a dated 'Session log' entry. If this "
        "turn was trivial (a question answered, no real change), it's fine to "
        "stop without updating."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
