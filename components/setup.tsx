"use client";

/**
 * Setup → academic structure. Thin configuration over <CrudTable>: which endpoint, which columns,
 * which fields. Edit rights shown here mirror the server's rules for convenience only; the server
 * re-checks every write.
 */
import { useCallback, useEffect, useState } from "react";

import Link from "next/link";

import { api } from "@/lib/client";
import { CrudTable, type Option } from "@/components/crud";
import { Pill } from "@/components/ui";

type Dept = { id: number; code: string; name: string; students: number; is_active: boolean };
type Batch = { id: number; label: string; start_year: number; end_year: number; students: number; is_active: boolean };
type Section = {
  id: number; name: string; year: number; semester: number; department_id: number;
  department_code: string; batch_id: number | null; batch: string | null; label: string; students: number;
  academic_year_id: number | null; academic_year: string | null; is_active: boolean;
};
type Year = { id: number; label: string; start_date: string; end_date: string; is_active: boolean; is_current: boolean; sections: number };

const activePill = (on: boolean) => (on ? <Pill tone="ok">active</Pill> : <Pill tone="neutral">inactive</Pill>);
type Subject = { id: number; code: string; name: string; department_id: number; department_code: string; year: number | null; semester: number | null; credits: number };
type Staff = { id: number; full_name: string; role: string; department: string | null };
type Room = { id: number; name: string; building: string | null; capacity: number | null; latitude: number | null; longitude: number | null; radius_m: number | null };
type Term = { id: number; name: string; start_date: string; end_date: string; is_active: boolean };

