"""Command-line driver for the document corpus. Dry run by default; --upload embeds and upserts to Qdrant.

  python -m ingestion.documents.cli                 # load + validate only, no network
  python -m ingestion.documents.cli --upload        # embed and upsert (needs OPEN_AI_KEY, QDRANT_*, OPEN_AI_EMBEDDING_MODEL)
  python -m ingestion.documents.cli --evaluate      # retrieval recall against rag_eval_questions.jsonl (needs the same)
"""

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS_DIR = ROOT / "larkspur_ridge_bank_corpus"
VECTOR_SIZE = 1536

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingestion.documents.corpus import load_corpus
from ingestion.documents.pipeline import ingest_documents
from ingestion.documents.store import DEFAULT_COLLECTION, DocumentQdrantStore


def _build_clients(root: Path) -> tuple[Any, DocumentQdrantStore, str]:
    from dotenv import load_dotenv
    from openai import OpenAI
    from qdrant_client import QdrantClient

    from app.helpers.config import AppConfig
    from app.helpers.embedder import OpenAIEmbedder

    load_dotenv(root / ".env")
    config = AppConfig.from_environment()
    if not config.qdrant_enabled or not config.openai_embedding_model:
        raise SystemExit("QDRANT_API_URL/QDRANT_API_KEY and OPEN_AI_EMBEDDING_MODEL must be configured.")
    embedder = OpenAIEmbedder(OpenAI(api_key=config.require_openai_api_key()), config.openai_embedding_model)
    store = DocumentQdrantStore(
        QdrantClient(url=config.qdrant_api_url, api_key=config.qdrant_api_key), DEFAULT_COLLECTION, VECTOR_SIZE,
    )
    return embedder, store, config.openai_embedding_model


def evaluate_recall(questions_path: Path, embedder: Any, store: Any, top_k: int) -> dict[str, float]:
    """Fraction of answerable questions whose source documents were all / partly retrieved in the top_k."""
    from app.agents.document_retrieval import DocumentRetriever

    retriever = DocumentRetriever(embedder, store, top_k=top_k)
    answerable = complete = 0
    hits = expected_total = 0
    for line in questions_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        expected = set(case.get("source_doc_ids") or [])
        if not expected:
            continue  # unanswerable questions have no source documents to recall
        retrieved = {document.citation for document in retriever.retrieve(case["question"])}
        found = expected & retrieved
        answerable += 1
        expected_total += len(expected)
        hits += len(found)
        complete += found == expected
        if found != expected:
            print(f"  miss {case['qid']} ({case['type']}): expected {sorted(expected)}, missing {sorted(expected - retrieved)}")
    return {"questions": answerable, "all_sources_found": complete / answerable, "source_recall": hits / expected_total}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--upload", action="store_true", help="embed and upsert to Qdrant")
    parser.add_argument("--evaluate", action="store_true", help="measure retrieval recall on the corpus's eval questions")
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args(argv)

    documents = load_corpus(args.corpus_dir)
    words = sum(len(str(d.payload["text"]).split()) for d in documents)
    print(f"Loaded {len(documents)} documents ({words} words) from {args.corpus_dir}.")

    if args.upload:
        embedder, store, model = _build_clients(ROOT)
        total = ingest_documents(documents, embedder, store, on_batch=lambda n: print(f"  upserted {n}/{len(documents)}"))
        print(f"Uploaded {total} documents to collection '{DEFAULT_COLLECTION}' with {model}.")
    if args.evaluate:
        embedder, store, _ = _build_clients(ROOT)
        result = evaluate_recall(args.corpus_dir / "rag_eval_questions.jsonl", embedder, store, args.top_k)
        print(f"Retrieval@{args.top_k} over {result['questions']} answerable questions: "
              f"all sources found {result['all_sources_found']:.0%}, source recall {result['source_recall']:.0%}.")
    if not (args.upload or args.evaluate):
        print("Dry run: nothing was embedded or uploaded. Pass --upload to ingest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
