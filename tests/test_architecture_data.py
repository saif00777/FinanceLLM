"""Pins the architecture page's data files (frontend/src/data/*.json) to the real code, so the interactive
explainer cannot drift from how the workflow and the SQL policy actually behave."""

from collections import Counter
import json
from pathlib import Path
import unittest

from app.agents.text_to_sql.contracts import RuntimeContract
from app.agents.text_to_sql.domain_guard import HardGuard
from app.agents.text_to_sql.specialists import SqlProposal
from app.agents.text_to_sql.workflow import MultiAgentWorkflow
from app.helpers.conversation import InMemoryConversationStore
from app.helpers.sql_policy import SqlPolicy, SqlPolicyError
from tests.test_workflow import (
    ClarifyingDomainGuardSpecialists,
    FakeRetriever,
    FakeRunner,
    FakeSpecialists,
    HybridDomainGuardSpecialists,
    ROOT,
    VALID_SQL,
)

DATA = ROOT / "frontend" / "src" / "data"


def _load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


class BadColumnThenValidSql(FakeSpecialists):
    """The SQL writer first names a column that is not on the approved list, then fixes it."""

    def generate_sql(self, question, linked, facts, repair_error, plan=None):
        self.sql_calls += 1
        return SqlProposal("SELECT u.state FROM main.users AS u LIMIT 5" if self.sql_calls == 1 else VALID_SQL)


def _real_graph():
    workflow = MultiAgentWorkflow(RuntimeContract.from_files(ROOT), FakeRunner(), FakeSpecialists(),
                                  InMemoryConversationStore(), HardGuard(), retriever=FakeRetriever())
    return workflow._graph.get_graph()


class ArchitectureGraphTests(unittest.TestCase):
    def setUp(self):
        self.architecture = _load("architecture.json")
        self.graph = _real_graph()

    def test_the_diagram_has_exactly_the_nodes_of_the_real_graph(self):
        drawn = {n["id"] for n in self.architecture["nodes"] if n["inGraph"]}
        real = set(self.graph.nodes) - {"__start__", "__end__"}
        self.assertEqual(drawn, real)

    def test_the_diagram_has_exactly_the_edges_of_the_real_graph(self):
        drawn = {(e["from"], e["to"]) for e in self.architecture["edges"] if not e.get("external")}
        real = {(e.source, e.target) for e in self.graph.edges} - {("__start__", "hard_guard"), ("suggestions", "__end__")}
        self.assertEqual(drawn, real)

    def test_every_edge_endpoint_is_a_drawn_node_and_every_node_is_explained(self):
        ids = {n["id"] for n in self.architecture["nodes"]}
        self.assertEqual(len(ids), len(self.architecture["nodes"]), "duplicate node ids")
        for edge in self.architecture["edges"]:
            self.assertIn(edge["from"], ids)
            self.assertIn(edge["to"], ids)
        for node in self.architecture["nodes"]:
            for field in ("label", "kind", "summary", "does", "never", "fact"):
                self.assertTrue(str(node[field]).strip(), f"{node['id']}.{field} is empty")
            self.assertTrue(node["uses"], f"{node['id']} lists nothing it uses")

    def test_no_two_nodes_share_a_position(self):
        positions = [(n["x"], n["row"]) for n in self.architecture["nodes"]]
        self.assertEqual(len(positions), len(set(positions)))


class ScenarioPathTests(unittest.TestCase):
    """Each scenario's stages must be exactly what the real workflow does for a question of that kind."""

    def setUp(self):
        self.scenarios = {s["id"]: s for s in _load("scenarios.json")}

    def _actual_path(self, scenario_id, specialists, retriever=None):
        workflow = MultiAgentWorkflow(RuntimeContract.from_files(ROOT), FakeRunner(), specialists,
                                      InMemoryConversationStore(), HardGuard(), retriever=retriever)
        return workflow.answer(self.scenarios[scenario_id]["question"]).specialist_path

    def _assert_stages_match(self, scenario_id, actual):
        stages = self.scenarios[scenario_id]["stages"]
        flat = [node for stage in stages for node in stage]
        self.assertEqual(len(flat), len(actual), f"{scenario_id}: {flat} vs {actual}")
        cursor = 0
        for stage in stages:  # parallel nodes may finish in any order, so compare each stage as a multiset
            self.assertEqual(Counter(stage), Counter(actual[cursor:cursor + len(stage)]), f"{scenario_id}: {stage}")
            cursor += len(stage)

    def test_the_data_question(self):
        self._assert_stages_match("sql-answer", self._actual_path("sql-answer", FakeSpecialists()))

    def test_the_forbidden_request(self):
        self._assert_stages_match("blocked", self._actual_path("blocked", FakeSpecialists()))

    def test_the_vague_question(self):
        self._assert_stages_match("clarify", self._actual_path("clarify", ClarifyingDomainGuardSpecialists(("sql",))))

    def test_the_document_question(self):
        self._assert_stages_match("documents", self._actual_path("documents", FakeSpecialists(), FakeRetriever()))

    def test_the_rejected_query(self):
        self._assert_stages_match("repair", self._actual_path("repair", BadColumnThenValidSql()))

    def test_the_two_source_question(self):
        self._assert_stages_match("hybrid", self._actual_path("hybrid", HybridDomainGuardSpecialists(), FakeRetriever()))

    def test_scenarios_are_well_formed(self):
        nodes = {n["id"] for n in _load("architecture.json")["nodes"]}
        seen_ids = set()
        for scenario in self.scenarios.values():
            self.assertNotIn(scenario["id"], seen_ids)
            seen_ids.add(scenario["id"])
            self.assertEqual(len(scenario["notes"]), len(scenario["stages"]), scenario["id"])
            self.assertTrue(all(note.strip() for note in scenario["notes"]))
            self.assertTrue({n for stage in scenario["stages"] for n in stage} <= nodes)
            self.assertNotIn("minLevel", scenario, "routes are no longer gated by a level")
        self.assertEqual(seen_ids, {"sql-answer", "blocked", "clarify", "documents", "repair", "hybrid"})


