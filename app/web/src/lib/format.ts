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
