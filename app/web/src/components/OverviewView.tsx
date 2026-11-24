import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { CircleAlert, Code2, MessagesSquare, RefreshCw, ShieldCheck } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type CatalogView, type OverviewView as Overview } from "../api/client";
import { compact, dayLabel, formatValue, monthLabel } from "../lib/format";
import { useIsDark } from "../lib/theme";
import { CountUp, rise, spring, stagger } from "./motion";
import { BarList, INK, Tip } from "./ResultChart";

type Table = Overview["tables"][string];
type Ask = (question: string) => void;

const num = (v: unknown) => (v === null || v === undefined || v === "" ? null : Number(v));
const rowsOf = (t?: Table) => (t ? t.rows.map((r) => Object.fromEntries(t.columns.map((c, i) => [c, r[i]]))) : []);
const hour = (h: number) => `${String(h).padStart(2, "0")}:00`;

// The month at a glance. Every figure comes from the governed path (catalogue, approved
// query templates, published layer); the page never calls the language model.
export default function OverviewView({ catalog, onAsk }: { catalog?: CatalogView; onAsk: Ask }) {
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview, staleTime: 5 * 60_000 });
  const ink = useInk();
  const data = overview.data;

  if (overview.isError) {
    return (
      <Shell>
        <div className="card flex items-start gap-3 p-5">
          <CircleAlert size={20} className="mt-0.5 shrink-0 text-bad-ink" aria-hidden="true" />
          <div className="flex-1">
            <h2 className="text-base font-semibold">The overview could not be loaded</h2>
            <p className="mt-1 text-sm text-ink-2">{String(overview.error)}</p>
          </div>
          <button className="btn-outline" onClick={() => overview.refetch()}>
            <RefreshCw size={15} aria-hidden="true" /> Retry
          </button>
        </div>
      </Shell>
    );
  }
  if (!data) return <Loading />;

  const month = monthLabel(data.latest_month);
  const before = monthLabel(data.previous_month);
  const units = Object.fromEntries(Object.entries(catalog?.metrics ?? {}).map(([k, m]) => [k, m.unit]));
  const kpi = rowsOf(data.tables.kpis)[0] ?? {};

  return (
    <Shell>
      <header className="flex flex-wrap items-end gap-4">
        <div className="min-w-0 flex-1">
          <div className="label">Overview</div>
          <h1 className="mt-1 text-[30px] font-semibold leading-tight sm:text-[34px]">{month} at a glance</h1>
          <p className="mt-1.5 text-sm text-ink-2">
            Compared with {before} · publication <span className="font-mono text-xs">{data.published_run}</span>, published{" "}
            {dayLabel(data.published_at)}
          </p>
        </div>
        <button className="btn-accent" onClick={() => onAsk(`How did ${month} compare with ${before}?`)}>
          <MessagesSquare size={16} aria-hidden="true" /> Ask about {monthLabel(data.latest_month, true)}
        </button>
      </header>

      <motion.section
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
        variants={stagger}
        initial="hidden"
        animate="show"
        aria-label="Key figures"
      >
        {Object.entries(data.measures).map(([metric, label]) => (
          <KpiTile
            key={metric}
            label={label}
            unit={units[metric] ?? ""}
            current={num(kpi[`${metric}_current`])}
            previous={num(kpi[`${metric}_previous`])}
            before={before}
            onAsk={() => onAsk(`What was the ${label.replace(/ \(.*\)$/, "").toLowerCase()} in ${month} compared with ${before}?`)}
          />
        ))}
      </motion.section>

      <Quality rate={data.valid_trip_rate} previous={data.previous_valid_trip_rate} month={month} before={before} />

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel
          className="lg:col-span-2"
          title="Monthly trend"
          subtitle="Every published month"
          table={data.tables.trend}
          onAsk={() => onAsk("Show the monthly trend of trips across all months")}
        >
          <Trend table={data.tables.trend} units={units} labels={data.measures} />
        </Panel>
        <Panel
          title="Pickup boroughs"
          subtitle={`Trips, ${month}`}
          table={data.tables.boroughs}
          onAsk={() => onAsk(`Break down trips by pickup borough in ${month}`)}
        >
          <BarList
            unit="trips"
            colors={ink}
            rows={rowsOf(data.tables.boroughs)
              .map((r) => ({ key: String(r.pickup_borough), value: num(r.trips) }))
              .filter((r) => r.value !== null)}
          />
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel
          className="lg:col-span-2"
          title="Trips by hour of the day"
          subtitle={`${month}, pickup hour`}
          table={data.tables.hourly}
          onAsk={() => onAsk(`How do trips vary by hour of the day in ${month}?`)}
        >
          <Hourly table={data.tables.hourly} />
        </Panel>
        <Panel
          title="Busiest pickup zones"
          subtitle={`Top 8, ${month}`}
          table={data.tables.zones}
          onAsk={() => onAsk(`What were the top 10 pickup zones by trips in ${month}?`)}
        >
          <BarList
            unit="trips"
            colors={ink}
            rows={rowsOf(data.tables.zones).map((r) => ({ key: String(r.pickup_zone), value: num(r.trips) }))}
          />
        </Panel>
      </div>

      <p className="flex items-start gap-2 pb-2 text-xs leading-5 text-ink-3">
        <ShieldCheck size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
        Every figure on this page comes from the governed measures, computed with approved query templates on the published
        layer: the same numbers as the assistant and the dashboards. No language model is involved here.
      </p>
    </Shell>
  );
}

