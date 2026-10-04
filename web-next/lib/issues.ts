/** Issue labels shared by the student and staff screens. */
export type IssueRow = {
  id: number; category: string; category_label: string; title: string; status: string;
  created_at: string; updated_at: string; comment_count: number;
  student: { name: string; roll_number: string | null; section: string | null };
  assigned_to: { id: number; name: string } | null;
};

export const ISSUE_CATEGORIES: [string, string][] = [
  ["attendance_correction", "Attendance correction"], ["academic", "Academic"],
  ["technical", "Technical problem"], ["personal", "Personal"], ["other", "Other"],
];

export function issueTone(status: string): "ok" | "warn" | "bad" | "neutral" {
  return status === "resolved" ? "ok" : status === "closed" ? "neutral" : status === "in_progress" ? "warn" : "bad";
}
