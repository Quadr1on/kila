import "server-only";

import { cookies } from "next/headers";
import type { User } from "./api";

const API_URL = process.env.KILA_API_URL ?? "http://127.0.0.1:8000";

/** Server-side session check: forwards the httpOnly cookie to FastAPI's /auth/me. */
export async function getCurrentUser(): Promise<User | null> {
  const token = (await cookies()).get("kila_session")?.value;
  if (!token) return null;
  try {
    const res = await fetch(`${API_URL}/auth/me`, {
      headers: { cookie: `kila_session=${token}` },
      cache: "no-store",
    });
    return res.ok ? ((await res.json()) as User) : null;
  } catch {
    return null;
  }
}
