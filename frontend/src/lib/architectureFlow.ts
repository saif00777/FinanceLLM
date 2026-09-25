/**
 * Pure logic for the architecture page's animated views. No React, no browser APIs, no path aliases, and only
 * erasable TypeScript syntax, so the same file runs in the app and under `node --test` (see frontend/tests).
 */

export interface Scenario {
  id: string;
  title: string;
  question: string;
  blurb: string;
  outcome: string;
  stages: string[][];
  notes: string[];
}

export type Verdict = "allow" | "fix" | "block";

export interface GateCase {
  id: string;
  sql: string;
  verdict: Verdict;
  /** The check that stops a blocked query, or bounds a fixed one. Absent for an allowed query. */
  check?: string;
  why: string;
}

export interface GateCheck {
  id: string;
  label: string;
  detail: string;
}

export interface Edge {
  from: string;
  to: string;
}

export function stageLabel(stage: string[], labels: Record<string, string>): string {
  return stage.map((id) => labels[id] ?? id).join(" + ");
}

// ---------------------------------------------------------------------------------------------- question player

export interface Frame {
  index: number;
  /** Where the packet is now (several nodes during a parallel stage). */
  activeIds: string[];
  /** Everything it has already passed. */
  visitedIds: string[];
  title: string;
  note: string;
  parallel: boolean;
}

/** Frame 0 is the question arriving, then one frame per stage, then the answer reaching you. */
export function buildFrames(scenario: Scenario, labels: Record<string, string>): Frame[] {
  const start = ["browser", "api"];
  const frames: Frame[] = [
    { index: 0, activeIds: ["api"], visitedIds: ["browser"], title: "Your question arrives", note: "It reaches the backend with your key attached to this one request.", parallel: false },
  ];
  scenario.stages.forEach((stage, i) => {
    frames.push({
      index: i + 1,
      activeIds: stage,
      // A stop being revisited (the repair loop) is shown as active, not as already visited.
      visitedIds: [...new Set([...start, ...scenario.stages.slice(0, i).flat()])].filter((id) => !stage.includes(id)),
      title: stageLabel(stage, labels),
      note: scenario.notes[i],
      parallel: stage.length > 1,
    });
  });
  frames.push({
    index: scenario.stages.length + 1,
    activeIds: ["answer"],
    visitedIds: [...start, ...scenario.stages.flat()],
    title: "Your answer",
    note: scenario.outcome,
    parallel: false,
  });
  return frames;
}

export function stepFrame(index: number, total: number, direction: 1 | -1): { index: number; atEnd: boolean } {
  const next = Math.min(Math.max(index + direction, 0), total - 1);
  return { index: next, atEnd: next >= total - 1 };
}

/** Milliseconds to dwell on each frame at a playback speed (1 = normal). Bounded so it is never frantic or stalled. */
export function delayForSpeed(speed: number): number {
  return Math.round(Math.min(Math.max(1900 / speed, 250), 6000));
}

// ---------------------------------------------------------------------------------------------- map selection

export function connections(nodeId: string, edges: Edge[]): { incoming: Edge[]; outgoing: Edge[]; neighborIds: string[] } {
  const incoming = edges.filter((e) => e.to === nodeId);
  const outgoing = edges.filter((e) => e.from === nodeId);
  const neighborIds = [...new Set([...incoming.map((e) => e.from), ...outgoing.map((e) => e.to)])];
  return { incoming, outgoing, neighborIds };
}

// ---------------------------------------------------------------------------------------------- SQL gate inspector

export type CheckStatus = "pending" | "running" | "pass" | "fail" | "fixed" | "skipped";

export interface CheckResult extends GateCheck {
  status: "pass" | "fail" | "fixed" | "skipped";
}

/** The final outcome of every check for one query, in the order the real gate runs them. */
export function evaluateGate(query: GateCase, checks: GateCheck[]): CheckResult[] {
  const stopAt = query.verdict === "allow" ? -1 : checks.findIndex((c) => c.id === query.check);
  return checks.map((check, i) => {
    if (query.verdict === "block" && stopAt >= 0) {
      return { ...check, status: i < stopAt ? "pass" : i === stopAt ? "fail" : "skipped" };
    }
    if (query.verdict === "fix" && i === stopAt) return { ...check, status: "fixed" };
    return { ...check, status: "pass" };
  });
}

/** What each row shows while the animation is at `step`: settled results, the one being checked, and what is still to come. */
export function statusesAtStep(results: CheckResult[], step: number): CheckStatus[] {
  return results.map((result, i) => (i < step ? result.status : i === step ? "running" : "pending"));
}

/** The query as the gate returns it when a limit was missing. */
export function fixedSql(sql: string): string {
  return `${sql.trim().replace(/;+\s*$/, "")} LIMIT 100`;
}
