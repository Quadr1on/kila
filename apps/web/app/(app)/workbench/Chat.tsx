"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css"; // bundled by Next with its fonts; no CDN
import { api, ApiError, formatTime, notifyLedgerChanged } from "@/lib/api";
import { chatApi, streamReply, type ChatMessage, type ChatSession, type ModelRole } from "@/lib/chat";
import { AttachmentChips, useAttachments } from "./attachments";
import { CiteChip, linkCitations, SourcesPanel } from "./citations";

type RoleInfo = { role: ModelRole; model: string; source: string };
const ROLE_LABEL: Record<ModelRole, string> = {
  small_text: "Small text",
  large_text: "Large text",
  coder: "Coder",
  vision: "Vision",
};

export function Chat() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [roles, setRoles] = useState<RoleInfo[]>([]);
  const [role, setRole] = useState<ModelRole>("small_text");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const attach = useAttachments();
  const [useKb, setUseKb] = useState(false);

  const loadRoles = useCallback(() => api<RoleInfo[]>("/models/roles").then(setRoles, () => undefined), []);

  useEffect(() => {
    chatApi.sessions().then(setSessions, () => setError("Can't load chats from the API."));
    loadRoles();
  }, [loadRoles]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  async function openSession(id: string) {
    if (busy) return;
    setActive(id);
    setError(null);
    setMessages(await chatApi.messages(id));
  }

  function newChat() {
    if (busy) return;
    setActive(null);
    setMessages([]);
    setError(null);
    inputRef.current?.focus();
  }

  async function send() {
    const content = draft.trim();
    if (!content || busy) return;
    if (attach.busy) {
      setError("Wait until the attached files are read and indexed.");
      return;
    }
    const attachments = attach.readyIds;
    const attachMeta = attach.items
      .filter((a) => a.state === "ready" && a.object_id)
      .map((a) => ({ object_id: a.object_id as string, name: a.name }));
    setBusy(true);
    setError(null);
    setDraft("");
    await loadRoles(); // pick up a hot-swap made on the Models page

    let sid = active;
    if (!sid) {
      const s = await chatApi.create();
      sid = s.id;
      setActive(s.id);
      setSessions((prev) => [{ ...s, title: content.split("\n")[0].slice(0, 80) }, ...prev]);
    }
    const pendingId = `pending-${Date.now()}`;
    setMessages((m) => [
      ...m,
      { id: `u-${Date.now()}`, role: "user", content, meta: { attachments: attachMeta, use_kb: useKb } },
      { id: pendingId, role: "assistant", content: "", meta: { role } },
    ]);
    const patch = (fn: (m: ChatMessage) => ChatMessage) =>
      setMessages((all) => all.map((m) => (m.id === pendingId ? fn(m) : m)));

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await streamReply(
        sid,
        content,
        role,
        (e) => {
          if (e.event === "start") patch((m) => ({ ...m, meta: { ...m.meta, model: e.data.model } }));
          else if (e.event === "status") patch((m) => ({ ...m, meta: { ...m.meta, stage: e.data.stage } }));
          else if (e.event === "sources")
            patch((m) => ({ ...m, meta: { ...m.meta, stage: undefined, sources: e.data.sources } }));
          else if (e.event === "delta") patch((m) => ({ ...m, content: m.content + e.data.text }));
          else if (e.event === "done") patch((m) => ({ ...m, meta: e.data }));
          else if (e.event === "error")
            patch((m) => ({ ...m, meta: { ...m.meta, stage: undefined, status: "error", error: e.data.detail } }));
        },
        ctrl.signal,
        { attachments, useKb },
      );
    } catch (e) {
      if (ctrl.signal.aborted) {
        patch((m) => ({ ...m, meta: { ...m.meta, status: "aborted" } }));
      } else {
        setError(e instanceof ApiError ? e.detail : "The reply stream was interrupted.");
        patch((m) => ({ ...m, meta: { ...m.meta, status: "error" } }));
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
      notifyLedgerChanged();
      inputRef.current?.focus();
    }
  }

  const current = roles.find((r) => r.role === role);

  return (
    <div className="mt-6 grid min-h-[560px] gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
      {/* Sessions */}
      <aside className="border border-rule bg-sheet lg:max-h-[calc(100vh-220px)] lg:overflow-y-auto">
        <div className="border-b border-rule p-3">
          <button
            type="button"
            onClick={newChat}
            disabled={busy}
            className="w-full border border-line px-3 py-1.5 text-sm hover:bg-sunk disabled:opacity-50"
          >
            New chat
          </button>
        </div>
        {sessions.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted">No chats yet. Your conversations are saved here.</p>
        ) : (
          <ul className="py-1">
            {sessions.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => openSession(s.id)}
                  aria-current={active === s.id ? "true" : undefined}
                  className={`block w-full border-l-2 px-3 py-2 text-left ${
                    active === s.id ? "border-control bg-sunk" : "border-transparent hover:bg-sunk/60"
                  }`}
                >
                  <span className="block truncate text-[13px]">{s.title || "Untitled"}</span>
                  <span className="block text-[11px] text-muted">{formatTime(s.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      {/* Thread */}
      <section className="flex min-w-0 flex-col border-[1.5px] border-line bg-sheet">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-4 py-2.5">
          <label className="flex items-center gap-2 text-sm">
            <span className="cell-label">Model role</span>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as ModelRole)}
              disabled={busy}
              className="border border-rule bg-ground/40 px-2 py-1 font-mono text-[13px] outline-none focus:border-control"
            >
              {(["small_text", "large_text", "coder"] as const).map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </select>
          </label>
          <p className="font-mono text-[12px] text-muted">
            {current ? (
              <>
                served by <span className="text-ink">{current.model}</span>
                {current.source === "activation" ? " (admin-activated)" : " (profile default)"}
              </>
            ) : (
              "loading model…"
            )}
            <span className="hidden sm:inline"> · routing by hand until phase 3</span>
          </p>
        </header>

        <div className="flex-1 space-y-5 overflow-y-auto px-4 py-5 lg:max-h-[calc(100vh-330px)]" aria-live="polite">
          {messages.length === 0 ? (
            <EmptyThread onPick={(t) => { setDraft(t); inputRef.current?.focus(); }} />
          ) : (
            messages.map((m) => <Turn key={m.id} m={m} streaming={busy && String(m.id).startsWith("pending")} />)
          )}
          <div ref={endRef} />
        </div>

        {error && (
          <p role="alert" className="mx-4 mb-2 border-l-2 border-alarm bg-alarm-wash px-3 py-2 text-sm">
            {error}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-rule px-3 pt-2.5">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={busy}
            className="border border-line px-2.5 py-1 text-[13px] hover:bg-sunk disabled:opacity-50"
          >
            Attach files
          </button>
          <input
            ref={fileRef}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files) attach.add(e.target.files);
              e.target.value = "";
            }}
          />
          <label className="flex items-center gap-2 text-[13px]">
            <input type="checkbox" checked={useKb} onChange={(e) => setUseKb(e.target.checked)} disabled={busy} />
            Search the knowledge base
          </label>
          {(useKb || attach.readyIds.length > 0) && (
            <span className="text-[12px] text-muted">Answers cite their sources as [S1], [S2]…</span>
          )}
          <div className="basis-full">
            <AttachmentChips items={attach.items} onRemove={busy ? undefined : attach.remove} />
          </div>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
          className="flex items-end gap-2 p-3"
        >
          <label className="sr-only" htmlFor="chat-input">
            Message
          </label>
          <textarea
            id="chat-input"
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={Math.min(8, Math.max(2, draft.split("\n").length))}
            placeholder="Ask about a procedure, a calculation or a piece of equipment. Enter to send, Shift+Enter for a new line."
            className="min-h-[52px] flex-1 resize-none border border-rule bg-ground/40 px-3 py-2 text-[14px] outline-none focus:border-control"
          />
          {busy ? (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              className="h-[52px] border border-alarm px-4 text-sm text-alarm hover:bg-alarm-wash"
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!draft.trim() || attach.busy}
              title={attach.busy ? "Waiting for attached files to be read" : undefined}
              className="h-[52px] bg-control px-5 font-medium text-control-ink disabled:opacity-50"
            >
              Send
            </button>
          )}
        </form>
      </section>
    </div>
  );
}

