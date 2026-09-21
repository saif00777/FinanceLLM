import unittest
from ingestion.complaints.documents import ComplaintDocument
from ingestion.complaints.pipeline import ComplaintRagPipeline

class FakeEmbedder:
    def embed(self, texts): return [[0.1, 0.2, 0.3] for _ in texts]
class FakeStore:
    def __init__(self): self.items=[]
    def ensure_collection(self): pass
    def upsert(self, items): self.items.extend(items)

class RagPipelineTests(unittest.TestCase):
    def test_default_batch_size_stays_within_qdrant_write_budget(self):
        self.assertEqual(ComplaintRagPipeline(FakeEmbedder(), FakeStore())._batch_size, 32)

    def test_pipeline_reports_progress_after_each_uploaded_batch(self):
        store=FakeStore()
        progress=[]
        pipeline=ComplaintRagPipeline(FakeEmbedder(), store, batch_size=2)
        docs=[ComplaintDocument(str(index), str(index), {"source_hash": str(index)}) for index in range(3)]
        pipeline.ingest_documents(docs, on_batch=progress.append)
        self.assertEqual(progress, [2, 3])

    def test_pipeline_batches_documents_for_embedding_and_upsert(self):
        store=FakeStore()
        pipeline=ComplaintRagPipeline(FakeEmbedder(), store, batch_size=2)
        docs=[ComplaintDocument('a', 'one', {'source_hash':'a'}), ComplaintDocument('b', 'two', {'source_hash':'b'})]
        count=pipeline.ingest_documents(docs)
        self.assertEqual(count, 2)
        self.assertEqual(len(store.items), 2)
        self.assertEqual(store.items[0][2]["text"], "one")
        self.assertEqual(store.items[0][2]["visibility"], "public")

if __name__ == '__main__': unittest.main()