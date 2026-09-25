"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useUser } from "@/components/UserContext";
import { ApiError, formatTime, notifyLedgerChanged } from "@/lib/api";
import { kbApi, type Hit, type KbDoc, type OcrLang, type SearchResult } from "@/lib/docs";
import { storage } from "@/lib/storage";
import { DropZone } from "../files/DropZone";

const TYPE_LABEL: Record<string, string> = {
  procedure: "Procedure",
  standard: "Standard",
  guide: "Guide",
  inspection_report: "Inspection report",
  spreadsheet: "Spreadsheet",
  code: "Code",
  document: "Document",
};

export function KnowledgeBase() {
  const user = useUser();
  const canWrite = user.role !== "reviewer";
  const [docs, setDocs] = useState<KbDoc[] | null>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "alarm"; text: string } | null>(null);
  const [lang, setLang] = useState<OcrLang>("en");
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setDocs(await kbApi.documents());
    } catch (e) {
      setMsg({ tone: "alarm", text: e instanceof ApiError ? e.detail : "Can't load the knowledge base." });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while anything is still being read or indexed.
  const busy = docs?.some((d) => d.status === "pending" || d.status === "indexing");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [busy, load]);

  async function upload(files: FileList | File[]) {
    setMsg(null);
    let n = 0;
    for (const f of Array.from(files)) {
      try {
        const obj = await storage.from("kb").upload(f);
        await kbApi.index(obj.object_id, lang);
        n++;
      } catch (e) {
        setMsg({ tone: "alarm", text: `${f.name}: ${e instanceof ApiError ? e.detail : "upload failed"}` });
      }
    }
    if (n) setMsg({ tone: "ok", text: `${n} file${n > 1 ? "s" : ""} added. Reading and indexing runs in the background.` });
    await load();
    notifyLedgerChanged();
  }

  async function seed() {
    setMsg(null);
    try {
      const r = await kbApi.seed();
      setMsg({
        tone: "ok",
        text: r.queued.length
          ? `Loading ${r.queued.length} synthetic demo documents (scans are OCR'd; about a minute on CPU).`
          : "The demo corpus is already loaded.",
      });
      await load();
      notifyLedgerChanged();
    } catch (e) {
      setMsg({ tone: "alarm", text: e instanceof ApiError ? e.detail : "Couldn't load the demo corpus." });
    }
  }

  async function reindex(d: KbDoc) {
    await kbApi.index(d.object_id, lang);
    await load();
  }

  async function remove(d: KbDoc) {
    if (!window.confirm(`Remove "${d.name}" from the knowledge base? It stays in the audit trail.`)) return;
    await kbApi.remove(d.object_id);
    await load();
    notifyLedgerChanged();
  }

  return (
    <div className="mt-6 space-y-6">
      {canWrite && (
        <section>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <label className="block">
              <span className="cell-label">Language of scanned documents</span>
              <select
                value={lang}
                onChange={(e) => setLang(e.target.value as OcrLang)}
                className="mt-1 block border border-rule bg-ground/40 px-2 py-1 text-sm outline-none focus:border-control"
              >
                <option value="en">English</option>
                <option value="hi">Hindi (Devanagari OCR)</option>
                <option value="kn">Kannada (vision model only)</option>
              </select>
            </label>
            {user.role === "admin" && (
              <button type="button" onClick={seed} className="border border-line px-3 py-1.5 text-sm hover:bg-sheet">
                Load demo corpus
              </button>
            )}
          </div>
          <DropZone bucket="kb" onFiles={upload} onPick={() => inputRef.current?.click()} />
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files) upload(e.target.files);
              e.target.value = "";
            }}
          />
        </section>
      )}

      {msg && (
        <p
          role={msg.tone === "alarm" ? "alert" : "status"}
          className={`border-l-2 px-3 py-2 text-sm ${msg.tone === "ok" ? "border-ok bg-ok-wash" : "border-alarm bg-alarm-wash"}`}
        >
          {msg.text}
        </p>
      )}

      <Documents docs={docs} canWrite={canWrite} onReindex={reindex} onRemove={remove} />
      <Playground ready={!!docs?.some((d) => d.status === "indexed")} />
    </div>
  );
}

