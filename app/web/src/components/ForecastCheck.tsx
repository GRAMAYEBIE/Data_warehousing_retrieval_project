import { CircleCheck, History, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, type TooltipProps, XAxis, YAxis } from "recharts";
import type { ForecastView } from "../api/client";
import { compact, formatValue, monthLabel } from "../lib/format";
import { INK } from "./ResultChart";
import Tabs from "./Tabs";

type Table = ForecastView["tables"][string];
type Ink = (typeof INK)["light"];
type Target = "trips" | "revenue";

const rowsOf = (t?: Table) => (t ? t.rows.map((r) => Object.fromEntries(t.columns.map((c, i) => [c, r[i]]))) : []);
const pct = (v: unknown, digits = 1) => (v === null || v === undefined ? "-" : `${(Number(v) * 100).toFixed(digits)} %`);
const signed = (v: unknown) => (v === null || v === undefined ? "-" : `${Number(v) >= 0 ? "+" : "−"}${Math.abs(Number(v) * 100).toFixed(1)} %`);
const BOROUGHS = ["all", "Manhattan", "Queens", "Brooklyn", "Bronx"];

// Every forecast month, once recorded, is compared with what happened (ml/check.py): the
// error against what the backtests promised, the bias, and whether the actual days fell in
// the 80 % range. A month far above its promised error is flagged as drift.
export default function ForecastCheck({ tables, ink }: { tables: ForecastView["tables"]; ink: Ink }) {
  const checks = rowsOf(tables.checks);
  const targets = (["trips", "revenue"] as Target[]).filter((t) => checks.some((c) => c.target === t));
  const [target, setTarget] = useState<Target>("trips");
  const shownTarget = targets.includes(target) ? target : targets[0];
  const months = checks.filter((c) => c.target === shownTarget).map((c) => String(c.month));
  const [chosen, setChosen] = useState<string>();
  const month = chosen && months.includes(chosen) ? chosen : months[months.length - 1];
  const [borough, setBorough] = useState("all");

  if (!checks.length) {
    return (
      <p className="text-sm text-ink-2">
        No forecast month has been recorded yet. The first check runs on its own when the next month is published.
      </p>
    );
  }

  const scores = rowsOf(tables.check_scores).filter((s) => s.target === shownTarget);
  const score = (m: string, type: string, segment: string) => scores.find((s) => s.month === m && s.segment_type === type && s.segment === segment);
  const usd = shownTarget === "revenue";
  const fmt = (n: number) => (usd ? `$${Math.round(n).toLocaleString("en-US")}` : formatValue(Math.round(n), "trips"));
  const days = rowsOf(tables.check_daily).filter((d) => d.target === shownTarget && d.month === month && (borough === "all" || d.borough === borough));
  const byDay = new Map<string, { predicted: number; actual: number; lower: number; upper: number }>();
  for (const d of days) {
    const e = byDay.get(String(d.date_day)) ?? { predicted: 0, actual: 0, lower: 0, upper: 0 };
    e.predicted += Number(d.predicted);
    e.actual += Number(d.actual);
    e.lower += Number(d.lower);
    e.upper += Number(d.upper);
    byDay.set(String(d.date_day), e);
  }
  const points = [...byDay.entries()].map(([day, v]) => {
    const date = new Date(`${day}T00:00:00`);
    return {
      key: date.toLocaleDateString("en-GB", { day: "numeric", month: "short" }),
      weekday: date.toLocaleDateString("en-GB", { weekday: "long" }),
      predicted: v.predicted,
      actual: v.actual,
      // The range of one borough's day; city-wide, the borough ranges cannot be added up.
      range: borough === "all" ? undefined : ([v.lower, v.upper] as [number, number]),
    };
  });
  const selected = checks.find((c) => c.target === shownTarget && c.month === month);
  const daySeg = score(month, "borough_day", borough);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">
        {targets.length > 1 && (
          <Tabs label="Measure" id="check-measure" items={targets.map((t) => [t, t === "trips" ? "Trips" : "Revenue"] as [Target, string])} value={shownTarget} onChange={setTarget} />
        )}
        <Tabs label="Borough" id="check-borough" items={BOROUGHS.map((b) => [b, b === "all" ? "All boroughs" : b] as [string, string])} value={borough} onChange={setBorough} />
      </div>

      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Months checked">
        {checks
          .filter((c) => c.target === shownTarget)
          .map((c) => {
            const m = String(c.month);
            const drift = c.status === "drift";
            const s = score(m, "borough_day", "all");
            return (
              <li key={m}>
                <button
                  onClick={() => setChosen(m)}
                  aria-pressed={m === month}
                  className={`w-full rounded-input border p-4 text-left transition-colors ${m === month ? "border-primary/50 bg-primary/5" : "border-line bg-surface hover:bg-tint"}`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-ink">{monthLabel(m)}</span>
                    <span className={`chip ${drift ? "border-bad/30 bg-bad/10 text-bad-ink" : "border-good/30 bg-good/10 text-good-ink"}`}>
                      {drift ? <TriangleAlert size={12} aria-hidden="true" /> : <CircleCheck size={12} aria-hidden="true" />}
                      {drift ? "Drift" : "As expected"}
                    </span>
                    {c.replay ? (
                      <span className="chip border-line bg-tint text-ink-2" title="Forecast made again from the months before it only, as at the time">
                        <History size={12} aria-hidden="true" /> Replay
                      </span>
                    ) : (
                      <span className="chip border-line bg-tint text-ink-2">Live</span>
                    )}
                  </div>
                  <div className="num mt-2 font-display text-[26px] font-semibold leading-tight text-ink">{pct(c.actual_wmape)}</div>
                  <div className="text-xs text-ink-3">
                    error per borough and day · promised <span className="num">{pct(c.expected_wmape)}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
                    <span>
                      Bias <span className="num font-medium text-ink">{signed(s?.bias)}</span>
                    </span>
                    <span>
                      Days in range <span className="num font-medium text-ink">{pct(s?.coverage_80, 0)}</span>
                    </span>
                  </div>
                </button>
              </li>
            );
          })}
      </ul>

      <figure>
        <figcaption className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-sm font-semibold text-ink">
            {monthLabel(month)} · {borough === "all" ? "all boroughs" : borough}, day by day
          </span>
          {daySeg && (
            <span className="text-xs text-ink-3">
              error <span className="num text-ink-2">{pct(daySeg.wmape)}</span> · bias <span className="num text-ink-2">{signed(daySeg.bias)}</span>
            </span>
          )}
        </figcaption>
        <div className="h-[270px] w-full">
          <ResponsiveContainer>
            <ComposedChart key={`${shownTarget}-${month}-${borough}`} data={points} margin={{ top: 10, right: 14, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={ink.grid} vertical={false} />
              <XAxis dataKey="key" tick={{ fontSize: 11, fill: ink.axis }} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={26} />
              <YAxis tickFormatter={(v: number) => (usd ? `$${compact(v)}` : compact(v))} tick={{ fontSize: 11, fill: ink.axis }} width={56} axisLine={false} tickLine={false} />
              <Tooltip content={<CheckTip fmt={fmt} />} cursor={{ stroke: ink.axis, strokeDasharray: "3 3" }} />
              {borough !== "all" && <Area dataKey="range" stroke="none" fill={ink.series[0]} fillOpacity={0.12} animationDuration={600} />}
              <Line dataKey="predicted" stroke={ink.series[0]} strokeWidth={2} strokeDasharray="5 4" dot={false} animationDuration={700} />
              <Line dataKey="actual" stroke={ink.series[1]} strokeWidth={2} dot={{ r: 2.5, strokeWidth: 0, fill: ink.series[1] }} activeDot={{ r: 4, strokeWidth: 2, stroke: "rgb(var(--surface))" }} animationDuration={800} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
          <span className="inline-flex items-center gap-1.5">
            <span className="w-4 border-t-2 border-dashed" style={{ borderColor: ink.series[0] }} /> Forecast
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-4 rounded" style={{ background: ink.series[1] }} /> Recorded
          </span>
          {borough !== "all" && (
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-4 rounded-sm" style={{ background: ink.series[0], opacity: 0.18 }} /> 80 % range
            </span>
          )}
          {selected?.replay ? <span>Replayed: forecast again from the months before it only.</span> : null}
        </div>
      </figure>

      <p className="text-xs leading-5 text-ink-3">
        Each forecast is checked as soon as its month is published, before the next one replaces it. A month whose error per borough and day is
        more than 1.5 times what the backtests promised, and 3 points above it, is flagged as drift: a sign the method no longer holds (a trend,
        an event or a data problem). Error: share of trips missed or over-counted; bias: below zero, the forecast was too low.
      </p>
    </div>
  );
}

function CheckTip({ active, payload, fmt }: TooltipProps<number, string> & { fmt: (n: number) => string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as { key: string; weekday: string; predicted: number; actual: number; range?: [number, number] };
  const gap = p.actual ? ((p.predicted - p.actual) / p.actual) * 100 : null;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-raised">
      <div className="mb-1 font-medium text-ink">
        {p.weekday} {p.key}
      </div>
      <div className="num text-ink">Recorded {fmt(p.actual)}</div>
      <div className="num text-ink-2">
        Forecast {fmt(p.predicted)}
        {gap !== null && ` (${gap >= 0 ? "+" : "−"}${Math.abs(gap).toFixed(1)} %)`}
      </div>
      {p.range && (
        <div className="num text-ink-3">
          80 % range {fmt(p.range[0])} to {fmt(p.range[1])}
        </div>
      )}
    </div>
  );
}
