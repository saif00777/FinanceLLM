"""Deterministic input guards that run before model specialists."""

from dataclasses import dataclass
import re
from typing import Literal


@dataclass(frozen=True)
class GuardVerdict:
    route: Literal["allow", "clarify", "abstain"]
    reason_code: str


class HardGuard:
    """Reject requests that cannot safely enter the agent graph."""

    _rules = (
        ("credential_request", r"\b(token|api[ _-]?key|password|secret|credential)\b"),
        ("private_source_request", r"\bsource\s*\.\s*\w+\b"),
        ("file_or_url_request", r"\b(read|scan|open|fetch|download)\b.*\b(file|csv|parquet|json|https?://)"),
        ("instruction_injection", r"\b(ignore|bypass|override)\b.*\b(policy|instructions|guard|rules)\b"),
        ("raw_pii_request", r"\b(card number|cvv|pin|home address|precise location)\b"),
    )

    def evaluate(self, question: str) -> GuardVerdict:
        normalized = question.strip().lower() if isinstance(question, str) else ""
        if not normalized:
            return GuardVerdict("clarify", "blank_question")
        for reason_code, pattern in self._rules:
            if re.search(pattern, normalized):
                return GuardVerdict("abstain", reason_code)
        return GuardVerdict("allow", "allowed")