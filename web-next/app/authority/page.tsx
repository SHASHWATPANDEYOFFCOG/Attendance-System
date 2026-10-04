import { redirect } from "next/navigation";

/** /authority is the easy-to-remember address; the dashboard lives at /dashboard. */
export default function AuthorityHome() {
  redirect("/dashboard");
}
