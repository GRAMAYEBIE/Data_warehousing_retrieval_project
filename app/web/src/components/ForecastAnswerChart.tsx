import { CalendarDays, Clock, TrendingUp } from "lucide-react";
import { Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, LabelList, Line, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, type TooltipProps, XAxis, YAxis } from "recharts";
import type { Answer } from "../api/client";
import { compact, formatValue } from "../lib/format";
import { useIsDark } from "../lib/theme";
import { CountUp } from "./motion";
import { BarList, INK } from "./ResultChart";

type Props = { answer: Answer; units: Record<string, string>; labels: Record<string, string>; month: string };
type Ink = (typeof INK)["light"];

// A forecast answer has its own figures: expected values, an 80 % range when it is valid,
// and the month it is about. One measure, one axis; the range is a band, never a series.
export default function ForecastAnswerChart({ answer, units, labels, month }: Props) {
  const ink = useIsDark() ? INK.dark : INK.light;
  const metric = answer.plan?.metrics[0] ?? "trips";
  const unit = units[metric] ?? "trips";
  const label = labels[metric] ?? metric.replace(/_/g, " ");
  const rows = answer.rows.map((r) => Object.fromEntries(answer.columns.map((c, i) => [c, r[i]])));
  const fmt = (n: number) => formatValue(n >= 100 ? Math.round(n) : Math.round(n * 10) / 10, unit);
  const tick = (v: number) => (unit.startsWith("USD") ? `$${compact(v)}` : compact(v));
  const first = answer.columns[0];

  if (answer.columns.includes(`${metric}_per_day`)) {
    const row = rows[0] ?? {};
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <Tile icon={<TrendingUp size={15} />} label={`${label} expected, ${month}`} value={Number(row[metric])} format={fmt} />
        <Tile icon={<CalendarDays size={15} />} label="On an average day" value={Number(row[`${metric}_per_day`])} format={fmt} />
      </div>
    );
  }
  if (first === "period") return <Daily rows={rows} metric={metric} fmt={fmt} tick={tick} ink={ink} />;
  if (first === "pickup_hour") return <Hourly rows={rows} metric={metric} fmt={fmt} tick={tick} ink={ink} />;
  return (
    <BarList
      unit={unit}
      colors={ink}
      title={`${label} expected, ${month}`}
      rows={rows.map((r) => ({ key: String(r[first]), value: Number(r[metric]) }))}
    />
  );
}

function Tile({ icon, label, value, format }: { icon: React.ReactNode; label: string; value: number; format: (n: number) => string }) {
  return (
    <div className="rounded-input border border-dashed border-accent/60 bg-accent/5 px-4 py-3.5">
      <div className="flex items-center gap-1.5 text-xs font-medium text-ink-2">
        <span className="text-primary-strong" aria-hidden="true">
          {icon}
        </span>
        {label}
      </div>
      <div className="num mt-1 font-display text-[34px] font-semibold leading-tight text-ink">
        {Number.isFinite(value) ? <CountUp value={value} format={format} /> : "-"}
      </div>
    </div>
  );
}

type Row = Record<string, unknown>;

function Daily({ rows, metric, fmt, tick, ink }: { rows: Row[]; metric: string; fmt: (n: number) => string; tick: (n: number) => string; ink: Ink }) {
  const ranged = rows.length > 0 && `${metric}_low_80` in rows[0];
  const points = rows.map((r) => {
    const day = new Date(`${r.period}T00:00:00`);
    return {
      key: day.toLocaleDateString("en-GB", { day: "numeric", month: "short" }),
      weekday: day.toLocaleDateString("en-GB", { weekday: "long" }),
      value: Number(r[metric]),
      range: ranged ? ([Number(r[`${metric}_low_80`]), Number(r[`${metric}_high_80`])] as [number, number]) : undefined,
    };
  });
  const average = points.reduce((s, p) => s + p.value, 0) / (points.length || 1);
  const peak = points.reduce((a, b) => (b.value > a.value ? b : a), points[0]);
  return (
    <figure>
      <div className="h-[250px] w-full">
        <ResponsiveContainer>
          <ComposedChart data={points} margin={{ top: 16, right: 14, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={ink.grid} vertical={false} />
            <XAxis dataKey="key" tick={{ fontSize: 11, fill: ink.axis }} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={26} />
            <YAxis tickFormatter={tick} tick={{ fontSize: 11, fill: ink.axis }} width={52} axisLine={false} tickLine={false} />
            <Tooltip content={<DayTip fmt={fmt} />} cursor={{ stroke: ink.axis, strokeDasharray: "3 3" }} />
            {ranged && <Area dataKey="range" stroke="none" fill={ink.series[0]} fillOpacity={0.14} animationDuration={700} />}
            <ReferenceLine y={average} stroke={ink.axis} strokeDasharray="4 4" ifOverflow="extendDomain" />
            <Line dataKey="value" stroke={ink.series[0]} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "rgb(var(--surface))" }} animationDuration={800} />
            {peak && <ReferenceDot x={peak.key} y={peak.value} r={5} fill={ink.series[0]} stroke="rgb(var(--surface))" strokeWidth={2} />}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
        <Key swatch={<span className="h-0.5 w-4 rounded" style={{ background: ink.series[0] }} />} text="Expected per day" />
        {ranged && <Key swatch={<span className="h-2.5 w-4 rounded-sm" style={{ background: ink.series[0], opacity: 0.18 }} />} text="80 % range" />}
        <Key swatch={<span className="w-4 border-t border-dashed" style={{ borderColor: ink.axis }} />} text={`Average, ${fmt(average)} a day`} />
        {peak && (
          <span>
            Busiest: <span className="font-medium text-ink-2">{peak.weekday} {peak.key}</span>
          </span>
        )}
      </figcaption>
    </figure>
  );
}

