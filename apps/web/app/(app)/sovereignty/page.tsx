import { Suspense } from "react";
import { TitleBlock } from "@/components/TitleBlock";
import { LedgerPanel } from "./LedgerPanel";

export default function SovereigntyPage() {
  return (
    <>
      <TitleBlock />
      <Suspense>
        <LedgerPanel />
      </Suspense>
    </>
  );
}
