import { redirect } from "next/navigation";

import { getMe } from "@/lib/api";
import { homeFor } from "@/lib/session";

/** Role-based landing: students to their portal, staff to the authority dashboard. */
export default async function Home() {
  const me = await getMe();
  redirect(me ? homeFor(me.role) : "/login");
}
