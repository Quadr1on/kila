import { PlannedPage } from "@/components/PlannedPage";
import { TitleBlock } from "@/components/TitleBlock";
import { NAV } from "@/lib/nav";

export default function Page() {
  return (
    <>
      <TitleBlock />
      <PlannedPage
        item={NAV[2]}
        bullets={[
          "Upload SOPs, standards and past reports into the kb bucket",
          "Index status per document: chunks, pages, last indexed",
          "Search playground: dense, BM25, fused and reranked results side by side",
        ]}
      />
    </>
  );
}
