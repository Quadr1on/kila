import { redirect } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { UserProvider } from "@/components/UserContext";
import { getCurrentUser } from "@/lib/server";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  return (
    <UserProvider user={user}>
      <div className="min-h-screen md:flex">
        <Sidebar />
        <main className="min-w-0 flex-1 px-4 py-4 md:px-8 md:py-6">{children}</main>
      </div>
    </UserProvider>
  );
}