function Turn({ m, streaming }: { m: ChatMessage; streaming: boolean }) {
  if (m.role === "user") {
    const files = m.meta.attachments ?? [];
    return (
      <div className="ml-auto max-w-[80%] border border-rule bg-sunk px-3.5 py-2.5">
        <div className="cell-label mb-1">You</div>
        <p className="whitespace-pre-wrap text-[14px]">{m.content}</p>
        {(files.length > 0 || m.meta.use_kb) && (
          <p className="mt-1.5 flex flex-wrap gap-1.5 font-mono text-[11px] text-muted">
            {files.map((f) => (
              <Link key={f.object_id} href={`/files/${f.object_id}`} className="border border-rule px-1.5 hover:text-ink">
                {f.name}
              </Link>
            ))}
            {m.meta.use_kb && <span className="border border-rule px-1.5">knowledge base</span>}
          </p>
        )}
      </div>
    );
  }
  const meta = m.meta;
  const sources = meta.grounding?.sources ?? meta.sources ?? [];
  const grounded = !!meta.grounding || !!meta.sources || meta.stage === "retrieving";
  return (
    <div className="max-w-[88%]">
      <div className="cell-label mb-1">
        KILA{meta.model ? ` · ${meta.model}` : ""}
        {grounded ? " · answering from documents" : ""}
      </div>
      {meta.stage === "retrieving" && (
        <p className="text-sm text-muted">Searching the documents… (reranking takes a few seconds on CPU)</p>
      )}
      {m.content ? (
        <div className="kila-prose text-[14px]">
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[[rehypeKatex, { throwOnError: false }]]}
            components={{
              a: ({ href, children }) =>
                href?.startsWith("#cite-") ? (
                  <CiteChip n={Number(href.slice(6))} sources={sources} />
                ) : (
                  <a href={href}>{children}</a>
                ),
            }}
          >
            {linkCitations(normaliseMath(m.content))}
          </ReactMarkdown>
          {streaming && <span className="ml-0.5 inline-block h-4 w-2 translate-y-0.5 animate-pulse bg-ink/60" aria-hidden />}
        </div>
      ) : streaming && meta.status !== "error" && meta.stage !== "retrieving" ? (
        <p className="text-sm text-muted">Waiting for the model… the first reply after a swap includes loading it.</p>
      ) : null}
      {grounded && meta.stage !== "retrieving" && <SourcesPanel g={meta.grounding} live={meta.sources} />}
      {meta.status === "error" && (
        <p className="mt-1 border-l-2 border-alarm bg-alarm-wash px-3 py-2 text-sm">
          {meta.error ?? "The reply failed."}
        </p>
      )}
      {meta.status === "aborted" && <p className="mt-1 text-xs text-warn">Stopped. The partial reply was saved.</p>}
      {meta.status === "ok" && <MetaLine meta={meta} />}
    </div>
  );
}

