"use client";

import { useCallback, useEffect, useState } from "react";
import { useUser } from "@/components/UserContext";
import { api, ApiError, formatBytes, formatTime, notifyLedgerChanged } from "@/lib/api";

type Warmup = {
  ts: string;
  tok_s: number | null;
  load_ms: number | null;
  was_resident: boolean | null;
  wall_ms: number;
  evicted?: string[];
  last_cold: { ts: string; load_ms: number; evicted?: string[] } | null;
};
type Candidate = { name: string; licence?: string; note?: string; pulled: boolean; loaded: boolean };
type RoleView = {
  role: string;
  model: string;
  backend: string;
  source: "activation" | "default";
  licence?: string;
  note?: string;
  reachable: boolean;
  pulled: boolean;
  loaded: { size: number; size_vram: number } | null;
  warmup: Warmup | null;
  candidates: Candidate[];
};
type Overview = {
  profile: string;
  notes: string;
  gpu: {
    available: boolean;
    reason?: string;
    gpus?: { name: string; vram_used_mib: number; vram_total_mib: number; driver: string; utilization_pct: number }[];
  };
  backends: Record<string, { base_url: string; reachable: boolean; error?: string; loaded: Record<string, { size_vram: number }> }>;
  roles: RoleView[];
};

const ROLE_LABEL: Record<string, string> = {
  small_text: "Small text",
  large_text: "Large text",
  coder: "Coder",
  vision: "Vision",
};

