import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


class FakeEmbedder:
    def __init__(self, vector):
        self._vector = vector
        self.calls = []

    def embed(self, texts):
        self.calls.append(texts)
        return [self._vector for _ in texts]


class MccResolverTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {"mcc": "4511", "description": "Airlines", "vector": [1.0, 0.0]},
            {"mcc": "7011", "description": "Hotels", "vector": [0.9, 0.1]},
            {"mcc": "5411", "description": "Grocery Stores", "vector": [0.0, 1.0]},
        ]

    def test_resolve_ranks_by_cosine_similarity_and_applies_threshold(self):
        from app.helpers.mcc_resolver import MccResolver

        resolver = MccResolver(FakeEmbedder([1.0, 0.0]), self.entries, top_k=5, threshold=0.5)
        matches = resolver.resolve("travel spending")

        self.assertEqual([match.mcc for match in matches], ["4511", "7011"])
        self.assertGreater(matches[0].score, matches[1].score)

    def test_resolve_limits_to_top_k(self):
        from app.helpers.mcc_resolver import MccResolver

        resolver = MccResolver(FakeEmbedder([1.0, 0.0]), self.entries, top_k=1, threshold=0.0)
        matches = resolver.resolve("travel spending")

        self.assertEqual([match.mcc for match in matches], ["4511"])

    def test_resolve_returns_empty_when_nothing_meets_the_threshold(self):
        from app.helpers.mcc_resolver import MccResolver

        resolver = MccResolver(FakeEmbedder([0.0, 1.0]), [self.entries[0]], top_k=5, threshold=0.5)
        self.assertEqual(resolver.resolve("groceries"), [])

    def test_resolve_embeds_the_question_exactly_once(self):
        from app.helpers.mcc_resolver import MccResolver

        embedder = FakeEmbedder([1.0, 0.0])
        MccResolver(embedder, self.entries, top_k=5, threshold=0.0).resolve("travel spending")
        self.assertEqual(embedder.calls, [["travel spending"]])

    def test_resolve_returns_empty_for_an_empty_catalog(self):
        from app.helpers.mcc_resolver import MccResolver

        resolver = MccResolver(FakeEmbedder([1.0, 0.0]), [], top_k=5, threshold=0.0)
        self.assertEqual(resolver.resolve("travel spending"), [])

    def test_rejects_invalid_top_k_and_threshold(self):
        from app.helpers.mcc_resolver import MccResolver

        with self.assertRaisesRegex(ValueError, "top_k"):
            MccResolver(FakeEmbedder([1.0, 0.0]), self.entries, top_k=0)
        with self.assertRaisesRegex(ValueError, "threshold"):
            MccResolver(FakeEmbedder([1.0, 0.0]), self.entries, threshold=1.5)

    def test_from_cache_file_loads_entries_from_disk(self):
        from app.helpers.mcc_resolver import MccResolver

        with TemporaryDirectory() as directory:
            path = Path(directory, "mcc_embeddings.json")
            path.write_text(json.dumps({"embedding_model": "test-model", "entries": self.entries}), encoding="utf-8")
            resolver = MccResolver.from_cache_file(FakeEmbedder([1.0, 0.0]), path, top_k=5, threshold=0.5)
            matches = resolver.resolve("travel spending")

        self.assertEqual([match.mcc for match in matches], ["4511", "7011"])


if __name__ == "__main__":
    unittest.main()
