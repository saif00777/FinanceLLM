import { getApiKey } from "@/lib/apiKey";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

/** Backend route outcomes — see app/agents/text_to_sql/workflow.py. */
export type ChatRoute = "answered" | "clarify" | "repair" | "abstain";

/** Graph node names as emitted by MultiAgentWorkflow.stream_answer — see workflow.py's _build_graph(). */
export type GraphNode =
  | "hard_guard"
  | "domain_guard"
  | "document_router"
  | "document_retrieval"
  | "planner"
  | "schema_link"
  | "metric_resolver"
  | "mcc_resolver"
  | "sql_generator"
  | "sql_policy"
  | "executor"
  | "data_analysis"
  | "analyst"
  | "reviewer"
  | "merge_results"
  | "suggestions";

export interface ChartSpec {
  type: "bar" | "line";
  x: string;
  y: string;
}

export interface AnalysisPayload {
  summary?: string;
  insights?: string[];
  caveats?: string[];
}

/** A cited source: for bank documents `source_hash` is the document id (e.g. FS-03) and the rest describe it. */
export interface Citation {
  source_hash: string;
  title?: string;
  doc_type?: string;
  category?: string;
  date?: string;
  [key: string]: unknown;
}

export interface ChatResponse {
  request_id: string;
  conversation_id: string;
  answer: string;
  sql: string | null;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  chart: ChartSpec | null;
  analysis: AnalysisPayload | null;
  suggested_questions: string[];
  route: ChatRoute;
  citations: Citation[];
  assumptions: string[];
}

export interface StreamChatCallbacks {
  onProgress: (node: GraphNode) => void;
  onThought: (node: GraphNode, text: string) => void;
  onResult: (response: ChatResponse) => void;
  /** `code` is set for errors the UI can act on, e.g. "invalid_api_key" or "missing_api_key". */
  onError: (message: string, requestId?: string, code?: string) => void;
}

function dispatchSseBlock(block: string, callbacks: StreamChatCallbacks): void {
  let eventName = "message";
  let dataLine = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) eventName = line.slice("event: ".length).trim();
    else if (line.startsWith("data: ")) dataLine = line.slice("data: ".length);
  }
  if (!dataLine) return;

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(dataLine);
  } catch {
    return;
  }

  if (eventName === "progress" && typeof payload.node === "string") {
    callbacks.onProgress(payload.node as GraphNode);
  } else if (eventName === "thought" && typeof payload.node === "string" && typeof payload.text === "string") {
    callbacks.onThought(payload.node as GraphNode, payload.text);
  } else if (eventName === "result") {
    callbacks.onResult(payload as unknown as ChatResponse);
  } else if (eventName === "error") {
    callbacks.onError(
      typeof payload.message === "string" ? payload.message : "The analysis request could not be completed.",
      payload.request_id as string | undefined,
      typeof payload.code === "string" ? payload.code : undefined,
    );
  }
}

function authHeaders(): Record<string, string> {
  const key = getApiKey();
  return key ? { "X-OpenAI-Key": key } : {};
}

export type KeyCheckCode =
  | "ok"
  | "bad_format"
  | "invalid_key"
  | "no_quota"
  | "rate_limited"
  | "no_model_access"
  | "network"
  | "error"
  | "too_many_attempts"
  | "unreachable";

export interface KeyCheckResult {
  valid: boolean;
  code: KeyCheckCode;
  message: string;
  checks: { name: string; ok: boolean }[];
}

/** Asks the backend to test the key with real OpenAI calls. Resolves (never throws) so the UI can show a reason. */
export async function validateApiKey(apiKey: string, signal?: AbortSignal): Promise<KeyCheckResult> {
  try {
    // Never spin forever: give up after 25s (the backend's own OpenAI calls time out at 20s each).
    const timeout = AbortSignal.timeout(25_000);
    const response = await fetch(`${API_BASE_URL}/api/validate-key`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    });
    if (response.status === 429) {
      return { valid: false, code: "too_many_attempts", message: "Too many attempts. Wait a minute and try again.", checks: [] };
    }
    if (!response.ok) {
      return { valid: false, code: "error", message: "The server could not check the key. Please try again.", checks: [] };
    }
    return (await response.json()) as KeyCheckResult;
  } catch (error) {
    if (signal?.aborted) throw error; // the caller left the page; not a failure to report
    return { valid: false, code: "unreachable", message: "Could not reach the backend in time. Check that it is running and try again.", checks: [] };
  }
}

/** Streams a chat turn over SSE, invoking callbacks as progress/result/error events arrive. */
export async function streamChatMessage(
  question: string,
  conversationId: string | null,
  callbacks: StreamChatCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ question, conversation_id: conversationId }),
      signal,
    });
  } catch {
    callbacks.onError("Could not reach the analysis backend. Check that it's running and reachable.");
    return;
  }

  if (!response.ok || !response.body) {
    callbacks.onError("The analysis request could not be completed. Please try again.");
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      dispatchSseBlock(buffer.slice(0, boundary), callbacks);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
  }
}
