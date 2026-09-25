from datetime import datetime, timedelta, timezone
import unittest

from app.helpers.conversation import (
    ConversationFacts,
    ConversationTurn,
    InMemoryConversationStore,
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

    def test_store_drops_a_raw_rows_filter_instead_of_persisting_it(self):
        context = self.store.load(None)
        facts = ConversationFacts(resolved_filters={"rows": [["secret"]], "year": 2019})

        updated = self.store.update_facts(context, facts)

        self.assertNotIn("rows", updated.facts.resolved_filters)
        self.assertEqual(updated.facts.resolved_filters["year"], 2019)

    def test_store_drops_a_forbidden_filter_key_even_with_an_otherwise_safe_scalar_value(self):
        # Regression: plan() only type-checks resolved_filters *values*, never key names, so a
        # question that happens to make the model name a filter "content" (a legitimate short
        # string, not a data dump) must not crash the whole request at the persistence step —
        # the answer was already successfully computed by this point.
        context = self.store.load(None)
        facts = ConversationFacts(resolved_filters={"content": "checking accounts", "year": 2019})

        updated = self.store.update_facts(context, facts)

        self.assertNotIn("content", updated.facts.resolved_filters)
        self.assertEqual(updated.facts.resolved_filters["year"], 2019)



if __name__ == "__main__":
    unittest.main()
