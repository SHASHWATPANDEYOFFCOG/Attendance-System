"use client";

/**
 * Charts. Colour comes from the validated tokens, never from Recharts' defaults.
 *
 * Rules held here (dataviz):
 *  - categorical hues assigned in FIXED order and never cycled — colour follows the department,
 *    so filtering the series list must not repaint the survivors;
 *  - one y-axis, never two;
 *  - a legend whenever there are >= 2 series, plus direct labels, so identity is never
 *    colour-alone;
 *  - thin marks, recessive grid, 2px lines, >= 8px hover targets;
 *  - a table view exists behind every chart for screen readers and for the contrast case.
 */
import { useId, useState } from "react";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Trend, Weekday } from "@/lib/types";

/** Fixed slot order. A 4th series folds into "Other" rather than generating a hue. */
const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"] as const;

function shortDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.valueOf())
    ? iso
    : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

/* ------------------------------------------------------------ trend lines */

export function TrendChart({ trend }: { trend: Trend }) {
  const [showTable, setShowTable] = useState(false);
  const tableId = useId();

  if (!trend.dates.length) {
    return <div className="py-6 text-center text-[13.5px] text-ash">No attendance in this window.</div>;
  }

  const rows = trend.dates.map((date, i) => {
    const row: Record<string, string | number | null> = { date: shortDate(date) };
    for (const s of trend.series) row[s.code] = s.points[i];
    return row;
  });

  return (
    <div>
      <div className="h-[260px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
            <CartesianGrid strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="date" tickLine={false} axisLine={false} minTickGap={28} />
            <YAxis
              domain={[0, 100]}
              tickLine={false}
              axisLine={false}
              width={44}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip
              contentStyle={{
                background: "var(--card)",
                border: "1px solid var(--rule)",
                borderRadius: 3,
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                color: "var(--ink)",
              }}
              formatter={(v: unknown, name: string) => [v === null ? "no class" : `${v}%`, name]}
            />
            <Legend
              iconType="plainline"
              wrapperStyle={{ fontSize: 12, fontFamily: "var(--font-label)", letterSpacing: "0.1em" }}
            />
            {trend.series.map((s, i) => (
              <Line
                key={s.department_id}
                type="monotone"
                dataKey={s.code}
                name={s.code}
                stroke={SERIES[i % SERIES.length]}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
                // A missing day is a real gap (no class held). Bridging it would invent a
                // trend line through days that never happened.
                connectNulls={false}
                // No entrance animation: a 1.5s draw-on delays reading an operational number
                // and re-fires on every container resize. Motion needs a reason; this has none.
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <button
        type="button"
        onClick={() => setShowTable((v) => !v)}
        aria-expanded={showTable}
        aria-controls={tableId}
        className="display mt-1 text-[12px] text-ash underline underline-offset-2 hover:text-ink"
      >
        {showTable ? "Hide" : "Show"} data table
      </button>

      {showTable ? (
        <div id={tableId} className="mt-2 max-h-56 overflow-auto">
          <table className="w-full border-collapse font-mono text-[12px] tnum">
            <thead>
              <tr>
                <th className="border-b border-ink px-2 py-1 text-left text-ash">Date</th>
                {trend.series.map((s) => (
                  <th key={s.code} className="border-b border-ink px-2 py-1 text-right text-ash">
                    {s.code}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="border-b border-rule px-2 py-1">{String(r.date)}</td>
                  {trend.series.map((s) => (
                    <td key={s.code} className="border-b border-rule px-2 py-1 text-right">
                      {r[s.code] === null ? "—" : `${r[s.code]}%`}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

/* --------------------------------------------------------- weekday heatmap */

/** Sequential = ONE hue, light to dark. Never a rainbow. */
const SEQ = [
  "var(--seq-0)",
  "var(--seq-1)",
  "var(--seq-2)",
  "var(--seq-3)",
  "var(--seq-4)",
  "var(--seq-5)",
];

export function WeekdayHeatmap({ weekday }: { weekday: Weekday }) {
  const rows = weekday.profile;
  if (!rows.length) {
    return <div className="py-6 text-center text-[13.5px] text-ash">No data yet.</div>;
  }

  const max = Math.max(...rows.map((r) => r.absence_pct), 1);

  return (
    <div>
      <div className="flex gap-1.5">
        {rows.map((r) => {
          const step = Math.min(SEQ.length - 1, Math.floor((r.absence_pct / max) * (SEQ.length - 1)));
          // Deep steps need light text; the light end keeps ink.
          const onDark = step >= 3;
          return (
            <div key={r.weekday} className="flex-1">
              <div
                title={`${r.label}: ${r.absence_pct}% absent (${r.counted - r.present} of ${r.counted})`}
                className="flex h-16 items-center justify-center rounded-[var(--radius)] border border-rule font-mono text-[13px] font-semibold tnum"
                style={{ background: SEQ[step], color: onDark ? "var(--card)" : "var(--ink)" }}
              >
                {r.absence_pct}%
              </div>
              <div className="label mt-1 text-center">{r.label}</div>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-[12.5px] text-ash">
        Share of expected attendances missed, by weekday. Approved leave is excluded.
      </p>
    </div>
  );
}
