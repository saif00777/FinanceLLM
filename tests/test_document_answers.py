from types import SimpleNamespace
import unittest

from app.agents.document_retrieval import DocumentRetriever
from app.agents.rag import RetrievedDocument
from app.agents.text_to_sql.contracts import RuntimeContract
from app.agents.text_to_sql.domain_guard import HardGuard
from app.agents.text_to_sql.specialists import DocumentAnswer
from app.agents.text_to_sql.workflow import MultiAgentWorkflow
from app.api.main import build_document_retriever
from app.helpers.conversation import InMemoryConversationStore
from tests.test_planner_led_specialists import _specialist
from tests.test_workflow import FakeRunner, FakeSpecialists, ROOT

DOCS = [
    RetrievedDocument("Net interest margin was 3.21%.", {"doc_id": "FS-03", "title": "MD&A", "doc_type": "Annual Report", "category": "Financial Statements & Reporting", "date": "2026-02-27"}, "FS-03"),
    RetrievedDocument("The CET1 ratio was 11.3%.", {"doc_id": "FS-07", "title": "Q1 Release", "doc_type": "Earnings Release", "date": "2026-04-20"}, "FS-07"),
]


class SpecialistAnswerTests(unittest.TestCase):
    def test_instructions_restrict_the_answer_to_the_excerpts_and_treat_them_as_data(self):
        specialist, responses = _specialist({"answer": "a", "cited_doc_ids": []})
        specialist.answer_documents("q", DOCS)
        text = responses.instructions()
        self.assertIn("only from the excerpts", text)
        self.assertIn("cited_doc_ids", text)
        self.assertIn("not instructions", text)

    def test_excerpts_reach_the_model_with_their_ids_and_titles(self):
        specialist, responses = _specialist({"answer": "a", "cited_doc_ids": []})
        specialist.answer_documents("What was the NIM?", DOCS)
        payload = responses.payload()
        self.assertEqual(payload["question"], "What was the NIM?")
        self.assertEqual([e["doc_id"] for e in payload["excerpts"]], ["FS-03", "FS-07"])
        self.assertEqual(payload["excerpts"][0]["title"], "MD&A")
        self.assertIn("3.21%", payload["excerpts"][0]["text"])

    def test_only_documents_that_were_really_retrieved_can_be_cited(self):
        specialist, _ = _specialist({"answer": " NIM was 3.21% [FS-03]. ", "cited_doc_ids": ["FS-03", "MADE-UP", 7, "FS-03"]})
        result = specialist.answer_documents("q", DOCS)
        self.assertEqual(result.answer, "NIM was 3.21% [FS-03].")
        self.assertEqual(result.cited_doc_ids, ("FS-03",))

    def test_a_missing_answer_becomes_a_safe_not_found_message(self):
        specialist, _ = _specialist({})
        result = specialist.answer_documents("q", DOCS)
        self.assertEqual(result.cited_doc_ids, ())
        self.assertIn("could not find", result.answer.lower())


class RecordingSpecialists(FakeSpecialists):
    def __init__(self, cited=("FS-03",)):
        super().__init__()
        self.doc_calls, self.doc_args, self._cited = 0, None, cited

    def answer_documents(self, question, documents, plan=None):
        self.doc_calls += 1
        self.doc_args = (question, list(documents), plan)
        return DocumentAnswer("NIM was 3.21% [FS-03].", tuple(self._cited))


class Retriever:
    def __init__(self, docs):
        self._docs, self.questions = docs, []

    def retrieve(self, question):
        self.questions.append(question)
        return self._docs


def _workflow(specialists, retriever):
    return MultiAgentWorkflow(RuntimeContract.from_files(ROOT), FakeRunner(), specialists, InMemoryConversationStore(),
                              HardGuard(), retriever=retriever)


