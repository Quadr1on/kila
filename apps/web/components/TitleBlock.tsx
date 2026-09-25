"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, LEDGER_CHANGED } from "@/lib/api";
import { navFor } from "@/lib/nav";
import { useUser } from "./UserContext";

const APP_REV = "0.1";

/**
 * Page header drawn as the title block of an engineering drawing. Every cell carries
 * a real value: drawing number = page, drawn by = signed-in user, ledger = live chain head.
 */
export function TitleBlock({ title, subtitle }: { title?: string; subtitle?: string }) {
  const pathname = usePathname();
  const nav = navFor(pathname);
  const user = useUser();
  const [head, setHead] = useState<{ length: number; head_hash: string } | null>(null);

  const load = useCallback(() => {
    api<{ length: number; head_hash: string }>("/ledger/head").then(setHead, () => setHead(null));
  }, []);

  useEffect(() => {
    load();
    window.addEventListener(LEDGER_CHANGED, load);
    return () => window.removeEventListener(LEDGER_CHANGED, load);
  }, [load]);

  return (
    <header className="border-[1.5px] border-line bg-sheet">
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_auto]">
        <div className="flex min-w-0 flex-col justify-end gap-1 px-5 py-4 xl:border-r-[1.5px] xl:border-line">
          <h1 className="break-words font-display text-[34px] font-semibold uppercase leading-none tracking-[0.04em]">
            {title ?? nav?.label}
          </h1>
          <p className="max-w-[62ch] text-muted">{subtitle ?? nav?.summary}</p>
        </div>

        <dl className="grid grid-cols-2 gap-px border-t-[1.5px] border-line bg-rule sm:grid-cols-3 xl:w-[520px] xl:border-t-0">
          <Cell label="Dwg no" value={nav?.dwg ?? "—"} />
          <Cell label="Rev" value={APP_REV} />
          <Cell label="Drawn by" value={user.name === user.role ? user.name : `${user.name} · ${user.role}`} />
          <Cell label="Class" value="Confidential" />
          <Cell
            label="Audit ledger"
            wide
            value={
              head ? (
                <span className="flex items-baseline gap-2">
                  <span className="tabular">{head.length.toLocaleString()} events</span>
                  <span className="truncate text-muted" title={head.head_hash}>
                    head {head.head_hash.slice(0, 10)}…
                  </span>
                </span>
              ) : (
                <span className="text-muted">unavailable</span>
              )
            }
          />
        </dl>
      </div>
    </header>
  );
}

function Cell({ label, value, wide }: { label: string; value: React.ReactNode; wide?: boolean }) {
  // Grid lines come from the dl's 1px gap over the rule colour, like ruled cells on a drawing.
  return (
    <div className={`min-w-0 bg-sheet px-3 py-2 ${wide ? "col-span-2" : ""}`}>
      <dt className="cell-label">{label}</dt>
      <dd className="truncate font-mono text-[13px]">{value}</dd>
    </div>
  );
}