function StatusChip({ d }: { d: KbDoc }) {
  if (d.status === "indexed") return <span className="text-ok">indexed</span>;
  if (d.status === "error")
    return (
      <span className="text-alarm" title={d.error ?? ""}>
        failed
      </span>
    );
  const ing = d.ingestion;
  if (ing && (ing.status === "queued" || ing.status === "running"))
    return (
      <span className="text-warn">
        reading{ing.pages_total ? ` ${ing.pages_done ?? 0}/${ing.pages_total}` : "…"}
      </span>
    );
  return <span className="text-warn">{d.status === "indexing" ? "indexing…" : "queued"}</span>;
}

function Documents({
  docs,
  canWrite,
  onReindex,
  onRemove,
}: {
  docs: KbDoc[] | null;
  canWrite: boolean;
  onReindex: (d: KbDoc) => void;
  onRemove: (d: KbDoc) => void;
}) {
  if (docs === null) return <div className="border border-rule bg-sheet px-4 py-8 text-center text-muted">Loading documents…</div>;
  if (docs.length === 0)
    return (
      <div className="border border-rule bg-sheet px-4 py-8 text-center">
        <p className="font-medium">The knowledge base is empty</p>
        <p className="mt-1 text-sm text-muted">Add SOPs, standards and past reports above. Admins can load the synthetic demo corpus.</p>
      </div>
    );
  const indexed = docs.filter((d) => d.status === "indexed");
  return (
    <section className="border border-rule bg-sheet">
      <div className="flex flex-wrap justify-between gap-2 border-b border-rule px-4 py-2">
        <span className="cell-label">Documents</span>
        <span className="font-mono text-[12px] text-muted">
          {indexed.length}/{docs.length} indexed · {indexed.reduce((n, d) => n + d.chunk_count, 0)} passages
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-[13px]">
          <thead>
            <tr className="border-b border-rule">
              <th className="cell-label px-4 py-2 font-normal">Document</th>
              <th className="cell-label px-3 py-2 font-normal">Type</th>
              <th className="cell-label px-3 py-2 font-normal">Status</th>
              <th className="cell-label px-3 py-2 text-right font-normal">Passages</th>
              <th className="cell-label px-3 py-2 font-normal">Indexed</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.object_id} className="group border-b border-rule last:border-b-0 hover:bg-sunk/60">
                <td className="max-w-[340px] px-4 py-2">
                  <Link href={`/files/${d.object_id}`} className="block truncate hover:underline" title={d.title}>
                    {d.title}
                  </Link>
                  <span className="block truncate font-mono text-[11px] text-muted">{d.name}</span>
                </td>
                <td className="px-3 py-2 text-muted">{TYPE_LABEL[d.doc_type] ?? d.doc_type}</td>
                <td className="px-3 py-2 font-mono text-[12px]">
                  <StatusChip d={d} />
                </td>
                <td className="tabular px-3 py-2 text-right font-mono text-[12px]">{d.chunk_count || "—"}</td>
                <td className="whitespace-nowrap px-3 py-2 text-[12px] text-muted">
                  {d.indexed_at ? formatTime(d.indexed_at) : "—"}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right">
                  {canWrite && (
                    <span className="reveal-actions inline-flex gap-3 text-[12px]">
                      <button type="button" onClick={() => onReindex(d)} className="text-control hover:underline">
                        Re-index
                      </button>
                      <button type="button" onClick={() => onRemove(d)} className="text-alarm hover:underline">
                        Remove
                      </button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const EXAMPLES = [
  "What is the popping pressure tolerance for a PSV set below 5 bar(g)?",
  "corrosion rate at nozzle N3 of E-2104",
  "How often is the hot work area re-tested for gas?",
];

function Playground({ ready }: { ready: boolean }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [focus, setFocus] = useState<string | null>(null);

  async function run(query = q) {
    if (!query.trim()) return;
    setQ(query);
    setBusy(true);
    setError(null);
    try {
      setRes(await kbApi.search(query));
      notifyLedgerChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Search failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="pg-h" className="border-[1.5px] border-line bg-sheet">
      <div className="border-b border-rule px-4 py-3">
        <h2 id="pg-h" className="font-display text-xl font-semibold uppercase tracking-[0.04em]">
          Search playground
        </h2>
        <p className="text-sm text-muted">
          See every stage of retrieval: meaning-based (dense) search, keyword (BM25) search, their fusion, and the
          reranker&apos;s final order. Hover a passage to find it in the other columns.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run();
          }}
          className="mt-3 flex gap-2"
        >
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={ready ? "Ask something the documents answer…" : "Index some documents first"}
            disabled={!ready}
            className="min-w-0 flex-1 border border-rule bg-ground/40 px-3 py-2 outline-none focus:border-control disabled:opacity-60"
          />
          <button type="submit" disabled={!ready || busy || !q.trim()} className="bg-control px-5 font-medium text-control-ink disabled:opacity-50">
            {busy ? "Searching…" : "Search"}
          </button>
        </form>
        {ready && !res && (
          <div className="mt-2 flex flex-wrap gap-2">
            {EXAMPLES.map((e) => (
              <button key={e} type="button" onClick={() => run(e)} className="border border-rule px-2 py-1 text-[12px] hover:border-line">
                {e}
              </button>
            ))}
          </div>
        )}
        {busy && <p className="mt-2 text-[12px] text-muted">Reranking on CPU takes a few seconds per query.</p>}
      </div>

      {error && <p role="alert" className="mx-4 my-3 border-l-2 border-alarm bg-alarm-wash px-3 py-2 text-sm">{error}</p>}

      {res && (
        <>
          <Timings res={res} />
          <div className="grid gap-px bg-rule md:grid-cols-2 2xl:grid-cols-4">
            <Column title="Dense (bge-m3)" note="meaning similarity" hits={res.dense} focus={focus} setFocus={setFocus} />
            <Column title="Keyword (BM25)" note="exact terms and tags" hits={res.bm25} focus={focus} setFocus={setFocus} />
            <Column title="Fused (RRF)" note="agreement between the two" hits={res.fused} focus={focus} setFocus={setFocus} />
            <Column
              title="Reranked"
              note={
                res.rerank.enabled
                  ? `${res.rerank.model} on ${res.rerank.device}, top ${res.rerank.candidates} of fused`
                  : "reranker off"
              }
              hits={res.reranked}
              focus={focus}
              setFocus={setFocus}
              final
            />
          </div>
        </>
      )}
    </section>
  );
}

function Timings({ res }: { res: SearchResult }) {
  const t = res.timings_ms;
  const parts: [string, number | undefined][] = [
    ["embed query", t.embed_query_ms],
    ["dense", t.dense_ms],
    ["BM25", t.bm25_ms],
    ["rerank", t.rerank_ms],
  ];
  return (
    <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 border-b border-rule px-4 py-2 font-mono text-[12px]">
      <span>
        relevance{" "}
        <span className="text-ink">{res.retrieval_relevance != null ? res.retrieval_relevance.toFixed(2) : "—"}</span>
      </span>
      {parts.map(([k, v]) =>
        v != null ? (
          <span key={k} className="text-muted">
            {k} {v < 1000 ? `${v.toFixed(0)} ms` : `${(v / 1000).toFixed(2)} s`}
          </span>
        ) : null,
      )}
      <span className="text-muted">
        total <span className="text-ink">{(t.total_ms / 1000).toFixed(2)} s</span> · embedder on {res.embedder.device}
      </span>
    </div>
  );
}

function Column({
  title,
  note,
  hits,
  focus,
  setFocus,
  final,
}: {
  title: string;
  note: string;
  hits: Hit[];
  focus: string | null;
  setFocus: (id: string | null) => void;
  final?: boolean;
}) {
  return (
    <div className="min-w-0 bg-sheet">
      <div className="border-b border-rule px-3 py-2">
        <div className={`text-sm font-medium ${final ? "text-control" : ""}`}>{title}</div>
        <div className="text-[11px] text-muted">{note}</div>
      </div>
      {hits.length === 0 ? (
        <p className="px-3 py-4 text-sm text-muted">No matches.</p>
      ) : (
        <ol>
          {hits.slice(0, 8).map((h) => (
            <li
              key={h.chunk_id}
              onMouseEnter={() => setFocus(h.chunk_id)}
              onMouseLeave={() => setFocus(null)}
              className={`border-b border-rule px-3 py-2 last:border-b-0 ${focus === h.chunk_id ? "bg-sunk" : ""}`}
            >
              <div className="flex items-baseline justify-between gap-2 text-[12px]">
                <Link href={`/files/${h.object_id}?page=${h.page}`} className="min-w-0 truncate text-control hover:underline">
                  {h.rank}. {h.name} · p{h.page}
                </Link>
                <span className="shrink-0 font-mono text-muted">{h.score.toFixed(h.score < 0.1 ? 4 : 3)}</span>
              </div>
              <p className="mt-0.5 line-clamp-3 text-[12px] text-muted">{h.text}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
