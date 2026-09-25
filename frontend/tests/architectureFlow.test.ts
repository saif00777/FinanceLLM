import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  buildFrames,
  connections,
  delayForSpeed,
  evaluateGate,
  fixedSql,
  stageLabel,
  statusesAtStep,
  stepFrame,
  type GateCase,
  type GateCheck,
  type Scenario,
} from "../src/lib/architectureFlow.ts";

const read = (name: string) => JSON.parse(readFileSync(new URL(`../src/data/${name}`, import.meta.url), "utf-8"));
const architecture = read("architecture.json");
const scenarios: Scenario[] = read("scenarios.json");
const cases: GateCase[] = read("guardrailQueries.json");
const checks: GateCheck[] = read("gateChecks.json");
const labels: Record<string, string> = Object.fromEntries(architecture.nodes.map((n: { id: string; label: string }) => [n.id, n.label]));

test("a parallel stage is labelled as one group", () => {
  assert.equal(stageLabel(["hard_guard"], labels), "Hard guard");
  assert.match(stageLabel(["schema_link", "metric_resolver", "mcc_resolver"], labels), /Schema linker \+ Metric resolver \+ Category matcher/);
});

test("every real scenario becomes: arrival, one frame per stage, then the answer", () => {
  for (const scenario of scenarios) {
    const frames = buildFrames(scenario, labels);
    assert.equal(frames.length, scenario.stages.length + 2, scenario.id);
    assert.deepEqual(frames[0].activeIds, ["api"]);
    assert.deepEqual(frames.at(-1)!.activeIds, ["answer"]);
    scenario.stages.forEach((stage, i) => {
      assert.deepEqual(frames[i + 1].activeIds, stage);
      assert.equal(frames[i + 1].note, scenario.notes[i]);
      assert.equal(frames[i + 1].parallel, stage.length > 1);
    });
    assert.equal(frames.at(-1)!.note, scenario.outcome);
  }
});

test("the trail of visited stops only grows, except that a stop being revisited (a repair loop) shows as active, not visited", () => {
  for (const scenario of scenarios) {
    const frames = buildFrames(scenario, labels);
    frames.forEach((frame, i) => {
      assert.ok(frame.activeIds.every((id) => !frame.visitedIds.includes(id)), `${scenario.id}#${i}: active stop listed as visited`);
      if (i > 0) assert.ok(frames[i - 1].visitedIds.every((id) => frame.visitedIds.includes(id) || frame.activeIds.includes(id)), `${scenario.id}#${i}: trail shrank`);
    });
  }
});

test("in the repair route the looped-back stops are active, so the writer is shown working again", () => {
  const repair = scenarios.find((s) => s.id === "repair")!;
  const frames = buildFrames(repair, labels);
  const writerFrames = frames.filter((f) => f.activeIds.includes("sql_generator"));
  assert.equal(writerFrames.length, 2, "the SQL writer runs twice");
  assert.ok(!writerFrames[1].visitedIds.includes("sql_generator"));
});

test("stepping clamps at both ends and reports whether playback should stop", () => {
  assert.deepEqual(stepFrame(0, 5, -1), { index: 0, atEnd: false });
  assert.deepEqual(stepFrame(2, 5, 1), { index: 3, atEnd: false });
  assert.deepEqual(stepFrame(3, 5, 1), { index: 4, atEnd: true });
  assert.deepEqual(stepFrame(4, 5, 1), { index: 4, atEnd: true });
});

test("faster speeds shorten the delay between frames, within sensible bounds", () => {
  assert.ok(delayForSpeed(2) < delayForSpeed(1));
  assert.ok(delayForSpeed(0.5) > delayForSpeed(1));
  assert.ok(delayForSpeed(100) >= 250 && delayForSpeed(0.001) <= 6000);
});

test("selecting a component finds its incoming and outgoing links and its neighbours", () => {
  const edges = architecture.edges;
  const c = connections("sql_policy", edges);
  assert.deepEqual(c.outgoing.map((e) => e.to).sort(), ["executor", "merge_results", "sql_generator"]);
  assert.deepEqual(c.incoming.map((e) => e.from), ["sql_generator"]);
  assert.deepEqual([...c.neighborIds].sort(), ["executor", "merge_results", "sql_generator"]);
  assert.equal(connections("no_such_node", edges).neighborIds.length, 0);
});

test("every check of the SQL gate is listed once, in running order, with an explanation", () => {
  assert.equal(new Set(checks.map((c) => c.id)).size, checks.length);
  assert.ok(checks.every((c) => c.label && c.detail));
});

test("a query that is allowed passes every check; a fixed one is fixed at the limit", () => {
  const allowed = cases.find((c) => c.verdict === "allow")!;
  assert.ok(evaluateGate(allowed, checks).every((r) => r.status === "pass"));
  const fix = cases.find((c) => c.verdict === "fix")!;
  const results = evaluateGate(fix, checks);
  assert.equal(results.at(-1)!.status, "fixed");
  assert.ok(results.slice(0, -1).every((r) => r.status === "pass"));
});

test("a blocked query passes the earlier checks, fails at its check, and never reaches the later ones", () => {
  for (const blocked of cases.filter((c) => c.verdict === "block")) {
    const results = evaluateGate(blocked, checks);
    const at = results.findIndex((r) => r.status === "fail");
    assert.equal(results[at].id, blocked.check, blocked.id);
    assert.ok(results.slice(0, at).every((r) => r.status === "pass"), blocked.id);
    assert.ok(results.slice(at + 1).every((r) => r.status === "skipped"), blocked.id);
    assert.equal(results.filter((r) => r.status === "fail").length, 1);
  }
});

test("the animation reveals checks one at a time: settled, then running, then pending", () => {
  const blocked = cases.find((c) => c.verdict === "block" && c.check === "columns")!;
  const results = evaluateGate(blocked, checks);
  assert.equal(statusesAtStep(results, 0)[0], "running");
  assert.ok(statusesAtStep(results, 0).slice(1).every((s) => s === "pending"));
  const mid = statusesAtStep(results, 2);
  assert.deepEqual(mid.slice(0, 2), ["pass", "pass"]);
  assert.equal(mid[2], "running");
  assert.equal(mid[3], "pending");
  assert.deepEqual(statusesAtStep(results, results.length), results.map((r) => r.status), "after the last step everything is settled");
});

test("the auto-fix result is the same query with the limit the gate adds", () => {
  assert.equal(fixedSql("SELECT t.mcc FROM main.transactions AS t GROUP BY t.mcc"), "SELECT t.mcc FROM main.transactions AS t GROUP BY t.mcc LIMIT 100");
  assert.equal(fixedSql("SELECT 1 FROM main.cards AS c;"), "SELECT 1 FROM main.cards AS c LIMIT 100");
});
