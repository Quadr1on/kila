import { PlannedPage } from "@/components/PlannedPage";
import { TitleBlock } from "@/components/TitleBlock";
import { NAV } from "@/lib/nav";

export default function Page() {
  return (
    <>
      <TitleBlock />
      <PlannedPage
        item={NAV[3]}
        bullets={[
          "Review queue of drafts from the agent",
          "Side-by-side view: deliverable, citations, verification report, step timeline",
          "Sign or reject. Only a reviewer can sign; KILA cannot",
        ]}
      />
    </>
  );
}
