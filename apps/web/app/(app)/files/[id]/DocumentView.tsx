"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, formatBytes, notifyLedgerChanged } from "@/lib/api";
import { confBand, ingestApi, METHOD_LABEL, type Attachment, type Ingestion, type OcrLang, type Page } from "@/lib/docs";
import { storage, type StoredObject } from "@/lib/storage";

const LANGS: { v: OcrLang; label: string }[] = [
  { v: "en", label: "English" },
  { v: "hi", label: "Hindi (Devanagari OCR)" },
  { v: "kn", label: "Kannada (vision model only)" },
  { v: "auto", label: "Detect" },
];

export function DocumentView({ objectId }: { objectId: string }) {
  const params = useSearchParams();
  const [obj, setObj] = useState<StoredObject | null>(null);
  const [ing, setIng] = useState<Ingestion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState<OcrLang>("en");
  const [pageNo, setPageNo] = useState<number>(Number(params.get("page")) || 1);

  const load = useCallback(async () => {
    try {
      const [o, i] = await Promise.all([storage.meta(objectId), ingestApi.get(objectId)]);
      setObj(o);
      setIng(i);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Can't load this file.");
    }
  }, [objectId]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while a read is in progress.
  useEffect(() => {
    if (!ing || (ing.status !== "queued" && ing.status !== "running")) return;
    const t = setTimeout(async () => {
      const next = await ingestApi.get(objectId).catch(() => null);
      if (next) {
        setIng(next);
        if (next.status === "done" || next.status === "error") notifyLedgerChanged();
      }
    }, 1200);
    return () => clearTimeout(t);
  }, [ing, objectId]);

  async function read(force: boolean) {
    setError(null);
    try {
      setIng(await ingestApi.start(objectId, lang, force));
      notifyLedgerChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Couldn't start reading.");
    }
  }

  const att = ing?.attachment;
  const busy = ing?.status === "queued" || ing?.status === "running";

  if (error) return <p role="alert" className="mt-6 border-l-2 border-alarm bg-alarm-wash px-3 py-2 text-sm">{error}</p>;
  if (!obj || !ing) return <div className="mt-6 border border-rule bg-sheet px-4 py-10 text-center text-muted">Loading…</div>;

  return (
    <div className="mt-6 space-y-4">
      {/* Header strip */}
      <section className="flex flex-wrap items-end justify-between gap-3 border-[1.5px] border-line bg-sheet px-4 py-3">
        <div className="min-w-0">
          <Link href="/files" className="text-sm text-control hover:underline">
            ← Files
          </Link>
          <h2 className="mt-1 truncate text-lg font-medium">{obj.original_name}</h2>
          <p className="font-mono text-[12px] text-muted">
            {obj.bucket} · {formatBytes(obj.size)} · sha256 {obj.sha256.slice(0, 16)}…
            {att && ` · ${att.kind.replace("_", " ")} · ${att.pages.length} page${att.pages.length === 1 ? "" : "s"}`}
            {ing.duration_ms != null && ing.status === "done" && ` · read in ${(ing.duration_ms / 1000).toFixed(1)} s`}
            {ing.duration_ms === 0 && " (reused an earlier read of identical content)"}
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
            <label className="block">
              <span className="cell-label">Document language</span>
              <select
                value={lang}
                onChange={(e) => setLang(e.target.value as OcrLang)}
                disabled={busy}
                className="mt-1 block border border-rule bg-ground/40 px-2 py-1 text-sm outline-none focus:border-control"
              >
                {LANGS.map((l) => (
                  <option key={l.v} value={l.v}>
                    {l.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={busy}
              onClick={() => read(ing.status === "done" || ing.status === "error")}
              className="h-[34px] bg-control px-4 font-medium text-control-ink disabled:opacity-50"
            >
              {busy ? "Reading…" : ing.status === "none" ? "Read document" : "Read again"}
            </button>
          </div>
      </section>

      {busy && <Progress done={ing.pages_done ?? 0} total={ing.pages_total ?? 0} />}
      {ing.status === "error" && (
        <p role="alert" className="border-l-2 border-alarm bg-alarm-wash px-3 py-2 text-sm">
          Reading failed: {ing.error}
        </p>
      )}
      {ing.status === "none" && (
        <p className="border border-dashed border-rule bg-sheet px-4 py-6 text-sm text-muted">
          This file hasn&apos;t been read yet. Choose its language and press <b>Read document</b>. Scans are OCR&apos;d on
          this machine; nothing leaves it.
        </p>
      )}

      {att && att.warnings.length > 0 && (
        <ul className="space-y-1 border-l-2 border-warn bg-warn-wash px-3 py-2 text-sm">
          {att.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      {att && att.pages.length > 0 && <Pages att={att} pageNo={pageNo} setPageNo={setPageNo} />}
      {att && att.tables.length > 0 && <Tables att={att} />}
      {att && att.code.length > 0 && <Code att={att} />}
    </div>
  );
}

function Progress({ done, total }: { done: number; total: number }) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <div className="border border-rule bg-sheet px-4 py-3" aria-live="polite">
      <div className="flex justify-between text-sm">
        <span>Reading{total ? ` page ${Math.min(done + 1, total)} of ${total}` : "…"}</span>
        <span className="font-mono text-muted">{pct}%</span>
      </div>
      <div className="mt-2 h-1.5 w-full bg-ground">
        <div className="h-full bg-control transition-[width] duration-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function Pages({ att, pageNo, setPageNo }: { att: Attachment; pageNo: number; setPageNo: (n: number) => void }) {
  const page = att.pages.find((p) => p.index === pageNo) ?? att.pages[0];
  return (
    <div className="grid gap-4 xl:grid-cols-[150px_minmax(0,1.15fr)_minmax(0,1fr)]">
      {/* page list */}
      <nav aria-label="Pages" className="flex gap-2 overflow-x-auto xl:flex-col xl:overflow-visible">
        {att.pages.map((p) => (
          <button
            key={p.index}
            type="button"
            onClick={() => setPageNo(p.index)}
            aria-current={p.index === page.index ? "page" : undefined}
            className={`shrink-0 border px-2.5 py-1.5 text-left text-[12px] ${
              p.index === page.index ? "border-control bg-sheet" : "border-rule bg-sheet/60 hover:border-line"
            }`}
          >
            <div className="font-medium">Page {p.index}</div>
            <div className="font-mono text-muted">{METHOD_LABEL[p.method]}</div>
            {p.ocr_conf != null && <ConfBadge c={p.ocr_conf} />}
          </button>
        ))}
      </nav>
      <PageImage page={page} />
      <PageText page={page} />
    </div>
  );
}

function ConfBadge({ c }: { c: number }) {
  const band = confBand(c);
  const cls = band === "ok" ? "text-ok" : band === "warn" ? "text-warn" : "text-alarm";
  return <div className={`font-mono ${cls}`}>{(c * 100).toFixed(1)}% conf</div>;
}

function PageImage({ page }: { page: Page }) {
  const [url, setUrl] = useState<string | null>(null);
  const [overlay, setOverlay] = useState(true);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    setUrl(null);
    if (page.image_object_id) storage.getSignedUrl(page.image_object_id, 600).then(setUrl, () => setUrl(null));
  }, [page.image_object_id]);

  const [w, h] = page.image_size ?? [1000, 1414];
  const counts = useMemo(() => {
    const c = { ok: 0, warn: 0, alarm: 0 };
    page.lines.forEach((l) => c[confBand(l.conf)]++);
    return c;
  }, [page.lines]);
  const hovered = hover != null ? page.lines[hover] : null;

  return (
    <section className="min-w-0 border border-rule bg-sheet">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule px-3 py-2">
        <span className="cell-label">Page image{page.skew_deg ? ` · straightened ${page.skew_deg.toFixed(1)}°` : ""}</span>
        {page.lines.length > 0 && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={overlay} onChange={(e) => setOverlay(e.target.checked)} />
            OCR confidence overlay
          </label>
        )}
      </div>
      <div className="relative bg-ground">
        {url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt={`Page ${page.index}`} className="block w-full" />
        ) : (
          <div className="flex h-72 items-center justify-center text-sm text-muted">
            {page.image_object_id ? "Loading page image…" : "No page image for this file type."}
          </div>
        )}
        {url && overlay && page.lines.length > 0 && (
          <svg viewBox={`0 0 ${w} ${h}`} className="absolute inset-0 h-full w-full" aria-hidden>
            {page.lines.map((l, i) => {
              const band = confBand(l.conf);
              return (
                <polygon
                  key={i}
                  points={l.box.map((p) => p.join(",")).join(" ")}
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                  className="cursor-help"
                  style={{
                    fill: `var(--${band})`,
                    fillOpacity: hover === i ? 0.35 : band === "ok" ? 0.08 : 0.22,
                    stroke: `var(--${band})`,
                    strokeWidth: hover === i ? 3 : 1.5,
                  }}
                />
              );
            })}
          </svg>
        )}
      </div>
      {page.lines.length > 0 && (
        <div className="border-t border-rule px-3 py-2 text-[12px]">
          {hovered ? (
            <p className="font-mono">
              <span className={confBand(hovered.conf) === "ok" ? "text-ok" : confBand(hovered.conf) === "warn" ? "text-warn" : "text-alarm"}>
                {(hovered.conf * 100).toFixed(1)}%
              </span>{" "}
              “{hovered.text}”
            </p>
          ) : (
            <p className="flex flex-wrap gap-x-4 gap-y-1 text-muted">
              <span>{page.lines.length} text lines · hover a box to see what was read</span>
              <span className="text-ok">■ ≥95%: {counts.ok}</span>
              <span className="text-warn">■ 85–95%: {counts.warn}</span>
              <span className="text-alarm">■ &lt;85%: {counts.alarm}</span>
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function PageText({ page }: { page: Page }) {
  return (
    <section className="min-w-0 space-y-4">
      <div className="border border-rule bg-sheet">
        <div className="flex justify-between border-b border-rule px-3 py-2">
          <span className="cell-label">Extracted text · {METHOD_LABEL[page.method]}</span>
          {page.ocr_conf != null && <ConfBadge c={page.ocr_conf} />}
        </div>
        <pre className="max-h-[640px] overflow-auto whitespace-pre-wrap px-3 py-2.5 font-mono text-[12px] leading-relaxed">
          {page.text || "(no text found on this page)"}
        </pre>
      </div>
      {page.vision && (
        <div className={`border ${page.vision.disagrees ? "border-warn" : "border-rule"} bg-sheet`}>
          <div className="flex flex-wrap justify-between gap-2 border-b border-rule px-3 py-2">
            <span className="cell-label">Second reading · vision model {page.vision.model}</span>
            {page.vision.similarity != null && (
              <span className={`font-mono text-[12px] ${page.vision.disagrees ? "text-warn" : "text-ok"}`}>
                {page.vision.disagrees ? "disagrees with OCR" : "agrees with OCR"} · similarity{" "}
                {(page.vision.similarity * 100).toFixed(0)}%
              </span>
            )}
          </div>
          {page.vision.error ? (
            <p className="px-3 py-2.5 text-sm text-alarm">Vision model unavailable: {page.vision.error}</p>
          ) : (
            <pre className="max-h-[360px] overflow-auto whitespace-pre-wrap px-3 py-2.5 font-mono text-[12px] leading-relaxed">
              {page.vision.text}
            </pre>
          )}
          <p className="border-t border-rule px-3 py-2 text-[12px] text-muted">
            Both readings are kept. Neither replaces the other; check the page image where they differ.
          </p>
        </div>
      )}
    </section>
  );
}

function Tables({ att }: { att: Attachment }) {
  return (
    <div className="space-y-4">
      {att.tables.map((t) => (
        <section key={t.name} className="border border-rule bg-sheet">
          <div className="border-b border-rule px-3 py-2">
            <span className="cell-label">
              Sheet “{t.name}” · {t.n_rows} rows × {t.n_cols} columns (first {t.preview.length} shown)
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[12.5px]">
              <thead>
                <tr className="border-b border-rule">
                  {t.columns.map((c) => (
                    <th key={c} className="whitespace-nowrap px-3 py-1.5 font-medium">
                      {c}
                      <div className="font-mono text-[10px] font-normal text-muted">{t.dtypes[c]}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {t.preview.map((row, i) => (
                  <tr key={i} className="border-b border-rule last:border-b-0">
                    {row.map((v, j) => (
                      <td key={j} className="whitespace-nowrap px-3 py-1 font-mono">
                        {v === "nan" ? "" : v}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}

function Code({ att }: { att: Attachment }) {
  const readable = att.code.filter((f) => f.text != null);
  const [sel, setSel] = useState(readable[0]?.path ?? null);
  const file = att.code.find((f) => f.path === sel);
  return (
    <section className="grid gap-0 border border-rule bg-sheet md:grid-cols-[260px_minmax(0,1fr)]">
      <ul className="max-h-[520px] overflow-auto border-b border-rule py-1 md:border-b-0 md:border-r">
        {att.code.map((f) => (
          <li key={f.path}>
            <button
              type="button"
              disabled={f.text == null}
              onClick={() => setSel(f.path)}
              className={`block w-full truncate px-3 py-1 text-left font-mono text-[12px] disabled:text-muted ${
                sel === f.path ? "bg-sunk" : "hover:bg-sunk/60"
              }`}
              title={f.text == null ? "binary or over the size cap" : f.path}
            >
              {f.path}
            </button>
          </li>
        ))}
      </ul>
      <pre className="max-h-[520px] overflow-auto px-3 py-2.5 font-mono text-[12px] leading-relaxed">
        {file?.text ?? "Select a file."}
      </pre>
    </section>
  );
}