import type { Tab } from "@/lib/setup-tabs";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function SetupScreens({
  tab,
  role,
  departmentId,
  userId,
}: {
  tab: Tab;
  role: string;
  departmentId: number | null;
  userId: number;
}) {
  const superAdmin = role === "super_admin";
  const admin = superAdmin || role === "admin";
  const inDept = (id: number | null | undefined) => superAdmin || (role === "admin" && id === departmentId);

  const [depts, setDepts] = useState<Dept[]>([]);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [staff, setStaff] = useState<Staff[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [terms, setTerms] = useState<Term[]>([]);
  const [years, setYears] = useState<Year[]>([]);

  const refresh = useCallback(() => {
    api.get<Dept[]>("/api/departments").then(setDepts).catch(() => {});
    api.get<Batch[]>("/api/batches").then(setBatches).catch(() => {});
    api.get<Section[]>("/api/sections").then(setSections).catch(() => {});
    api.get<Subject[]>("/api/subjects").then(setSubjects).catch(() => {});
    api.get<Staff[]>("/api/admin/users").then(setStaff).catch(() => {});
    api.get<Room[]>("/api/rooms").then(setRooms).catch(() => {});
    api.get<Term[]>("/api/terms").then(setTerms).catch(() => {});
    api.get<Year[]>("/api/academic-years").then(setYears).catch(() => {});
  }, []);
  useEffect(refresh, [refresh]);

  const deptOpts: Option[] = depts
    .filter((d) => superAdmin || d.id === departmentId)
    .map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` }));
  const allDeptOpts: Option[] = depts.map((d) => ({ value: d.id, label: d.code }));
  const batchOpts: Option[] = batches.map((b) => ({ value: b.id, label: b.label }));
  const sectionOpts: Option[] = sections.map((s) => ({ value: s.id, label: s.label }));
  const subjectOpts = (deptId?: string): Option[] =>
    subjects
      .filter((s) => !deptId || String(s.department_id) === deptId)
      .map((s) => ({ value: s.id, label: `${s.code} — ${s.name}` }));
  const teacherOpts: Option[] = staff.map((t) => ({
    value: t.id,
    label: `${t.full_name}${t.department ? ` (${t.department})` : ""}`,
  }));
  const roomOpts: Option[] = rooms.map((r) => ({ value: r.name, label: `${r.name}${r.building ? ` · ${r.building}` : ""}` }));
  const termOpts: Option[] = terms.map((t) => ({ value: t.id, label: `${t.name}${t.is_active ? " (active)" : ""}` }));
  const yearOpts: Option[] = years.map((y) => ({ value: y.id, label: `${y.label}${y.is_current ? " (current)" : ""}${y.is_active ? "" : " (inactive)"}` }));

  switch (tab) {
    case "years":
      return (
        <CrudTable<Year>
          title="Academic years"
          endpoint="/api/academic-years"
          canCreate={superAdmin}
          canEdit={superAdmin}
          canDelete={superAdmin}
          deleteLabel={(y) => `academic year ${y.label}`}
          onChange={refresh}
          intro="An academic year (e.g. 2026-27) groups the class groups of that year. Mark one as current; class groups are assigned to a year under Sections, and the approval list filters by it."
          toForm={(y) => ({ label: y.label, start_date: y.start_date, end_date: y.end_date, is_active: String(y.is_active), is_current: String(y.is_current) })}
          columns={[
            { key: "label", label: "Academic year", render: (y) => <strong>{y.label}</strong> },
            { key: "start_date", label: "From", className: "font-mono tnum" },
            { key: "end_date", label: "To", className: "font-mono tnum" },
            { key: "sections", label: "Sections", className: "font-mono tnum" },
            { key: "is_active", label: "Status", render: (y) => <>{activePill(y.is_active)} {y.is_current ? <Pill tone="ok">current</Pill> : null}</> },
          ]}
          fields={[
            { name: "label", label: "Academic year", required: true, placeholder: "2026-27" },
            { name: "start_date", label: "Starts", type: "date", required: true },
            { name: "end_date", label: "Ends", type: "date", required: true },
            { name: "is_current", label: "This is the current academic year", type: "checkbox" },
            { name: "is_active", label: "Active", type: "checkbox", defaultValue: "true" },
          ]}
          empty="Add the academic years, e.g. 2025-26, 2026-27."
        />
      );
    case "branches":
      return (
        <CrudTable<Dept>
          title="Branches"
          endpoint="/api/departments"
          canCreate={superAdmin}
          canEdit={(d) => inDept(d.id)}
          canDelete={superAdmin}
          deleteLabel={(d) => `branch ${d.code}`}
          onChange={refresh}
          columns={[
            { key: "code", label: "Code", render: (d) => <strong>{d.code}</strong> },
            { key: "name", label: "Name" },
            { key: "students", label: "Students", className: "font-mono tnum" },
            { key: "is_active", label: "Status", render: (d) => activePill(d.is_active) },
          ]}
          fields={[
            { name: "code", label: "Code", required: true, placeholder: "CSE" },
            { name: "name", label: "Name", required: true, placeholder: "Computer Science & Engineering" },
            { name: "is_active", label: "Active (offered to new registrations)", type: "checkbox", defaultValue: "true" },
          ]}
          empty="Add your first branch, e.g. CSE."
        />
      );
    case "batches":
      return (
        <CrudTable<Batch>
          title="Batches"
          endpoint="/api/batches"
          canCreate={superAdmin}
          canEdit={superAdmin}
          canDelete={superAdmin}
          deleteLabel={(b) => `batch ${b.label}`}
          onChange={refresh}
          columns={[
            { key: "label", label: "Batch", render: (b) => <strong>{b.label}</strong> },
            { key: "students", label: "Students", className: "font-mono tnum" },
            { key: "is_active", label: "Status", render: (b) => activePill(b.is_active) },
          ]}
          fields={[
            { name: "start_year", label: "Start year", type: "number", required: true, placeholder: "2023" },
            { name: "end_year", label: "End year", type: "number", required: true, placeholder: "2027" },
            { name: "is_active", label: "Active (offered to new registrations)", type: "checkbox", defaultValue: "true" },
          ]}
          empty="Add an intake batch, e.g. 2023–2027."
        />
      );
    case "sections":
      return (
        <CrudTable<Section>
          title="Sections"
          endpoint="/api/sections"
          canCreate={admin}
          canEdit={(s) => inDept(s.department_id)}
          canDelete={(s) => inDept(s.department_id)}
          deleteLabel={(s) => `section ${s.label}`}
          onChange={refresh}
          intro="A section is a class group: branch + year + batch + section letter. Students register into one."
          columns={[
            { key: "label", label: "Class group", render: (s) => <strong>{s.label}</strong> },
            { key: "academic_year", label: "Academic year", render: (s) => s.academic_year ?? <span className="text-ash">—</span> },
            { key: "semester", label: "Sem", className: "font-mono tnum" },
            { key: "students", label: "Students", className: "font-mono tnum" },
            { key: "is_active", label: "Status", render: (s) => activePill(s.is_active) },
          ]}
          toForm={(s) => ({
            department_id: String(s.department_id), batch_id: String(s.batch_id ?? ""), name: s.name,
            year: String(s.year), semester: String(s.semester),
            academic_year_id: String(s.academic_year_id ?? ""), is_active: String(s.is_active),
          })}
          fields={[
            { name: "department_id", label: "Branch", type: "select", options: deptOpts, required: true },
            { name: "batch_id", label: "Batch", type: "select", options: batchOpts, required: true },
            { name: "year", label: "Year", type: "number", required: true },
            { name: "semester", label: "Semester", type: "number", required: true },
            { name: "name", label: "Section", required: true, placeholder: "A" },
            { name: "academic_year_id", label: "Academic year", type: "select", options: yearOpts, hint: "Used to filter approvals by academic year." },
            { name: "is_active", label: "Active (offered to new registrations)", type: "checkbox", defaultValue: "true" },
          ]}
          empty="Create branches and batches first, then add sections."
        />
      );
    case "subjects":
      return (
        <CrudTable<Subject>
          title="Subjects"
          endpoint="/api/subjects"
          canCreate={admin}
          canEdit={(s) => inDept(s.department_id)}
          canDelete={(s) => inDept(s.department_id)}
          deleteLabel={(s) => s.code}
          onChange={refresh}
          columns={[
            { key: "code", label: "Code", render: (s) => <strong className="font-mono">{s.code}</strong> },
            { key: "name", label: "Name" },
            { key: "department_code", label: "Branch" },
            { key: "year", label: "Year", className: "font-mono tnum" },
            { key: "semester", label: "Sem", className: "font-mono tnum" },
          ]}
          fields={[
            { name: "code", label: "Code", required: true, placeholder: "CS301" },
            { name: "name", label: "Name", required: true },
            { name: "department_id", label: "Branch", type: "select", options: deptOpts, required: true },
            { name: "year", label: "Year", type: "number" },
            { name: "semester", label: "Semester", type: "number" },
            { name: "credits", label: "Credits", type: "number" },
          ]}
        />
      );
    case "assignments":
      return (
        <CrudTable<{ id: number; faculty_name: string; subject_code: string; subject_name: string; section_label: string }>
          title="Teacher assignments"
          endpoint="/api/assignments"
          canCreate={admin}
          canEdit={false}
          canDelete={admin}
          deleteLabel={(a) => `${a.faculty_name} → ${a.subject_code} ${a.section_label}`}
          intro="Who teaches which subject to which class. This is the boundary for what a teacher can see and mark."
          columns={[
            { key: "faculty_name", label: "Teacher" },
            { key: "subject_code", label: "Subject", render: (a) => <><strong className="font-mono">{a.subject_code}</strong> {a.subject_name}</> },
            { key: "section_label", label: "Class" },
          ]}
          fields={[
            { name: "faculty_id", label: "Teacher", type: "select", options: teacherOpts, required: true },
            { name: "section_id", label: "Class", type: "select", options: sectionOpts, required: true },
            {
              name: "subject_id", label: "Subject", type: "select", required: true,
              options: (f) => subjectOpts(String(sections.find((s) => String(s.id) === f.section_id)?.department_id ?? "")),
            },
          ]}
        />
      );
    case "timetable":
      return (
        <CrudTable<{ id: number; section_label: string; subject_code: string; faculty_name: string; faculty_id: number; day: string; day_of_week: number; start_time: string; end_time: string; room: string; section_id: number; subject_id: number }>
          title="Timetable"
          endpoint="/api/timetable"
          listQuery={admin ? "" : "?mine=true"}
          canEdit={(s) => admin || s.faculty_id === userId}
          canDelete={(s) => admin || s.faculty_id === userId}
          deleteLabel={(s) => `${s.subject_code} on ${s.day} ${s.start_time}`}
          intro="Weekly periods for the active term. Sessions are opened from these automatically at start time (unless it is a holiday)."
          toForm={(s) => ({
            section_id: String(s.section_id), subject_id: String(s.subject_id), faculty_id: String(s.faculty_id),
            day_of_week: String(s.day_of_week), start_time: s.start_time, end_time: s.end_time, room: s.room,
          })}
          columns={[
            { key: "day", label: "Day" },
            { key: "start_time", label: "Time", render: (s) => <span className="font-mono tnum">{s.start_time}–{s.end_time}</span> },
            { key: "subject_code", label: "Subject", render: (s) => <strong className="font-mono">{s.subject_code}</strong> },
            { key: "section_label", label: "Class" },
            { key: "faculty_name", label: "Teacher" },
            { key: "room", label: "Room" },
          ]}
          fields={[
            { name: "section_id", label: "Class", type: "select", options: sectionOpts, required: true, clears: ["subject_id"] },
            {
              name: "subject_id", label: "Subject", type: "select", required: true,
              options: (f) => subjectOpts(String(sections.find((s) => String(s.id) === f.section_id)?.department_id ?? "")),
            },
            {
              name: "faculty_id", label: "Teacher", type: "select", required: true,
              options: admin ? teacherOpts : teacherOpts.filter((t) => t.value === userId),
            },
            { name: "day_of_week", label: "Day", type: "select", required: true, options: DAYS.map((d, i) => ({ value: i, label: d })) },
            { name: "start_time", label: "Start", type: "time", required: true },
            { name: "end_time", label: "End", type: "time", required: true },
            rooms.length
              ? { name: "room", label: "Room", type: "select", options: roomOpts, required: true }
              : { name: "room", label: "Room", required: true, hint: "Add rooms under the Rooms tab to choose from a list." },
          ]}
          empty={terms.length ? "No periods yet." : <>Create an academic term first under <Link href="/staff/setup?tab=terms" className="underline">Terms</Link>.</>}
        />
      );
    case "rooms":
      return (
        <CrudTable<Room>
          title="Rooms"
          endpoint="/api/rooms"
          canCreate={admin}
          canEdit={admin}
          canDelete={admin}
          deleteLabel={(r) => `room ${r.name}`}
          onChange={refresh}
          intro="Coordinates are optional: set them to narrow mobile attendance to one building instead of the whole campus."
          columns={[
            { key: "name", label: "Room", render: (r) => <strong>{r.name}</strong> },
            { key: "building", label: "Building" },
            { key: "capacity", label: "Seats", className: "font-mono tnum" },
            { key: "geo", label: "Geofence", render: (r) => r.latitude != null ? <span className="font-mono text-[12px]">{r.latitude.toFixed(5)}, {r.longitude?.toFixed(5)} · {r.radius_m ?? "campus"} m</span> : <span className="text-ash">campus-wide</span> },
          ]}
          fields={[
            { name: "name", label: "Name", required: true, placeholder: "LH-101" },
            { name: "building", label: "Building" },
            { name: "capacity", label: "Seats", type: "number" },
            { name: "latitude", label: "Latitude", type: "number", hint: "Decimal degrees, e.g. 18.52043" },
            { name: "longitude", label: "Longitude", type: "number" },
            { name: "radius_m", label: "Radius (m)", type: "number" },
          ]}
        />
      );
    case "holidays":
      return (
        <CrudTable<{ id: number; date: string; name: string; department_code: string | null }>
          title="Holidays"
          endpoint="/api/holidays"
          canCreate={admin}
          canEdit={false}
          canDelete={(h) => superAdmin || (role === "admin" && h.department_code === depts.find((d) => d.id === departmentId)?.code)}
          deleteLabel={(h) => `${h.name} (${h.date})`}
          intro="No sessions are opened on a holiday, and it does not count against anyone's percentage."
          columns={[
            { key: "date", label: "Date", render: (h) => <span className="font-mono tnum">{h.date}</span> },
            { key: "name", label: "Holiday" },
            { key: "department_code", label: "Applies to", render: (h) => h.department_code ?? <Pill tone="neutral">whole college</Pill> },
          ]}
          fields={[
            { name: "date", label: "Date", type: "date", required: true },
            { name: "name", label: "Name", required: true },
            {
              name: "department_code", label: "Applies to", type: "select",
              options: superAdmin ? allDeptOpts.map((o) => ({ value: o.label, label: o.label }))
                : depts.filter((d) => d.id === departmentId).map((d) => ({ value: d.code, label: d.code })),
              required: !superAdmin,
              hint: superAdmin ? "Leave empty for the whole college." : undefined,
            },
          ]}
        />
      );
    case "terms":
      return (
        <CrudTable<Term>
          title="Terms"
          endpoint="/api/terms"
          canCreate={superAdmin}
          canEdit={superAdmin}
          canDelete={superAdmin}
          deleteLabel={(t) => t.name}
          onChange={refresh}
          toForm={(t) => ({ name: t.name, start_date: t.start_date, end_date: t.end_date, is_active: String(t.is_active) })}
          columns={[
            { key: "name", label: "Term", render: (t) => <strong>{t.name}</strong> },
            { key: "start_date", label: "From", className: "font-mono tnum" },
            { key: "end_date", label: "To", className: "font-mono tnum" },
            { key: "is_active", label: "", render: (t) => (t.is_active ? <Pill tone="ok">active</Pill> : null) },
          ]}
          fields={[
            { name: "name", label: "Name", required: true, placeholder: "2026 Odd Semester" },
            { name: "start_date", label: "Starts", type: "date", required: true },
            { name: "end_date", label: "Ends", type: "date", required: true },
            { name: "is_active", label: "Active term", type: "checkbox" },
          ]}
        />
      );
  }
}
