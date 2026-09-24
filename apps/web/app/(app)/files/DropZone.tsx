"use client";

import { useEffect, useState } from "react";
import { UploadIcon } from "@/components/icons";

function hasFiles(e: DragEvent | React.DragEvent) {
  return Array.from(e.dataTransfer?.types ?? []).includes("Files");
}

/**
 * Large drop target. When a file is dragged anywhere over the window the zone "arms" and
 * grows smoothly so it's easy to hit; directly over it, it lights up. Clicking opens the picker.
 */
export function DropZone({
  bucket,
  onFiles,
  onPick,
}: {
  bucket: string;
  onFiles: (files: FileList) => void;
  onPick: () => void;
}) {
  const [armed, setArmed] = useState(false);
  const [hot, setHot] = useState(false);

  useEffect(() => {
    let depth = 0; // dragenter/leave fire for every child element; count to know when we really left
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth += 1;
      setArmed(true);
    };
    const leave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setArmed(false);
    };
    // Stop the browser from navigating to a file dropped outside the zone.
    const over = (e: DragEvent) => hasFiles(e) && e.preventDefault();
    const reset = (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault();
      depth = 0;
      setArmed(false);
      setHot(false);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", over);
    window.addEventListener("drop", reset);
    window.addEventListener("dragend", reset);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", reset);
      window.removeEventListener("dragend", reset);
    };
  }, []);

  const state = hot ? "hot" : armed ? "armed" : "idle";

  return (
    <button
      type="button"
      onClick={onPick}
      onDragOver={(e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
        setHot(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setHot(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setHot(false);
        setArmed(false);
        if (e.dataTransfer.files.length) onFiles(e.dataTransfer.files);
      }}
      data-state={state}
      className={`mt-4 flex w-full flex-col items-center justify-center gap-2 border-[1.5px] border-dashed px-6 text-center transition-[min-height,background-color,border-color,color] duration-300 ease-out ${
        state === "idle"
          ? "min-h-[150px] border-rule text-muted hover:border-line hover:text-ink"
          : state === "armed"
            ? "min-h-[260px] border-control/60 bg-sheet text-ink"
            : "min-h-[260px] border-control bg-sheet text-ink shadow-[inset_0_0_0_3px_var(--control)]"
      }`}
    >
      <span
        className={`flex h-10 w-10 items-center justify-center border border-current transition-transform duration-300 ease-out ${
          state === "idle" ? "" : "-translate-y-1 scale-110"
        }`}
      >
        <UploadIcon width={18} height={18} />
      </span>
      <span className="text-[15px] font-medium text-ink">
        {state === "hot"
          ? `Release to add to ${bucket}`
          : state === "armed"
            ? "Drop the files here"
            : "Drop files here, or click to choose"}
      </span>
      <span className="max-w-[60ch] text-sm">
        Scans, PDFs, spreadsheets or code go into <span className="font-mono">{bucket}</span>. Each file is hashed
        (SHA-256), stored once, and recorded in the audit ledger.
      </span>
    </button>
  );
}
