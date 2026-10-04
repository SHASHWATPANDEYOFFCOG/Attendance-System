"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/client";

export type MeLite = { id: number; display_name: string; role: string; email: string | null; phone?: string | null; department_id?: number | null };

/** The signed-in user, for showing or hiding controls. The server enforces every rule anyway. */
export function useMe() {
  const [me, setMe] = useState<MeLite | null>(null);
  useEffect(() => {
    api.get<MeLite>("/api/me").then(setMe).catch(() => setMe(null));
  }, []);
  return { me, isAdministrator: me?.role === "super_admin", isStaff: !!me && ["faculty", "admin", "super_admin"].includes(me.role) };
}

export const ROLE_LABEL: Record<string, string> = {
  faculty: "Teacher", admin: "HOD", super_admin: "Administrator", student: "Student", parent: "Guardian",
};
