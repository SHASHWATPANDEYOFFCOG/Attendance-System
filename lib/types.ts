/**
 * Shapes returned by the FastAPI backend, validated with Zod at the boundary.
 *
 * Parsing rather than casting means a backend change surfaces as a clear error here instead of
 * as `undefined` deep inside a chart. Schemas are shared by client and server (Section 1).
 */
import { z } from "zod";

export const AttendanceStatus = z.enum([
  "present",
  "late",
  "absent",
  "partial",
  "left_early",
  "on_duty",
  "excused",
  "on_leave",
  "needs_review",
]);
export type AttendanceStatus = z.infer<typeof AttendanceStatus>;

export const Role = z.enum(["super_admin", "admin", "faculty", "student", "parent"]);
export type Role = z.infer<typeof Role>;

export const SummarySchema = z.object({
  records_counted: z.number(),
  average_pct: z.number(),
  defaulters: z.number(),
  at_risk: z.number(),
  threshold_pct: z.number(),
});
export type Summary = z.infer<typeof SummarySchema>;

export const TrendSchema = z.object({
  dates: z.array(z.string()),
  series: z.array(
    z.object({
      department_id: z.number(),
      code: z.string(),
      name: z.string(),
      // An explicit null is a day with no classes — never a silently closed gap,
      // which would slide the line and misstate the trend.
      points: z.array(z.number().nullable()),
    }),
  ),
});
export type Trend = z.infer<typeof TrendSchema>;

export const WeekdaySchema = z.object({
  days: z.number(),
  profile: z.array(
    z.object({
      weekday: z.number(),
      label: z.string(),
      counted: z.number(),
      present: z.number(),
      absence_pct: z.number(),
      attendance_pct: z.number(),
    }),
  ),
});
export type Weekday = z.infer<typeof WeekdaySchema>;

export const DefaultersSchema = z.object({
  threshold_pct: z.number(),
  count: z.number(),
  defaulters: z.array(
    z.object({
      user_id: z.number(),
      display_name: z.string(),
      roll_number: z.string().nullable(),
      counted: z.number(),
      present: z.number(),
      attendance_pct: z.number(),
      shortfall_classes: z.number(),
    }),
  ),
});
export type Defaulters = z.infer<typeof DefaultersSchema>;

export const TimetableTodaySchema = z.object({
  date: z.string(),
  periods: z.array(
    z.object({
      slot_id: z.number(),
      session_id: z.number().nullable(),
      subject_code: z.string(),
      subject_name: z.string(),
      section_id: z.number(),
      section_label: z.string(),
      room: z.string(),
      start_time: z.string(),
      end_time: z.string(),
      marked: z.boolean(),
      locked: z.boolean(),
      capture_method: z.string().nullable(),
    }),
  ),
});
export type TimetableToday = z.infer<typeof TimetableTodaySchema>;

export const DashboardSchema = z.object({
  role: Role,
  user: z.object({
    id: z.number(),
    username: z.string(),
    display_name: z.string(),
    roll_number: z.string().nullable().optional(),
  }),
  timezone: z.string(),
  server_time_utc: z.string(),
  system: z
    .object({ warnings: z.array(z.string()).optional() })
    .partial()
    .optional(),
});
export type Dashboard = z.infer<typeof DashboardSchema>;

/** Parse, or return null so one bad panel cannot blank the page. */
export function safe<T>(schema: z.ZodType<T>, value: unknown): T | null {
  const parsed = schema.safeParse(value);
  return parsed.success ? parsed.data : null;
}