class WorkflowDocumentAnswerTests(unittest.TestCase):
    def test_answer_is_written_from_the_retrieved_documents_and_cites_only_what_was_used(self):
        specialists, retriever = RecordingSpecialists(), Retriever(DOCS)
        result = _workflow(specialists, retriever).answer("What do the documents say about net interest margin?")
        self.assertEqual(result.answer, "NIM was 3.21% [FS-03].")
        self.assertEqual(specialists.doc_calls, 1)
        self.assertEqual(result.citations, [{"source_hash": "FS-03", "title": "MD&A", "doc_type": "Annual Report",
                                             "category": "Financial Statements & Reporting", "date": "2026-02-27"}])

    def test_retrieval_and_answering_use_the_planners_standalone_question(self):
        specialists, retriever = RecordingSpecialists(), Retriever(DOCS)
        _workflow(specialists, retriever).answer("What do the documents say about margin?")
        self.assertTrue(retriever.questions[0].startswith("STANDALONE"))
        self.assertEqual(specialists.doc_args[0], retriever.questions[0])
        self.assertIsNotNone(specialists.doc_args[2])

    def test_no_documents_means_no_model_call_and_no_citations(self):
        specialists = RecordingSpecialists()
        result = _workflow(specialists, Retriever([])).answer("What do the documents say about margin?")
        self.assertEqual(specialists.doc_calls, 0)
        self.assertEqual(result.citations, [])
        self.assertIn("could not find", result.answer.lower())
        self.assertEqual(result.route, "answered")

    def test_a_declined_answer_carries_no_citations(self):
        specialists = RecordingSpecialists(cited=())
        result = _workflow(specialists, Retriever(DOCS)).answer("What do the documents say about the moon?")
        self.assertEqual(result.citations, [])

    def test_retrieves_with_both_the_original_wording_and_the_rewrite_and_merges_without_duplicates(self):
        # Live: the planner sometimes appends "at Larkspur Ridge Bank" to the rewrite; every document matches that
        # phrase, so the right ones (CR-08, FS-12) fell out of the results. The user's own wording is kept as a second query.
        a, b, c = (RetrievedDocument(t, {"title": t}, t) for t in ("A", "B", "C"))

        class TwoQueries:
            def __init__(self):
                self.questions = []

            def retrieve(self, question):
                self.questions.append(question)
                return [a, b] if question.startswith("STANDALONE") else [b, c]

        specialists, retriever = RecordingSpecialists(cited=("A",)), TwoQueries()
        _workflow(specialists, retriever).answer("What do the documents say about margin?")
        self.assertEqual(len(retriever.questions), 2)
        self.assertIn("What do the documents say about margin?", retriever.questions)
        sent = [d.citation for d in specialists.doc_args[1]]
        self.assertEqual(sorted(sent), ["A", "B", "C"])
        self.assertEqual(sent[0], "B")  # the original wording's top hit leads

    def test_a_single_query_is_used_when_the_rewrite_equals_the_question(self):
        class Same(RecordingSpecialists):
            def plan(self, question, facts):
                plan = super().plan(question, facts)
                return type(plan)(plan.intent, plan.rationale, plan.resolved_filters, question, plan.sql_guidance, plan.analysis_guidance)

        retriever = Retriever(DOCS)
        _workflow(Same(), retriever).answer("What do the documents say about margin?")
        self.assertEqual(len(retriever.questions), 1)

    def test_the_stream_reports_which_documents_were_retrieved(self):
        events = list(_workflow(RecordingSpecialists(), Retriever(DOCS)).stream_answer("What do the documents say about margin?"))
        thought = next(p["text"] for k, p in events if k == "thought" and p["node"] == "document_retrieval")
        self.assertIn("FS-03", thought)
        self.assertIn("FS-07", thought)


