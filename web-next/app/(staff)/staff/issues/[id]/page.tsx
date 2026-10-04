import { getMe } from "@/lib/api";
import { IssueDetail } from "@/components/issue-detail";

export default async function StaffIssuePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const me = await getMe();
  return <IssueDetail id={Number(id)} staff meId={me?.id ?? 0} />;
}
