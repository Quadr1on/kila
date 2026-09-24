"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, formatBytes, formatTime, notifyLedgerChanged, shortMime } from "@/lib/api";
import { storage, type BucketInfo, type BucketName, type StoredObject } from "@/lib/storage";
import { FilePreview } from "./FilePreview";

const HIDDEN_BUCKETS: BucketName[] = ["thumbnails"]; // derived previews, not user files
const ORDER: BucketName[] = ["uploads", "kb", "pid", "deliverables", "models"];

type UploadRow = { key: string; name: string; state: "uploading" | "done" | "error"; detail?: string };

export function FilesBrowser() {
  const [buckets, setBuckets] = useState<BucketInfo[]>([]);
  const [bucket, setBucket] = useState<BucketName>("uploads");
  const [objects, setObjects] = useState<StoredObject[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<StoredObject | null>(null);
  const [uploads, setUploads] = useState<UploadRow[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const current = buckets.find((b) => b.name === bucket);

  useEffect(() => {
    storage.buckets().then(
      (bs) =>
        setBuckets(
          bs
            .filter((b) => b.can_read && !HIDDEN_BUCKETS.includes(b.name))
            .sort((a, b) => ORDER.indexOf(a.name) - ORDER.indexOf(b.name)),
        ),
      () => setLoadError("Can't load buckets from the API."),
    );
  }, []);

  const refresh = useCallback(async () => {
    try {
      setObjects(await storage.from(bucket).list());
      setLoadError(null);
    } catch (e) {
      setObjects([]);
      setLoadError(e instanceof ApiError ? e.detail : "Can't load files.");
    }
  }, [bucket]);

  useEffect(() => {
    setObjects(null);
    setSelected(null);
    refresh();
  }, [refresh]);

  async function uploadFiles(files: FileList | File[]) {
    const list = Array.from(files);
    if (!list.length) return;
    const rows = list.map((f, i) => ({ key: `${Date.now()}-${i}`, name: f.name, state: "uploading" as const }));
    setUploads((u) => [...rows, ...u].slice(0, 8));
    let last: StoredObject | null = null;
    for (const [i, file] of list.entries()) {
      try {
        last = await storage.from(bucket).upload(file);
        setUploads((u) => u.map((r) => (r.key === rows[i].key ? { ...r, state: "done" } : r)));
      } catch (e) {
        const detail = e instanceof ApiError ? e.detail : "Upload failed";
        setUploads((u) => u.map((r) => (r.key === rows[i].key ? { ...r, state: "error", detail } : r)));
      }
    }
    await refresh();
    if (last) setSelected(last);
    notifyLedgerChanged();
  }

  async function remove(obj: StoredObject) {
    if (!window.confirm(`Remove "${obj.original_name}" from ${bucket}? It stays in the audit trail.`)) return;
    try {
      await storage.remove(obj.object_id);
      setSelected(null);
      await refresh();
      notifyLedgerChanged();
    } catch (e) {
      window.alert(e instanceof ApiError ? e.detail : "Couldn't remove the file.");
    }
  }

  return (
    <div className="mt-6">
      {/* Bucket selector + upload */}
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-rule">
        <div role="tablist" aria-label="Buckets" className="-mb-px flex flex-wrap">
          {buckets.map((b) => (
            <button
              key={b.name}
              role="tab"
              type="button"
              aria-selected={b.name === bucket}
              onClick={() => setBucket(b.name)}
              className={`border-b-2 px-3 py-2 font-mono text-[13px] ${
                b.name === bucket ? "border-control text-ink" : "border-transparent text-muted hover:text-ink"
              }`}
            >
              {b.name}
            </button>
          ))}
        </div>
        {current?.can_write && (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="mb-2 bg-control px-4 py-1.5 font-medium text-control-ink"
          >
            Upload files
          </button>
        )}
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files) uploadFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {current?.can_write ? (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            uploadFiles(e.dataTransfer.files);
          }}
          className={`mt-4 border border-dashed px-4 py-3 text-sm ${
            dragging ? "border-control bg-sheet text-ink" : "border-rule text-muted"
          }`}
        >
          Drop scans, PDFs, spreadsheets or code here to add them to <span className="font-mono">{bucket}</span>. Each
          file is hashed (SHA-256), stored once, and recorded in the audit ledger.
        </div>
      ) : (
        current && (
          <p className="mt-4 text-sm text-muted">
            You can view files in <span className="font-mono">{bucket}</span>. Adding them needs an engineer or admin
            account.
          </p>
        )
      )}

      {uploads.length > 0 && (
        <ul className="mt-3 space-y-1 font-mono text-[12px]" aria-live="polite">
          {uploads.map((u) => (
            <li key={u.key} className="flex gap-3">
              <span
                className={
                  u.state === "done" ? "text-ok" : u.state === "error" ? "text-alarm" : "text-warn"
                }
              >
                {u.state === "done" ? "stored" : u.state === "error" ? "failed" : "uploading"}
              </span>
              <span className="truncate">{u.name}</span>
              {u.detail && <span className="text-alarm">{u.detail}</span>}
            </li>
          ))}
        </ul>
      )}

      {loadError && (
        <p role="alert" className="mt-4 border-l-2 border-alarm bg-alarm-wash px-3 py-2 text-sm">
          {loadError}
        </p>
      )}

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
        <ObjectTable objects={objects} selected={selected} onSelect={setSelected} bucket={bucket} />
        <FilePreview
          obj={selected}
          canDelete={!!current?.can_write}
          onDelete={remove}
        />
      </div>
    </div>
  );
}

