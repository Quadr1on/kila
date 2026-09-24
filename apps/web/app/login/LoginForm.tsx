"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";

export function LoginForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
      });
      router.push("/files");
      router.refresh();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Username or password is wrong. Check both and try again."
          : "Can't reach the KILA API. Check that the api service is running.",
      );
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="mt-7 space-y-4">
      <Field name="username" label="Username" autoComplete="username" />
      <Field name="password" label="Password" type="password" autoComplete="current-password" />
      {error && (
        <p role="alert" className="border-l-2 border-alarm bg-alarm-wash px-3 py-2 text-sm">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={busy}
        className="w-full bg-control px-4 py-2.5 font-medium text-control-ink disabled:opacity-60"
      >
        {busy ? "Signing in…" : "Sign in"}
      </button>
      <p className="text-xs text-muted">
        Demo accounts: <span className="font-mono">engineer</span>, <span className="font-mono">reviewer</span>,{" "}
        <span className="font-mono">admin</span>. Password is set by <span className="font-mono">KILA_SEED_PASSWORD</span>.
      </p>
    </form>
  );
}

function Field(props: { name: string; label: string; type?: string; autoComplete?: string }) {
  return (
    <label className="block">
      <span className="cell-label">{props.label}</span>
      <input
        name={props.name}
        type={props.type ?? "text"}
        autoComplete={props.autoComplete}
        required
        className="mt-1 block w-full border border-rule bg-ground/40 px-3 py-2 font-mono text-[14px] outline-none focus:border-control"
      />
    </label>
  );
}
