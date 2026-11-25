import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { CircleAlert, Clock, Code2, Info, MapPin, Plus, RefreshCw, X } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, type TooltipProps, XAxis, YAxis } from "recharts";
import { api, type PlannerView as Plan } from "../api/client";
import { compact, formatValue, monthLabel } from "../lib/format";
import { useIsDark } from "../lib/theme";
import { rise, spring, stagger } from "./motion";
import { BarList, INK } from "./ResultChart";

type Zone = Plan["zones"][number];
type Table = Plan["tables"][string];
type DayType = "weekday" | "weekend" | "all";

const MAX_ZONES = 5;
const rowsOf = (t?: Table) => (t ? t.rows.map((r) => Object.fromEntries(t.columns.map((c, i) => [c, r[i]]))) : []);
const hourLabel = (h: number) => `${String(h).padStart(2, "0")}:00`;
const usd = (n?: number | null, digits = 0) =>
  n === null || n === undefined ? "-" : `$${n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
const trips = (n?: number | null) => (n === null || n === undefined ? "-" : formatValue(Math.round(n), "trips"));
const one = (n?: number | null) => (n === null || n === undefined ? "-" : n.toFixed(1));
const DAY_TYPES: [DayType, string][] = [
  ["weekday", "Weekdays"],
  ["weekend", "Weekends & holidays"],
  ["all", "All days"],
];
const DAY_TEXT: Record<DayType, string> = { weekday: "weekday", weekend: "weekend or holiday", all: "day" };
const TIER_TEXT: Record<string, string> = { high: "High demand", medium: "Medium demand", low: "Low demand", sparse: "Sparse" };

// What a few pickup zones offer over a shift window next month: the published forecast for
// the window, and what was recorded there over the last eight weeks. Zone opportunity only:
// the data has no taxi or driver identifier, so one driver's share is unknown.
export default function PlannerView() {
  const ink = useIsDark() ? INK.dark : INK.light;
  const options = useQuery({ queryKey: ["planner-zones"], queryFn: api.plannerZones, staleTime: 10 * 60_000 });
  const [zones, setZones] = useState<string[]>([]);
  const [dayType, setDayType] = useState<DayType>("weekday");
  const [start, setStart] = useState(7);
  const [hours, setHours] = useState(8);

  // Start with the three busiest zones of the forecast.
  useEffect(() => {
    if (!zones.length && options.data?.rows.length) setZones(options.data.rows.slice(0, 3).map((r) => String(r[0])));
  }, [options.data, zones.length]);

  const plan = useQuery({
    queryKey: ["planner", zones, dayType, start, hours],
    queryFn: () => api.plan({ zones, day_type: dayType, start_hour: start, hours }),
    enabled: zones.length > 0,
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
  const data = plan.data;
  const failed = options.isError || plan.isError || (data && !data.available);

  if (failed) {
    return (
      <Shell>
        <div className="card flex items-start gap-3 p-5">
          <CircleAlert size={20} className="mt-0.5 shrink-0 text-bad-ink" aria-hidden="true" />
          <div className="flex-1">
            <h2 className="text-base font-semibold">The planner is not available</h2>
            <p className="mt-1 text-sm text-ink-2">{data?.message ?? String(plan.error ?? options.error)}</p>
          </div>
          <button className="btn-outline" onClick={() => (options.isError ? options.refetch() : plan.refetch())}>
            <RefreshCw size={15} aria-hidden="true" /> Retry
          </button>
        </div>
      </Shell>
    );
  }

  const month = data?.forecast_month ? monthLabel(data.forecast_month) : "next month";
  const shift = `${hourLabel(start)} to ${hourLabel((start + hours) % 24)}`;
  const known = (options.data?.rows ?? []).map((r) => ({ name: String(r[0]), borough: String(r[1]) }));
  const add = (name: string) => setZones((z) => (z.includes(name) || z.length >= MAX_ZONES ? z : [...z, name]));
  const remove = (name: string) => setZones((z) => z.filter((n) => n !== name));

  return (
    <Shell>
      <header>
        <div className="label flex flex-wrap items-center gap-2">
          Shift planner
          <span className="chip border-accent/40 bg-accent/15 normal-case tracking-normal text-ink">Estimate · zone opportunity</span>
        </div>
        <h1 className="mt-1 text-[30px] font-semibold leading-tight sm:text-[34px]">Where and when to work, {month}</h1>
        <p className="mt-1.5 max-w-3xl text-sm text-ink-2">
          Pick up to {MAX_ZONES} pickup zones and a shift. You get the trips and revenue the forecast expects there on a typical{" "}
          {DAY_TEXT[dayType]}, and what was actually recorded over the last eight weeks. These figures describe the zone, shared by every
          taxi working it, not what one taxi will earn.
        </p>
      </header>

      <Controls
        known={known}
        zones={zones}
        onAdd={add}
        onRemove={remove}
        dayType={dayType}
        onDayType={setDayType}
        start={start}
        onStart={setStart}
        hours={hours}
        onHours={setHours}
      />

      {!data ? (
        <Loading />
      ) : (
        <div className={`space-y-5 transition-opacity ${plan.isFetching ? "opacity-60" : ""}`} aria-busy={plan.isFetching}>
          {data.unknown_zones.length > 0 && (
            <p className="flex items-center gap-2 text-sm text-ink-2">
              <Info size={15} aria-hidden="true" /> No forecast for: {data.unknown_zones.join(", ")}.
            </p>
          )}
          <motion.section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" variants={stagger} initial="hidden" animate="show" aria-label="Zones">
            {data.zones.map((zone) => (
              <ZoneCard key={zone.zone_name} zone={zone} shift={shift} days={data.recent_days} />
            ))}
          </motion.section>

          <Panel
            title="Hour by hour"
            subtitle={`Expected trips per hour on a typical ${DAY_TEXT[dayType]} of ${month}, with the 80 % range`}
            sql={data.tables.profile?.sql}
          >
            <Profile table={data.tables.profile} zones={data.zones.map((z) => z.zone_name)} start={data.hours[0] ?? start} ink={ink} />
          </Panel>

          <div className="grid gap-4 lg:grid-cols-5">
            <Panel className="lg:col-span-3" title="Side by side" subtitle={`${shift}, typical ${DAY_TEXT[dayType]} · recent: ${data.recent_from} to ${data.recent_to}`} sql={data.tables.history?.sql}>
              <Compare zones={data.zones} />
            </Panel>
            <Panel
              className="lg:col-span-2"
              title="Other zones to consider"
              subtitle={`Busiest in the same boroughs over ${shift}, expected trips`}
              sql={data.tables.alternatives?.sql}
            >
              <Alternatives table={data.tables.alternatives} ink={ink} full={zones.length >= MAX_ZONES} onAdd={add} />
            </Panel>
          </div>

          <Panel title="How to read this" subtitle="What the planner can and cannot tell">
            <Reading champion={data.champion} />
          </Panel>
        </div>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return <div className="mx-auto w-full max-w-[1180px] space-y-5 px-4 py-7 sm:px-6 lg:py-9">{children}</div>;
}

function Panel({ title, subtitle, className = "", sql, children }: { title: string; subtitle: string; className?: string; sql?: string; children: ReactNode }) {
  return (
    <section className={`card flex flex-col p-5 ${className}`} aria-label={title}>
      <header className="mb-4">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-xs text-ink-3">{subtitle}</p>
      </header>
      <div className="flex flex-1 flex-col">{children}</div>
      {sql && (
        <details className="mt-3 border-t border-line pt-3">
          <summary className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-ink-2 hover:text-ink">
            <Code2 size={13} aria-hidden="true" /> Approved query
          </summary>
          <pre className="mt-2 max-h-56 overflow-auto rounded-lg bg-tint p-3 font-mono text-[11px] leading-5 text-ink-2">{sql}</pre>
        </details>
      )}
    </section>
  );
}

type ControlsProps = {
  known: { name: string; borough: string }[];
  zones: string[];
  onAdd: (name: string) => void;
  onRemove: (name: string) => void;
  dayType: DayType;
  onDayType: (d: DayType) => void;
  start: number;
  onStart: (h: number) => void;
  hours: number;
  onHours: (h: number) => void;
};

// All the filters in one row above the results (wrapping on small screens).
function Controls({ known, zones, onAdd, onRemove, dayType, onDayType, start, onStart, hours, onHours }: ControlsProps) {
  const [text, setText] = useState("");
  const names = useMemo(() => new Set(known.map((k) => k.name)), [known]);
  const pick = (value: string) => {
    if (names.has(value)) {
      onAdd(value);
      setText("");
    } else setText(value);
  };
  const full = zones.length >= MAX_ZONES;
  return (
    <section className="card space-y-4 p-5" aria-label="Shift">
      <div className="flex flex-wrap items-end gap-4">
        <label className="min-w-[220px] flex-1">
          <span className="mb-1 flex items-center gap-1.5 text-xs font-medium text-ink-2">
            <MapPin size={13} aria-hidden="true" /> Add a pickup zone {full && <span className="text-ink-3">(at most {MAX_ZONES})</span>}
          </span>
          <input
            className="input w-full"
            list="planner-zone-list"
            placeholder={full ? "Remove a zone to add another" : "Type a zone, e.g. JFK Airport"}
            value={text}
            disabled={full}
            onChange={(e) => pick(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                const match = known.find((k) => k.name.toLowerCase().startsWith(text.toLowerCase()));
                if (match && text) pick(match.name);
              }
            }}
          />
          <datalist id="planner-zone-list">
            {known
              .filter((k) => !zones.includes(k.name))
              .map((k) => (
                <option key={k.name} value={k.name}>
                  {k.borough}
                </option>
              ))}
          </datalist>
        </label>
        <div>
          <span className="mb-1 block text-xs font-medium text-ink-2">Days</span>
          <Tabs label="Days" id="planner-days" items={DAY_TYPES} value={dayType} onChange={onDayType} />
        </div>
        <label>
          <span className="mb-1 flex items-center gap-1.5 text-xs font-medium text-ink-2">
            <Clock size={13} aria-hidden="true" /> Starts at
          </span>
          <select className="input" value={start} onChange={(e) => onStart(Number(e.target.value))}>
            {Array.from({ length: 24 }, (_, h) => (
              <option key={h} value={h}>
                {hourLabel(h)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="mb-1 block text-xs font-medium text-ink-2">Length</span>
          <select className="input" value={hours} onChange={(e) => onHours(Number(e.target.value))}>
            {Array.from({ length: 12 }, (_, i) => i + 1).map((h) => (
              <option key={h} value={h}>
                {h} {h === 1 ? "hour" : "hours"}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ul className="flex flex-wrap gap-2" aria-label="Chosen zones">
        {zones.map((name) => (
          <li key={name} className="chip gap-1 border-line bg-tint py-1 pl-2.5 pr-1 text-sm text-ink">
            {name}
            <button className="grid h-5 w-5 place-items-center rounded-full text-ink-3 hover:bg-surface hover:text-ink" onClick={() => onRemove(name)} aria-label={`Remove ${name}`}>
              <X size={13} aria-hidden="true" />
            </button>
          </li>
        ))}
        {!zones.length && <li className="text-sm text-ink-3">No zone chosen yet.</li>}
      </ul>
    </section>
  );
}

function Tabs<T extends string>({ label, id, items, value, onChange }: { label: string; id: string; items: [T, string][]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex flex-wrap rounded-input bg-tint p-1" role="tablist" aria-label={label}>
      {items.map(([key, text]) => (
        <button
          key={key}
          role="tab"
          aria-selected={value === key}
          onClick={() => onChange(key)}
          className={`relative rounded-[8px] px-3 py-1.5 text-xs font-medium transition-colors ${value === key ? "text-ink" : "text-ink-2 hover:text-ink"}`}
        >
          {value === key && <motion.span layoutId={id} className="absolute inset-0 rounded-[8px] bg-surface shadow-soft" transition={spring} />}
          <span className="relative">{text}</span>
        </button>
      ))}
    </div>
  );
}

function ZoneCard({ zone, shift, days }: { zone: Zone; shift: string; days: number }) {
  const recent = zone.recent_median !== null && zone.recent_median !== undefined;
  return (
    <motion.article variants={rise} className="card lift flex flex-col p-5" aria-label={zone.zone_name}>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-base font-semibold" title={zone.zone_name}>
            {zone.zone_name}
          </h2>
          <p className="text-xs text-ink-3">
            {zone.borough} · {TIER_TEXT[zone.demand_tier] ?? zone.demand_tier}
          </p>
        </div>
        {zone.low_confidence && <span className="chip shrink-0 border-accent/40 bg-accent/15 text-ink">low confidence</span>}
      </div>
      <div className="mt-3 flex items-baseline gap-2">
        <span className="num font-display text-[32px] font-semibold leading-none tracking-tight">{trips(zone.expected_trips)}</span>
        <span className="text-sm text-ink-2">trips expected, {shift}</span>
      </div>
      <p className="mt-1 text-sm text-ink-2">
        <span className="num font-medium text-ink">{usd(zone.expected_revenue)}</span> paid in total over the window
      </p>
      <p className="mt-2 text-xs leading-5 text-ink-3">
        {recent ? (
          <>
            Last 8 weeks: <span className="num text-ink-2">{trips(zone.recent_median)}</span> on a typical day, from{" "}
            <span className="num">{trips(zone.recent_p10)}</span> to <span className="num">{trips(zone.recent_p90)}</span> on 8 days in 10 ({days} days).
          </>
        ) : (
          "No recorded trip in this window over the last 8 weeks."
        )}
      </p>
      <dl className="mt-4 grid grid-cols-3 gap-3 border-t border-line pt-3 text-xs">
        <Stat label="Fare / trip" value={usd(zone.fare_per_trip, 2)} />
        <Stat label="Minutes / trip" value={one(zone.minutes_per_trip)} />
        <Stat label="Miles / trip" value={one(zone.miles_per_trip)} />
      </dl>
    </motion.article>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-ink-3">{label}</dt>
      <dd className="num mt-0.5 text-sm font-medium text-ink">{value}</dd>
    </div>
  );
}

type Ink = (typeof INK)["light"];

// One zone at a time (one series, its 80 % range): the tabs pick it.
function Profile({ table, zones, start, ink }: { table?: Table; zones: string[]; start: number; ink: Ink }) {
  const [chosen, setChosen] = useState<string>();
  const zone = chosen && zones.includes(chosen) ? chosen : zones[0];
  const rows = rowsOf(table).filter((r) => r.zone_name === zone);
  // Keep the shift's order when it runs past midnight (22, 23, 0, 1).
  const points = rows
    .map((r) => ({
      hour: Number(r.pickup_hour),
      label: hourLabel(Number(r.pickup_hour)),
      trips: Number(r.trips),
      range: [Number(r.lower), Number(r.upper)] as [number, number],
      revenue: r.revenue === null ? null : Number(r.revenue),
    }))
    .sort((a, b) => ((a.hour - start + 24) % 24) - ((b.hour - start + 24) % 24));
  if (!zone) return <p className="text-sm text-ink-3">Choose a zone above.</p>;
  return (
    <div className="flex flex-col">
      {zones.length > 1 && (
        <div className="mb-3">
          <Tabs label="Zone" id="planner-profile-zone" items={zones.map((z) => [z, z] as [string, string])} value={zone} onChange={setChosen} />
        </div>
      )}
      <div className="h-[260px] w-full">
        <ResponsiveContainer>
          <ComposedChart key={zone} data={points} margin={{ top: 10, right: 14, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={ink.grid} vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 12, fill: ink.axis }} axisLine={false} tickLine={false} />
            <YAxis tickFormatter={(v: number) => compact(v)} tick={{ fontSize: 12, fill: ink.axis }} width={48} axisLine={false} tickLine={false} />
            <Tooltip content={<HourTip />} cursor={{ stroke: ink.axis, strokeDasharray: "3 3" }} />
            <Area dataKey="range" stroke="none" fill={ink.series[0]} fillOpacity={0.14} animationDuration={600} />
            <Line dataKey="trips" stroke={ink.series[0]} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "rgb(var(--surface))", fill: ink.series[0] }} activeDot={{ r: 5 }} animationDuration={700} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function HourTip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as { label: string; trips: number; range: [number, number]; revenue: number | null };
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-raised">
      <div className="mb-1 font-medium text-ink">{p.label}</div>
      <div className="num text-ink">{one(p.trips)} trips expected</div>
      <div className="num text-ink-3">
        80 % range {one(p.range[0])} to {one(p.range[1])}
      </div>
      {p.revenue !== null && <div className="num text-ink-3">{usd(p.revenue)} paid</div>}
    </div>
  );
}

function Compare({ zones }: { zones: Zone[] }) {
  const cell = "num whitespace-nowrap py-2 pl-3 text-right";
  const head = "pb-1.5 pl-3 text-right font-medium";
  return (
    <div className="-mx-1 overflow-x-auto px-1">
      <table className="w-full min-w-[520px] text-sm">
        <thead>
          <tr className="text-left text-xs text-ink-3">
            <th className="pb-1.5 font-medium">Zone</th>
            <th className={head}>Trips expected</th>
            <th className={head}>Paid, total</th>
            <th className={head} title="Expected trips x minutes per trip: paid ride time the zone generates, shared by all taxis">
              Ride hours
            </th>
            <th className={head} title="Fare per hour with a passenger on board; waiting and driving empty not included">
              $ per ride hour
            </th>
          </tr>
        </thead>
        <tbody>
          {zones.map((z) => (
            <tr key={z.zone_name} className="border-t border-line">
              <td className="max-w-[200px] truncate py-2 text-ink-2" title={z.zone_name}>
                {z.zone_name}
              </td>
              <td className={`${cell} font-medium text-ink`}>{trips(z.expected_trips)}</td>
              <td className={cell}>{usd(z.expected_revenue)}</td>
              <td className={cell}>{one(z.ride_hours)}</td>
              <td className={cell}>{usd(z.fare_per_ride_hour)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs leading-5 text-ink-3">
        Ride hours: the paid ride time the zone generates in the window, shared by every taxi there. $ per ride hour counts only the time
        with a passenger; waiting and driving empty are not in the data.
      </p>
    </div>
  );
}

function Alternatives({ table, ink, full, onAdd }: { table?: Table; ink: Ink; full: boolean; onAdd: (name: string) => void }) {
  const rows = rowsOf(table);
  if (!rows.length) return <p className="text-sm text-ink-3">No other zone in these boroughs.</p>;
  return (
    <div className="space-y-3">
      <BarList unit="trips" colors={ink} rows={rows.map((r) => ({ key: String(r.zone_name), value: Math.round(Number(r.trips)) }))} />
      <div className="flex flex-wrap gap-2">
        {rows.map((r) => (
          <button key={String(r.zone_name)} className="btn-outline h-8 px-2.5 text-xs" disabled={full} onClick={() => onAdd(String(r.zone_name))}>
            <Plus size={13} aria-hidden="true" /> {String(r.zone_name)}
          </button>
        ))}
      </div>
    </div>
  );
}

function Reading({ champion }: { champion?: string | null }) {
  const items: [string, string][] = [
    [
      "A zone, not a taxi",
      "The trip records carry no taxi or driver identifier, so the planner shows what a zone offers to all the taxis working it. How much of it one driver gets depends on how many others are there.",
    ],
    [
      "Expected, then recorded",
      `The expected figures come from the published forecast (${champion === "model" ? "the LightGBM model" : "the seasonal baseline"}, the method in service). The range below each zone is what was actually recorded over the last eight weeks, empty days included.`,
    ],
    [
      "Only paid ride time",
      "Fares, durations and distances are averages of recorded valid trips in the same zones and hours. Waiting time and empty driving are not recorded, so earnings per hour worked would be lower than per ride hour.",
    ],
    ["Night shifts", "A shift past midnight is read on one calendar date: 22:00 to 02:00 adds the late evening and the early hours of the same day."],
  ];
  return (
    <ol className="grid gap-4 md:grid-cols-2">
      {items.map(([title, text], i) => (
        <li key={title} className="flex gap-3">
          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary/10 text-xs font-semibold text-primary-strong">{i + 1}</span>
          <div>
            <div className="text-sm font-medium text-ink">{title}</div>
            <p className="text-xs leading-5 text-ink-2">{text}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

function Loading() {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      {[0, 1, 2].map((i) => (
        <div key={i} className="card space-y-3 p-5">
          <div className="skeleton h-4 w-36" />
          <div className="skeleton h-9 w-28" />
          <div className="skeleton h-4 w-48" />
          <div className="skeleton h-10 w-full" />
        </div>
      ))}
    </div>
  );
}
