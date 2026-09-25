"use client";

import Link from "next/link";
import { useState } from "react";
import type { Grounding, Source } from "@/lib/chat";

/** Turn [S1] markers into markdown links the renderer can recognise. */
export function linkCitations(md: string): string {
  return md.replace(/\[S(\d+)\](?!\()/g, "[S$1](#cite-$1)");
}

export function CiteChip({ n, sources }: { n: number; sources: Source[] }) {
  const s = sources.find((x) => x.n === n);
  if (!s) {
    return (
      <span className="mx-0.5 border border-alarm px-1 font-mono text-[11px] text-alarm" title="This citation points to no source">
        S{n}?
      </span>
    );
  }
  return (
    <Link
      href={`/files/${s.object_id}?page=${s.page}`}
      className="mx-0.5 inline-block border border-control/50 px-1 align-baseline font-mono text-[11px] leading-[1.35] text-control no-underline hover:bg-sunk"
      title={`${s.name}, page ${s.page}: ${s.snippet.slice(0, 160)}…`}
    >
      S{n}
    </Link>
  );
}

export function SourcesPanel({ g, live }: { g?: Grounding; live?: Source[] }) {
  const sources = g?.sources ?? live ?? [];
  const [open, setOpen] = useState<number | null>(null);
  if (!sources.length) {
    return g ? <p className="mt-2 text-xs text-warn">No matching passages were found in the documents.</p> : null;
  }
  const cited = new Set(g?.cited ?? []);
  return (
    <div className="mt-2 border border-rule">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-rule px-3 py-1.5">
        <span className="cell-label">Sources</span>
        {g?.retrieval_relevance != null && (
          <span className="font-mono text-[11px] text-muted">best relevance {g.retrieval_relevance.toFixed(2)}</span>
        )}
      </div>
      <ol>
        {sources.map((s) => {
          const used = !g || cited.has(s.n);
          return (
            <li key={s.n} className="border-b border-rule last:border-b-0">
              <button
                type="button"
                onClick={() => setOpen(open === s.n ? null : s.n)}
                aria-expanded={open === s.n}
                className={`flex w-full items-baseline gap-2 px-3 py-1.5 text-left text-[12px] hover:bg-sunk/60 ${used ? "" : "opacity-60"}`}
              >
                <span className="font-mono text-control">S{s.n}</span>
                <span className="min-w-0 flex-1 truncate">
                  {s.name} · page {s.page}
                </span>
                <span className="font-mono text-muted">{s.score.toFixed(2)}</span>
                {g && !used && <span className="text-muted">not cited</span>}
              </button>
              {open === s.n && (
                <div className="px-3 pb-2">
                  <p className="whitespace-pre-wrap border-l-2 border-rule pl-2 font-mono text-[11.5px] text-muted">{s.snippet}</p>
                  <Link href={`/files/${s.object_id}?page=${s.page}`} className="mt-1 inline-block text-[12px] text-control hover:underline">
                    Open page {s.page} of {s.name}
                  </Link>
                </div>
              )}
            </li>
          );
        })}
      </ol>
      {g && (g.invalid.length > 0 || g.uncited_answer) && (
        <p className="border-t border-rule bg-warn-wash px-3 py-1.5 text-[12px]">
          {g.uncited_answer
            ? "The answer cites no source. Treat it as unverified."
            : `Citation${g.invalid.length > 1 ? "s" : ""} ${g.invalid.map((n) => `S${n}`).join(", ")} point to no source.`}
        </p>
      )}
    </div>
  );
}
