import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/server";
import { LoginForm } from "./LoginForm";

export default async function LoginPage() {
  if (await getCurrentUser()) redirect("/files");
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-[560px] border-[1.5px] border-line bg-sheet">
        <div className="px-6 pb-6 pt-7 sm:px-8">
          <div className="font-display text-[44px] font-semibold leading-none tracking-[0.18em]">KILA</div>
          <p className="mt-2 max-w-[44ch] text-muted">
            Local AI workbench for engineering documents. Runs on this site&apos;s hardware; nothing is sent
            outside the plant network.
          </p>
          <LoginForm />
        </div>
        <dl className="grid grid-cols-3 border-t-[1.5px] border-line">
          <div className="border-r border-rule px-3 py-2">
            <dt className="cell-label">Sign-in</dt>
            <dd className="font-mono text-[13px]">Local accounts</dd>
          </div>
          <div className="border-r border-rule px-3 py-2">
            <dt className="cell-label">Network</dt>
            <dd className="font-mono text-[13px]">No external IdP</dd>
          </div>
          <div className="px-3 py-2">
            <dt className="cell-label">Class</dt>
            <dd className="font-mono text-[13px]">Confidential</dd>
          </div>
        </dl>
      </div>
    </main>
  );
}
