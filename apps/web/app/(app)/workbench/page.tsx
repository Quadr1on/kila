import { PlannedPage } from "@/components/PlannedPage";
import { TitleBlock } from "@/components/TitleBlock";
import { NAV } from "@/lib/nav";

export default function Page() {
  return (
    <>
      <TitleBlock />
      <PlannedPage
        item={NAV[0]}
        bullets={[
          "Streaming chat with the small_text model, every call written to the ledger (phase 1)",
          "Task timeline: router decision, plan, tool calls, verifier results (phase 4)",
          "Deliverable preview and download: .docx, .xlsx, .pptx with citations (phase 4)",
        ]}
      />
    </>
  );
}
