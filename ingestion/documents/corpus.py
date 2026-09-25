"""Loads the Larkspur Ridge document corpus: full text (JSONL) joined with its manifest metadata (CSV)."""

import csv
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class CorpusDocument:
    doc_id: str
    embedding_text: str
    payload: dict[str, object]


def _entities(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def load_corpus(directory: Path) -> list[CorpusDocument]:
    """One document per doc_id. Documents are at most ~540 words, so each is embedded whole (no chunking),
    which keeps a whole letter, memo or statement retrievable as one unit."""
    with (directory / "manifest.csv").open(encoding="utf-8", newline="") as stream:
        manifest = {row["doc_id"]: row for row in csv.DictReader(stream)}

    documents: list[CorpusDocument] = []
    seen: set[str] = set()
    with (directory / "corpus_plaintext.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            record = json.loads(line)
            doc_id = record["doc_id"]
            if doc_id in seen:
                raise ValueError(f"duplicate doc_id in corpus: {doc_id}")
            seen.add(doc_id)
            row = manifest.get(doc_id)
            if row is None:
                raise ValueError(f"{doc_id} is in corpus_plaintext.jsonl but missing from manifest.csv")
            text = record["text"].strip()
            payload: dict[str, object] = {
                "doc_id": doc_id,
                "title": record["title"],
                "category": record["category"],
                "doc_type": record["doc_type"],
                "date": record["date"],
                "source_file": record["source_file"],
                "entities": _entities(row.get("entities", "")),
                "summary": row.get("summary", ""),
                "text": text,
            }
            documents.append(CorpusDocument(doc_id, f"{record['title']}\n\n{text}", payload))
    return documents
