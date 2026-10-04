"use client";

/** Who a message or notice goes to. The server re-resolves it within the sender's own scope. */
import { useEffect, useState } from "react";

import { api } from "@/lib/client";
import { Checkbox, SelectField, TextField } from "@/components/forms";

export type Audience = { type: "all" | "department" | "batch" | "section" | "students"; ids: number[] };
type Opt = { id: number; label: string };

export function AudiencePicker({ value, onChange, error }: { value: Audience; onChange: (a: Audience) => void; error?: string | null }) {
  const [opts, setOpts] = useState<Opt[]>([]);
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Opt[]>([]);
  const [chosenLabels, setChosenLabels] = useState<Record<number, string>>({});

  useEffect(() => {
    const t = value.type;
    if (t === "section") api.get<{ id: number; label: string }[]>("/api/sections?mine=true").then(setOpts).catch(() => setOpts([]));
    else if (t === "batch") api.get<{ id: number; label: string }[]>("/api/batches").then(setOpts).catch(() => setOpts([]));
    else if (t === "department") api.get<{ id: number; code: string; name: string }[]>("/api/departments")
      .then((d) => setOpts(d.map((x) => ({ id: x.id, label: `${x.code} — ${x.name}` })))).catch(() => setOpts([]));
    else setOpts([]);
  }, [value.type]);

  useEffect(() => {
    if (value.type !== "students" || q.trim().length < 2) return setFound([]);
    const t = setTimeout(() => {
      api.get<{ rows: { id: number; full_name: string; roll_number: string | null; section: string | null }[] }>(
        `/api/students?status=approved&page_size=20&q=${encodeURIComponent(q.trim())}`)
        .then((r) => setFound(r.rows.map((s) => ({ id: s.id, label: `${s.full_name} · ${s.roll_number ?? ""} · ${s.section ?? ""}` }))))
        .catch(() => setFound([]));
    }, 250);
    return () => clearTimeout(t);
  }, [q, value.type]);

  const toggle = (o: Opt, on: boolean) => {
    setChosenLabels((m) => ({ ...m, [o.id]: o.label }));
    onChange({ ...value, ids: on ? [...new Set([...value.ids, o.id])] : value.ids.filter((x) => x !== o.id) });
  };

  return (
    <div className="grid gap-2">
      <SelectField label="Send to" value={value.type} error={error}
                   onChange={(e) => onChange({ type: e.target.value as Audience["type"], ids: [] })}>
        <option value="students">Selected students</option>
        <option value="section">Whole class (section)</option>
        <option value="batch">Batch</option>
        <option value="department">Branch</option>
        <option value="all">All my students</option>
      </SelectField>
      {value.type === "students" ? (
        <>
          <TextField label="Find students" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or roll number (2+ letters)" />
          {found.length ? (
            <div className="grid max-h-[180px] gap-1 overflow-y-auto rounded-[var(--radius)] border border-rule p-2">
              {found.map((o) => <Checkbox key={o.id} label={o.label} checked={value.ids.includes(o.id)} onChange={(e) => toggle(o, e.target.checked)} />)}
            </div>
          ) : null}
          {value.ids.length ? (
            <p className="m-0 text-[12.5px] text-ash">Selected: {value.ids.map((id) => chosenLabels[id]?.split(" · ")[0] ?? `#${id}`).join(", ")}</p>
          ) : null}
        </>
      ) : value.type !== "all" ? (
        <div className="grid max-h-[180px] gap-1 overflow-y-auto rounded-[var(--radius)] border border-rule p-2">
          {opts.length ? opts.map((o) => <Checkbox key={o.id} label={o.label} checked={value.ids.includes(o.id)} onChange={(e) => toggle(o, e.target.checked)} />)
            : <span className="text-[13px] text-ash">Nothing to choose from.</span>}
        </div>
      ) : (
        <p className="m-0 text-[12.5px] text-ash">Everyone in the classes you are responsible for.</p>
      )}
    </div>
  );
}