function Hourly({ rows, metric, fmt, tick, ink }: { rows: Row[]; metric: string; fmt: (n: number) => string; tick: (n: number) => string; ink: Ink }) {
  const points = rows.map((r) => ({ key: `${String(r.pickup_hour).padStart(2, "0")}:00`, value: Number(r[metric]) }));
  const peak = points.reduce((a, b) => (b.value > a.value ? b : a), points[0]);
  const low = points.reduce((a, b) => (b.value < a.value ? b : a), points[0]);
  return (
    <figure>
      <div className="h-[240px] w-full">
        <ResponsiveContainer>
          <BarChart data={points} margin={{ top: 22, right: 6, left: 0, bottom: 0 }} barCategoryGap="14%">
            <CartesianGrid stroke={ink.grid} vertical={false} />
            <XAxis dataKey="key" tick={{ fontSize: 11, fill: ink.axis }} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={18} />
            <YAxis tickFormatter={tick} tick={{ fontSize: 11, fill: ink.axis }} width={48} axisLine={false} tickLine={false} />
            <Tooltip content={<HourTip fmt={fmt} />} cursor={{ fill: ink.grid, opacity: 0.6 }} />
            <Bar dataKey="value" radius={[4, 4, 0, 0]} animationDuration={700}>
              {points.map((p) => (
                <Cell key={p.key} fill={ink.series[0]} fillOpacity={p.key === peak?.key ? 1 : 0.38} />
              ))}
              <LabelList
                dataKey="value"
                position="top"
                content={(props) => {
                  const { x, y, width, index } = props as { x: number; y: number; width: number; index: number };
                  if (points[index]?.key !== peak?.key) return null;
                  return (
                    <text x={x + width / 2} y={y - 6} textAnchor="middle" fontSize={11} fill={ink.label}>
                      {fmt(points[index].value)}
                    </text>
                  );
                }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-3">
        <span className="inline-flex items-center gap-1.5">
          <Clock size={12} aria-hidden="true" /> On an average day
        </span>
        {peak && (
          <span>
            Peak <span className="font-medium text-ink-2">{peak.key}</span> ({fmt(peak.value)})
          </span>
        )}
        {low && (
          <span>
            Quietest <span className="font-medium text-ink-2">{low.key}</span> ({fmt(low.value)})
          </span>
        )}
      </figcaption>
    </figure>
  );
}

function Key({ swatch, text }: { swatch: React.ReactNode; text: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {swatch}
      {text}
    </span>
  );
}

function DayTip({ active, payload, fmt }: TooltipProps<number, string> & { fmt: (n: number) => string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as { key: string; weekday: string; value: number; range?: [number, number] };
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-raised">
      <div className="mb-1 font-medium text-ink">
        {p.weekday} {p.key}
      </div>
      <div className="num text-ink">{fmt(p.value)} expected</div>
      {p.range && (
        <div className="num text-ink-3">
          80 % range {fmt(p.range[0])} to {fmt(p.range[1])}
        </div>
      )}
    </div>
  );
}

function HourTip({ active, payload, fmt }: TooltipProps<number, string> & { fmt: (n: number) => string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as { key: string; value: number };
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-raised">
      <div className="mb-1 font-medium text-ink">{p.key}</div>
      <div className="num text-ink">{fmt(p.value)} expected on an average day</div>
    </div>
  );
}
