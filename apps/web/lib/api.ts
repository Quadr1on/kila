// Browser-side API client. Every call goes to /api/* on this origin (proxied to FastAPI).

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
  }
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && typeof init.body === "string" && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  const res = await fetch(`/api${path}`, { ...init, headers, credentials: "same-origin", cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/login")) {
      window.location.href = "/login";
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Signed URLs come back relative to the API root; the browser needs the /api prefix. */
export function apiUrl(relative: string): string {
  return relative.startsWith("/api/") ? relative : `/api${relative}`;
}

export type User = { id: number; name: string; role: "engineer" | "reviewer" | "admin" };

export type LedgerEvent = {
  seq: number;
  ts: string;
  actor: string;
  event_type: string;
  payload: Record<string, unknown>;
  prev_hash: string;
  hash: string;
};

export type VerifyResult = {
  ok: boolean;
  length: number;
  first_bad_seq: number | null;
  reason: string | null;
  head_hash: string;
};

/** Pages broadcast this after anything that writes to the ledger, so status cells refresh. */
export const LEDGER_CHANGED = "kila:ledger-changed";
export function notifyLedgerChanged() {
  window.dispatchEvent(new Event(LEDGER_CHANGED));
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function formatTime(iso: string): string {
  const d = new Date(iso.endsWith("Z") || /[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function shortMime(m: string) {
  const map: Record<string, string> = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/octet-stream": "binary",
  };
  return map[m] ?? m.replace(/^(image|text|application)\//, "");
}
