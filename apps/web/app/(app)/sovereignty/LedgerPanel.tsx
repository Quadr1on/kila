"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useUser } from "@/components/UserContext";
import {
  api,
  ApiError,
  formatTime,
  LEDGER_CHANGED,
  notifyLedgerChanged,
  type LedgerEvent,
  type VerifyResult,
} from "@/lib/api";

const PAGE = 100;

export function LedgerPanel() {
  const user = useUser();
  const params = useSearchParams();
  const focusSeq = Number(params.get("seq")) || null;

  const [events, setEvents] = useState<LedgerEvent[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [verify, setVerify] = useState<(VerifyResult & { at: string }) | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadLatest = useCallback(async () => {
    try {
      // When deep-linked to an old seq, load enough rows to include it.
      const head = await api<{ length: number }>("/ledger/head");
      const need = focusSeq ? Math.min(1000, Math.max(PAGE, head.length - focusSeq + 10)) : PAGE;
      const evs = await api<LedgerEvent[]>(`/ledger/events?limit=${need}`);
      setEvents(evs);
      setHasMore(evs.length === need && evs[evs.length - 1]?.seq > 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Can't load the ledger.");
    }
  }, [focusSeq]);

  async function loadOlder() {
    if (!events?.length) return;
    const before = events[events.length - 1].seq;
    const older = await api<LedgerEvent[]>(`/ledger/events?limit=${PAGE}&before_seq=${before}`);
    setEvents([...events, ...older]);
    setHasMore(older.length === PAGE);
  }

  const runVerify = useCallback(async () => {
    setVerifying(true);
    try {
      const r = await api<VerifyResult>("/ledger/verify");
      setVerify({ ...r, at: new Date().toISOString() });
      notifyLedgerChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Verification request failed.");
    } finally {
      setVerifying(false);
    }
  }, []);

  useEffect(() => {
    loadLatest();
    window.addEventListener(LEDGER_CHANGED, loadLatest);
    return () => window.removeEventListener(LEDGER_CHANGED, loadLatest);
  }, [loadLatest]);

  return (
    <div className="mt-6 grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <section aria-labelledby="ledger-h" className="order-2 min-w-0 xl:order-1">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="ledger-h" className="font-display text-xl font-semibold uppercase tracking-[0.04em]">
            Tamper-evident audit ledger
          </h2>
          <p className="text-sm text-muted">Newest first. Hashes are SHA-256 over the previous hash and the event.</p>
        </div>
        {error && (
          <p role="alert" className="mt-3 border-l-2 border-alarm bg-alarm-wash px-3 py-2 text-sm">
            {error}
          </p>
        )}
        <LedgerTable events={events} badSeq={verify && !verify.ok ? verify.first_bad_seq : null} focusSeq={focusSeq} />
        {hasMore && (
          <button type="button" onClick={loadOlder} className="mt-3 text-sm text-control hover:underline">
            Load older entries
          </button>
        )}
      </section>

      <div className="order-1 grid content-start gap-5 md:grid-cols-2 xl:sticky xl:top-6 xl:order-2 xl:grid-cols-1 xl:self-start">
        <VerifyCard verify={verify} verifying={verifying} onVerify={runVerify} />
        <IsolationCard />
        {user.role === "admin" && <AdminTools events={events} onChanged={runVerify} />}
      </div>
    </div>
  );
}

function VerifyCard({
  verify,
  verifying,
  onVerify,
}: {
  verify: (VerifyResult & { at: string }) | null;
  verifying: boolean;
  onVerify: () => void;
}) {
  const tone = !verify ? "idle" : verify.ok ? "ok" : "alarm";
  return (
    <section
      aria-live="polite"
      className={`border-[1.5px] ${
        tone === "ok" ? "border-ok bg-ok-wash" : tone === "alarm" ? "border-alarm bg-alarm-wash" : "border-line bg-sheet"
      }`}
    >
      <div className="px-4 py-3">
        <div className="cell-label">Chain integrity</div>
        {!verify && <p className="mt-1 text-[15px]">Not checked in this session.</p>}
        {verify?.ok && (
          <>
            <p className="mt-1 font-display text-2xl font-semibold uppercase tracking-[0.04em] text-ok">Intact</p>
            <p className="text-sm">
              All <span className="tabular font-mono">{verify.length.toLocaleString()}</span> entries recomputed and
              match.
            </p>
          </>
        )}
        {verify && !verify.ok && (
          <>
            <p className="mt-1 font-display text-2xl font-semibold uppercase tracking-[0.04em] text-alarm">
              Broken at #{verify.first_bad_seq}
            </p>
            <p className="text-sm">{verify.reason}.</p>
            <p className="mt-1 text-sm">
              Entries from #{verify.first_bad_seq} onward can&apos;t be trusted until the row is restored.
            </p>
          </>
        )}
        {verify && (
          <p className="mt-2 break-all font-mono text-[11px] text-muted">
            head {verify.head_hash} · checked {formatTime(verify.at)}
          </p>
        )}
      </div>
      <div className="border-t border-rule px-4 py-3">
        <button
          type="button"
          onClick={onVerify}
          disabled={verifying}
          className="bg-control px-4 py-1.5 font-medium text-control-ink disabled:opacity-60"
        >
          {verifying ? "Verifying…" : "Verify chain"}
        </button>
      </div>
    </section>
  );
}

function IsolationCard() {
  return (
    <section className="border border-dashed border-rule bg-sheet px-4 py-3">
      <div className="cell-label">Network isolation</div>
      <p className="mt-1 text-[15px]">Untested</p>
      <p className="mt-1 text-sm text-muted">
        The egress self-test (DNS, TCP and HTTPS probes that must all fail) is built in phase 7. Until then this page makes
        no claim about isolation.
      </p>
    </section>
  );
}

function AdminTools({ events, onChanged }: { events: LedgerEvent[] | null; onChanged: () => void }) {
  const defaultSeq = events?.find((e) => e.event_type === "storage.upload")?.seq ?? events?.[events.length - 1]?.seq;
  const [seq, setSeq] = useState<string>("");
  const [msg, setMsg] = useState<string | null>(null);
  const target = Number(seq || defaultSeq || 1);

  async function tamper() {
    setMsg(null);
    try {
      await api("/ledger/debug/tamper", { method: "POST", body: JSON.stringify({ seq: target }) });
      setMsg(`Row #${target} edited directly in SQLite. Verify the chain to see the break.`);
      onChanged();
    } catch (e) {
      setMsg(e instanceof ApiError ? e.detail : "Tamper request failed.");
    }
  }

  async function restore() {
    const r = await api<{ restored: number[] }>("/ledger/debug/restore", { method: "POST" });
    setMsg(r.restored.length ? `Restored row${r.restored.length > 1 ? "s" : ""} #${r.restored.join(", #")}.` : "Nothing to restore.");
    onChanged();
  }

  async function exportSigned() {
    const snap = await api<unknown>("/ledger/export");
    const blob = new Blob([JSON.stringify(snap, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `kila-ledger-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "")}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    notifyLedgerChanged();
  }

  return (
    <section className="border-[1.5px] border-line bg-sheet">
      <div className="border-b border-rule px-4 py-3">
        <div className="cell-label">Admin · tamper demo</div>
        <p className="mt-1 text-sm">
          Edits one ledger row straight in the SQLite file, the way someone with disk access could. The app&apos;s writer
          is bypassed; verification should catch it.
        </p>
        <div className="mt-3 flex items-end gap-2">
          <label className="block">
            <span className="cell-label">Row</span>
            <input
              inputMode="numeric"
              value={seq}
              placeholder={String(defaultSeq ?? 1)}
              onChange={(e) => setSeq(e.target.value.replace(/\D/g, ""))}
              className="mt-1 block w-24 border border-rule bg-ground/40 px-2 py-1.5 font-mono text-sm outline-none focus:border-control"
            />
          </label>
          <button type="button" onClick={tamper} className="whitespace-nowrap border border-alarm px-3 py-1.5 text-sm text-alarm hover:bg-alarm-wash">
            Edit row #{target}
          </button>
          <button type="button" onClick={restore} className="px-2 py-1.5 text-sm text-control hover:underline">
            Restore
          </button>
        </div>
        {msg && <p className="mt-2 text-sm text-muted">{msg}</p>}
      </div>
      <div className="px-4 py-3">
        <div className="cell-label">Audit export</div>
        <p className="mt-1 text-sm text-muted">Full ledger with a manifest signed by this node&apos;s ed25519 key.</p>
        <button type="button" onClick={exportSigned} className="mt-2 border border-line px-3 py-1 text-sm hover:bg-sunk">
          Download signed snapshot
        </button>
      </div>
    </section>
  );
}

function LedgerTable({
  events,
  badSeq,
  focusSeq,
}: {
  events: LedgerEvent[] | null;
  badSeq: number | null;
  focusSeq: number | null;
}) {
  const focusRef = useRef<HTMLTableRowElement>(null);
  useEffect(() => {
    focusRef.current?.scrollIntoView({ block: "center" });
  }, [events, focusSeq]);

  if (events === null) {
    return <div className="mt-3 border border-rule bg-sheet px-4 py-10 text-center text-muted">Loading ledger…</div>;
  }
  return (
    <div className="mt-3 overflow-x-auto border border-rule bg-sheet">
      <table className="w-full min-w-[760px] text-left text-[12.5px]">
        <thead>
          <tr className="border-b border-rule">
            <th className="cell-label px-3 py-2 text-right font-normal">Seq</th>
            <th className="cell-label px-3 py-2 font-normal">Time</th>
            <th className="cell-label px-3 py-2 font-normal">Actor</th>
            <th className="cell-label px-3 py-2 font-normal">Event</th>
            <th className="cell-label px-3 py-2 font-normal">Detail</th>
            <th className="cell-label px-3 py-2 font-normal">Hash</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => {
            const bad = badSeq === e.seq;
            const focused = focusSeq === e.seq;
            return (
              <tr
                key={e.seq}
                ref={focused ? focusRef : undefined}
                className={`border-b border-rule align-top last:border-b-0 ${
                  bad ? "bg-alarm-wash" : focused ? "bg-sunk outline outline-1 -outline-offset-1 outline-control" : ""
                }`}
              >
                <td className={`tabular px-3 py-1.5 text-right font-mono ${bad ? "font-medium text-alarm" : ""}`}>
                  {e.seq}
                </td>
                <td className="whitespace-nowrap px-3 py-1.5 text-muted">{formatTime(e.ts)}</td>
                <td className="px-3 py-1.5">{e.actor}</td>
                <td className="whitespace-nowrap px-3 py-1.5 font-mono">{e.event_type}</td>
                <td className="max-w-[320px] px-3 py-1.5 text-muted">
                  <span className="line-clamp-2 break-all font-mono text-[11.5px]">{summarise(e.payload)}</span>
                </td>
                <td className="px-3 py-1.5 font-mono text-[11.5px] text-muted" title={`prev ${e.prev_hash}\nhash ${e.hash}`}>
                  {e.hash.slice(0, 10)}
                  {bad && <div className="font-sans text-[11px] text-alarm">content no longer matches</div>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function summarise(p: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(p)) {
    if (k === "sha256" && typeof v === "string") parts.push(`sha ${v.slice(0, 10)}`);
    else if (typeof v === "object" && v !== null) parts.push(`${k}=${JSON.stringify(v)}`);
    else parts.push(`${k}=${String(v)}`);
  }
  return parts.join(" · ") || "—";
}
