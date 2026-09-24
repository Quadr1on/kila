"use client";

import { createContext, useContext } from "react";
import type { User } from "@/lib/api";

const Ctx = createContext<User | null>(null);

export function UserProvider({ user, children }: { user: User; children: React.ReactNode }) {
  return <Ctx.Provider value={user}>{children}</Ctx.Provider>;
}

export function useUser(): User {
  const u = useContext(Ctx);
  if (!u) throw new Error("useUser outside UserProvider");
  return u;
}
