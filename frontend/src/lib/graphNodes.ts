import type { GraphNode } from "@/lib/api";

/** Human-friendly labels for each graph node — see app/agents/text_to_sql/workflow.py's _build_graph(). */
export const NODE_LABELS: Record<GraphNode, string> = {
  hard_guard: "Checking request safety",
  domain_guard: "Understanding your question",
  document_router: "Choosing data sources",
  document_retrieval: "Searching documents",
  planner: "Planning the analysis",
  schema_link: "Selecting relevant tables",
  metric_resolver: "Resolving the metric",
  mcc_resolver: "Matching merchant categories",
  sql_generator: "Writing the query",
  sql_policy: "Validating the query",
  executor: "Running the query",
  data_analysis: "Summarizing the results",
  analyst: "Grounding the answer",
  reviewer: "Reviewing for accuracy",
  merge_results: "Preparing the response",
  suggestions: "Preparing follow-up questions",
};

/**
 * Nodes the real graph runs in parallel (see workflow.py's `add_edge(["a", "b"], "next")`
 * bundled joins) get grouped visually under one shared parent step, since they genuinely
 * happen at the same time — the progress tree should say so, not imply a false sequence.
 */
const PARALLEL_GROUPS: Record<string, { label: string; members: Set<GraphNode> }> = {
  context: { label: "Selecting relevant data", members: new Set(["schema_link", "metric_resolver", "mcc_resolver"]) },
  postQuery: { label: "Analyzing results", members: new Set(["data_analysis", "analyst"]) },
};

function groupFor(node: GraphNode): { key: string; label: string; total: number } | null {
  for (const [key, group] of Object.entries(PARALLEL_GROUPS)) {
    if (group.members.has(node)) return { key, label: group.label, total: group.members.size };
  }
  return null;
}

export interface ProgressLeaf {
  kind: "single";
  key: string;
  node: GraphNode;
  label: string;
  thought?: string;
}

export interface ProgressGroup {
  kind: "group";
  key: string;
  label: string;
  children: { node: GraphNode; label: string; thought?: string }[];
  total: number;
}

export type ProgressStep = ProgressLeaf | ProgressGroup;

/** Folds a flat, ordered stream of node-completion events into a tree, grouping adjacent parallel siblings. */
export function appendProgressStep(steps: ProgressStep[], node: GraphNode, eventIndex: number): ProgressStep[] {
  const group = groupFor(node);
  if (group) {
    const last = steps[steps.length - 1];
    // group.key is stable per group (not per event) so a run of sibling events folds into one step.
    if (last?.kind === "group" && last.key === group.key) {
      return [...steps.slice(0, -1), { ...last, children: [...last.children, { node, label: NODE_LABELS[node] }] }];
    }
    return [...steps, { kind: "group", key: group.key, label: group.label, total: group.total, children: [{ node, label: NODE_LABELS[node] }] }];
  }
  return [...steps, { kind: "single", key: `${node}-${eventIndex}`, node, label: NODE_LABELS[node] }];
}

/** Attaches an agent's thought to the latest step (or group child) for that node; ignored if the step isn't there yet. */
export function attachThought(steps: ProgressStep[], node: GraphNode, thought: string): ProgressStep[] {
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    const step = steps[index];
    if (step.kind === "single" && step.node === node) {
      return steps.map((candidate, i) => (i === index ? { ...step, thought } : candidate));
    }
    if (step.kind === "group" && step.children.some((child) => child.node === node)) {
      const children = step.children.map((child) => (child.node === node ? { ...child, thought } : child));
      return steps.map((candidate, i) => (i === index ? { ...step, children } : candidate));
    }
  }
  return steps;
}
