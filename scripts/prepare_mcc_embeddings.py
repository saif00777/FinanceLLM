"""Offline: cache MCC-code description embeddings for cosine-similarity resolution.

Queries the live main.mcc_codes view (MotherDuck) and embeds each description once via
OPEN_AI_EMBEDDING_MODEL, caching the result to context/mcc_embeddings.json so the runtime
MccResolver never calls an embedding API for the reference catalog itself, only for the
incoming question. Re-run only when main.mcc_codes or OPEN_AI_EMBEDDING_MODEL changes.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from app.helpers.config import AppConfig
from app.helpers.embedder import OpenAIEmbedder
from ingestion.motherduck import connect_motherduck


def main() -> int:
    load_dotenv(ROOT / ".env")
    config = AppConfig.from_environment()
    if not config.openai_embedding_model:
        print("OPEN_AI_EMBEDDING_MODEL is not configured; nothing to cache.")
        return 1

    connection = connect_motherduck(config.motherduck_token)
    connection.execute("USE financial_transactions")
    rows = connection.execute("SELECT mcc, description FROM main.mcc_codes ORDER BY mcc").fetchall()
    if not rows:
        print("main.mcc_codes returned no rows.")
        return 1

    from openai import OpenAI

    embedder = OpenAIEmbedder(OpenAI(api_key=config.require_openai_api_key()), config.openai_embedding_model)
    descriptions = [description for _, description in rows]
    vectors = embedder.embed(descriptions)
    if len(vectors) != len(rows):
        print(f"Embedder returned {len(vectors)} vectors for {len(rows)} descriptions.")
        return 1

    payload = {
        "embedding_model": config.openai_embedding_model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries": [
            {"mcc": mcc, "description": description, "vector": vector}
            for (mcc, description), vector in zip(rows, vectors)
        ],
    }
    output_path = ROOT / "context" / "mcc_embeddings.json"
    output_path.write_text(json.dumps(payload), encoding="utf-8")
    print(f"Cached {len(payload['entries'])} MCC embeddings to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
