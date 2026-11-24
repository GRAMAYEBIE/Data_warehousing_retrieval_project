// Number formatting by governed unit, the same conventions as the dashboards.
export function formatValue(value: unknown, unit = ""): string {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  if (unit === "ratio") return `${(n * 100).toFixed(1)} %`;
  if (unit.startsWith("USD")) {
    return n >= 1000
      ? `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`
      : `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (Number.isInteger(n)) return n.toLocaleString("en-US");
  return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function compact(value: number): string {
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(
    value,
  );
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

// "2025-05" or "2025-05-01" -> "May 2025" ("May" when short).
export function monthLabel(value: unknown, short = false): string {
  const match = /^(\d{4})-(\d{2})/.exec(String(value ?? ""));
  if (!match) return String(value ?? "-");
  const name = MONTHS[Number(match[2]) - 1] ?? match[2];
  return short ? name.slice(0, 3) : `${name} ${match[1]}`;
}

// "2026-11-18 11:58:25+00" -> "18 Nov 2026".
export function dayLabel(value: string): string {
  const time = Date.parse(value.replace(" ", "T").replace(/([+-]\d{2})$/, "$1:00"));
  if (Number.isNaN(time)) return value;
  return new Date(time).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function seconds(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

// "Manhattan", "not Bronx", "payment type: Cash" (a place speaks for itself).
export function filterText(f: { dimension: string; operator: string; values: unknown[] }): string {
  const values = f.values.join(", ");
  const negated = f.operator === "!=" || f.operator === "not in";
  if (/borough|zone/.test(f.dimension)) return negated ? `not ${values}` : values;
  const name = f.dimension.replace(/_/g, " ");
  return negated ? `${name}: not ${values}` : `${name}: ${values}`;
}
