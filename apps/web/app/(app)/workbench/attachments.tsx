"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, notifyLedgerChanged } from "@/lib/api";
import { kbApi, type KbDoc } from "@/lib/docs";
import { storage } from "@/lib/storage";

export type AttachmentItem = {
  key: string;
  object_id?: string;
  name: string;
  state: "uploading" | "reading" | "indexing" | "ready" | "error";
  detail?: string;
};

/** Upload -> read (OCR) -> index, tracked per file until it can ground an answer. */
export function useAttachments() {
  const [items, setItems] = useState<AttachmentItem[]>([]);
  const itemsRef = useRef(items);
  itemsRef.current = items;

  const patch = (key: string, p: Partial<AttachmentItem>) =>
    setItems((all) => all.map((a) => (a.key === key ? { ...a, ...p } : a)));

  async function add(files: FileList | File[]) {
    for (const f of Array.from(files)) {
      const key = `${Date.now()}-${f.name}`;
      setItems((all) => [...all, { key, name: f.name, state: "uploading" }]);
      try {
        const obj = await storage.from("uploads").upload(f);
        await kbApi.index(obj.object_id);
        patch(key, { object_id: obj.object_id, state: "reading" });
        notifyLedgerChanged();
      } catch (e) {
        patch(key, { state: "error", detail: e instanceof ApiError ? e.detail : "upload failed" });
      }
    }
  }

  const poll = useCallback(async () => {
    for (const a of itemsRef.current) {
      if (!a.object_id || a.state === "ready" || a.state === "error") continue;
      try {
        const d = await api<KbDoc & { status: KbDoc["status"] | "none" }>(`/kb/documents/${a.object_id}`);
        if (d.status === "indexed") patch(a.key, { state: "ready", detail: `${d.chunk_count} passages` });
        else if (d.status === "error") patch(a.key, { state: "error", detail: d.error ?? "could not be read" });
        else if (d.status === "indexing") patch(a.key, { state: "indexing", detail: undefined });
        else {
          const ing = d.ingestion;
          const pages = ing?.pages_total ? `page ${Math.min((ing.pages_done ?? 0) + 1, ing.pages_total)}/${ing.pages_total}` : undefined;
          patch(a.key, { state: "reading", detail: pages });
        }
      } catch {
        /* transient; try again next tick */
      }
    }
  }, []);

  const pending = items.some((a) => a.object_id && (a.state === "reading" || a.state === "indexing"));
  useEffect(() => {
    if (!pending) return;
    const t = setInterval(poll, 1200);
    return () => clearInterval(t);
  }, [pending, poll]);

  return {
    items,
    add,
    remove: (key: string) => setItems((all) => all.filter((a) => a.key !== key)),
    clear: () => setItems([]),
    readyIds: items.filter((a) => a.state === "ready" && a.object_id).map((a) => a.object_id as string),
    busy: items.some((a) => a.state === "uploading" || a.state === "reading" || a.state === "indexing"),
  };
}

const STATE_LABEL: Record<AttachmentItem["state"], string> = {
  uploading: "uploading",
  reading: "reading",
  indexing: "indexing",
  ready: "ready",
  error: "failed",
};

export function AttachmentChips({ items, onRemove }: { items: AttachmentItem[]; onRemove?: (key: string) => void }) {
  if (!items.length) return null;
  return (
    <ul className="flex flex-wrap gap-2" aria-live="polite">
      {items.map((a) => (
        <li
          key={a.key}
          className={`flex max-w-full items-center gap-2 border px-2 py-1 text-[12px] ${
            a.state === "error" ? "border-alarm" : a.state === "ready" ? "border-rule" : "border-warn"
          }`}
          title={a.detail}
        >
          <span className="truncate">{a.name}</span>
          <span
            className={`shrink-0 font-mono ${a.state === "ready" ? "text-ok" : a.state === "error" ? "text-alarm" : "text-warn"}`}
          >
            {STATE_LABEL[a.state]}
            {a.detail && a.state !== "error" ? ` · ${a.detail}` : ""}
          </span>
          {onRemove && (
            <button type="button" onClick={() => onRemove(a.key)} aria-label={`Remove ${a.name}`} className="text-muted hover:text-ink">
              ×
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
