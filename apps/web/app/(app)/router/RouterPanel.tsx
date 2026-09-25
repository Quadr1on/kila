"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, formatTime, notifyLedgerChanged } from "@/lib/api";
import {
  routerApi,
  TASK_LABEL,
  type Calibration,
  type DecisionRow,
  type RouteDecision,
  type RouterConfig,
  type RouterStats,
} from "@/lib/routerApi";

const KINDS = [
  { v: "pdf_scanned", label: "scanned PDF" },
  { v: "image", label: "photo / drawing" },
  { v: "sheet", label: "spreadsheet" },
  { v: "code", label: "code" },
];
const EXAMPLES = [
  "What is the PSV test interval?",
  "Draft an approval note recommending re-inspection of E-2104 based on the attached report",
  "Fix the bug in this python function that computes corrosion rate",
  "इस निरीक्षण रिपोर्ट का सारांश बनाइए",
  "ಈ ತಪಾಸಣಾ ವರದಿಯ ಸಾರಾಂಶ ನೀಡಿ",
];

export function RouterPanel() {
  const [stats, setStats] = useState<RouterStats | null>(null);
  const [rows, setRows] = useState<DecisionRow[]>([]);
  const [cal, setCal] = useState<Calibration | null | "missing">(null);
  const [cfg, setCfg] = useState<RouterConfig | null>(null);

  const load = useCallback(async () => {
    const [s, d, c] = await Promise.all([routerApi.stats(), routerApi.decisions(), routerApi.config()]);
    setStats(s);
    setRows(d);
    setCfg(c);
    routerApi.calibration().then(setCal, (e) => setCal(e instanceof ApiError && e.status === 404 ? "missing" : null));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="mt-6 space-y-6">
      <Playground cfg={cfg} onRouted={load} />
      <Stats stats={stats} cfg={cfg} />
      <CalibrationView cal={cal} />
      <Decisions rows={rows} />
    </div>
  );
}

// ------------------------------------------------------------------ playground

function Playground({ cfg, onRouted }: { cfg: RouterConfig | null; onRouted: () => void }) {
  const [text, setText] = useState("");
  const [kinds, setKinds] = useState<string[]>([]);
  const [useRel, setUseRel] = useState(false);
  const [rel, setRel] = useState(0.6);
  const [res, setRes] = useState<RouteDecision | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(t = text) {
    if (!t.trim()) return;
    setText(t);
    setBusy(true);
    setError(null);
    try {
      setRes(await routerApi.preview(t, kinds, useRel ? rel : null));
      notifyLedgerChanged();
      onRouted();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Routing failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="border-[1.5px] border-line bg-sheet">
      <div className="border-b border-rule px-4 py-3">
        <h2 className="font-display text-xl font-semibold uppercase tracking-[0.04em]">Try the router</h2>
        <p className="text-sm text-muted">
          See how a request would be classified and which model would answer it. Nothing is answered or saved as a
          task.
          {cfg && !cfg.classifier.loaded && " The classifier loads on first use (about 15 s on CPU)."}
        </p>
      </div>
      <div className="grid gap-4 px-4 py-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-3">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            placeholder="Type a request, in English, Hindi or Kannada"
            className="w-full resize-y border border-rule bg-ground/40 px-3 py-2 outline-none focus:border-control"
          />
          <div className="flex flex-wrap gap-2 text-[12px]">
            {EXAMPLES.map((e) => (
              <button key={e} type="button" onClick={() => run(e)} className="max-w-full truncate border border-rule px-2 py-1 hover:border-line">
                {e}
              </button>
            ))}
          </div>
          <fieldset className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
            <legend className="cell-label mb-1">Pretend attachments</legend>
            {KINDS.map((k) => (
              <label key={k.v} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={kinds.includes(k.v)}
                  onChange={(e) => setKinds((ks) => (e.target.checked ? [...ks, k.v] : ks.filter((x) => x !== k.v)))}
                />
                {k.label}
              </label>
            ))}
          </fieldset>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={useRel} onChange={(e) => setUseRel(e.target.checked)} />
              Retrieval relevance
            </label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={rel}
              disabled={!useRel}
              onChange={(e) => setRel(Number(e.target.value))}
              aria-label="Retrieval relevance"
              className="w-40 disabled:opacity-40"
            />
            <span className="font-mono text-[12px]">{useRel ? rel.toFixed(2) : "none (no documents)"}</span>
          </div>
          <button
            type="button"
            onClick={() => run()}
            disabled={busy || !text.trim()}
            className="bg-control px-5 py-1.5 font-medium text-control-ink disabled:opacity-50"
          >
            {busy ? "Routing…" : "Route"}
          </button>
          {error && <p role="alert" className="border-l-2 border-alarm bg-alarm-wash px-3 py-2 text-sm">{error}</p>}
        </div>
        <div className="min-w-0">{res ? <DecisionCard d={res} /> : <p className="text-sm text-muted">The decision appears here.</p>}</div>
      </div>
    </section>
  );
}

export function DecisionCard({ d }: { d: RouteDecision }) {
  if (!d.ok) {
    return <p className="border-l-2 border-warn bg-warn-wash px-3 py-2 text-sm">{d.summary}</p>;
  }
  return (
    <div className="space-y-3">
      <div className={`border-l-2 px-3 py-2 ${d.escalated ? "border-warn bg-warn-wash" : "border-ok bg-ok-wash"}`}>
        <div className="font-mono text-[13px]">{d.summary}</div>
        <div className="mt-1 text-[12px] text-muted">
          answered by <span className="font-mono text-ink">{d.chosen_model}</span> ({d.chosen_role}) · routed in{" "}
          {(d.latency_ms / 1000).toFixed(2)} s
          {d.classifier && ` · Laya ${d.classifier.checkpoint} on ${d.classifier.device}, ${d.classifier.latency_ms.toFixed(0)} ms`}
        </div>
        {d.perception && <div className="mt-1 text-[12px] text-muted">vision: {d.perception}</div>}
      </div>
      {d.questions &&
        Object.entries(d.questions).map(([q, r]) => (
          <div key={q}>
            <div className="flex justify-between text-[12px]">
              <span className="cell-label">{q.replace("_", " ")}</span>
              <span className="font-mono text-muted">
                calibrated {(r.conf * 100).toFixed(0)}% · raw {(r.raw_conf * 100).toFixed(0)}%
              </span>
            </div>
            <ul className="mt-1 space-y-0.5">
              {Object.entries(r.probs)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 4)
                .map(([k, p]) => (
                  <li key={k} className="grid grid-cols-[130px_minmax(0,1fr)_42px] items-center gap-2 text-[12px]">
                    <span className={`truncate ${k === r.choice ? "font-medium" : "text-muted"}`}>
                      {q === "needs_vision" ? (k === "A" ? "yes" : "no") : (TASK_LABEL[k] ?? k)}
                    </span>
                    <span className="h-1.5 bg-ground">
                      <span className={`block h-full ${k === r.choice ? "bg-control" : "bg-rule"}`} style={{ width: `${p * 100}%` }} />
                    </span>
                    <span className="text-right font-mono">{(p * 100).toFixed(0)}%</span>
                  </li>
                ))}
            </ul>
          </div>
        ))}
    </div>
  );
}

// ------------------------------------------------------------------ stats

function Stats({ stats, cfg }: { stats: RouterStats | null; cfg: RouterConfig | null }) {
  if (!stats) return null;
  const tiles: [string, string][] = [
    ["Routed requests", String(stats.decisions)],
    ["Escalation rate", stats.escalation_rate != null ? `${(stats.escalation_rate * 100).toFixed(0)}%` : "—"],
    ["Routing latency p50", stats.latency_ms ? `${(stats.latency_ms.p50 / 1000).toFixed(2)} s` : "—"],
    ["α / τ", cfg ? `${cfg.cascade.alpha} / ${cfg.cascade.tau}` : "—"],
  ];
  const total = Object.values(stats.by_model).reduce((a, b) => a + b, 0);
  return (
    <section className="border border-rule bg-sheet">
      <dl className="grid grid-cols-2 gap-px bg-rule md:grid-cols-4">
        {tiles.map(([k, v]) => (
          <div key={k} className="bg-sheet px-4 py-3">
            <dt className="cell-label">{k}</dt>
            <dd className="mt-1 font-mono text-xl">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="grid gap-4 border-t border-rule px-4 py-3 md:grid-cols-2">
        <div>
          <div className="cell-label">Share per model</div>
          {total === 0 ? (
            <p className="mt-1 text-sm text-muted">No routed chats yet. Send a message in Workbench with Auto routing.</p>
          ) : (
            <ul className="mt-1 space-y-1 text-[13px]">
              {Object.entries(stats.by_model).map(([m, n]) => (
                <li key={m} className="flex justify-between font-mono">
                  <span>{m}</span>
                  <span className="text-muted">
                    {n} · {((n / total) * 100).toFixed(0)}%
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <div className="cell-label">Requests per task type</div>
          <ul className="mt-1 space-y-1 text-[13px]">
            {Object.entries(stats.by_task_type).map(([t, n]) => (
              <li key={t} className="flex justify-between">
                <span>{TASK_LABEL[t] ?? t}</span>
                <span className="font-mono text-muted">{n}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ calibration

function CalibrationView({ cal }: { cal: Calibration | null | "missing" }) {
  if (cal === null) return null;
  if (cal === "missing")
    return (
      <p className="border border-dashed border-rule bg-sheet px-4 py-4 text-sm text-muted">
        Not calibrated yet. Run <span className="font-mono">python -m kila.router.calibrate</span> to fit the
        temperatures and τ on the labelled set.
      </p>
    );
  const chosen = cal.tau_sweep.chosen_on_test;
  return (
    <section className="border border-rule bg-sheet">
      <div className="border-b border-rule px-4 py-3">
        <h2 className="font-display text-xl font-semibold uppercase tracking-[0.04em]">Calibration</h2>
        <p className="text-sm text-muted">
          Fitted on {cal.fit} of {cal.labels} synthetic labelled requests; every number below is on the {cal.test} held
          out. {formatTime(cal.ts)}.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-[13px]">
          <thead>
            <tr className="border-b border-rule">
              {["Question", "Temperature", "Accuracy", "ECE before", "ECE after", "NLL before → after"].map((h) => (
                <th key={h} className="cell-label px-4 py-2 font-normal">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(cal.questions).map(([q, r]) => (
              <tr key={q} className="border-b border-rule last:border-b-0">
                <td className="px-4 py-2">{q.replace("_", " ")}</td>
                <td className="px-4 py-2 font-mono">{r.temperature}</td>
                <td className="px-4 py-2 font-mono">{(r.after.accuracy * 100).toFixed(1)}%</td>
                <td className="px-4 py-2 font-mono">{r.before.ece.toFixed(3)}</td>
                <td className={`px-4 py-2 font-mono ${r.after.ece < r.before.ece ? "text-ok" : "text-warn"}`}>
                  {r.after.ece.toFixed(3)}
                </td>
                <td className="px-4 py-2 font-mono text-muted">
                  {r.before.nll.toFixed(2)} → {r.after.nll.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid gap-4 border-t border-rule px-4 py-3 md:grid-cols-3">
        <div>
          <div className="cell-label">Task-type accuracy by language</div>
          <ul className="mt-1 space-y-0.5 font-mono text-[13px]">
            {Object.entries(cal.task_type_accuracy_by_language).map(([l, v]) => (
              <li key={l} className="flex justify-between">
                <span>{{ en: "English", hi: "Hindi", kn: "Kannada" }[l] ?? l}</span>
                <span>
                  {(v.accuracy * 100).toFixed(0)}% <span className="text-muted">(n={v.n})</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="cell-label">Most common confusions</div>
          <ul className="mt-1 space-y-0.5 text-[12px]">
            {cal.task_type_top_confusions.slice(0, 5).map(([k, n]) => (
              <li key={k} className="flex justify-between gap-2">
                <span className="truncate font-mono">{k}</span>
                <span className="text-muted">{n}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="cell-label">Classifier speed</div>
          <p className="mt-1 font-mono text-[13px]">
            p50 {cal.laya_latency_ms.p50.toFixed(0)} ms · p95 {cal.laya_latency_ms.p95.toFixed(0)} ms on{" "}
            {cal.laya_latency_ms.device}
          </p>
          <p className="mt-1 text-[12px] text-muted">
            {Object.entries(cal.laya_latency_ms.by_checkpoint_p50)
              .map(([k, v]) => `${k} ${v.toFixed(0)} ms`)
              .join(" · ")}
          </p>
        </div>
      </div>
      <div className="border-t border-rule px-4 py-3">
        <div className="cell-label">τ sweep (held-out split, no retrieval)</div>
        <p className="mt-1 text-sm text-muted">
          Chosen τ = <span className="font-mono text-ink">{cal.tau_sweep.chosen_tau}</span>: the least escalation that keeps
          task-type accuracy on the requests staying on the small model ≥{" "}
          {(cal.tau_sweep.target_kept_accuracy * 100).toFixed(0)}% on the fit split. On held-out data it escalates{" "}
          {(chosen.escalation_rate * 100).toFixed(0)}% with {chosen.kept_accuracy != null ? (chosen.kept_accuracy * 100).toFixed(1) : "—"}% kept
          accuracy. α ({cal.alpha.value}) is not tuned yet: {cal.alpha.note}.
        </p>
        <div className="mt-2 overflow-x-auto">
          <table className="text-left text-[12px]">
            <thead>
              <tr className="border-b border-rule">
                {["τ", "Escalation rate", "Kept accuracy", "Hard tasks escalated"].map((h) => (
                  <th key={h} className="cell-label px-3 py-1.5 font-normal">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cal.tau_sweep.test
                .filter((p) => p.tau >= 0.3)
                .map((p) => (
                  <tr key={p.tau} className={`border-b border-rule last:border-b-0 ${p.tau === cal.tau_sweep.chosen_tau ? "bg-sunk font-medium" : ""}`}>
                    <td className="px-3 py-1 font-mono">{p.tau.toFixed(2)}</td>
                    <td className="px-3 py-1 font-mono">{(p.escalation_rate * 100).toFixed(0)}%</td>
                    <td className="px-3 py-1 font-mono">{p.kept_accuracy != null ? `${(p.kept_accuracy * 100).toFixed(1)}%` : "—"}</td>
                    <td className="px-3 py-1 font-mono">{p.hard_escalated != null ? `${(p.hard_escalated * 100).toFixed(0)}%` : "—"}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ recent decisions

function Decisions({ rows }: { rows: DecisionRow[] }) {
  return (
    <section className="border border-rule bg-sheet">
      <div className="border-b border-rule px-4 py-2">
        <span className="cell-label">Recent routed requests</span>
      </div>
      {rows.length === 0 ? (
        <p className="px-4 py-4 text-sm text-muted">None yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-[12.5px]">
            <thead>
              <tr className="border-b border-rule">
                {["When", "Task type", "Conf", "Difficulty", "Relevance", "Score / τ", "Model", ""].map((h) => (
                  <th key={h} className="cell-label px-3 py-2 font-normal">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.task_id} className="border-b border-rule last:border-b-0">
                  <td className="whitespace-nowrap px-3 py-1.5 text-muted">{formatTime(r.created_at)}</td>
                  <td className="px-3 py-1.5">{TASK_LABEL[r.task_type] ?? r.task_type}</td>
                  <td className="px-3 py-1.5 font-mono">{r.task_conf.toFixed(2)}</td>
                  <td className="px-3 py-1.5">{r.difficulty}</td>
                  <td className="px-3 py-1.5 font-mono">{r.alpha === 1 ? "—" : r.retrieval_relevance.toFixed(2)}</td>
                  <td className="px-3 py-1.5 font-mono">
                    {r.score.toFixed(2)} {r.score < r.tau ? "<" : "≥"} {r.tau.toFixed(2)}
                  </td>
                  <td className="px-3 py-1.5 font-mono">{r.chosen_model}</td>
                  <td className="px-3 py-1.5">{r.escalated && <span className="text-warn">escalated</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
