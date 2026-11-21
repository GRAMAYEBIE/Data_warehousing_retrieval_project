import type { ReactElement } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  type TooltipProps,
  XAxis,
  YAxis,
} from "recharts";
import { compact, formatValue } from "../lib/format";
import { CountUp } from "./motion";

const SERIES = ["#F7B500", "#2E6DA4", "#14B8A6", "#F0564A", "#8B5CF6"];

type Props = {
  columns: string[];
  rows: unknown[][];
  metrics: string[];
  units?: Record<string, string>;
  labels?: Record<string, string>;
};

// The chart follows the shape of the governed result, never the model's wording:
// one row of metrics -> indicator tiles; a "period" or hour column -> area trend;
// *_previous and *_current columns -> before/after bars; otherwise ranked bars.
export default function ResultChart({ columns, rows, metrics, units = {}, labels = {} }: Props) {
  if (!rows.length || !metrics.length) return null;
  const data = rows.map((row) => Object.fromEntries(columns.map((c, i) => [c, row[i]])));
  const num = (v: unknown) => (v === null || v === undefined ? null : Number(v));
  const label = (m: string) => labels[m] ?? m.replace(/_/g, " ");
  const first = metrics[0];
  const compare = columns.includes(`${first}_current`);
  const dims = columns.filter(
    (c) => !metrics.some((m) => c === m || c.startsWith(`${m}_`)) && c !== "period_role",
  );
  const tick = (v: number) => (units[first] === "ratio" ? `${Math.round(v * 100)}%` : compact(v));
  const unitOf = (name: string) =>
    units[metrics.find((m) => name === m || name === label(m)) ?? first] ?? "";

  if (!compare && rows.length === 1 && dims.length === 0) {
    const shown = metrics.filter((m) => columns.includes(m));
    return (
      <div className={`grid gap-3 ${shown.length > 1 ? "sm:grid-cols-2 lg:grid-cols-3" : ""}`}>
        {shown.map((m, i) => (
          <div
            key={m}
            className="relative overflow-hidden rounded-2xl bg-night-900 px-5 py-4 text-white"
          >
            <div className="absolute -right-6 -top-6 h-24 w-24 rounded-full opacity-25" style={{ background: SERIES[i % SERIES.length] }} />
            <div className="eyebrow text-slate-400">{label(m)}</div>
            <div className="mt-1 text-[2.6rem] font-extrabold leading-none tracking-tight tabular-nums">
              {Number.isFinite(Number(data[0][m])) ? (
                <CountUp value={Number(data[0][m])} format={(n) => formatValue(n, units[m])} />
              ) : (
                formatValue(data[0][m], units[m])
              )}
            </div>
            <div className="mt-1 text-xs text-slate-400">{units[m]}</div>
          </div>
        ))}
      </div>
    );
  }

  const keyOf = (d: Record<string, unknown>) =>
    (dims.length ? dims : ["period"]).map((c) => d[c] ?? "total").join(" · ");

  if (compare) {
    const points = data.map((d) => ({
      key: dims.length ? keyOf(d) : label(first),
      previous: num(d[`${first}_previous`]),
      current: num(d[`${first}_current`]),
    }));
    return (
      <Frame>
        <BarChart data={points} margin={{ top: 8, left: 4, right: 8 }} barGap={4}>
          <Gradients />
          <CartesianGrid strokeDasharray="4 4" stroke="#E2E8F0" vertical={false} />
          <XAxis dataKey="key" tick={{ fontSize: 11, fill: "#64748B" }} interval={0} angle={-18} height={64} textAnchor="end" axisLine={false} tickLine={false} />
          <YAxis tickFormatter={tick} tick={{ fontSize: 11, fill: "#64748B" }} width={56} axisLine={false} tickLine={false} />
          <Tooltip content={<Tip unit={units[first]} />} cursor={{ fill: "rgba(15,32,56,0.04)" }} />
          <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="previous" name="Previous period" fill="#CBD5E1" radius={[6, 6, 0, 0]} />
          <Bar dataKey="current" name="Current period" fill="url(#g0)" radius={[6, 6, 0, 0]} />
        </BarChart>
      </Frame>
    );
  }

  const shown = metrics.filter((m) => columns.includes(m)).slice(0, 3);
  const trend = columns.includes("period") || columns[0] === "pickup_hour";
  const points = data.map((d) => ({
    key: trend ? String(d.period ?? d.pickup_hour).slice(0, 10) : keyOf(d),
    ...Object.fromEntries(shown.map((m) => [label(m), num(d[m])])),
  }));

  if (trend) {
    return (
      <Frame>
        <AreaChart data={points} margin={{ top: 8, left: 4, right: 8 }}>
          <Gradients />
          <CartesianGrid strokeDasharray="4 4" stroke="#E2E8F0" vertical={false} />
          <XAxis dataKey="key" tick={{ fontSize: 11, fill: "#64748B" }} axisLine={false} tickLine={false} minTickGap={16} />
          <YAxis tickFormatter={tick} tick={{ fontSize: 11, fill: "#64748B" }} width={56} axisLine={false} tickLine={false} />
          <Tooltip content={<Tip unitOf={unitOf} />} />
          {shown.length > 1 && <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />}
          {shown.map((m, i) => (
            <Area
              key={m}
              type="monotone"
              dataKey={label(m)}
              stroke={SERIES[i]}
              strokeWidth={2.5}
              fill={`url(#g${i})`}
              dot={points.length < 32 ? { r: 3, strokeWidth: 0, fill: SERIES[i] } : false}
              activeDot={{ r: 5 }}
            />
          ))}
        </AreaChart>
      </Frame>
    );
  }

  return (
    <Frame>
      <BarChart data={points.slice(0, 25)} margin={{ top: 8, left: 4, right: 8 }}>
        <Gradients />
        <CartesianGrid strokeDasharray="4 4" stroke="#E2E8F0" vertical={false} />
        <XAxis dataKey="key" tick={{ fontSize: 11, fill: "#64748B" }} interval={0} angle={-18} height={64} textAnchor="end" axisLine={false} tickLine={false} />
        <YAxis tickFormatter={tick} tick={{ fontSize: 11, fill: "#64748B" }} width={56} axisLine={false} tickLine={false} />
        <Tooltip content={<Tip unitOf={unitOf} />} cursor={{ fill: "rgba(15,32,56,0.04)" }} />
        <Bar dataKey={label(first)} fill="url(#g0)" radius={[8, 8, 0, 0]} maxBarSize={56} />
      </BarChart>
    </Frame>
  );
}

function Gradients() {
  return (
    <defs>
      {SERIES.map((color, i) => (
        <linearGradient key={color} id={`g${i}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.95} />
          <stop offset="100%" stopColor={color} stopOpacity={0.25} />
        </linearGradient>
      ))}
    </defs>
  );
}

function Tip({
  active,
  payload,
  label,
  unit,
  unitOf,
}: TooltipProps<number, string> & { unit?: string; unitOf?: (name: string) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl bg-night-900 px-3 py-2 text-xs text-white shadow-lift">
      <div className="mb-1 font-semibold text-taxi-300">{label}</div>
      {payload.map((p) => (
        <div key={String(p.name)} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color === "url(#g0)" ? SERIES[0] : p.color }} />
          <span className="text-slate-300">{p.name}</span>
          <span className="ml-auto pl-3 font-semibold tabular-nums">
            {formatValue(p.value, unit ?? unitOf?.(String(p.name)) ?? "")}
          </span>
        </div>
      ))}
    </div>
  );
}

function Frame({ children }: { children: ReactElement }) {
  return (
    <div className="h-80 w-full">
      <ResponsiveContainer>{children}</ResponsiveContainer>
    </div>
  );
}
