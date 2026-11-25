import { Radio } from "lucide-react";
import { useState } from "react";
import { Area, Bar, CartesianGrid, Cell, ComposedChart, Line, ResponsiveContainer, Tooltip, type TooltipProps, XAxis, YAxis } from "recharts";
import type { ForecastView } from "../api/client";
import { compact, formatValue } from "../lib/format";
import { INK } from "./ResultChart";
import Tabs from "./Tabs";

type Table = ForecastView["tables"][string];
type Ink = (typeof INK)["light"];
const rowsOf = (t?: Table) => (t ? t.rows.map((r) => Object.fromEntries(t.columns.map((c, i) => [c, r[i]]))) : []);
const BOROUGHS = ["all", "Manhattan", "Queens", "Brooklyn", "Bronx"];
const trips = (n: number) => formatValue(Math.round(n), "trips");

// The forecast month as it streams in through Kafka: provisional trips (counted with the
// plausibility rules of silver) against the forecast of the same days, until the official
// file is published. Only complete days are compared; the day in progress is shown apart.
export default function ForecastLive({ tables, ink }: { tables: ForecastView["tables"]; ink: Ink }) {
  const [borough, setBorough] = useState("all");
  const status = rowsOf(tables.live_status)[0];
  const clock = status?.clock ? new Date(String(status.clock).replace(" ", "T")) : null;
  const today = status?.clock ? String(status.clock).slice(0, 10) : ""; // local time, no time zone shift
  const byDay = new Map<string, { predicted: number; live: number; lower: number; upper: number }>();
  for (const d of rowsOf(tables.live_daily)) {
    if (borough !== "all" && d.borough !== borough) continue;
    const e = byDay.get(String(d.date_day)) ?? { predicted: 0, live: 0, lower: 0, upper: 0 };
    e.predicted += Number(d.predicted);
    e.live += Number(d.live);
    e.lower += Number(d.lower);
    e.upper += Number(d.upper);
    byDay.set(String(d.date_day), e);
  }
  const points = [...byDay.entries()].map(([day, v]) => {
    const date = new Date(`${day}T00:00:00`);
    const state = day < today ? "complete" : day === today ? "in progress" : "to come";
    return {
      day,
      key: date.toLocaleDateString("en-GB", { day: "numeric", month: "short" }),
      weekday: date.toLocaleDateString("en-GB", { weekday: "long" }),
      predicted: v.predicted,
      live: state === "to come" ? null : v.live,
      range: borough === "all" ? undefined : ([v.lower, v.upper] as [number, number]),
      state,
    };
  });
  const complete = points.filter((p) => p.state === "complete");
  const liveDone = complete.reduce((s, p) => s + Number(p.live), 0);
  const forecastDone = complete.reduce((s, p) => s + p.predicted, 0);
  const gap = forecastDone ? (liveDone / forecastDone - 1) * 100 : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <span className="inline-flex items-center gap-2 font-medium text-ink">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-good opacity-60 motion-reduce:hidden" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-good" />
          </span>
          Streaming through Kafka
        </span>
        {clock && (
          <span className="text-ink-2">
            Replay clock{" "}
            <span className="num font-medium text-ink">
              {clock.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}{" "}
              {clock.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
            </span>
          </span>
        )}
        <span className="ml-auto">
          <Tabs label="Borough" id="live-borough" items={BOROUGHS.map((b) => [b, b === "all" ? "All boroughs" : b] as [string, string])} value={borough} onChange={setBorough} />
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Figure label="Trips received" value={trips(Number(status?.received ?? 0))} note={`${trips(Number(status?.plausible ?? 0))} plausible · ${trips(Number(status?.rejected ?? 0))} rejected by the contract`} />
        <Figure label={`Complete days: ${complete.length}`} value={trips(liveDone)} note={`forecast for those days ${trips(forecastDone)}`} />
        <Figure
          label="Recorded against forecast"
          value={gap === null ? "-" : `${gap >= 0 ? "+" : "−"}${Math.abs(gap).toFixed(1)} %`}
          note="complete days only; the day in progress is left out"
        />
      </div>

      <div className="h-[260px] w-full">
        <ResponsiveContainer>
          <ComposedChart data={points} margin={{ top: 10, right: 14, left: 0, bottom: 0 }} barCategoryGap="18%">
            <CartesianGrid stroke={ink.grid} vertical={false} />
            <XAxis dataKey="key" tick={{ fontSize: 11, fill: ink.axis }} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={26} />
            <YAxis tickFormatter={(v: number) => compact(v)} tick={{ fontSize: 11, fill: ink.axis }} width={52} axisLine={false} tickLine={false} />
            <Tooltip content={<LiveTip />} cursor={{ fill: ink.grid, opacity: 0.5 }} />
            {borough !== "all" && <Area dataKey="range" stroke="none" fill={ink.series[0]} fillOpacity={0.12} isAnimationActive={false} />}
            <Bar dataKey="live" radius={[3, 3, 0, 0]} isAnimationActive={false}>
              {points.map((p) => (
                <Cell key={p.day} fill={ink.series[1]} fillOpacity={p.state === "complete" ? 0.85 : 0.35} />
              ))}
            </Bar>
            <Line dataKey="predicted" stroke={ink.series[0]} strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-3 rounded-sm" style={{ background: ink.series[1], opacity: 0.85 }} /> Received (provisional)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-3 rounded-sm" style={{ background: ink.series[1], opacity: 0.35 }} /> Day in progress
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-4 border-t-2 border-dashed" style={{ borderColor: ink.series[0] }} /> Forecast
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Radio size={12} aria-hidden="true" /> Provisional: never in the governed measures; replaced by the official file, then checked
        </span>
      </div>
    </div>
  );
}

function Figure({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="rounded-input border border-line bg-page/40 px-4 py-3">
      <div className="text-xs font-medium text-ink-3">{label}</div>
      <div className="num mt-0.5 font-display text-[26px] font-semibold leading-tight text-ink">{value}</div>
      <div className="text-xs text-ink-3">{note}</div>
    </div>
  );
}

function LiveTip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as { key: string; weekday: string; predicted: number; live: number | null; state: string; range?: [number, number] };
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-raised">
      <div className="mb-1 font-medium text-ink">
        {p.weekday} {p.key} <span className="font-normal text-ink-3">· {p.state}</span>
      </div>
      {p.live !== null && <div className="num text-ink">Received {trips(p.live)}</div>}
      <div className="num text-ink-2">Forecast {trips(p.predicted)}</div>
      {p.range && (
        <div className="num text-ink-3">
          80 % range {trips(p.range[0])} to {trips(p.range[1])}
        </div>
      )}
    </div>
  );
}
