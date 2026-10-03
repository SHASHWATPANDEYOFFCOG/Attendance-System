import Link from "next/link";

import { getMe } from "@/lib/api";
import { Page, PageHeader } from "@/components/shell";
import { SetupScreens } from "@/components/setup";
import { TABS, type Tab } from "@/lib/setup-tabs";

export const metadata = { title: "Setup" };

export default async function SetupPage({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const me = await getMe();
  const { tab: raw } = await searchParams;
  const tab = (TABS.some(([k]) => k === raw) ? raw : "branches") as Tab;

  return (
    <Page wide>
      <PageHeader title="Setup" subtitle="Academic structure, timetable, rooms and calendar" />
      <nav aria-label="Setup sections" className="-mx-1 mb-4 overflow-x-auto pb-1">
        <ul className="m-0 flex min-w-max list-none gap-1 p-0 px-1">
          {TABS.map(([key, label]) => (
            <li key={key}>
              <Link
                href={`/staff/setup?tab=${key}`}
                aria-current={tab === key ? "page" : undefined}
                className="display block rounded-[3px] border px-3 py-1.5 text-[11.5px] no-underline"
                style={
                  tab === key
                    ? { background: "var(--ink)", borderColor: "var(--ink)", color: "var(--card)" }
                    : { borderColor: "var(--rule)", color: "var(--ink)" }
                }
              >
                {label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      {me ? (
        <SetupScreens key={tab} tab={tab} role={me.role} departmentId={me.department_id} userId={me.id} />
      ) : null}
    </Page>
  );
}
