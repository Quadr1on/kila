// Ingestion (document reading) and knowledge-base API types + calls. Mirrors kila/ingest and kila/rag.

import { api } from "./api";

export type OcrLine = { text: string; conf: number; box: [number, number][] };
export type VisionCheck = { model: string; text: string; similarity: number | null; disagrees: boolean; error: string | null };
export type Page = {
  index: number;
  method: "text_layer" | "ocr" | "ocr+vision" | "vision" | "none";
  text: string;
  ocr_conf: number | null;
  image_object_id: string | null;
  image_size: [number, number] | null;
  skew_deg: number | null;
  lines: OcrLine[];
  vision: VisionCheck | null;
};
export type SheetTable = {
  name: string;
  n_rows: number;
  n_cols: number;
  columns: string[];
  dtypes: Record<string, string>;
  preview: string[][];
};
export type CodeFile = { path: string; size: number; language: string | null; text: string | null };
export type Attachment = {
  object_id: string;
  sha256: string;
  name: string;
  mime: string;
  kind: string;
  language: string;
  pages: Page[];
  tables: SheetTable[];
  code: CodeFile[];
  warnings: string[];
  timings_ms: Record<string, number>;
};
export type Ingestion = {
  object_id: string;
  status: "none" | "queued" | "running" | "done" | "error";
  ingestion_id?: string;
  lang?: string;
  pages_done?: number;
  pages_total?: number;
  error?: string | null;
  pipeline?: string;
  duration_ms?: number | null;
  attachment?: Attachment;
};
export type OcrLang = "en" | "hi" | "kn" | "auto";

export const ingestApi = {
  get: (objectId: string) => api<Ingestion>(`/ingest/${objectId}`),
  start: (objectId: string, lang: OcrLang = "en", force = false) =>
    api<Ingestion>(`/ingest/${objectId}?lang=${lang}&force=${force}`, { method: "POST" }),
};

export type KbDoc = {
  object_id: string;
  name: string;
  sha256: string;
  size: number;
  title: string;
  doc_type: string;
  status: "pending" | "indexing" | "indexed" | "error";
  error: string | null;
  chunk_count: number;
  indexed_at: string | null;
  ingestion: { status: string; pages_total?: number; pages_done?: number; duration_ms?: number | null } | null;
};
export type Hit = {
  chunk_id: string;
  object_id: string;
  name: string;
  title: string;
  doc_type: string;
  bucket: string;
  page: number;
  char_start: number;
  char_end: number;
  text: string;
  score: number;
  rank: number;
};
export type SearchResult = {
  query: string;
  dense: Hit[];
  bm25: Hit[];
  fused: Hit[];
  reranked: Hit[];
  results: Hit[];
  retrieval_relevance: number | null;
  rerank: { enabled: boolean; model?: string; device?: string; top_n?: number; candidates?: number };
  embedder: { name: string; device: string };
  timings_ms: Record<string, number>;
};

export const kbApi = {
  documents: () => api<KbDoc[]>("/kb/documents"),
  index: (objectId: string, lang: OcrLang = "en") =>
    api<{ status: string }>(`/kb/documents/${objectId}/index?lang=${lang}`, { method: "POST" }),
  remove: (objectId: string) => api<void>(`/kb/documents/${objectId}`, { method: "DELETE" }),
  search: (query: string, objectIds?: string[]) =>
    api<SearchResult>("/kb/search", { method: "POST", body: JSON.stringify({ query, object_ids: objectIds }) }),
  seed: () => api<{ queued: string[]; skipped: number }>("/kb/seed", { method: "POST" }),
};

export const METHOD_LABEL: Record<Page["method"], string> = {
  text_layer: "text layer",
  ocr: "OCR",
  "ocr+vision": "OCR + vision check",
  vision: "vision model only",
  none: "unreadable",
};

/** Confidence bands for the OCR heat overlay (ISA-101 palette: colour means state). */
export function confBand(c: number): "ok" | "warn" | "alarm" {
  return c >= 0.95 ? "ok" : c >= 0.85 ? "warn" : "alarm";
}
