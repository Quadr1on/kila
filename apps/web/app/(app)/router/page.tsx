import { PlannedPage } from "@/components/PlannedPage";
import { TitleBlock } from "@/components/TitleBlock";
import { NAV } from "@/lib/nav";

export default function Page() {
  return (
    <>
      <TitleBlock />
      <PlannedPage
        item={NAV[5]}
        bullets={[
          "Every routing decision: task type, confidence, retrieval relevance, score against threshold",
          "Escalation rate and per-model share",
          "Accuracy against escalation rate across the alpha/tau sweep",
        ]}
      />
    </>
  );
}