function useInk() {
  return useIsDark() ? INK.dark : INK.light;
}

function Shell({ children }: { children: ReactNode }) {
  return <div className="mx-auto w-full max-w-[1180px] space-y-5 px-4 py-7 sm:px-6 lg:py-9">{children}</div>;
}

function KpiTile({
  label,
  unit,
  current,
  previous,
  before,
  onAsk,
}: {
  label: string;
  unit: string;
  current: number | null;
  previous: number | null;
  before: string;
  onAsk: () => void;
}) {
  const change = current !== null && previous ? ((current - previous) / Math.abs(previous)) * 100 : null;
  // Ratios move in points: "+0.4 pt" reads better than a percentage of a percentage.
  const points = unit === "ratio" && current !== null && previous !== null ? (current - previous) * 100 : null;
  const up = (points ?? change ?? 0) >= 0;
  return (
    <motion.div variants={rise} className="card lift group relative p-5">
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm font-medium text-ink-2">{label}</div>
        <button
          className="btn-ghost -mr-2 -mt-1.5 h-8 w-8 p-0 opacity-70 group-hover:opacity-100"
          onClick={onAsk}
          aria-label={`Ask the assistant about ${label}`}
          title="Ask the assistant"
        >
          <MessagesSquare size={15} aria-hidden="true" />
        </button>
      </div>
      <div className="num mt-1 font-display text-[34px] font-semibold leading-tight tracking-tight text-ink">
        {current === null ? "-" : <CountUp value={current} format={(n) => tileValue(n, unit)} />}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        {(points ?? change) !== null && (
          <span
            className={`chip num ${up ? "border-good/30 bg-good/10 text-good-ink" : "border-bad/30 bg-bad/10 text-bad-ink"}`}
            aria-label={`${up ? "up" : "down"} ${Math.abs(points ?? change ?? 0).toFixed(1)} ${points !== null ? "points" : "percent"}`}
          >
            {up ? "▲" : "▼"} {Math.abs(points ?? change ?? 0).toFixed(1)} {points !== null ? "pt" : "%"}
          </span>
        )}
        <span className="num text-ink-3">
          vs {previous === null ? "-" : tileValue(previous, unit)} in {before}
        </span>
      </div>
    </motion.div>
  );
}

