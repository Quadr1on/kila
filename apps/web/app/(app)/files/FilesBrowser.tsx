"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { GridIcon, ListIcon } from "@/components/icons";
import { ApiError, notifyLedgerChanged } from "@/lib/api";
import { storage, type BucketInfo, type BucketName, type StoredObject } from "@/lib/storage";
import { DropZone } from "./DropZone";
import { FileList, type ViewMode } from "./FileList";
import { FilePreview } from "./FilePreview";

const HIDDEN_BUCKETS: BucketName[] = ["thumbnails"]; // derived previews, not user files
const ORDER: BucketName[] = ["uploads", "kb", "pid", "deliverables", "models"];

const VIEW_KEY = "kila.files.view";

type UploadRow = { key: string; name: string; state: "uploading" | "done" | "error"; detail?: string };

export function FilesBrowser() {
  const [buckets, setBuckets] = useState<BucketInfo[]>([]);
  const [bucket, setBucket] = useState<BucketName>("uploads");
  const [objects, setObjects] = useState<StoredObject[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<StoredObject | null>(null);
  const [uploads, setUploads] = useState<UploadRow[]>([]);
  const [view, setView] = useState<ViewMode>("list");
  const inputRef = useRef<HTMLInputElement>(null);

  // View preference is a per-browser convenience; storage may be unavailable.
  useEffect(() => {
    try {
      const v = localStorage.getItem(VIEW_KEY);
      if (v === "list" || v === "grid") setView(v);
    } catch {
      /* ignore */
    }
  }, []);
  function chooseView(v: ViewMode) {
    setView(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* ignore */
    }
  }

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
        <div className="mb-2 flex items-center gap-2">
          <div role="group" aria-label="View" className="flex border border-rule">
            {(["list", "grid"] as const).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                aria-label={v === "list" ? "List view" : "Grid view"}
                title={v === "list" ? "List view" : "Grid view"}
                onClick={() => chooseView(v)}
                className={`flex h-8 w-8 items-center justify-center transition-colors ${
                  view === v ? "bg-sunk text-ink" : "text-muted hover:text-ink"
                }`}
              >
                {v === "list" ? <ListIcon /> : <GridIcon />}
              </button>
            ))}
          </div>
          {current?.can_write && (
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="h-8 bg-control px-4 font-medium text-control-ink"
            >
              Upload files
            </button>
          )}
        </div>
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
        <DropZone bucket={bucket} onFiles={uploadFiles} onPick={() => inputRef.current?.click()} />
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
        <FileList
          objects={objects}
          selected={selected}
          onSelect={setSelected}
          onDelete={remove}
          canDelete={!!current?.can_write}
          bucket={bucket}
          view={view}
        />
        <FilePreview
          obj={selected}
          canDelete={!!current?.can_write}
          onDelete={remove}
        />
      </div>
    </div>
  );
}
