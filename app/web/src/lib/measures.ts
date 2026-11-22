import type { CatalogView } from "../api/client";

// Presentation of the governed measures. The catalogue (API) is the source of every
// definition; this file only groups them for reading and derives what the catalogue
// implies (grains from the source table). Unknown measures fall into "Other".
export const CATEGORIES = ["Demand", "Revenue", "Fares & tips", "Geography", "Quality", "Other"] as const;
export type Category = (typeof CATEGORIES)[number];

const CATEGORY: Record<string, Category> = {
  trips: "Demand",
  trips_per_active_hour: "Demand",
  avg_duration: "Demand",
  avg_distance: "Demand",
  total_revenue: "Revenue",
  revenue_per_mile: "Revenue",
  congestion_fee_revenue: "Revenue",
  congestion_surcharge_revenue: "Revenue",
  airport_fee_revenue: "Revenue",
  avg_fare: "Fares & tips",
  avg_tip: "Fares & tips",
  tip_rate: "Fares & tips",
  airport_trips: "Geography",
  valid_trip_rate: "Quality",
  est_co2_kg: "Quality",
};

export const UNIT_SHORT: Record<string, string> = {
  USD: "USD",
  trips: "trips",
  ratio: "%",
  "miles per trip": "mi",
  "minutes per trip": "min",
  "trips per active hour": "trips/h",
  "USD per mile": "USD/mi",
  "USD per trip": "USD",
  "USD per card trip": "USD",
  "kg CO2 (estimate)": "kg",
};

export type Measure = {
  name: string;
  label: string;
  description: string;
  unit: string;
  unitShort: string;
  category: Category;
  formula: string;
  filters: string;
  source: string;
  grains: string;
  estimate: boolean;
};

export function measuresOf(catalog?: CatalogView): Measure[] {
  return Object.entries(catalog?.metrics ?? {}).map(([name, m]) => ({
    name,
    label: m.label,
    description: m.description,
    unit: m.unit,
    unitShort: UNIT_SHORT[m.unit] ?? m.unit,
    category: CATEGORY[name] ?? "Other",
    formula: m.sql_expression,
    filters: m.filters,
    source: m.base_table,
    grains: /hourly/.test(m.base_table) ? "Hour, day, week, month" : "Day, week, month",
    estimate: m.is_estimate,
  }));
}

export const DATA_OWNER = "AYEBIE GRAM MESCHAC";
