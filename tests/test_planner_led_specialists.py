import json
from pathlib import Path
import unittest

from app.agents.text_to_sql.contracts import LinkedContext, RuntimeContract
from app.agents.text_to_sql.specialists import OpenAIResponsesSpecialists, SqlProposal, TaskPlan

ROOT = Path(__file__).resolve().parents[1]


class _Responses:
    """Queues raw model outputs (repeating the last) and records every call."""

    def __init__(self, *payloads):
        self._texts = [p if isinstance(p, str) else json.dumps(p) for p in payloads]
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self._texts[min(len(self.calls) - 1, len(self._texts) - 1)]
        return type("Response", (), {"output_text": text})()

    def payload(self, index=0):
        return json.loads(self.calls[index]["input"])

    def instructions(self, index=0):
        return self.calls[index]["instructions"]


def _specialist(*payloads, catalog=None):
    responses = _Responses(*payloads)
    client = type("Client", (), {"responses": responses})()
    return OpenAIResponsesSpecialists(client, "m", catalog if catalog is not None else RuntimeContract.from_files(ROOT)), responses


PLAN = TaskPlan(
    "aggregate_query", "r", {}, standalone_question="What is the total credit limit of cards that have a chip?",
    sql_guidance="Use main.cards, filter has_chip = TRUE, SUM(credit_limit).", analysis_guidance="State the total and how many cards.",
)


class DomainGuardAsTheOnlyClarifierTests(unittest.TestCase):
    def test_receives_the_business_context_and_owns_clarification(self):
        specialist, responses = _specialist({"route": "clarify", "reason_code": "vague", "sources": ["sql"], "clarification": "Which metric?"})

        specialist.domain_guard("show me stuff", {"recent_user_questions": []})

        self.assertIn("main.cards", responses.payload()["business_context"])
        instructions = responses.instructions()
        self.assertIn('"clarification"', instructions)
        self.assertIn("only agent", instructions)

    def test_returns_the_clarifying_question_it_wrote(self):
        specialist, _ = _specialist({"route": "clarify", "reason_code": "vague", "sources": ["sql"], "clarification": "  Which metric do you want?  "})

        decision = specialist.domain_guard("show me stuff", {})

        self.assertEqual(decision.route, "clarify")
        self.assertEqual(decision.clarification, "Which metric do you want?")

    def test_clarification_is_absent_when_not_given_or_blank(self):
        specialist, _ = _specialist({"route": "in_scope", "reason_code": "ok", "sources": ["sql"], "clarification": "  "})

        self.assertIsNone(specialist.domain_guard("total spending", {}).clarification)


