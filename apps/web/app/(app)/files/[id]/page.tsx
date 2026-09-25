import { Suspense } from "react";
import { TitleBlock } from "@/components/TitleBlock";
import { DocumentView } from "./DocumentView";

export default async function DocumentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <>
      <TitleBlock title="Document" subtitle="What KILA read from this file, page by page, and how sure it is." />
      <Suspense>
        <DocumentView objectId={id} />
      </Suspense>
    </>
  );
}