// Millions read as "4.01M" and "$115.0M" on a tile; the exact figures are in the panels,
// the tooltips and the assistant's answers.
function tileValue(n: number, unit: string) {
  if (Math.abs(n) < 1_000_000) return unit === "trips" ? formatValue(Math.round(n), unit) : formatValue(n, unit);
  return unit.startsWith("USD") ? `$${(n / 1_000_000).toFixed(1)}M` : `${(n / 1_000_000).toFixed(2)}M`;
}

function Quality({ rate, previous, month, before }: { rate: number | null; previous: number | null; month: string; before: string }) {
  if (rate === null) return null;
  const pct = rate * 100;
  return (
    <section className="card flex flex-wrap items-center gap-x-5 gap-y-3 px-5 py-4" aria-label="Data quality">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-good/10 text-good-ink">
        <ShieldCheck size={20} aria-hidden="true" />
      </span>
      <div className="min-w-[220px] flex-1">
        <div className="text-sm font-semibold">
          <span className="num">{pct.toFixed(1)} %</span> of {month} trips passed the quality checks
        </div>
        <p className="mt-0.5 text-xs text-ink-3">
          {previous !== null && <span className="num">{(previous * 100).toFixed(1)} % in {before}. </span>}
          Trips that fail a check stay in the warehouse for audit and are left out of every figure.
        </p>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-tint sm:w-48" role="img" aria-label={`${pct.toFixed(1)} percent valid`}>
        <motion.div
          className="h-full rounded-full bg-good"
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ ...spring, delay: 0.2 }}
        />
      </div>
    </section>
  );
}

function Panel({
  title,
  subtitle,
  table,
  onAsk,
  className = "",
  children,
}: {
  title: string;
  subtitle: string;
  table?: Table;
  onAsk: () => void;
  className?: string;
  children: ReactNode;
}) {
  return (
    <motion.section
      className={`card flex flex-col p-5 ${className}`}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
      aria-label={title}
    >
      <header className="mb-4 flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold">{title}</h2>
          <p className="text-xs text-ink-3">{subtitle}</p>
        </div>
        <button className="btn-ghost h-8 px-2.5 text-xs" onClick={onAsk}>
          <MessagesSquare size={14} aria-hidden="true" /> Ask
        </button>
      </header>
      <div className="flex flex-1 flex-col">{children}</div>
      {table && (
        <details className="mt-3 border-t border-line pt-3">
          <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-ink-2 hover:text-ink">
            <Code2 size={13} aria-hidden="true" /> Approved query
          </summary>
          <pre className="mt-2 max-h-56 overflow-auto rounded-lg bg-tint p-3 font-mono text-[11px] leading-5 text-ink-2">{table.sql}</pre>
        </details>
      )}
    </motion.section>
  );
}