function ObjectTable({
  objects,
  selected,
  onSelect,
  bucket,
}: {
  objects: StoredObject[] | null;
  selected: StoredObject | null;
  onSelect: (o: StoredObject) => void;
  bucket: string;
}) {
  if (objects === null) {
    return <div className="border border-rule bg-sheet px-4 py-10 text-center text-muted">Loading files…</div>;
  }
  if (objects.length === 0) {
    return (
      <div className="border border-rule bg-sheet px-4 py-10 text-center">
        <p className="font-medium">No files in {bucket} yet</p>
        <p className="mt-1 text-sm text-muted">Upload a scanned report or drawing to see its preview and audit trail.</p>
      </div>
    );
  }
  return (
    <div className="overflow-x-auto border border-rule bg-sheet">
      <table className="w-full min-w-[640px] text-left text-[13px]">
        <thead>
          <tr className="border-b border-rule">
            <th className="cell-label w-14 px-3 py-2 font-normal" aria-label="Preview" />
            <th className="cell-label px-3 py-2 font-normal">Name</th>
            <th className="cell-label px-3 py-2 font-normal">Type</th>
            <th className="cell-label px-3 py-2 text-right font-normal">Size</th>
            <th className="cell-label px-3 py-2 font-normal">SHA-256</th>
            <th className="cell-label px-3 py-2 font-normal">Added</th>
          </tr>
        </thead>
        <tbody>
          {objects.map((o) => {
            const active = selected?.object_id === o.object_id;
            return (
              <tr
                key={o.object_id}
                onClick={() => onSelect(o)}
                className={`cursor-pointer border-b border-rule last:border-b-0 ${
                  active ? "bg-sunk" : "hover:bg-sunk/60"
                }`}
              >
                <td className="px-3 py-1.5">
                  <div className="flex h-10 w-10 items-center justify-center overflow-hidden border border-rule bg-ground">
                    {o.thumbnail_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={`/api${o.thumbnail_url}`} alt="" className="h-full w-full object-cover" />
                    ) : (
                      <span className="font-mono text-[10px] uppercase text-muted">{extOf(o.original_name)}</span>
                    )}
                  </div>
                </td>
                <td className="max-w-[280px] px-3 py-1.5">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelect(o);
                    }}
                    className={`block truncate text-left ${active ? "font-medium" : ""}`}
                  >
                    {o.original_name}
                  </button>
                  {o.path !== o.original_name && <div className="truncate text-xs text-muted">{o.path}</div>}
                </td>
                <td className="px-3 py-1.5 font-mono text-[12px] text-muted">{shortMime(o.mime)}</td>
                <td className="tabular whitespace-nowrap px-3 py-1.5 text-right font-mono text-[12px]">{formatBytes(o.size)}</td>
                <td className="px-3 py-1.5 font-mono text-[12px] text-muted" title={o.sha256}>
                  {o.sha256.slice(0, 12)}
                </td>
                <td className="whitespace-nowrap px-3 py-1.5 text-[12px] text-muted">{formatTime(o.created_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function extOf(name: string) {
  const i = name.lastIndexOf(".");
  return i > 0 ? name.slice(i + 1, i + 5) : "file";
}