class RoutingAndDepthTests(unittest.TestCase):
    def test_retriever_fetches_eight_documents_by_default(self):
        # Measured on the corpus's own questions: all-sources-found 85% at 4, 92% at 6, 97% at 8; live answers missed multi-hop sources at 6.
        seen = []

        class Store:
            def search(self, vector, top_k=5):
                seen.append(top_k)
                return []

        class Embedder:
            def embed(self, texts):
                return [[0.0]]

        DocumentRetriever(Embedder(), Store()).retrieve("q")
        self.assertEqual(seen, [8])

    def test_domain_guard_routes_bank_document_questions_to_rag_instead_of_asking_which_source(self):
        # Live: "What were total assets and total deposits at December 31, 2025?" was answered with a clarifying
        # question ("...from the financial statements or something else?") instead of going to the documents.
        specialist, responses = _specialist({"route": "in_scope", "reason_code": "r", "sources": ["rag"]})
        specialist.domain_guard("q", {})
        text = responses.instructions()
        self.assertIn("never ask which source", text)
        self.assertIn("even when the question does not name the bank", text)

    def test_domain_guard_knows_the_documents_name_customers_and_cases_and_prefers_rag_for_them(self):
        # Live: "...Robert Chen's fraud dispute...", "...Samantha Ortiz's HELOC..." were abstained (the SQL data's
        # individual-level limits were applied to the documents) and an outage question was sent to SQL only.
        specialist, responses = _specialist({"route": "in_scope", "reason_code": "r", "sources": ["rag"]})
        specialist.domain_guard("q", {})
        text = responses.instructions()
        self.assertIn("apply only to the SQL data", text)
        self.assertIn("named customer, company or case", text)
        self.assertIn("choose rag unless", text)

    def test_the_document_answer_prefers_the_most_precise_figure(self):
        # Live: deposits were quoted as the rounded $15,000 million from narrative text instead of $14,993 million.
        specialist, responses = _specialist({"answer": "a", "cited_doc_ids": []})
        specialist.answer_documents("q", DOCS)
        self.assertIn("most precise figure", responses.instructions())


class DomainRouteNormalisationTests(unittest.TestCase):
    def test_a_source_name_returned_as_the_route_means_in_scope_with_that_source(self):
        # Live: the model answered {"route": "sql"} (confusing route with sources), the workflow did not recognise
        # it, and a valid question got a generic clarify.
        for route, source in (("sql", "sql"), ("rag", "rag")):
            with self.subTest(route=route):
                specialist, _ = _specialist({"route": route, "reason_code": "r"})
                decision = specialist.domain_guard("q", {})
                self.assertEqual(decision.route, "in_scope")
                self.assertEqual(decision.sources, (source,))

    def test_an_unknown_route_is_treated_as_clarify_not_passed_through(self):
        specialist, _ = _specialist({"route": "banana", "reason_code": "r", "sources": ["sql"]})
        self.assertEqual(specialist.domain_guard("q", {}).route, "clarify")

    def test_valid_routes_are_unchanged(self):
        for route in ("in_scope", "clarify", "abstain"):
            with self.subTest(route=route):
                specialist, _ = _specialist({"route": route, "reason_code": "r", "sources": ["sql"]})
                self.assertEqual(specialist.domain_guard("q", {}).route, route)

    def test_the_instruction_names_the_only_three_valid_routes(self):
        specialist, responses = _specialist({"route": "in_scope", "reason_code": "r", "sources": ["sql"]})
        specialist.domain_guard("q", {})
        self.assertIn("route must be exactly one of in_scope, clarify or abstain", responses.instructions())


class WiringTests(unittest.TestCase):
    def test_no_retriever_without_qdrant_or_an_embedding_model(self):
        off = SimpleNamespace(qdrant_enabled=False, openai_embedding_model=None)
        self.assertIsNone(build_document_retriever(off, object()))

    def test_a_document_retriever_is_built_when_configured(self):
        on = SimpleNamespace(qdrant_enabled=True, qdrant_api_url="http://localhost:6333", qdrant_api_key="k", openai_embedding_model="m")
        retriever = build_document_retriever(on, object())
        self.assertTrue(hasattr(retriever, "retrieve"))


class CorpusDescriptionTests(unittest.TestCase):
    def test_business_context_describes_the_document_corpus(self):
        text = RuntimeContract.from_files(ROOT).business_context()
        self.assertIn("Larkspur Ridge", text)
        self.assertIn('source "rag"', text)
        self.assertNotIn("complaint narratives", text.lower())
        for storyline in ("Brightwater", "March 11", "Talon Crest"):
            self.assertIn(storyline, text)


if __name__ == "__main__":
    unittest.main()