class PlannerAsTheGuideTests(unittest.TestCase):
    def test_planner_receives_the_full_business_context(self):
        specialist, responses = _specialist({"intent": "i", "rationale": "r", "standalone_question": "q"})

        specialist.plan("tell me the average", {"recent_user_questions": ["credit limit of chip cards?"], "sources": ["sql"]})

        payload = responses.payload()
        self.assertIn("main.cards", payload["business_context"])
        self.assertIn("Governed metrics", payload["business_context"])
        self.assertEqual(payload["facts"]["recent_user_questions"], ["credit limit of chip cards?"])

    def test_planner_is_told_to_rewrite_the_question_and_guide_the_other_agents(self):
        specialist, responses = _specialist({"intent": "i", "rationale": "r"})

        specialist.plan("tell me the average", {})

        instructions = responses.instructions()
        for key in ("standalone_question", "sql_guidance", "analysis_guidance"):
            self.assertIn(key, instructions)

    def test_planner_carries_over_the_subject_and_latest_aggregate_but_not_filters(self):
        # Reproduced live: "what is the total credit limit?" was rewritten to "...of cards that have chips"
        # (a filter copied from an earlier question), and "I need for the cards with chips" reused the FIRST
        # question's average instead of the most recent question's total.
        specialist, responses = _specialist({"intent": "i", "rationale": "r"})

        specialist.plan("q", {})

        instructions = responses.instructions()
        self.assertIn("Do not carry over filters", instructions)
        self.assertIn("most recent earlier question", instructions)
        self.assertIn("facts.most_recent_earlier_question", instructions)

    def test_planner_instructions_include_few_shot_examples_for_follow_ups(self):
        # Prompt steering alone kept the latest aggregate only 4/6 times live; worked examples pin the behaviour.
        specialist, responses = _specialist({"intent": "i", "rationale": "r"})

        specialist.plan("q", {})

        instructions = responses.instructions()
        self.assertIn("Examples", instructions)
        self.assertIn("Earlier questions:", instructions)
        self.assertIn("Rewrite:", instructions)
        self.assertIn("I need for the cards with chips", instructions)

    def test_planner_output_carries_the_rewrite_and_guidance(self):
        specialist, _ = _specialist({
            "intent": "aggregate_query", "rationale": "r", "resolved_filters": {"has_chip": True},
            "standalone_question": " What is the average credit limit of cards with a chip? ",
            "sql_guidance": "Use main.cards.", "analysis_guidance": "Give the average.",
        })

        plan = specialist.plan("tell me the average", {})

        self.assertEqual(plan.standalone_question, "What is the average credit limit of cards with a chip?")
        self.assertEqual(plan.sql_guidance, "Use main.cards.")
        self.assertEqual(plan.analysis_guidance, "Give the average.")
        self.assertEqual(plan.resolved_filters, {"has_chip": True})

    def test_missing_rewrite_or_guidance_becomes_empty_strings_not_errors(self):
        specialist, _ = _specialist({"intent": "i", "rationale": "r", "sql_guidance": ["not", "text"]})

        plan = specialist.plan("q", {})

        self.assertEqual((plan.standalone_question, plan.sql_guidance, plan.analysis_guidance), ("", "", ""))

    def test_planner_still_works_when_the_catalog_has_no_business_context(self):
        specialist, responses = _specialist({"intent": "i", "rationale": "r"}, catalog=object())

        specialist.plan("q", {})

        self.assertEqual(responses.payload()["business_context"], "")


class SqlAgentHasNoClarificationPathTests(unittest.TestCase):
    def test_instructions_do_not_offer_a_clarification_option(self):
        specialist, responses = _specialist({"sql": "SELECT 1"})

        specialist.generate_sql("q", LinkedContext(relations=(), prompt="p"), {}, None, plan=PLAN)

        self.assertNotIn("clarification", responses.instructions())

    def test_a_model_supplied_clarification_is_ignored_and_the_proposal_has_none(self):
        specialist, _ = _specialist({"clarification": "Which card?"})

        proposal = specialist.generate_sql("q", LinkedContext(relations=(), prompt="p"), {}, None)

        self.assertIsNone(proposal.sql)
        self.assertFalse(hasattr(proposal, "clarification"))

    def test_the_plan_guides_sql_generation(self):
        specialist, responses = _specialist({"sql": "SELECT 1"})

        specialist.generate_sql(PLAN.standalone_question, LinkedContext(relations=(), prompt="p"), {}, None, plan=PLAN)

        payload = responses.payload()
        self.assertEqual(payload["question"], PLAN.standalone_question)
        self.assertEqual(payload["plan"]["sql_guidance"], PLAN.sql_guidance)
        self.assertIn("plan", responses.instructions())

    def test_generate_sql_works_without_a_plan(self):
        specialist, responses = _specialist({"sql": "SELECT 1"})

        proposal = specialist.generate_sql("q", LinkedContext(relations=(), prompt="p"), {}, None)

        self.assertEqual(proposal.sql, "SELECT 1")
        self.assertIsNone(responses.payload()["plan"])


