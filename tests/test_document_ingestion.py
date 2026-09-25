import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.agents.document_retrieval import DocumentRetriever
from app.agents.rag import RetrievedDocument
from ingestion.documents.corpus import CorpusDocument, load_corpus
from ingestion.documents.pipeline import ingest_documents
from ingestion.documents.store import DocumentQdrantStore

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_FIELDS = ["doc_id", "category", "doc_type", "format", "title", "date", "path", "word_count", "entities", "summary"]


def _write_corpus(directory: Path, docs: list[dict], manifest_ids: list[str] | None = None) -> None:
    with (directory / "corpus_plaintext.jsonl").open("w", encoding="utf-8") as stream:
        for doc in docs:
            stream.write(json.dumps({"doc_id": doc["doc_id"], "title": doc["title"], "category": doc["category"],
                                     "doc_type": doc["doc_type"], "date": doc["date"], "source_file": doc["path"],
                                     "text": doc["text"]}) + "\n")
    with (directory / "manifest.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for doc in docs:
            if manifest_ids is None or doc["doc_id"] in manifest_ids:
                row = {field: "" for field in MANIFEST_FIELDS}
                row.update({key: value for key, value in doc.items() if key in MANIFEST_FIELDS})
                row.update({"format": "txt", "word_count": 3})
                writer.writerow(row)


DOC = {"doc_id": "FS-01", "title": "Balance Sheet", "category": "Financial Statements & Reporting", "doc_type": "Balance Sheet",
       "date": "2026-02-27", "path": "01/FS-01.pdf", "entities": "Larkspur Ridge Financial Corp.; Daniel Okafor",
       "summary": "FY2025 balance sheet.", "text": "Total assets were $19.2B."}


class LoadCorpusTests(unittest.TestCase):
    def test_joins_the_full_text_with_the_manifest_metadata(self):
        with TemporaryDirectory() as directory:
            _write_corpus(Path(directory), [DOC])
            (document,) = load_corpus(Path(directory))
        self.assertEqual(document.doc_id, "FS-01")
        self.assertEqual(document.payload["summary"], "FY2025 balance sheet.")
        self.assertEqual(document.payload["entities"], ["Larkspur Ridge Financial Corp.", "Daniel Okafor"])
        self.assertEqual(document.payload["category"], "Financial Statements & Reporting")
        self.assertEqual(document.payload["text"], "Total assets were $19.2B.")

    def test_embedding_text_carries_the_title_so_titles_help_retrieval(self):
        with TemporaryDirectory() as directory:
            _write_corpus(Path(directory), [DOC])
            (document,) = load_corpus(Path(directory))
        self.assertIn("Balance Sheet", document.embedding_text)
        self.assertIn("Total assets were $19.2B.", document.embedding_text)

    def test_a_document_missing_from_the_manifest_is_an_error(self):
        with TemporaryDirectory() as directory:
            _write_corpus(Path(directory), [DOC], manifest_ids=[])
            with self.assertRaisesRegex(ValueError, "FS-01"):
                load_corpus(Path(directory))

    def test_duplicate_doc_ids_are_an_error(self):
        with TemporaryDirectory() as directory:
            _write_corpus(Path(directory), [DOC, DOC])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_corpus(Path(directory))

    def test_the_real_larkspur_corpus_loads_completely(self):
        documents = load_corpus(ROOT / "larkspur_ridge_bank_corpus")
        self.assertEqual(len(documents), 50)
        self.assertEqual(len({d.doc_id for d in documents}), 50)
        self.assertTrue(all(d.payload["text"].strip() and d.payload["title"] for d in documents))


class FakeClient:
    def __init__(self, exists=False, failures=0):
        self.exists, self.failures, self.created, self.upserts, self.queries = exists, failures, [], [], []

    def collection_exists(self, name):
        return self.exists

    def create_collection(self, **kwargs):
        self.created.append(kwargs)

    def upsert(self, collection_name, points):
        if self.failures:
            self.failures -= 1
            raise TimeoutError("write timed out")
        self.upserts.append((collection_name, points))

    def query_points(self, **kwargs):
        self.queries.append(kwargs)
        point = type("P", (), {"payload": {"doc_id": "FS-01", "title": "Balance Sheet", "text": "Total assets."}})()
        return type("R", (), {"points": [point]})()


class StoreTests(unittest.TestCase):
    def test_creates_the_collection_only_when_missing(self):
        client = FakeClient(exists=False)
        DocumentQdrantStore(client, vector_size=3).ensure_collection()
        self.assertEqual(len(client.created), 1)
        client = FakeClient(exists=True)
        DocumentQdrantStore(client, vector_size=3).ensure_collection()
        self.assertEqual(client.created, [])

    def test_upsert_uses_a_deterministic_point_id_per_doc(self):
        first, second = FakeClient(), FakeClient()
        for client in (first, second):
            DocumentQdrantStore(client, vector_size=2).upsert([("FS-01", [0.1, 0.2], {"doc_id": "FS-01", "text": "t"})])
        self.assertEqual(first.upserts[0][1][0].id, second.upserts[0][1][0].id)
        self.assertEqual(first.upserts[0][1][0].payload["doc_id"], "FS-01")

    def test_rejects_a_vector_of_the_wrong_size(self):
        with self.assertRaises(ValueError):
            DocumentQdrantStore(FakeClient(), vector_size=3).upsert([("FS-01", [0.1], {})])

    def test_retries_a_transient_write_failure_once(self):
        client = FakeClient(failures=1)
        DocumentQdrantStore(client, vector_size=1).upsert([("FS-01", [0.1], {})])
        self.assertEqual(len(client.upserts), 1)

    def test_a_second_write_failure_is_raised(self):
        with self.assertRaises(TimeoutError):
            DocumentQdrantStore(FakeClient(failures=2), vector_size=1).upsert([("FS-01", [0.1], {})])

    def test_search_returns_payloads_and_caps_top_k(self):
        client = FakeClient()
        hits = DocumentQdrantStore(client, vector_size=1).search([0.1], top_k=50)
        self.assertEqual(hits[0]["doc_id"], "FS-01")
        self.assertLessEqual(client.queries[0]["limit"], 10)


class FakeEmbedder:
    def __init__(self):
        self.batches = []

    def embed(self, texts):
        self.batches.append(list(texts))
        return [[float(len(t))] for t in texts]


class FakeStore:
    def __init__(self):
        self.ensured, self.records = 0, []

    def ensure_collection(self):
        self.ensured += 1

    def upsert(self, records):
        self.records.extend(records)


class PipelineTests(unittest.TestCase):
    @staticmethod
    def _docs(count):
        return [CorpusDocument(f"D-{i}", f"text {i}", {"doc_id": f"D-{i}", "text": f"text {i}"}) for i in range(count)]

    def test_embeds_in_batches_and_upserts_every_document(self):
        embedder, store, progress = FakeEmbedder(), FakeStore(), []
        total = ingest_documents(self._docs(5), embedder, store, batch_size=2, on_batch=progress.append)
        self.assertEqual(total, 5)
        self.assertEqual([len(b) for b in embedder.batches], [2, 2, 1])
        self.assertEqual([r[0] for r in store.records], [f"D-{i}" for i in range(5)])
        self.assertEqual(store.ensured, 1)
        self.assertEqual(progress, [2, 4, 5])


class RetrieverTests(unittest.TestCase):
    class Store:
        def search(self, vector, top_k=5):
            return [{"doc_id": "FS-01", "title": "Balance Sheet", "category": "Financial Statements & Reporting",
                     "doc_type": "Balance Sheet", "date": "2026-02-27", "summary": "s", "text": "Total assets.", "secret": "x"}]

    def test_returns_documents_cited_by_doc_id_without_unlisted_fields(self):
        (doc,) = DocumentRetriever(FakeEmbedder(), self.Store()).retrieve("assets?")
        self.assertIsInstance(doc, RetrievedDocument)
        self.assertEqual(doc.citation, "FS-01")
        self.assertEqual(doc.text, "Total assets.")
        self.assertEqual(doc.payload["title"], "Balance Sheet")
        self.assertNotIn("secret", doc.payload)
        self.assertNotIn("text", doc.payload)

    def test_requires_exactly_one_query_vector(self):
        class Bad:
            def embed(self, texts):
                return []

        with self.assertRaises(ValueError):
            DocumentRetriever(Bad(), self.Store()).retrieve("q")


if __name__ == "__main__":
    unittest.main()
