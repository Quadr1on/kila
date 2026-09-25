// Chat API + a small SSE reader (fetch + ReadableStream; EventSource can't POST).

import { api, ApiError } from "./api";
import type { RouteDecision } from "./routerApi";

export type ModelRole = "small_text" | "large_text" | "coder" | "vision";

export type ChatSession = { id: string; title: string; created_at: string };

export type ReplyMeta = {
  role: ModelRole;
  model: string;
  backend: string;
  status: "ok" | "aborted" | "error";
  input_tokens: number | null;
  output_tokens: number | null;
  ttft_ms: number | null;
  latency_ms: number;
  tok_s: number | null;
  message_id?: number;
  ledger_seq?: number;
};

export type Source = {
  n: number;
  chunk_id: string;
  object_id: string;
  name: string;
  title: string;
  page: number;
  score: number;
  snippet: string;
};

export type Grounding = {
  sources: Source[];
  retrieval_relevance: number | null;
  retrieval_ms?: Record<string, number>;
  cited: number[];
  invalid: number[];
  uncited_answer: boolean;
};

export type ChatMessage = {
  id: number | string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
  meta: Partial<ReplyMeta> & {
    error?: string;
    stage?: "retrieving" | "routing";
    route?: RouteDecision;
    sources?: Source[]; // live, before `done` arrives
    grounding?: Grounding;
    attachments?: { object_id: string; name: string }[]; // user messages
    use_kb?: boolean;
  };
};

export type StreamEvent =
  | { event: "start"; data: { role: ModelRole; model: string; backend: string; source: string } }
  | { event: "status"; data: { stage: "retrieving" | "routing" } }
  | { event: "route"; data: RouteDecision }
  | { event: "sources"; data: { sources: Source[]; retrieval_relevance: number | null } }
  | { event: "delta"; data: { text: string } }
  | { event: "done"; data: ReplyMeta & { grounding?: Grounding; route?: RouteDecision } }
  | { event: "error"; data: { detail: string } };

export const chatApi = {
  sessions: () => api<ChatSession[]>("/chat/sessions"),
  create: () => api<ChatSession>("/chat/sessions", { method: "POST", body: JSON.stringify({}) }),
  messages: (id: string) => api<ChatMessage[]>(`/chat/sessions/${id}/messages`),
};

export async function streamReply(
  sessionId: string,
  content: string,
  role: ModelRole | "auto",
  onEvent: (e: StreamEvent) => void,
  signal: AbortSignal,
  grounding: { attachments?: string[]; useKb?: boolean } = {},
): Promise<void> {
  const res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ content, role, attachments: grounding.attachments ?? [], use_kb: !!grounding.useKb }),
    credentials: "same-origin",
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, String(detail));
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let cut: number;
    while ((cut = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, cut);
      buf = buf.slice(cut + 2);
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) onEvent({ event, data: JSON.parse(data) } as StreamEvent);
    }
  }
}
