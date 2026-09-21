import unittest

from ingestion.complaints.qdrant_store import ComplaintQdrantStore


class FakeClient:
    def __init__(self):
        self.created = None
        self.points = []
        self.search_call = None

    def collection_exists(self, name):
        return False

    def create_collection(self, **kwargs):
        self.created = kwargs

    def upsert(self, **kwargs):
        self.points.extend(kwargs["points"])

    def query_points(self, **kwargs):
        self.search_call = kwargs
        return type("Response", (), {"points": [
            type("Point", (), {"payload": {"text": "safe", "source_hash": "source-a", "zipcode": "10001"}})()
        ]})()


class TimeoutClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.upsert_calls = 0

    def upsert(self, **kwargs):
        self.upsert_calls += 1
        if self.upsert_calls == 1:
            raise TimeoutError("simulated write timeout")
        super().upsert(**kwargs)


class QdrantStoreTests(unittest.TestCase):
    def test_store_creates_collection_and_upserts_safe_payload(self):
        client = FakeClient()
        store = ComplaintQdrantStore(client, "complaints_v1", vector_size=3)
        store.ensure_collection()
        store.upsert([("source-a", [0.1, 0.2, 0.3], {"product": "Mortgage", "source_hash": "source-a"})])
        self.assertEqual(client.created["collection_name"], "complaints_v1")
        self.assertEqual(len(client.points), 1)

    def test_store_retries_an_idempotent_timeout_once(self):
        client = TimeoutClient()
        store = ComplaintQdrantStore(client, "complaints_v1", vector_size=3)

        store.upsert([("source-a", [0.1, 0.2, 0.3], {"product": "Mortgage"})])

        self.assertEqual(client.upsert_calls, 2)
        self.assertEqual(len(client.points), 1)

    def test_store_validates_vectors_and_queries_with_capped_limit(self):
        client = FakeClient()
        store = ComplaintQdrantStore(client, "complaints_v1", vector_size=3)

        with self.assertRaisesRegex(ValueError, "length 3"):
            store.search([0.1, 0.2], top_k=1)
        with self.assertRaisesRegex(ValueError, "top_k"):
            store.search([0.1, 0.2, 0.3], top_k=0)

        result = store.search([0.1, 0.2, 0.3], top_k=42)

        self.assertEqual(client.search_call["collection_name"], "complaints_v1")
        self.assertEqual(client.search_call["limit"], 5)
        self.assertIsNotNone(client.search_call["query_filter"])
        self.assertEqual(result[0]["payload"]["source_hash"], "source-a")


if __name__ == "__main__":
    unittest.main()
