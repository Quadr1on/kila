import { PlannedPage } from "@/components/PlannedPage";
import { TitleBlock } from "@/components/TitleBlock";
import { NAV } from "@/lib/nav";

export default function Page() {
  return (
    <>
      <TitleBlock />
      <PlannedPage
        item={NAV[6]}
        bullets={[
          "Golden tasks across every task type",
          "Task-type accuracy, verifier pass rate, numeric correctness, citation validity",
          "p50/p95 latency per task type, measured on this hardware",
        ]}
      />
    </>
  );
}
