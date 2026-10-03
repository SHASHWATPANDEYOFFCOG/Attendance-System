/** Setup tabs. A plain module (not "use client") so the server page can read the values;
 *  exports from a client module reach a Server Component as references, not arrays. */
export const TABS = [
  ["branches", "Branches"], ["batches", "Batches"], ["sections", "Sections"], ["subjects", "Subjects"],
  ["assignments", "Teacher assignments"], ["timetable", "Timetable"], ["rooms", "Rooms"],
  ["holidays", "Holidays"], ["terms", "Terms"],
] as const;
export type Tab = (typeof TABS)[number][0];