// One measure at a time (one axis): the switch picks it.
function Trend({ table, units, labels }: { table?: Table; units: Record<string, string>; labels: Record<string, string> }) {
  const ink = useInk();
  const [metric, setMetric] = useState("trips");
  const unit = units[metric] ?? (metric === "trips" ? "trips" : "USD");
  const points = rowsOf(table).map((r) => ({ month: monthLabel(r.period), value: num(r[metric]) }));
  const last = points.length - 1;
  const tick = (v: number) => (unit.startsWith("USD") ? `$${compact(v)}` : compact(v));
  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 inline-flex self-start rounded-input bg-tint p-1" role="tablist" aria-label="Measure">
        {["trips", "total_revenue"].map((m) => (
          <button
            key={m}
            role="tab"
            aria-selected={metric === m}
            onClick={() => setMetric(m)}
            className={`relative rounded-[8px] px-3 py-1 text-xs font-medium transition-colors ${metric === m ? "text-ink" : "text-ink-2 hover:text-ink"}`}
          >
            {metric === m && <motion.span layoutId="trend-tab" className="absolute inset-0 rounded-[8px] bg-surface shadow-soft" transition={spring} />}
            <span className="relative">{labels[m] ?? m}</span>
          </button>
        ))}
      </div>
      <div className="min-h-[250px] w-full flex-1">
        <ResponsiveContainer>
          <AreaChart key={metric} data={points} margin={{ top: 10, right: 14, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="overview-trend" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={ink.series[0]} stopOpacity={0.18} />
                <stop offset="100%" stopColor={ink.series[0]} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={ink.grid} vertical={false} />
            <XAxis
              dataKey="month"
              tickFormatter={(v: string) => v.slice(0, 3)}
              tick={{ fontSize: 12, fill: ink.axis }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis tickFormatter={tick} tick={{ fontSize: 12, fill: ink.axis }} width={56} axisLine={false} tickLine={false} />
            <Tooltip content={<Tip unit={unit} />} cursor={{ stroke: ink.axis, strokeDasharray: "3 3" }} />
            <Area
              type="monotone"
              dataKey="value"
              name={labels[metric] ?? metric}
              stroke={ink.series[0]}
              strokeWidth={2}
              fill="url(#overview-trend)"
              dot={(p: { cx?: number; cy?: number; index?: number }) => (
                <circle
                  key={p.index}
                  cx={p.cx}
                  cy={p.cy}
                  r={p.index === last ? 5 : 3.5}
                  fill={p.index === last ? ink.series[0] : "rgb(var(--surface))"}
                  stroke={ink.series[0]}
                  strokeWidth={2}
                />
              )}
              activeDot={{ r: 5, strokeWidth: 2, stroke: "rgb(var(--surface))" }}
              animationDuration={800}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// 24 columns; the busiest hour is the one full-strength bar and is named above the chart.
function Hourly({ table }: { table?: Table }) {
  const ink = useInk();
  const points = rowsOf(table).map((r) => ({ hour: Number(r.pickup_hour), label: hour(Number(r.pickup_hour)), value: num(r.trips) ?? 0 }));
  if (!points.length) return null;
  const peak = points.reduce((a, b) => (b.value > a.value ? b : a));
  const quiet = points.reduce((a, b) => (b.value < a.value ? b : a));
  return (
    <div className="flex h-full flex-col">
      <p className="mb-3 text-sm text-ink-2">
        Busiest at <span className="font-semibold text-ink">{peak.label}</span> (<span className="num">{formatValue(peak.value, "trips")}</span> trips),
        quietest at <span className="font-semibold text-ink">{quiet.label}</span>.
      </p>
      <div className="min-h-[230px] w-full flex-1">
        <ResponsiveContainer>
          <BarChart data={points} margin={{ top: 4, right: 6, left: 0, bottom: 0 }} barCategoryGap="16%">
            <CartesianGrid stroke={ink.grid} vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 12, fill: ink.axis }}
              axisLine={false}
              tickLine={false}
              interval="preserveStartEnd"
              minTickGap={18}
            />
            <YAxis tickFormatter={(v: number) => compact(v)} tick={{ fontSize: 12, fill: ink.axis }} width={48} axisLine={false} tickLine={false} />
            <Tooltip content={<Tip unit="trips" />} cursor={{ fill: ink.grid, opacity: 0.6 }} />
            <Bar dataKey="value" name="Trips" radius={[4, 4, 0, 0]} animationDuration={700}>
              {points.map((p) => (
                <Cell key={p.hour} fill={ink.series[0]} fillOpacity={p.hour === peak.hour ? 1 : 0.5} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Loading() {
  return (
    <Shell>
      <div className="space-y-2">
        <div className="skeleton h-4 w-24" />
        <div className="skeleton h-9 w-72" />
        <div className="skeleton h-4 w-96 max-w-full" />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="card space-y-3 p-5">
            <div className="skeleton h-4 w-24" />
            <div className="skeleton h-9 w-32" />
            <div className="skeleton h-4 w-40" />
          </div>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card h-[340px] p-5 lg:col-span-2">
          <div className="skeleton h-full w-full" />
        </div>
        <div className="card h-[340px] p-5">
          <div className="skeleton h-full w-full" />
        </div>
      </div>
    </Shell>
  );
}
