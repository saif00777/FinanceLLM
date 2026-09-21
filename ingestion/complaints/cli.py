"""Command-line entry point for resumable consented consumer-complaints RAG ingestion."""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv

from app.helpers.config import AppConfig
from ingestion.complaints.documents import ComplaintDocument, build_document
from ingestion.complaints.pipeline import ComplaintRagPipeline, OpenAIEmbedder
from ingestion.complaints.qdrant_store import ComplaintQdrantStore

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "consumerComplaints" / "consumer_complaints.csv"
DEFAULT_CHECKPOINT = ROOT / ".complaints-rag-checkpoint.json"


def source_fingerprint(source: Path) -> str:
    with source.open("rb") as handle:
        return sha256(handle.read()).hexdigest()


def load_checkpoint(path: Path, fingerprint: str) -> int:
    if not path.is_file():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("source_sha256") != fingerprint:
        raise ValueError("Checkpoint belongs to a different complaints source; use --restart.")
    completed = data.get("completed_documents", 0)
    if not isinstance(completed, int) or completed < 0:
        raise ValueError("Checkpoint has an invalid completed document count.")
    return completed


def write_checkpoint(path: Path, fingerprint: str, completed: int) -> None:
    path.write_text(json.dumps({"source_sha256": fingerprint, "completed_documents": completed}) + "\n", encoding="utf-8")


def documents(source: Path, limit: int | None = None, skip: int = 0) -> Iterator[ComplaintDocument]:
    """Yield only consented, redacted documents after a prior completed count."""
    selected, eligible = 0, 0
    with source.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            document = build_document(row)
            if document is None:
                continue
            eligible += 1
            if eligible <= skip:
                continue
            yield document
            selected += 1
            if limit is not None and selected >= limit:
                return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--upload", action="store_true", help="embed and upsert instead of performing a local dry run")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--restart", action="store_true", help="ignore and replace the existing checkpoint")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env", override=True)
    if not args.upload:
        print({"prepared_documents": sum(1 for _ in documents(args.source, args.limit)), "mode": "dry_run"})
        return 0

    config = AppConfig.from_environment()
    if not config.qdrant_enabled or not config.openai_embedding_model:
        raise SystemExit("Qdrant settings and OPEN_AI_EMBEDDING_MODEL are required.")
    fingerprint = source_fingerprint(args.source)
    skip = 0 if args.restart else load_checkpoint(args.checkpoint, fingerprint)

    from openai import OpenAI
    from qdrant_client import QdrantClient

    pipeline = ComplaintRagPipeline(
        OpenAIEmbedder(OpenAI(api_key=config.openai_api_key), config.openai_embedding_model),
        ComplaintQdrantStore(QdrantClient(url=config.qdrant_api_url, api_key=config.qdrant_api_key)),
    )

    def checkpoint(uploaded: int) -> None:
        write_checkpoint(args.checkpoint, fingerprint, skip + uploaded)

    uploaded = pipeline.ingest_documents(documents(args.source, args.limit, skip), on_batch=checkpoint)
    print({"uploaded_documents": uploaded, "completed_documents": skip + uploaded, "collection": "complaints_v1"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())