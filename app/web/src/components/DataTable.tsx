import { formatValue } from "../lib/format";

type Props = {
  columns: string[];
  rows: unknown[][];
  units?: Record<string, string>;
  max?: number;
};

// The governed result exactly as returned by the query: the numbers the narrative may
// quote and the chart draws.
export default function DataTable({ columns, rows, units = {}, max = 50 }: Props) {
  const unitOf = (c: string) =>
    units[c] ?? units[Object.keys(units).find((m) => c.startsWith(`${m}_`)) ?? ""] ?? "";
  const cell = (c: string, v: unknown) => {
    if (c.endsWith("_change_pct")) {
      if (v === null || v === undefined) return <span className="text-slate-400">-</span>;
      const n = Number(v);
      return <span className={n >= 0 ? "text-mint-700" : "text-coral-600"}>{n > 0 ? "+" : ""}{n} %</span>;
    }
    const numeric = typeof v === "number" || /^-?\d+(\.\d+)?$/.test(String(v));
    return numeric ? formatValue(v, unitOf(c)) : String(v ?? "-");
  };
  return (
    <div className="max-h-80 overflow-auto rounded-xl ring-1 ring-slate-200">
      <table className="min-w-full bg-white text-sm">
        <thead className="sticky top-0 bg-night-900 text-left text-[11px] uppercase tracking-wider text-slate-300">
          <tr>
            {columns.map((c) => (
              <th key={c} className="whitespace-nowrap px-3 py-2.5 font-semibold">{c.replace(/_/g, " ")}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.slice(0, max).map((row, i) => (
            <tr key={i} className="odd:bg-white even:bg-mist/50 hover:bg-taxi-400/10">
              {row.map((v, j) => (
                <td key={j} className="whitespace-nowrap px-3 py-2 tabular-nums">{cell(columns[j], v)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > max && <p className="bg-mist px-3 py-2 text-xs text-slate-500">{rows.length - max} more rows not shown.</p>}
    </div>
  );
}
