import { motion } from "framer-motion";
import type { ReactElement } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  type TooltipProps,
  XAxis,
  YAxis,
} from "recharts";
import { compact, formatValue } from "../lib/format";
import { useIsDark } from "../lib/theme";

// Chart colours by role. SVG attributes cannot read CSS variables, so the two themes are
// spelled out here with the same values as src/index.css (palette validated for colour
// vision deficiencies on both surfaces).
export const INK = {
  light: { series: ["#1f7ae0", "#eb6834", "#1baf7a"], muted: "#c5d3e3", grid: "#e3ecf5", axis: "#5f6f85", label: "#5b6b80" },
  dark: { series: ["#4c9af0", "#d95926", "#199e70"], muted: "#3a4c66", grid: "#212f45", axis: "#8c9db5", label: "#a0b0c6" },
};

type Props = {
  columns: string[];
  rows: unknown[][];
  metrics: string[];
  units?: Record<string, string>;
  labels?: Record<string, string>;
};

// The form follows the shape of the governed result, never the model's wording:
// a time column -> line over time; *_previous / *_current -> paired bars;
// categories -> horizontal ranked bars (long zone names stay readable).
// A single row is shown as headline figures by the answer itself, not as a chart.
export default function ResultChart({ columns, rows, metrics, units = {}, labels = {} }: Props) {
  const ink = useIsDark() ? INK.dark : INK.light;
  if (rows.length < 2 || !metrics.length) return null;

  const data = rows.map((row) => Object.fromEntries(columns.map((c, i) => [c, row[i]])));
  const num = (v: unknown) => (v === null || v === undefined || v === "" ? null : Number(v));
  const label = (m: string) => labels[m] ?? m.replace(/_/g, " ");
  const first = metrics[0];
  const unit = units[first] ?? "";
  const tick = (v: number) => (unit === "ratio" ? `${Math.round(v * 100)}%` : unit.startsWith("USD") ? `$${compact(v)}` : compact(v));
  const dims = columns.filter((c) => !metrics.some((m) => c === m || c.startsWith(`${m}_`)) && c !== "period_role");
  const keyOf = (d: Record<string, unknown>) => (dims.length ? dims.map((c) => d[c] ?? "-").join(" · ") : String(d.period ?? ""));
  // One axis only: series of another unit than the first metric are left to the table.
  const shown = metrics.filter((m) => columns.includes(m) && (units[m] ?? "") === unit).slice(0, 3);

  if (columns.includes(`${first}_current`)) {
    return (
      <BarList
        unit={unit}
        colors={ink}
        rows={data.map((d) => ({
          key: dims.length ? keyOf(d) : label(first),
          value: num(d[`${first}_current`]),
          previous: num(d[`${first}_previous`]),
        }))}
      />
    );
  }

  const trend = columns.includes("period") || columns[0] === "pickup_hour";
  const points = data.map((d) => ({
    key: trend ? String(d.period ?? d.pickup_hour).slice(0, 10) : keyOf(d),
    ...Object.fromEntries(shown.map((m) => [label(m), num(d[m])])),
  }));

  if (trend) {
    return (
      <Frame height={260}>
        <AreaChart data={points} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <defs>
            {ink.series.map((color, i) => (
              <linearGradient key={color} id={`fill-${i}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.16} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid stroke={ink.grid} vertical={false} />
          <XAxis dataKey="key" tick={{ fontSize: 11, fill: ink.axis }} axisLine={false} tickLine={false} minTickGap={28} />
          <YAxis tickFormatter={tick} tick={{ fontSize: 11, fill: ink.axis }} width={52} axisLine={false} tickLine={false} />
          <Tooltip content={<Tip unit={unit} />} cursor={{ stroke: ink.axis, strokeDasharray: "3 3" }} />
          {shown.length > 1 && <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: ink.label }} />}
          {shown.map((m, i) => (
            <Area
              key={m}
              type="monotone"
              dataKey={label(m)}
              stroke={ink.series[i]}
              strokeWidth={2}
              fill={`url(#fill-${i})`}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--chart-surface, #fff)" }}
              isAnimationActive
              animationDuration={700}
            />
          ))}
        </AreaChart>
      </Frame>
    );
  }

  return (
    <BarList
      unit={unit}
      colors={ink}
      title={label(first)}
      rows={data.slice(0, 15).map((d) => ({ key: keyOf(d), value: num(d[first]) }))}
    />
  );
}

type BarRow = { key: string; value: number | null; previous?: number | null };

// Ranked categories as an HTML bar list: the full name stays readable (truncated with its
// full text on hover), values align right in tabular figures, bars share one scale.
export function BarList({
  rows,
  unit,
  colors,
  title,
}: {
  rows: BarRow[];
  unit: string;
  colors: (typeof INK)["light"];
  title?: string;
}) {
  const compare = rows.some((r) => r.previous !== undefined);
  const max = Math.max(1, ...rows.flatMap((r) => [Math.abs(r.value ?? 0), Math.abs(r.previous ?? 0)]));
  const width = (v: number | null | undefined) => `${Math.max(0.6, (100 * Math.abs(v ?? 0)) / max)}%`;
  return (
    <div>
      <div className="mb-2 flex items-center gap-4 text-xs text-ink-3">
        {compare ? (
          <>
            <Swatch color={colors.series[0]} text="This period" />
            <Swatch color={colors.muted} text="Previous period" />
          </>
        ) : (
          title && <span>{title}</span>
        )}
      </div>
      <ul className="space-y-1">
        {rows.map((r, i) => {
          const change =
            compare && r.previous && r.value !== null ? ((r.value - r.previous) / Math.abs(r.previous)) * 100 : null;
          return (
            <li
              key={`${r.key}-${i}`}
              className="group rounded-lg px-2 py-1.5 transition-colors hover:bg-tint"
              title={`${r.key}: ${formatValue(r.value, unit)}${compare ? ` (previous ${formatValue(r.previous, unit)})` : ""}`}
            >
              <div className="flex items-baseline gap-3 text-sm">
                <span className="min-w-0 flex-1 truncate text-ink-2 group-hover:text-ink">{r.key}</span>
                {change !== null && (
                  <span className={`text-xs tabular-nums ${change >= 0 ? "text-good-ink" : "text-bad-ink"}`}>
                    {change >= 0 ? "+" : ""}
                    {change.toFixed(1)} %
                  </span>
                )}
                <span className="font-medium tabular-nums text-ink">{formatValue(r.value, unit)}</span>
              </div>
              <div className="mt-1.5 space-y-1">
                <Track color={colors.series[0]} width={width(r.value)} delay={i * 0.03} />
                {compare && <Track color={colors.muted} width={width(r.previous)} delay={i * 0.03 + 0.05} thin />}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Track({ color, width, delay, thin }: { color: string; width: string; delay: number; thin?: boolean }) {
  return (
    <div className={`overflow-hidden rounded-full bg-tint ${thin ? "h-1" : "h-1.5"}`}>
      <motion.div
        className="h-full rounded-full"
        style={{ background: color }}
        initial={{ width: 0 }}
        animate={{ width }}
        transition={{ duration: 0.6, delay, ease: [0.22, 1, 0.36, 1] }}
      />
    </div>
  );
}

function Swatch({ color, text }: { color: string; text: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      {text}
    </span>
  );
}

export function Tip({ active, payload, label, unit }: TooltipProps<number, string> & { unit: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-raised">
      <div className="mb-1 font-medium text-ink">{label}</div>
      {payload.map((p) => (
        <div key={String(p.name)} className="flex items-center gap-2 text-ink-2">
          <span className="h-2 w-2 rounded-full" style={{ background: String(p.color ?? p.stroke ?? "") }} />
          <span>{p.name}</span>
          <span className="ml-auto pl-4 font-medium tabular-nums text-ink">{formatValue(p.value, unit)}</span>
        </div>
      ))}
    </div>
  );
}

function Frame({ children, height }: { children: ReactElement; height: number }) {
  return (
    <div className="w-full" style={{ height }}>
      <ResponsiveContainer>{children}</ResponsiveContainer>
    </div>
  );
}