export function ModelsPanel() {
  const user = useUser();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<Record<string, { tone: "ok" | "alarm"; text: string }>>({});

  const load = useCallback(async () => {
    try {
      setData(await api<Overview>("/models"));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Can't load the model plane.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function run(role: string, label: string, fn: () => Promise<void>) {
    setBusy((b) => ({ ...b, [role]: label }));
    setMsg((m) => ({ ...m, [role]: undefined as never }));
    try {
      await fn();
    } catch (e) {
      setMsg((m) => ({ ...m, [role]: { tone: "alarm", text: e instanceof ApiError ? e.detail : "Request failed." } }));
    } finally {
      setBusy((b) => {
        const { [role]: _, ...rest } = b;
        return rest;
      });
      await load();
      notifyLedgerChanged();
    }
  }

  const warm = (role: string) =>
    run(role, "Warming up…", async () => {
      const r = await api<Warmup & { model: string }>(`/models/${role}/warmup`, { method: "POST" });
      setMsg((m) => ({
        ...m,
        [role]: {
          tone: "ok",
          text: `${r.model}: ${r.tok_s ?? "?"} tok/s${
            r.was_resident === false ? `, loaded in ${((r.load_ms ?? 0) / 1000).toFixed(2)} s` : ", was already resident"
          }${r.evicted?.length ? ` (evicted ${r.evicted.join(", ")})` : ""}.`,
        },
      }));
    });

  const activate = (role: string, name: string) =>
    run(role, "Activating…", async () => {
      await api(`/models/${role}/activate`, { method: "POST", body: JSON.stringify({ name }) });
      setMsg((m) => ({
        ...m,
        [role]: { tone: "ok", text: `${name} now serves ${ROLE_LABEL[role]}. The next request uses it; no restart.` },
      }));
    });

  if (error) {
    return (
      <p role="alert" className="mt-6 border-l-2 border-alarm bg-alarm-wash px-3 py-2 text-sm">
        {error}
      </p>
    );
  }
  if (!data) return <div className="mt-6 border border-rule bg-sheet px-4 py-10 text-center text-muted">Checking model servers…</div>;

  const gpu = data.gpu.gpus?.[0];
  const residents = Object.values(data.backends).flatMap((b) => Object.entries(b.loaded));

  return (
    <div className="mt-6 space-y-5">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {/* GPU */}
        <section className="border-[1.5px] border-line bg-sheet px-4 py-3">
          <div className="cell-label">GPU</div>
          {gpu ? (
            <>
              <p className="mt-1 font-medium">{gpu.name}</p>
              <VramBar used={gpu.vram_used_mib} total={gpu.vram_total_mib} />
              <p className="mt-1 font-mono text-[12px] text-muted">
                {(gpu.vram_used_mib / 1024).toFixed(1)} of {(gpu.vram_total_mib / 1024).toFixed(1)} GiB in use (all
                processes) · {gpu.utilization_pct}% busy · driver {gpu.driver}
              </p>
            </>
          ) : (
            <p className="mt-1 text-sm text-muted">No GPU telemetry here ({data.gpu.reason}).</p>
          )}
          <div className="mt-3 border-t border-rule pt-2">
            <div className="cell-label">Resident right now</div>
            {residents.length === 0 ? (
              <p className="mt-1 text-sm text-muted">No model loaded. The next request loads one.</p>
            ) : (
              <ul className="mt-1 space-y-0.5 font-mono text-[12px]">
                {residents.map(([name, info]) => (
                  <li key={name}>
                    {name} <span className="text-muted">· {formatBytes(info.size_vram)} in VRAM</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {/* Profile */}
        <section className="border border-rule bg-sheet px-4 py-3">
          <div className="cell-label">Hardware profile</div>
          <p className="mt-1 font-mono text-[15px]">{data.profile}</p>
          <p className="mt-1 text-sm text-muted">{data.notes}</p>
          {Object.entries(data.backends).map(([name, b]) => (
            <p key={name} className="mt-2 font-mono text-[12px]">
              <span className={b.reachable ? "text-ok" : "text-alarm"}>{b.reachable ? "reachable" : "unreachable"}</span>{" "}
              {name} · {b.base_url}
              {!b.reachable && b.error && <span className="block text-muted">{b.error}</span>}
            </p>
          ))}
        </section>
      </div>

      {/* Roles */}
      <section className="border border-rule bg-sheet">
        <div className="hidden grid-cols-[120px_minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_130px] gap-4 border-b border-rule px-4 py-2 lg:grid">
          <span className="cell-label">Role</span>
          <span className="cell-label">Serving model</span>
          <span className="cell-label">State</span>
          <span className="cell-label">Measured here</span>
          <span />
        </div>
        <ul>
          {data.roles.map((r) => (
            <RoleRow
              key={r.role}
              r={r}
              isAdmin={user.role === "admin"}
              canWarm={user.role !== "reviewer"}
              busy={busy[r.role]}
              msg={msg[r.role]}
              onWarm={() => warm(r.role)}
              onActivate={(name) => activate(r.role, name)}
            />
          ))}
        </ul>
      </section>
      <p className="text-xs text-muted">
        Throughput and load times are measured on this machine by <span className="font-medium">Warm up</span> and
        saved to <span className="font-mono">metrics/model_warmup.json</span>. &ldquo;Last swap&rdquo; is the most recent load
        of a model that wasn&apos;t already resident. VRAM figures come from the model server and nvidia-smi.
      </p>
    </div>
  );
}

function RoleRow({
  r,
  isAdmin,
  canWarm,
  busy,
  msg,
  onWarm,
  onActivate,
}: {
  r: RoleView;
  isAdmin: boolean;
  canWarm: boolean;
  busy?: string;
  msg?: { tone: "ok" | "alarm"; text: string };
  onWarm: () => void;
  onActivate: (name: string) => void;
}) {
  const [choice, setChoice] = useState(r.model);
  useEffect(() => setChoice(r.model), [r.model]);
  const w = r.warmup;

  return (
    <li className="grid gap-x-4 gap-y-2 border-b border-rule px-4 py-3 last:border-b-0 lg:grid-cols-[120px_minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_130px] lg:items-start">
      <div>
        <div className="font-medium">{ROLE_LABEL[r.role] ?? r.role}</div>
        <div className="font-mono text-[11px] text-muted">{r.role}</div>
      </div>

      <div className="min-w-0">
        {isAdmin ? (
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={choice}
              onChange={(e) => setChoice(e.target.value)}
              disabled={!!busy}
              aria-label={`Model for ${r.role}`}
              className="min-w-0 border border-rule bg-ground/40 px-2 py-1 font-mono text-[13px] outline-none focus:border-control"
            >
              {r.candidates.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                  {c.pulled ? "" : " (not downloaded)"}
                </option>
              ))}
            </select>
            {choice !== r.model && (
              <button
                type="button"
                onClick={() => onActivate(choice)}
                disabled={!!busy}
                className="bg-control px-3 py-1 text-sm font-medium text-control-ink disabled:opacity-50"
              >
                Activate
              </button>
            )}
          </div>
        ) : (
          <div className="font-mono text-[13px]">{r.model}</div>
        )}
        <div className="mt-1 text-[11px] text-muted">
          {r.source === "activation" ? "admin-activated" : "profile default"}
          {r.licence && ` · ${r.licence}`}
          {r.note && ` · ${r.note}`}
        </div>
      </div>

      <div className="text-[13px]">
        {!r.reachable ? (
          <span className="text-alarm">server unreachable</span>
        ) : !r.pulled ? (
          <span className="text-warn">not downloaded</span>
        ) : r.loaded ? (
          <span className="text-ok">resident · {formatBytes(r.loaded.size_vram)} VRAM</span>
        ) : (
          <span>downloaded · not loaded</span>
        )}
      </div>

      <div className="font-mono text-[12px]">
        {w ? (
          <>
            <div>
              <span className="text-ink">{w.tok_s ?? "—"}</span> <span className="text-muted">tok/s</span>
            </div>
            <div className="text-muted">
              last swap {w.last_cold ? `${(w.last_cold.load_ms / 1000).toFixed(2)} s` : "not measured"}
            </div>
            <div className="text-[11px] text-muted">{formatTime(w.ts)}</div>
          </>
        ) : (
          <span className="text-muted">not measured yet</span>
        )}
      </div>

      <div className="lg:text-right">
        {canWarm && (
          <button
            type="button"
            onClick={onWarm}
            disabled={!!busy || !r.pulled}
            title={r.pulled ? "Load the model and measure throughput" : "Download the model first"}
            className="border border-line px-3 py-1 text-sm hover:bg-sunk disabled:opacity-40"
          >
            {busy ?? "Warm up"}
          </button>
        )}
      </div>

      {msg && (
        <p
          className={`text-sm lg:col-span-5 ${msg.tone === "ok" ? "text-ok" : "border-l-2 border-alarm bg-alarm-wash px-3 py-1.5 text-ink"}`}
        >
          {msg.text}
        </p>
      )}
    </li>
  );
}

function VramBar({ used, total }: { used: number; total: number }) {
  const pct = Math.min(100, (used / total) * 100);
  return (
    <div className="mt-2 h-2.5 w-full border border-rule bg-ground" role="meter" aria-valuemin={0} aria-valuemax={total} aria-valuenow={used} aria-label="VRAM in use">
      <div className={`h-full ${pct > 90 ? "bg-warn" : "bg-control"}`} style={{ width: `${pct}%` }} />
    </div>
  );
}
