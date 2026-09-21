from datetime import datetime, timedelta, timezone
import unittest

from app.helpers.conversation import (
    ConversationFacts,
    ConversationTurn,
    InMemoryConversationStore,
    SupabaseConversationStore,
)


class Clock:
    def __init__(self):
        self.current = datetime(2026, 9, 17, tzinfo=timezone.utc)

    def __call__(self):
        return self.current

    def advance(self, seconds):
        self.current += timedelta(seconds=seconds)


class ConversationStoreTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.store = InMemoryConversationStore(ttl_seconds=1800, clock=self.clock)

    def test_store_keeps_two_opaque_sessions_isolated(self):
        first = self.store.append(self.store.load(None), ConversationTurn.user("first"))
        second = self.store.append(self.store.load(None), ConversationTurn.user("second"))

        self.assertEqual(self.store.load(first.id).turns[-1].content, "first")
        self.assertEqual(self.store.load(second.id).turns[-1].content, "second")

    def test_store_redacts_sensitive_turn_content_before_persistence(self):
        context = self.store.append(
            self.store.load(None),
            ConversationTurn.user("Contact jane@example.com about account 123456789012."),
        )
        stored = self.store.load(context.id).turns[-1].content
        self.assertNotIn("jane@example.com", stored)
        self.assertNotIn("123456789012", stored)

    def test_expired_context_returns_an_empty_new_context(self):
        context = self.store.append(self.store.load(None), ConversationTurn.user("old"))
        self.clock.advance(1801)

        self.assertEqual(self.store.load(context.id).turns, ())

    def test_store_persists_only_structured_redacted_facts(self):
        context = self.store.load(None)
        facts = ConversationFacts(
            resolved_metric="Net signed recorded amount",
            resolved_filters={"year": 2019, "customer_note": "alice@example.com"},
            selected_relation_ids=("main.transactions",),
            last_sql_hash="a" * 64,
            result_digest="b" * 64,
            semantic_version="2.0.0",
        )

        updated = self.store.update_facts(context, facts)

        loaded = self.store.load(updated.id)
        self.assertEqual(loaded.facts.resolved_metric, "Net signed recorded amount")
        self.assertEqual(loaded.facts.resolved_filters["year"], 2019)
        self.assertEqual(loaded.facts.resolved_filters["customer_note"], "[redacted]")
        self.assertEqual(loaded.facts.last_sql_hash, "a" * 64)
        self.assertEqual(loaded.facts.result_digest, "b" * 64)
        self.assertEqual(loaded.facts.semantic_version, "2.0.0")

    def test_store_rejects_result_rows_as_facts(self):
        context = self.store.load(None)
        facts = ConversationFacts(resolved_filters={"rows": [["secret"]]})

        with self.assertRaises(ValueError):
            self.store.update_facts(context, facts)


class _Response:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, client, name):
        self.client = client
        self.name = name

    def select(self, *_columns):
        return self

    def eq(self, *_args):
        return self

    def order(self, *_args):
        return self

    def limit(self, *_args):
        return self

    def upsert(self, payload):
        self.client.writes.append((self.name, payload))
        return self

    def insert(self, payload):
        self.client.writes.append((self.name, payload))
        return self

    def execute(self):
        return _Response(self.client.reads.get(self.name, []))


class _SupabaseClient:
    def __init__(self, reads=None):
        self.reads = reads or {}
        self.writes = []

    def table(self, name):
        return _Table(self, name)


class SupabaseConversationStoreTests(unittest.TestCase):
    def test_loads_and_writes_structured_facts_without_raw_rows(self):
        expires_at = "2027-09-18T00:00:00+00:00"
        client = _SupabaseClient(
            {
                "conversations": [{"id": "session", "expires_at": expires_at, "semantic_version": "2.0.0"}],
                "messages": [],
                "conversation_facts": [{
                    "resolved_metric": "Recorded transaction count",
                    "filters": {"year": 2019},
                    "selected_relations": ["main.transactions"],
                    "last_sql_hash": "c" * 64,
                    "result_digest": "d" * 64,
                }],
            }
        )
        store = SupabaseConversationStore(client)

        loaded = store.load("session")
        updated = store.update_facts(loaded, loaded.facts)

        self.assertEqual(updated.facts.semantic_version, "2.0.0")
        fact_write = next(payload for table, payload in client.writes if table == "conversation_facts")
        self.assertEqual(fact_write["filters"], {"year": 2019})
        self.assertNotIn("rows", fact_write)
        self.assertNotIn("sql", fact_write)


if __name__ == "__main__":
    unittest.main()
