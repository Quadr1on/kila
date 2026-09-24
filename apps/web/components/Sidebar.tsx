"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { CURRENT_PHASE, NAV, type NavItem } from "@/lib/nav";
import { useUser } from "./UserContext";

const GROUPS: NavItem["group"][] = ["Work", "Plant", "Assurance"];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const user = useUser();
  const [open, setOpen] = useState(false);

  useEffect(() => setOpen(false), [pathname]);

  async function signOut() {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      router.push("/login");
      router.refresh();
    }
  }

  return (
    <>
      {/* Mobile bar */}
      <div className="flex items-center justify-between border-b border-rule bg-sheet px-4 py-3 md:hidden">
        <Wordmark />
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls="kila-nav"
          className="border border-line px-3 py-1 font-mono text-xs uppercase tracking-wider"
        >
          {open ? "Close" : "Menu"}
        </button>
      </div>

      <nav
        id="kila-nav"
        aria-label="Main"
        className={`${open ? "flex" : "hidden"} w-full flex-col border-r border-rule bg-sheet md:sticky md:top-0 md:flex md:h-screen md:w-60 md:shrink-0`}
      >
        <div className="hidden border-b border-rule px-5 py-5 md:block">
          <Wordmark />
        </div>

        <div className="flex-1 overflow-y-auto px-3 py-4">
          {GROUPS.map((g) => (
            <div key={g} className="mb-5">
              <div className="cell-label px-2 pb-1.5">{g}</div>
              <ul>
                {NAV.filter((n) => n.group === g).map((n) => {
                  const active = pathname === n.href || pathname.startsWith(`${n.href}/`);
                  const planned = n.livePhase > CURRENT_PHASE;
                  return (
                    <li key={n.href}>
                      <Link
                        href={n.href}
                        aria-current={active ? "page" : undefined}
                        className={`group flex items-center justify-between border-l-2 px-2.5 py-1.5 ${
                          active
                            ? "border-control bg-sunk font-medium text-ink"
                            : "border-transparent text-muted hover:border-rule hover:text-ink"
                        }`}
                      >
                        <span>{n.label}</span>
                        {planned && (
                          <span className="font-mono text-[10px] text-muted" title={`Built in phase ${n.livePhase}`}>
                            P{n.livePhase}
                          </span>
                        )}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>

        <div className="border-t border-rule px-5 py-4">
          <div className="flex items-baseline justify-between">
            <span className="font-medium">{user.name}</span>
            <span className="cell-label">{user.role}</span>
          </div>
          <button type="button" onClick={signOut} className="mt-2 text-sm text-control hover:underline">
            Sign out
          </button>
        </div>
      </nav>
    </>
  );
}

function Wordmark() {
  return (
    <Link href="/workbench" className="flex items-baseline gap-2">
      <span className="font-display text-2xl font-semibold leading-none tracking-[0.18em]">KILA</span>
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted">on-prem</span>
    </Link>
  );
}
