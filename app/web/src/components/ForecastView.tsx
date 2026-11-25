import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowUpRight, CircleAlert, CircleDollarSign, FlaskConical, Gauge, RefreshCw, Target, TrendingUp, Trophy } from "lucide-react";
import { type ReactNode, useState } from "react";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  type TooltipProps,
  XAxis,
  YAxis,
} from "recharts";
import { api, type ForecastView as Forecast } from "../api/client";
import { useConfig } from "../lib/config";
import { compact, formatValue, monthLabel } from "../lib/format";
import { useIsDark } from "../lib/theme";
import { CountUp, rise, spring, stagger } from "./motion";
import { BarList, INK, Tip } from "./ResultChart";

type Table = Forecast["tables"][string];

const rowsOf = (t?: Table) => (t ? t.rows.map((r) => Object.fromEntries(t.columns.map((c, i) => [c, r[i]]))) : []);
const pct = (v?: number | null, digits = 1) => (v === null || v === undefined ? "-" : `${(v * 100).toFixed(digits)} %`);
const millions = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : formatValue(Math.round(n), "trips"));
const BOROUGHS = ["Manhattan", "Queens", "Brooklyn", "Bronx"];
const TIER_TEXT: Record<string, string> = {
  high: "High demand (20+ trips an hour)",
  medium: "Medium (2 to 20 an hour)",
  low: "Low (0.2 to 2 an hour)",
  sparse: "Sparse (under 0.2 an hour)",
};

