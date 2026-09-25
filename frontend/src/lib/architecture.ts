import architectureData from "@/data/architecture.json";
import scenariosData from "@/data/scenarios.json";
import guardrailData from "@/data/guardrailQueries.json";
import gateChecksData from "@/data/gateChecks.json";
import type { GateCase, GateCheck, Scenario } from "@/lib/architectureFlow";

export type NodeKind = "guard" | "llm" | "code" | "data" | "edge";

export interface ArchNode {
  id: string;
  inGraph: boolean;
  label: string;
  kind: NodeKind;
  x: number;
  row: number;
  summary: string;
  does: string;
  never: string;
  uses: string[];
  fact: string;
}

export interface ArchEdge {
  from: string;
  to: string;
  label?: string;
  kind?: "stop" | "loop";
  external?: boolean;
}

export const NODES = architectureData.nodes as ArchNode[];
export const EDGES = architectureData.edges as ArchEdge[];
export const SCENARIOS = scenariosData as Scenario[];
export const GATE_CASES = guardrailData as GateCase[];
export const GATE_CHECKS = gateChecksData as GateCheck[];

export const NODE_BY_ID: Record<string, ArchNode> = Object.fromEntries(NODES.map((n) => [n.id, n]));
export const LABELS: Record<string, string> = Object.fromEntries(NODES.map((n) => [n.id, n.label]));
export const GRAPH_NODE_IDS = NODES.filter((n) => n.inGraph).map((n) => n.id);

/** Human wording and colour for each kind of component. */
export const KIND_INFO: Record<NodeKind, { label: string; blurb: string; color: string }> = {
  guard: { label: "Guardrail", blurb: "Plain rules that cannot be persuaded", color: "#f59e0b" },
  llm: { label: "AI agent", blurb: "A model with one narrow job", color: "#a78bfa" },
  code: { label: "Plain code", blurb: "Deterministic, no model involved", color: "#60a5fa" },
  data: { label: "Meaning search", blurb: "Embeddings compared by similarity", color: "#22d3ee" },
  edge: { label: "Edge of the system", blurb: "Where you meet the machine", color: "#94a3b8" },
};

// ---------------------------------------------------------------------------------------------- diagram geometry

export const VIEW_WIDTH = 620;
export const NODE_W = 152;
export const NODE_H = 54;
const TOP = 36;
const ROW_GAP = 98;

export function nodeCenter(node: ArchNode): { x: number; y: number } {
  return { x: (node.x / 100) * VIEW_WIDTH, y: TOP + NODE_H / 2 + node.row * ROW_GAP };
}

export const VIEW_HEIGHT = TOP * 2 + NODE_H + Math.max(...NODES.map((n) => n.row)) * ROW_GAP;

/** SVG path between two nodes. Long or looping edges are routed around the side so they never cross a card. */
export function edgePath(edge: ArchEdge): { d: string; labelAt: { x: number; y: number } } {
  const a = nodeCenter(NODE_BY_ID[edge.from]);
  const b = nodeCenter(NODE_BY_ID[edge.to]);
  const key = `${edge.from}>${edge.to}`;

  if (edge.kind === "loop") {
    const right = a.x + NODE_W / 2;
    const bulge = right + 70;
    return { d: `M ${right} ${a.y} C ${bulge} ${a.y}, ${bulge} ${b.y}, ${b.x + NODE_W / 2} ${b.y}`, labelAt: { x: bulge + 6, y: (a.y + b.y) / 2 } };
  }
  if (key === "document_retrieval>merge_results") {
    const edgeX = VIEW_WIDTH - 14;
    const y1 = a.y + NODE_H / 2;
    const y2 = b.y;
    return { d: `M ${a.x} ${y1} C ${a.x} ${y1 + 40}, ${edgeX} ${y1 + 20}, ${edgeX} ${y1 + 90} L ${edgeX} ${y2 - 40} C ${edgeX} ${y2}, ${b.x + NODE_W / 2 + 30} ${y2}, ${b.x + NODE_W / 2} ${y2}`, labelAt: { x: edgeX - 4, y: (y1 + y2) / 2 } };
  }
  if (key === "sql_policy>merge_results") {
    const left = a.x - NODE_W / 2;
    const edgeX = 16;
    return { d: `M ${left} ${a.y} C ${edgeX + 20} ${a.y}, ${edgeX} ${a.y + 40}, ${edgeX} ${a.y + 110} L ${edgeX} ${b.y - 40} C ${edgeX} ${b.y}, ${b.x - NODE_W / 2 - 30} ${b.y}, ${b.x - NODE_W / 2} ${b.y}`, labelAt: { x: edgeX + 6, y: (a.y + b.y) / 2 } };
  }
  if (edge.kind === "stop" && edge.to === "suggestions") {
    const edgeX = key.startsWith("hard_guard") ? 40 : 6;
    const startX = a.x - NODE_W / 2;
    const endX = b.x - NODE_W / 2;
    return { d: `M ${startX} ${a.y} C ${edgeX} ${a.y}, ${edgeX} ${b.y}, ${endX} ${b.y}`, labelAt: { x: edgeX + 4, y: a.y + 24 } };
  }
  const y1 = a.y + NODE_H / 2;
  const y2 = b.y - NODE_H / 2;
  const mid = (y1 + y2) / 2;
  return { d: `M ${a.x} ${y1} C ${a.x} ${mid}, ${b.x} ${mid}, ${b.x} ${y2}`, labelAt: { x: (a.x + b.x) / 2, y: mid } };
}
