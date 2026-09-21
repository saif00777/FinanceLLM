"""Safe, local construction of consented complaint retrieval documents."""

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Mapping

_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"\b(?:\+?1[-. ]?)?(?:\(?\d{3}\)?[-. ]?)\d{3}[-. ]\d{4}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_LONG_NUMBER = re.compile(r"\b\d{9,19}\b")

@dataclass(frozen=True)
class ComplaintDocument:
    source_hash: str
    text: str
    payload: dict[str, object]

def redact_text(value: str) -> str:
    text = _EMAIL.sub("[REDACTED_EMAIL]", value)
    text = _PHONE.sub("[REDACTED_PHONE]", text)
    text = _SSN.sub("[REDACTED_SSN]", text)
    return _LONG_NUMBER.sub("[REDACTED_NUMBER]", text)

def build_document(row: Mapping[str, str]) -> ComplaintDocument | None:
    if (row.get("consumer_consent_provided") or "").strip().lower() != "consent provided":
        return None
    narrative = (row.get("consumer_complaint_narrative") or "").strip()
    if not narrative:
        return None
    source_hash = sha256((row.get("complaint_id") or "").encode()).hexdigest()
    received = (row.get("date_received") or "")
    year = int(received.rsplit("/", 1)[-1]) if re.fullmatch(r"\d{2}/\d{2}/\d{4}", received) else None
    payload = {"source_hash": source_hash, "product": (row.get("product") or "").strip(), "sub_product": (row.get("sub_product") or "").strip(), "issue": (row.get("issue") or "").strip(), "company": (row.get("company") or "").strip(), "state": (row.get("state") or "").strip(), "received_year": year}
    return ComplaintDocument(source_hash=source_hash, text=redact_text(narrative), payload=payload)