import { PlannedPage } from "@/components/PlannedPage";
import { TitleBlock } from "@/components/TitleBlock";
import { NAV } from "@/lib/nav";

export default function Page() {
  return (
    <>
      <TitleBlock />
      <PlannedPage
        item={NAV[4]}
        bullets={[
          "Each role (small_text, large_text, coder, vision, embedder, reranker) and the model serving it",
          "Health, VRAM from nvidia-smi and tokens/sec from a warm-up call",
          "Activate or roll back a model without restarting",
        ]}
      />
    </>
  );
}