function MetaLine({ meta }: { meta: ChatMessage["meta"] }) {
  const parts = [
    meta.output_tokens != null && `${meta.output_tokens} tokens`,
    meta.tok_s != null && `${meta.tok_s} tok/s`,
    meta.ttft_ms != null && `first token ${(meta.ttft_ms / 1000).toFixed(2)} s`,
  ].filter(Boolean);
  return (
    <p className="mt-1.5 font-mono text-[11px] text-muted">
      {parts.join(" · ")}
      {meta.ledger_seq != null && (
        <>
          {" · "}
          <Link href={`/sovereignty?seq=${meta.ledger_seq}`} className="text-control hover:underline">
            ledger #{meta.ledger_seq}
          </Link>
        </>
      )}
    </p>
  );
}

// Models emit \( \) and \[ \] as often as $ / $$; remark-math only understands dollars.
function normaliseMath(md: string): string {
  return md
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, x) => `\n$$${x}$$\n`)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, x) => `$${x}$`);
}

const STARTERS = [
  "Explain the difference between a PSV and a PRV in two sentences.",
  "What checks should precede a hot-work permit near a hydrocarbon line?",
  "Convert 12.5 bar(g) to kPa(a) and show the steps.",
];

function EmptyThread({ onPick }: { onPick: (t: string) => void }) {
  return (
    <div className="mx-auto max-w-[56ch] py-8">
      <p className="text-[15px]">
        Chat runs on the local model shown above. Nothing leaves this machine, and each reply is recorded in the audit
        ledger as hashes and token counts.
      </p>
      <p className="mt-2 text-sm text-muted">
        Attach a scanned report or tick <b>Search the knowledge base</b> to get answers that cite the exact page.
        Planning with tools and drafting documents come in phase 4.
      </p>
      <ul className="mt-5 space-y-2">
        {STARTERS.map((s) => (
          <li key={s}>
            <button
              type="button"
              onClick={() => onPick(s)}
              className="w-full border border-rule px-3 py-2 text-left text-sm hover:border-line hover:bg-sunk"
            >
              {s}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
