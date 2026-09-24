import { TitleBlock } from "@/components/TitleBlock";
import { Chat } from "./Chat";

export default function WorkbenchPage() {
  return (
    <>
      <TitleBlock subtitle="Chat with the local model. Task planning, tools and deliverables arrive in phase 4." />
      <Chat />
    </>
  );
}