class DownstreamAgentsFollowThePlanTests(unittest.TestCase):
    def test_data_analysis_answer_and_review_all_receive_the_plan(self):
        specialist, responses = _specialist(
            {"summary": "s", "insights": [], "caveats": []}, {"answer": "a"}, {"approved": True, "reason_code": "ok"},
        )

        specialist.data_analysis("q", ["c"], [[1]], plan=PLAN)
        specialist.analyze("q", ["c"], [[1]], SqlProposal("SELECT 1"), plan=PLAN)
        specialist.review("q", ["c"], [[1]], "a", None, plan=PLAN)

        for index in range(3):
            self.assertEqual(responses.payload(index)["plan"]["analysis_guidance"], PLAN.analysis_guidance, index)
            self.assertIn("plan", responses.instructions(index), index)

    def test_they_still_work_without_a_plan(self):
        specialist, responses = _specialist(
            {"summary": "s"}, {"answer": "a"}, {"approved": True, "reason_code": "ok"},
        )

        specialist.data_analysis("q", ["c"], [[1]])
        specialist.analyze("q", ["c"], [[1]], SqlProposal("SELECT 1"))
        review = specialist.review("q", ["c"], [[1]], "a", None)

        self.assertTrue(review.approved)
        self.assertIsNone(responses.payload(1)["plan"])


class SuggestionsAreDrivenByBusinessIntentTests(unittest.TestCase):
    def test_suggest_is_an_llm_call_with_intent_route_relations_and_business_context(self):
        specialist, responses = _specialist({"suggestions": ["How many cards have a chip?", "Average credit limit by card brand?"]})

        suggestions = specialist.suggest(
            "tell me the average", {"recent_user_questions": ["credit limit of chip cards?"]}, ("main.cards",),
            plan=PLAN, route="answered", columns=["avg_credit_limit"],
        )

        self.assertEqual(suggestions, ["How many cards have a chip?", "Average credit limit by card brand?"])
        payload = responses.payload()
        self.assertEqual(payload["question"], PLAN.standalone_question)
        self.assertEqual(payload["intent"], "aggregate_query")
        self.assertEqual(payload["route"], "answered")
        self.assertEqual(payload["relations"], ["main.cards"])
        self.assertEqual(payload["columns"], ["avg_credit_limit"])
        self.assertIn("Governed metrics", payload["business_context"])

    def test_suggest_never_sends_result_rows(self):
        specialist, responses = _specialist({"suggestions": ["A?"]})

        specialist.suggest("q", {}, ("main.cards",), plan=PLAN, route="answered", columns=["c"])

        self.assertNotIn("rows", responses.payload())

    def test_suggestions_are_cleaned_deduplicated_and_capped_at_three(self):
        raw = ["  One?  ", "one?", "", 5, "Two?", "Three?", "Four?"]
        specialist, _ = _specialist({"suggestions": raw})

        self.assertEqual(specialist.suggest("q", {}, ()), ["One?", "Two?", "Three?"])

    def test_the_current_question_is_never_suggested_back(self):
        specialist, _ = _specialist({"suggestions": ["What is total spending?", "By year?"]})

        self.assertEqual(specialist.suggest("What is total spending?", {}, ()), ["By year?"])

    def test_falls_back_to_the_deterministic_suggester_on_a_bad_response(self):
        for bad in ({"suggestions": "not a list"}, {"suggestions": []}, {"other": 1}, "not json"):
            specialist, _ = _specialist(bad)
            result = specialist.suggest("Total spending", {}, ("main.transactions",))
            self.assertTrue(result, bad)
            self.assertTrue(all(isinstance(s, str) and s for s in result), bad)

    def test_falls_back_when_the_model_call_itself_fails(self):
        class Boom:
            def create(self, **kwargs):
                raise RuntimeError("model unavailable")

        client = type("Client", (), {"responses": Boom()})()
        specialist = OpenAIResponsesSpecialists(client, "m", RuntimeContract.from_files(ROOT))

        self.assertTrue(specialist.suggest("Total spending", {}, ("main.transactions",)))

    def test_instructions_ask_for_intent_based_answerable_suggestions(self):
        specialist, responses = _specialist({"suggestions": ["A?"]})

        specialist.suggest("q", {}, ())

        instructions = responses.instructions()
        self.assertIn("business intent", instructions)
        self.assertIn("answerable", instructions)


if __name__ == "__main__":
    unittest.main()
