import { formatValue } from "../lib/format";

type Props = {
  columns: string[];
  rows: unknown[][];
  units?: Record<string, string>;
  max?: number;
};

// The governed result exactly as returned by the query: the numbers the narrative may
// quote and the chart draws. Numeric columns align right in tabular figures.
export default function DataTable({ columns, rows, units = {}, max = 50 }: Props) {
  const unitOf = (c: string) =>
    units[c] ?? units[Object.keys(units).find((m) => c.startsWith(`${m}_`)) ?? ""] ?? "";
  const isNumeric = (v: unknown) => typeof v === "number" || /^-?\d+(\.\d+)?$/.test(String(v));
  const numericColumn = columns.map((_, j) => rows.length > 0 && rows.every((r) => r[j] === null || isNumeric(r[j])));
  const cell = (c: string, v: unknown) => {
    if (c.endsWith("_change_pct")) {
      if (v === null || v === undefined) return <span className="text-ink-3">-</span>;
      const n = Number(v);
      return <span className={n >= 0 ? "text-good-ink" : "text-bad-ink"}>{n > 0 ? "+" : ""}{n} %</span>;
    }
    return isNumeric(v) ? formatValue(v, unitOf(c)) : String(v ?? "-");
  };
  return (
    <div className="max-h-80 overflow-auto rounded-input border border-line">
      <table className="min-w-full text-sm">
        <thead className="sticky top-0 bg-tint text-left">
          <tr>
            {columns.map((c, j) => (
              <th
                key={c}
                className={`whitespace-nowrap border-b border-line px-3 py-2 text-xs font-medium text-ink-2 ${numericColumn[j] ? "text-right" : ""}`}
              >
                {c.replace(/_/g, " ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line bg-surface">
          {rows.slice(0, max).map((row, i) => (
            <tr key={i} className="transition-colors hover:bg-tint">
              {row.map((v, j) => (
                <td key={j} className={`whitespace-nowrap px-3 py-2 ${numericColumn[j] ? "text-right tabular-nums" : ""}`}>
                  {cell(columns[j], v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > max && (
        <p className="border-t border-line bg-tint px-3 py-2 text-xs text-ink-3">{rows.length - max} more rows not shown.</p>
      )}
    </div>
  );
}
