// Chat API + a small SSE reader (fetch + ReadableStream; EventSource can't POST).

import { api, ApiError } from "./api";

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

export type ChatMessage = {
  id: number | string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
  meta: Partial<ReplyMeta> & { error?: string };
};

export type StreamEvent =
  | { event: "start"; data: { role: ModelRole; model: string; backend: string; source: string } }
  | { event: "delta"; data: { text: string } }
  | { event: "done"; data: ReplyMeta }
  | { event: "error"; data: { detail: string } };

export const chatApi = {
  sessions: () => api<ChatSession[]>("/chat/sessions"),
  create: () => api<ChatSession>("/chat/sessions", { method: "POST", body: JSON.stringify({}) }),
  messages: (id: string) => api<ChatMessage[]>(`/chat/sessions/${id}/messages`),
};

export async function streamReply(
  sessionId: string,
  content: string,
  role: ModelRole,
  onEvent: (e: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ content, role }),
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
