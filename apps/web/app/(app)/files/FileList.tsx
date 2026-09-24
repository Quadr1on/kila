"use client";

import { useState } from "react";
import { CheckIcon, CopyIcon, DownloadIcon, TrashIcon } from "@/components/icons";
import { formatBytes, formatTime, notifyLedgerChanged, shortMime } from "@/lib/api";
import type { StoredObject } from "@/lib/storage";

export type ViewMode = "list" | "grid";

type Props = {
  objects: StoredObject[] | null;
  selected: StoredObject | null;
  onSelect: (o: StoredObject) => void;
  onDelete: (o: StoredObject) => void;
  canDelete: boolean;
  bucket: string;
  view: ViewMode;
};

export function FileList(props: Props) {
  const { objects, bucket, view } = props;
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
  return view === "grid" ? <GridView {...props} objects={objects} /> : <ListView {...props} objects={objects} />;
}

// ------------------------------------------------------------------ list

// thumb | name | type | size | sha | added | actions
const LIST_COLS =
  "grid grid-cols-[44px_minmax(0,1fr)_auto] md:grid-cols-[44px_minmax(0,1fr)_64px_76px_auto] 2xl:grid-cols-[44px_minmax(0,1fr)_64px_76px_112px_168px_auto]";

function ListView({ objects, selected, onSelect, onDelete, canDelete }: Props & { objects: StoredObject[] }) {
  return (
    <div className="border border-rule bg-sheet">
      <div className={`${LIST_COLS} items-center gap-x-3 border-b border-rule px-3 py-2`} aria-hidden>
        <span />
        <span className="cell-label">Name</span>
        <span className="cell-label hidden md:block">Type</span>
        <span className="cell-label hidden text-right md:block">Size</span>
        <span className="cell-label hidden 2xl:block">SHA-256</span>
        <span className="cell-label hidden 2xl:block">Added</span>
        <span className="cell-label w-[104px] text-right">Actions</span>
      </div>
      <ul>
        {objects.map((o) => {
          const active = selected?.object_id === o.object_id;
          return (
            <li
              key={o.object_id}
              onClick={() => onSelect(o)}
              className={`group ${LIST_COLS} cursor-pointer items-center gap-x-3 border-b border-l-2 border-b-rule px-3 py-1.5 transition-colors last:border-b-0 ${
                active ? "border-l-control bg-sunk" : "border-l-transparent hover:bg-sunk/60"
              }`}
            >
              <Thumb obj={o} className="h-10 w-10" />
              <div className="min-w-0">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelect(o);
                  }}
                  aria-current={active ? "true" : undefined}
                  className={`block max-w-full truncate text-left text-[13px] ${active ? "font-medium" : ""}`}
                >
                  {o.original_name}
                </button>
                <div className="truncate text-xs text-muted">
                  {o.path !== o.original_name ? o.path : formatTime(o.created_at)}
                  <span className="md:hidden"> · {formatBytes(o.size)}</span>
                </div>
              </div>
              <span className="hidden font-mono text-[12px] text-muted md:block">{shortMime(o.mime)}</span>
              <span className="tabular hidden whitespace-nowrap text-right font-mono text-[12px] md:block">
                {formatBytes(o.size)}
              </span>
              <span className="hidden truncate font-mono text-[12px] text-muted 2xl:block" title={o.sha256}>
                {o.sha256.slice(0, 12)}
              </span>
              <span className="hidden whitespace-nowrap text-[12px] text-muted 2xl:block">{formatTime(o.created_at)}</span>
              <div className="w-[104px] overflow-hidden py-0.5">
                <FileActions obj={o} canDelete={canDelete} onDelete={onDelete} className="reveal-actions justify-end" />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ------------------------------------------------------------------ grid

function GridView({ objects, selected, onSelect, onDelete, canDelete }: Props & { objects: StoredObject[] }) {
  return (
    <ul className="grid grid-cols-[repeat(auto-fill,minmax(168px,1fr))] gap-3">
      {objects.map((o) => {
        const active = selected?.object_id === o.object_id;
        return (
          <li
            key={o.object_id}
            onClick={() => onSelect(o)}
            className={`group cursor-pointer border bg-sheet transition-colors ${
              active ? "border-control shadow-[inset_0_0_0_1px_var(--control)]" : "border-rule hover:border-line"
            }`}
          >
            <div className="relative aspect-[4/3] overflow-hidden border-b border-rule bg-ground">
              <Thumb obj={o} className="h-full w-full" large />
              {/* action bar slides up from the bottom edge of the thumbnail */}
              <div className="absolute inset-x-0 bottom-0">
                <FileActions
                  obj={o}
                  canDelete={canDelete}
                  onDelete={onDelete}
                  className="reveal-actions justify-center border-t border-rule bg-sheet/95 py-1 backdrop-blur-[2px]"
                />
              </div>
            </div>
            <div className="px-2.5 py-2">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(o);
                }}
                aria-current={active ? "true" : undefined}
                className={`block max-w-full truncate text-left text-[13px] ${active ? "font-medium" : ""}`}
                title={o.original_name}
              >
                {o.original_name}
              </button>
              <div className="mt-0.5 flex justify-between gap-2 font-mono text-[11px] text-muted">
                <span>{shortMime(o.mime)}</span>
                <span className="tabular">{formatBytes(o.size)}</span>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// ------------------------------------------------------------------ shared

function Thumb({ obj, className, large }: { obj: StoredObject; className: string; large?: boolean }) {
  return (
    <div className={`flex items-center justify-center overflow-hidden border border-rule bg-ground ${className} ${large ? "border-0" : ""}`}>
      {obj.thumbnail_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={`/api${obj.thumbnail_url}`}
          alt=""
          className={`h-full w-full ${large ? "object-contain p-2" : "object-cover"}`}
        />
      ) : (
        <span className={`font-mono uppercase text-muted ${large ? "text-lg tracking-wider" : "text-[10px]"}`}>
          {extOf(obj.original_name)}
        </span>
      )}
    </div>
  );
}

export function FileActions({
  obj,
  canDelete,
  onDelete,
  className = "",
}: {
  obj: StoredObject;
  canDelete: boolean;
  onDelete: (o: StoredObject) => void;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();

  async function copy(e: React.MouseEvent) {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(obj.sha256);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked (e.g. insecure context); nothing to do */
    }
  }

  return (
    <div className={`flex items-center gap-1 ${className}`} onClick={stop}>
      <a
        href={`/api/storage/object/${obj.object_id}`}
        download={obj.original_name}
        onClick={(e) => {
          stop(e);
          setTimeout(notifyLedgerChanged, 800);
        }}
        className={ICON_BTN}
        aria-label={`Download ${obj.original_name}`}
        title="Download"
      >
        <DownloadIcon />
      </a>
      <button
        type="button"
        onClick={copy}
        className={`${ICON_BTN} ${copied ? "text-ok" : ""}`}
        aria-label={copied ? "SHA-256 copied" : `Copy SHA-256 of ${obj.original_name}`}
        title={copied ? "Copied" : "Copy SHA-256"}
      >
        {copied ? <CheckIcon /> : <CopyIcon />}
      </button>
      {canDelete && (
        <button
          type="button"
          onClick={(e) => {
            stop(e);
            onDelete(obj);
          }}
          className={`${ICON_BTN} hover:border-alarm hover:text-alarm`}
          aria-label={`Remove ${obj.original_name}`}
          title="Remove"
        >
          <TrashIcon />
        </button>
      )}
    </div>
  );
}

const ICON_BTN =
  "flex h-8 w-8 items-center justify-center border border-transparent text-muted transition-colors hover:border-line hover:bg-sheet hover:text-ink";

function extOf(name: string) {
  const i = name.lastIndexOf(".");
  return i > 0 ? name.slice(i + 1, i + 5) : "file";
}