// The published forecast of recorded trips and how well its model did on the last month.
// An estimate, shown apart from the governed measures and labelled as such everywhere.
export default function ForecastView() {
  const config = useConfig();
  const ink = useIsDark() ? INK.dark : INK.light;
  const query = useQuery({ queryKey: ["forecast"], queryFn: api.forecast, staleTime: 5 * 60_000 });
  const data = query.data;

  if (query.isError || (data && !data.available)) {
    return (
      <Shell>
        <div className="card flex items-start gap-3 p-5">
          <CircleAlert size={20} className="mt-0.5 shrink-0 text-bad-ink" aria-hidden="true" />
          <div className="flex-1">
            <h2 className="text-base font-semibold">No forecast to show</h2>
            <p className="mt-1 text-sm text-ink-2">{data?.message ?? String(query.error)}</p>
          </div>
          <button className="btn-outline" onClick={() => query.refetch()}>
            <RefreshCw size={15} aria-hidden="true" /> Retry
          </button>
        </div>
      </Shell>
    );
  }
  if (!data?.run) return <Loading />;

  const run = data.run;
  const month = monthLabel(run.forecast_month);
  const validated = monthLabel(run.validated_month);
  const score = (kind: string, name: string) => data.evaluation.find((e) => e.segment_type === kind && e.segment === name);
  const daily = rowsOf(data.tables.daily);
  const total = daily.reduce((s, r) => s + Number(r.predicted), 0);
  const days = new Set(daily.map((r) => r.date_day)).size || 1;
  const actual = rowsOf(data.tables.last_actual);
  const actualTotal = actual.reduce((s, r) => s + Number(r.trips), 0);
  const actualDays = Number(actual[0]?.days ?? 1);
  const perDayChange = actualTotal ? (total / days / (actualTotal / actualDays) - 1) * 100 : null;
  const cityDay = score("borough_day", "all");
  const overall = score("overall", "all");
  const backtests = rowsOf(data.tables.backtests) as Backtest[];
  const champion = run.champion === "model" ? "model" : "baseline";
  const championDays = backtests.filter((b) => b.method === champion && b.segment_type === "borough_day" && b.segment === "all");
  const meanDay = championDays.length ? championDays.reduce((s, b) => s + Number(b.wmape), 0) / championDays.length : null;
  const zones = rowsOf(data.tables.zones);
  const revenueDaily = rowsOf(data.tables.revenue_daily);
  const revenueActual = rowsOf(data.tables.revenue_last_actual);
  const revenueTotal = revenueDaily.reduce((s, r) => s + Number(r.predicted), 0);
  const revenuePast = revenueActual.reduce((s, r) => s + Number(r.revenue), 0);
  const revenueChange = revenuePast ? (revenueTotal / days / (revenuePast / actualDays) - 1) * 100 : null;

  return (
    <Shell>
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <div className="label flex flex-wrap items-center gap-2">
            Forecast
            <span className="chip border-accent/40 bg-accent/15 normal-case tracking-normal text-ink">Estimate · not a measured figure</span>
          </div>
          <h1 className="mt-1 text-[30px] font-semibold leading-tight sm:text-[34px]">{month} demand forecast</h1>
          <p className="mt-1.5 max-w-3xl text-sm text-ink-2">
            Recorded trips expected for every pickup zone and hour. Trained on {monthLabel(run.history_months[0])} to{" "}
            {monthLabel(run.history_months[run.history_months.length - 1])} (publication{" "}
            <span className="font-mono text-xs">{run.data_run}</span>), checked on {validated} against a simple baseline.
          </p>
        </div>
        <a className="btn-outline self-start sm:self-auto" href={`${config.mlflowUrl}/#/models/demand_forecast`} target="_blank" rel="noreferrer">
          <FlaskConical size={16} aria-hidden="true" /> Open in MLflow <ArrowUpRight size={14} aria-hidden="true" />
        </a>
      </header>

      <Decision champion={champion} decision={run.decision} />


      <motion.section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" variants={stagger} initial="hidden" animate="show" aria-label="Key figures">
        <Tile icon={<TrendingUp size={16} />} label={`Expected trips, ${month}`}>
          <CountUp value={total} format={millions} />
          <Note>
            {perDayChange !== null && (
              <>
                <span className="num">{perDayChange >= 0 ? "+" : ""}{perDayChange.toFixed(1)} %</span> a day vs {validated}
              </>
            )}
          </Note>
        </Tile>
        <Tile icon={<Target size={16} />} label={`Error per borough and day, ${validated}`}>
          <CountUp value={(cityDay?.wmape ?? 0) * 100} format={(n) => `${n.toFixed(1)} %`} />
          <Note>
            {meanDay !== null && (
              <>
                <span className="num">{pct(meanDay)}</span> on average over the {championDays.length} test months
              </>
            )}
          </Note>
        </Tile>
        <Tile icon={<Gauge size={16} />} label="80 % range held the actual">
          <CountUp value={(overall?.coverage_80 ?? 0) * 100} format={(n) => `${n.toFixed(1)} %`} />
          <Note>of the zone-hours of {validated} (aim: 80 %)</Note>
        </Tile>
        <Tile icon={<CircleDollarSign size={16} />} label={`Expected revenue, ${month}`}>
          {revenueDaily.length ? <CountUp value={revenueTotal} format={(n) => `$${(n / 1_000_000).toFixed(1)}M`} /> : "-"}
          <Note>
            {revenueChange !== null && (
              <>
                <span className="num">{revenueChange >= 0 ? "+" : ""}{revenueChange.toFixed(1)} %</span> a day vs {validated} · total paid
              </>
            )}
          </Note>
        </Tile>
      </motion.section>

      <Panel title="Day by day" subtitle={`${month}, with the 80 % range · dashed: the daily average of ${validated}`}>
        <Daily
          series={{
            trips: { rows: daily, actual: actual.map((a) => ({ borough: a.borough, total: a.trips, days: a.days })) },
            ...(revenueDaily.length
              ? { revenue: { rows: revenueDaily, actual: revenueActual.map((a) => ({ borough: a.borough, total: a.revenue, days: a.days })) } }
              : {}),
          }}
          ink={ink}
        />
      </Panel>

      <div className="grid gap-4 lg:grid-cols-5">
        <Panel
          className="lg:col-span-3"
          title="Baseline against the model, month by month"
          subtitle="Each month forecast from the weeks before it. Error = share of trips missed or over-counted (WMAPE); lower is better."
        >
          <Accuracy backtests={backtests} champion={champion} days={actualDays} />
        </Panel>
        <Panel className="lg:col-span-2" title="Busiest pickup zones" subtitle={`Expected trips, ${month}`}>
          <BarList unit="trips" colors={ink} rows={zones.map((z) => ({ key: String(z.zone_name), value: Math.round(Number(z.predicted)) }))} />
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <Panel className="lg:col-span-3" title="An average day, hour by hour" subtitle={`Expected trips per hour, city-wide, ${month}`}>
          <Hourly table={data.tables.hourly} ink={ink} />
        </Panel>
        <Panel className="lg:col-span-2" title="How this forecast is made" subtitle="Rules applied to every run">
          <Method validated={validated} runId={run.run_id} rounds={run.rounds} />
        </Panel>
      </div>
    </Shell>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return <div className="mx-auto w-full max-w-[1180px] space-y-5 px-4 py-7 sm:px-6 lg:py-9">{children}</div>;
}

function Tile({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <motion.div variants={rise} className="card lift p-5">
      <div className="flex items-center gap-2 text-sm font-medium text-ink-2">
        <span className="text-primary-strong" aria-hidden="true">
          {icon}
        </span>
        {label}
      </div>
      <div className="num mt-1.5 font-display text-[34px] font-semibold leading-tight tracking-tight text-ink">{children}</div>
    </motion.div>
  );
}

function Note({ children }: { children: ReactNode }) {
  return <div className="mt-1.5 font-sans text-xs font-normal tracking-normal text-ink-3">{children}</div>;
}

function Panel({ title, subtitle, className = "", children }: { title: string; subtitle: string; className?: string; children: ReactNode }) {
  return (
    <motion.section
      className={`card flex flex-col p-5 ${className}`}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
      aria-label={title}
    >
      <header className="mb-4">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-xs text-ink-3">{subtitle}</p>
      </header>
      <div className="flex flex-1 flex-col">{children}</div>
    </motion.section>
  );
}

type Ink = (typeof INK)["light"];

type Series = { rows: Record<string, unknown>[]; actual: { borough: unknown; total: unknown; days: unknown }[] };

// One measure at a time (one axis): trips or revenue, per borough.
function Daily({ series, ink }: { series: { trips: Series; revenue?: Series }; ink: Ink }) {
  const [borough, setBorough] = useState("Manhattan");
  const [measure, setMeasure] = useState<"trips" | "revenue">("trips");
  const shown = (measure === "revenue" && series.revenue) || series.trips;
  const usd = measure === "revenue" && Boolean(series.revenue);
  const points = shown.rows
    .filter((r) => r.borough === borough)
    .map((r) => {
      const day = new Date(`${r.date_day}T00:00:00`);
      return {
        day: day.toLocaleDateString("en-GB", { day: "numeric", month: "short" }),
        weekday: day.toLocaleDateString("en-GB", { weekday: "short" }),
        predicted: Number(r.predicted),
        range: [Number(r.lower), Number(r.upper)] as [number, number],
      };
    });
  const past = shown.actual.find((a) => a.borough === borough);
  const pastAverage = past ? Number(past.total) / Number(past.days) : undefined;
  const measures: [typeof measure, string][] = series.revenue ? [["trips", "Trips"], ["revenue", "Revenue"]] : [["trips", "Trips"]];
  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 flex flex-wrap gap-2">
        <Tabs label="Measure" id="forecast-measure" items={measures} value={measure} onChange={setMeasure} />
        <Tabs label="Borough" id="forecast-borough" items={BOROUGHS.map((b) => [b, b] as [string, string])} value={borough} onChange={setBorough} />
      </div>
      <div className="h-[280px] w-full">
        <ResponsiveContainer>
          <ComposedChart key={`${measure}-${borough}`} data={points} margin={{ top: 10, right: 14, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={ink.grid} vertical={false} />
            <XAxis dataKey="day" tick={{ fontSize: 12, fill: ink.axis }} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={24} />
            <YAxis tickFormatter={(v: number) => (usd ? `$${compact(v)}` : compact(v))} tick={{ fontSize: 12, fill: ink.axis }} width={56} axisLine={false} tickLine={false} />
            <Tooltip content={<DayTip usd={usd} />} cursor={{ stroke: ink.axis, strokeDasharray: "3 3" }} />
            <Area dataKey="range" stroke="none" fill={ink.series[0]} fillOpacity={0.14} isAnimationActive animationDuration={700} />
            {pastAverage !== undefined && (
              <ReferenceLine y={pastAverage} stroke={ink.axis} strokeDasharray="4 4" ifOverflow="extendDomain" />
            )}
            <Line dataKey="predicted" stroke={ink.series[0]} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "rgb(var(--surface))" }} animationDuration={800} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Tabs<T extends string>({
  label,
  id,
  items,
  value,
  onChange,
}: {
  label: string;
  id: string;
  items: [T, string][];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded-input bg-tint p-1" role="tablist" aria-label={label}>
      {items.map(([key, text]) => (
        <button
          key={key}
          role="tab"
          aria-selected={value === key}
          onClick={() => onChange(key)}
          className={`relative rounded-[8px] px-3 py-1 text-xs font-medium transition-colors ${value === key ? "text-ink" : "text-ink-2 hover:text-ink"}`}
        >
          {value === key && <motion.span layoutId={id} className="absolute inset-0 rounded-[8px] bg-surface shadow-soft" transition={spring} />}
          <span className="relative">{text}</span>
        </button>
      ))}
    </div>
  );
}

function DayTip({ active, payload, usd }: TooltipProps<number, string> & { usd: boolean }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as { day: string; weekday: string; predicted: number; range: [number, number] };
  const fmt = (n: number) => (usd ? `$${Math.round(n).toLocaleString("en-US")}` : formatValue(Math.round(n), "trips"));
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-raised">
      <div className="mb-1 font-medium text-ink">
        {p.weekday} {p.day}
      </div>
      <div className="num text-ink">
        {fmt(p.predicted)} {usd ? "expected" : "trips expected"}
      </div>
      <div className="num text-ink-3">
        80 % range {fmt(p.range[0])} to {fmt(p.range[1])}
      </div>
    </div>
  );
}

type Backtest = { month: string; method: string; segment_type: string; segment: string; rows: number; wmape: number; bias: number };

const METHOD_NAME: Record<string, string> = { baseline: "Baseline", model: "Model" };

// The champion is the method in service; the bars and the table say which one won where.
function Accuracy({ backtests, champion, days }: { backtests: Backtest[]; champion: string; days: number }) {
  const get = (month: string, method: string, type: string, segment: string) =>
    backtests.find((b) => b.month === month && b.method === method && b.segment_type === type && b.segment === segment);
  const months = [...new Set(backtests.map((b) => b.month))].sort();
  const last = months[months.length - 1] ?? "";
  const challenger = champion === "model" ? "baseline" : "model";
  const boroughs = [...new Set(backtests.filter((b) => b.segment_type === "borough_day" && b.segment !== "all").map((b) => b.segment))]
    .map((name) => ({ name, champ: get(last, champion, "borough_day", name), chall: get(last, challenger, "borough_day", name) }))
    .sort((a, b) => Number(a.champ?.wmape ?? 9) - Number(b.champ?.wmape ?? 9));
  const max = Math.max(0.01, ...boroughs.flatMap((b) => [Number(b.champ?.wmape ?? 0), Number(b.chall?.wmape ?? 0)]));
  const cell = "num whitespace-nowrap py-1.5 pl-3 text-right";
  return (
    <div className="space-y-6">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-ink-3">
            <th className="pb-1.5 font-medium">Month tested</th>
            <th className="pb-1.5 pl-3 text-right font-medium">Baseline</th>
            <th className="pb-1.5 pl-3 text-right font-medium">Model</th>
            <th className="pb-1.5 pl-3 text-right font-medium">Winner</th>
          </tr>
        </thead>
        <tbody>
          {months.map((m) => {
            const base = Number(get(m, "baseline", "overall", "all")?.wmape);
            const model = Number(get(m, "model", "overall", "all")?.wmape);
            const winner = model < base ? "model" : "baseline";
            return (
              <tr key={m} className="border-t border-line">
                <td className="py-1.5 text-ink-2">{monthLabel(m)}</td>
                <td className={`${cell} ${winner === "baseline" ? "font-semibold text-ink" : "text-ink-3"}`}>{pct(base)}</td>
                <td className={`${cell} ${winner === "model" ? "font-semibold text-ink" : "text-ink-3"}`}>{pct(model)}</td>
                <td className="py-1.5 pl-3 text-right">
                  <span className={`chip ${winner === champion ? "border-primary/30 bg-primary/10 text-primary-strong" : "border-line bg-tint text-ink-2"}`}>
                    {METHOD_NAME[winner]}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="-mt-3 text-xs leading-5 text-ink-3">Error per zone and hour. The model is promoted when it wins most months, on average, and on the busy zones.</p>

      <div>
        <h3 className="mb-2 text-sm font-semibold">Per borough and day, {monthLabel(last)}</h3>
        <div className="mb-2 flex flex-wrap items-center gap-4 text-xs text-ink-3">
          <Legend className="bg-primary" text={`${METHOD_NAME[champion]} (in service)`} />
          <Legend className="bg-line-strong" text={`${METHOD_NAME[challenger]}`} />
        </div>
        <ul className="space-y-2.5">
          {boroughs.map(({ name, champ, chall }) => (
            <li key={name}>
              <div className="flex items-baseline gap-3 text-sm">
                <span className="min-w-0 flex-1 truncate text-ink-2">{name}</span>
                <span className="num w-16 text-right font-medium text-ink">{pct(champ?.wmape)}</span>
                <span className="num w-16 text-right text-ink-3">{pct(chall?.wmape)}</span>
              </div>
              <div className="mt-1 space-y-1">
                <Track width={(100 * Number(champ?.wmape ?? 0)) / max} className="bg-primary" />
                <Track width={(100 * Number(chall?.wmape ?? 0)) / max} className="bg-line-strong" thin />
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h3 className="mb-2 text-sm font-semibold">By demand level of the zone, per zone and hour, {monthLabel(last)}</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-ink-3">
              <th className="pb-1.5 font-medium">Zones</th>
              <th className="pb-1.5 pl-3 text-right font-medium">Baseline</th>
              <th className="pb-1.5 pl-3 text-right font-medium">Model</th>
            </tr>
          </thead>
          <tbody>
            {["high", "medium", "low", "sparse"].map((tier) => {
              const base = get(last, "baseline", "tier", tier);
              const model = get(last, "model", "tier", tier);
              if (!base) return null;
              return (
                <tr key={tier} className="border-t border-line">
                  <td className="py-1.5 text-ink-2">
                    {TIER_TEXT[tier]}
                    <span className="num text-ink-3"> · {Math.round(Number(base.rows) / (days * 24))} zones</span>
                    {tier === "sparse" && <span className="chip ml-2 border-accent/40 bg-accent/15 text-ink">low confidence</span>}
                  </td>
                  <td className={`${cell} ${champion === "baseline" ? "font-medium" : "text-ink-3"}`}>{pct(base.wmape, 0)}</td>
                  <td className={`${cell} ${champion === "model" ? "font-medium" : "text-ink-3"}`}>{pct(model?.wmape, 0)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="mt-2 text-xs leading-5 text-ink-3">
          Quiet zones have many hours with no trip, so their error per hour is large for any method; they are scored apart and their
          forecasts are flagged, never hidden in an average.
        </p>
      </div>
    </div>
  );
}

function Decision({ champion, decision }: { champion: string; decision?: string | null }) {
  return (
    <section className="card flex flex-wrap items-start gap-4 px-5 py-4" aria-label="Method in service">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-primary/10 text-primary-strong">
        <Trophy size={19} aria-hidden="true" />
      </span>
      <div className="min-w-[220px] flex-1">
        <div className="text-sm font-semibold">
          Method in service: {champion === "model" ? "the LightGBM model" : "the seasonal baseline"}
        </div>
        <p className="mt-0.5 text-xs leading-5 text-ink-3">
          {champion === "model"
            ? "The model beat the baseline in most of the last test months; the baseline is kept as the reference to beat."
            : "Same weekday and hour, averaged over the last four weeks. The LightGBM model is trained and tested every month as the challenger and takes over when it wins."}
          {decision && <span className="block text-ink-2">{decision.replace(/^(model promoted|baseline kept in service): /, "Last decision: ")}.</span>}
        </p>
      </div>
    </section>
  );
}

function Legend({ className, text }: { className: string; text: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${className}`} />
      {text}
    </span>
  );
}

function Track({ width, className, thin }: { width: number; className: string; thin?: boolean }) {
  return (
    <div className={`overflow-hidden rounded-full bg-tint ${thin ? "h-1" : "h-1.5"}`}>
      <motion.div
        className={`h-full rounded-full ${className}`}
        initial={{ width: 0 }}
        animate={{ width: `${Math.max(1, width)}%` }}
        transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
      />
    </div>
  );
}

function Hourly({ table, ink }: { table?: Table; ink: Ink }) {
  const points = rowsOf(table).map((r) => ({ label: `${String(r.pickup_hour).padStart(2, "0")}:00`, value: Math.round(Number(r.predicted)) }));
  const peak = points.reduce((a, b) => (b.value > a.value ? b : a), points[0] ?? { label: "-", value: 0 });
  return (
    <div className="flex h-full flex-col">
      <p className="mb-3 text-sm text-ink-2">
        Busiest expected hour: <span className="font-semibold text-ink">{peak.label}</span> (
        <span className="num">{formatValue(peak.value, "trips")}</span> trips on an average day).
      </p>
      <div className="min-h-[220px] w-full flex-1">
        <ResponsiveContainer>
          <BarChart data={points} margin={{ top: 4, right: 6, left: 0, bottom: 0 }} barCategoryGap="16%">
            <CartesianGrid stroke={ink.grid} vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 12, fill: ink.axis }} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={18} />
            <YAxis tickFormatter={(v: number) => compact(v)} tick={{ fontSize: 12, fill: ink.axis }} width={48} axisLine={false} tickLine={false} />
            <Tooltip content={<Tip unit="trips" />} cursor={{ fill: ink.grid, opacity: 0.6 }} />
            <Bar dataKey="value" name="Expected trips" fill={ink.series[0]} fillOpacity={0.75} radius={[4, 4, 0, 0]} animationDuration={700} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Method({ validated, runId, rounds }: { validated: string; runId: string; rounds: number }) {
  const items: [string, string][] = [
    ["Tested on unseen months", `Each of the last three months, up to ${validated}, is forecast from the weeks before it, the model trained on earlier months only. Never a random split.`],
    ["Champion and challenger", "The seasonal baseline and the LightGBM model compete every month. The model is used only when it wins most of those months; otherwise it keeps training as the challenger."],
    ["Imbalance taken into account", "Errors are measured per borough and per demand level, weighted by trips, so the busy Manhattan zones cannot hide the rest."],
    ["What it predicts", "Recorded trips, not total need: a ride that could not find a taxi leaves no trace in the data."],
  ];
  return (
    <div className="space-y-3">
      <ol className="space-y-3">
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
      <p className="border-t border-line pt-3 text-xs leading-5 text-ink-3">
        Gradient-boosted trees (LightGBM, {rounds} trees) for the expected value and the 80 % range. Run{" "}
        <code className="font-mono">{runId.slice(0, 12)}</code> in MLflow holds its data version, settings, scores and model.
      </p>
    </div>
  );
}

function Loading() {
  return (
    <Shell>
      <div className="space-y-2">
        <div className="skeleton h-4 w-24" />
        <div className="skeleton h-9 w-80" />
        <div className="skeleton h-4 w-[28rem] max-w-full" />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="card space-y-3 p-5">
            <div className="skeleton h-4 w-28" />
            <div className="skeleton h-9 w-32" />
            <div className="skeleton h-4 w-40" />
          </div>
        ))}
      </div>
      <div className="card h-[360px] p-5">
        <div className="skeleton h-full w-full" />
      </div>
    </Shell>
  );
}
