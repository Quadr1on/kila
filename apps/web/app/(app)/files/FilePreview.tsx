"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, formatBytes, formatTime, notifyLedgerChanged, shortMime, type LedgerEvent } from "@/lib/api";
import { storage, type StoredObject } from "@/lib/storage";

const TEXT_PREVIEW_BYTES = 20_000;

export function FilePreview({
  obj,
  canDelete,
  onDelete,
}: {
  obj: StoredObject | null;
  canDelete: boolean;
  onDelete: (o: StoredObject) => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [events, setEvents] = useState<LedgerEvent[]>([]);
  const [copied, setCopied] = useState(false);

  // Provenance is reloaded after the preview itself has been read, so that read shows up too.
  const loadTrail = useCallback(async (objectId: string) => {
    const evs = await api<LedgerEvent[]>(`/ledger/events?object_id=${objectId}&limit=50`);
    setEvents((prev) => (evs.length === prev.length && evs[0]?.seq === prev[0]?.seq ? prev : evs));
    notifyLedgerChanged();
  }, []);
  const onPreviewLoaded = () => obj && loadTrail(obj.object_id);

  useEffect(() => {
    setUrl(null);
    setText(null);
    setEvents([]);
    setCopied(false);
    if (!obj) return;
    let cancelled = false;
    (async () => {
      const signed = await storage.getSignedUrl(obj.object_id, 300);
      if (cancelled) return;
      setUrl(signed);
      if (isText(obj.mime)) {
        const body = await (await fetch(signed)).text();
        if (!cancelled) setText(body.slice(0, TEXT_PREVIEW_BYTES));
      }
      await loadTrail(obj.object_id);
    })().catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [obj, loadTrail]);

  if (!obj) {
    return (
      <aside className="border border-rule bg-sheet px-5 py-10 text-center text-muted xl:sticky xl:top-6 xl:self-start">
        Select a file to preview it and see its audit trail.
      </aside>
    );
  }

  return (
    <aside className="border-[1.5px] border-line bg-sheet xl:sticky xl:top-6 xl:self-start">
      <div className="border-b border-rule px-4 py-3">
        <h2 className="truncate font-medium" title={obj.original_name}>
          {obj.original_name}
        </h2>
        <p className="font-mono text-[12px] text-muted">
          {obj.bucket}/{obj.path}
        </p>
      </div>

      <div className="flex max-h-[520px] min-h-[180px] items-center justify-center overflow-auto bg-ground">
        {!url ? (
          <span className="text-sm text-muted">Loading preview…</span>
        ) : obj.mime.startsWith("image/") && obj.mime !== "image/svg+xml" ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt={obj.original_name} className="max-h-[520px] max-w-full object-contain" onLoad={onPreviewLoaded} />
        ) : obj.mime === "application/pdf" ? (
          <iframe src={url} title={obj.original_name} className="h-[520px] w-full border-0 bg-white" onLoad={onPreviewLoaded} />
        ) : text !== null ? (
          <pre className="h-full max-h-[520px] w-full overflow-auto whitespace-pre-wrap px-4 py-3 font-mono text-[12px] leading-relaxed">
            {text}
            {obj.size > TEXT_PREVIEW_BYTES && <span className="text-muted">{"\n"}… preview truncated</span>}
          </pre>
        ) : (
          <p className="px-6 py-8 text-center text-sm text-muted">
            No inline preview for {shortMime(obj.mime)} files yet. Download it to open locally.
          </p>
        )}
      </div>

      <dl className="grid grid-cols-2 border-t border-rule text-[13px]">
        <Meta label="Type" value={shortMime(obj.mime)} />
        <Meta label="Size" value={formatBytes(obj.size)} />
        <Meta label="Added" value={formatTime(obj.created_at)} />
        <Meta label="Object id" value={obj.object_id.slice(0, 12)} />
        <div className="col-span-2 border-b border-rule px-4 py-2">
          <dt className="cell-label">SHA-256</dt>
          <dd className="break-all font-mono text-[12px]">{obj.sha256}</dd>
        </div>
      </dl>

      <div className="flex flex-wrap gap-2 px-4 py-3">
        <a
          href={`/api/storage/object/${obj.object_id}`}
          download={obj.original_name}
          className="border border-line px-3 py-1 text-sm hover:bg-sunk"
          onClick={() => setTimeout(notifyLedgerChanged, 800)}
        >
          Download
        </a>
        <button
          type="button"
          className="border border-line px-3 py-1 text-sm hover:bg-sunk"
          onClick={async () => {
            await navigator.clipboard.writeText(obj.sha256);
            setCopied(true);
          }}
        >
          {copied ? "Copied" : "Copy SHA-256"}
        </button>
        {canDelete && (
          <button
            type="button"
            className="ml-auto px-3 py-1 text-sm text-alarm hover:underline"
            onClick={() => onDelete(obj)}
          >
            Remove
          </button>
        )}
      </div>

      <section className="border-t border-rule px-4 py-3">
        <h3 className="cell-label">Audit trail for this file</h3>
        {events.length === 0 ? (
          <p className="mt-1 text-sm text-muted">Loading ledger entries…</p>
        ) : (
          <ol className="mt-2 space-y-1">
            {events.map((e) => (
              <li key={e.seq} className="grid grid-cols-[auto_1fr_auto] items-baseline gap-3 text-[12px]">
                <Link href={`/sovereignty?seq=${e.seq}`} className="font-mono text-control hover:underline">
                  #{e.seq}
                </Link>
                <span className="truncate">
                  <span className="font-mono">{e.event_type}</span>
                  <span className="text-muted"> · {e.actor}</span>
                </span>
                <span className="text-muted">{formatTime(e.ts)}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </aside>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-b border-r border-rule px-4 py-2 even:border-r-0">
      <dt className="cell-label">{label}</dt>
      <dd className="truncate font-mono text-[12px]">{value}</dd>
    </div>
  );
}

function isText(mime: string) {
  return mime.startsWith("text/") || mime === "application/json";
}