# The policy's own error text -> the id of the check that produced it (the order below is the order it runs them).
CHECK_FOR_MESSAGE = [
    ("could not be parsed", "parse"),
    ("Exactly one SQL statement", "one-statement"),
    ("Only SELECT", "select-only"),
    ("fully qualified", "tables"),
    ("Relation is not in the allowed", "tables"),
    ("Column is not in the allowed", "columns"),
    ("wildcard", "wildcard"),
    ("Function is not allowed", "functions"),
    ("LIMIT", "limit"),
]


def _check_that_stopped(sql):
    try:
        SqlPolicy().validate(sql)
    except SqlPolicyError as error:
        for fragment, check in CHECK_FOR_MESSAGE:
            if fragment in str(error):
                return check
        raise AssertionError(f"unmapped policy message: {error}")
    return None


class GuardrailQueryTests(unittest.TestCase):
    """The SQL gate inspector must tell the truth about what the real SqlPolicy does, check by check."""

    def test_every_verdict_matches_the_real_policy(self):
        policy = SqlPolicy()
        for case in _load("guardrailQueries.json"):
            with self.subTest(case=case["id"]):
                try:
                    validated = policy.validate(case["sql"])
                except SqlPolicyError:
                    self.assertEqual(case["verdict"], "block", f"{case['id']} was rejected")
                    continue
                had_limit = " LIMIT " in f" {case['sql'].upper()} "
                added_limit = validated.upper().rstrip().endswith("LIMIT 100") and not had_limit
                self.assertEqual(case["verdict"], "fix" if added_limit else "allow", f"{case['id']} -> {validated}")

    def test_the_check_the_animation_stops_at_is_the_check_that_really_stops_the_query(self):
        for case in _load("guardrailQueries.json"):
            with self.subTest(case=case["id"]):
                if case["verdict"] == "block":
                    self.assertEqual(case["check"], _check_that_stopped(case["sql"]))
                elif case["verdict"] == "fix":
                    self.assertEqual(case["check"], "limit")  # passes every check; the limit is added
                    self.assertIsNone(_check_that_stopped(case["sql"]))
                else:
                    self.assertNotIn("check", case)
                    self.assertIsNone(_check_that_stopped(case["sql"]))

    def test_the_listed_checks_are_the_checks_the_policy_can_fail_on_in_running_order(self):
        checks = [c["id"] for c in _load("gateChecks.json")]
        expected = []
        for _, check in CHECK_FOR_MESSAGE:
            if check not in expected:
                expected.append(check)
        self.assertEqual(checks, expected)
        for check in _load("gateChecks.json"):
            self.assertTrue(check["label"].strip() and check["detail"].strip())

    def test_when_two_rules_are_broken_the_earlier_check_is_the_one_that_reports(self):
        # These pin the running order that the animation relies on.
        self.assertEqual(_check_that_stopped("SELECT cvv FROM source.cards"), "tables")          # tables before columns
        self.assertEqual(_check_that_stopped("SELECT * FROM main.cards WHERE cvv = 1"), "columns")  # columns before wildcard
        self.assertEqual(_check_that_stopped("SELECT * FROM main.cards"), "wildcard")            # wildcard before limit

    def test_the_inspector_covers_all_three_verdicts_and_explains_each_one(self):
        cases = _load("guardrailQueries.json")
        self.assertEqual({c["verdict"] for c in cases}, {"allow", "fix", "block"})
        self.assertGreaterEqual(len(cases), 8)
        self.assertTrue(all(c["why"].strip() for c in cases))
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        blocked_at = {c["check"] for c in cases if c["verdict"] == "block"}
        self.assertGreaterEqual(len(blocked_at), 5, "the queries should exercise several different checks")


if __name__ == "__main__":
    unittest.main()
