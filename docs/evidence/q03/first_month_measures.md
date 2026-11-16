# Measures on the first loaded months (bronze)

Measured on 16 November 2026 on `bronze.yellow_trips_raw`, before fixing the silver
quality rules. These numbers justify two rules: the `cross_month` tolerance and the
`not_reported` flag.

## 1. Rows, schema and the congestion-fee column

| Source file | Contract | Rows in file | Rows in bronze | `cbd_congestion_fee` not null |
|---|---|---|---|---|
| 2024-12 | v2024 | 3,668,371 | 3,668,371 | 0 |
| 2025-01 | v2025 | 3,475,226 | 3,475,226 | 3,475,226 |

The 2024-12 file does not contain `cbd_congestion_fee`; the column appears in 2025-01.
This is the real schema change handled by the versioned source contract.

## 2. Pickup date compared with the month of the file

| Source file | Pickup in month | Within 3 days of the month (`cross_month`) | Far from the month (`out_of_period`) | Earliest pickup | Latest pickup |
|---|---|---|---|---|---|
| 2024-12 | 3,668,337 | 26 | 8 | 2008-12-31 23:03:59 | 2025-03-23 20:42:06 |
| 2025-01 | 3,475,204 | 22 | 0 | 2024-12-31 20:47:55 | 2025-02-01 00:00:44 |

- Rows a few hours outside the month exist in both files (26 and 22 rows): they are
  late or early rows of real trips. They stay `valid`, carry the informative flag
  `cross_month`, and are counted on their real pickup date.
- Aberrant dates exist too (8 rows in 2024-12, from year 2008 to a date three months
  after the file month). They are `invalid` with the flag `out_of_period`.
- The 3-day tolerance separates the two groups with no ambiguous row in either file.

## 3. Rows with unreported codes (`payment_type = 0`), file 2025-01

| payment_type | Rows | Share | Rows with NULL rate code | Rows with NULL passenger count | Sum of total_amount (USD) |
|---|---|---|---|---|---|
| 0 | 540,149 | 15.54 % | 540,149 | 540,149 | 10,849,095 |
| 1 | 2,444,393 | 70.34 % | 0 | 0 | 68,636,615 |
| 2 | 390,429 | 11.23 % | 0 | 0 | 8,488,063 |
| 3 | 23,773 | 0.68 % | 0 | 0 | 146,105 |
| 4 | 76,481 | 2.20 % | 0 | 0 | 885,149 |
| 5 | 1 | 0.00 % | 0 | 0 | 0 |

Every row with `payment_type = 0` has a NULL rate code and a NULL passenger count, and
no other row does. These rows are 15.5 % of trips and about 12 % of `total_amount`.
The 2024-12 file has 326,291 such rows (8.9 %).

Decision: a NULL code means "not reported by the vendor", which is different from a
wrong code. These rows keep the status `valid` with the informative flag `not_reported`.
Marking them `suspicious` would remove 15 % of trips and 12 % of revenue from approved
metrics without a business reason. Consequences: tip metrics stay limited to
`payment_type = 1`, and breakdowns by rate code or passenger count show a
"Not reported" category.

`ratecodeid = 99` (41,963 rows in 2025-01) is a present but unknown code: flag
`unknown_ratecode`, status `suspicious`.

## 4. Volume on the development machine

| File | Parquet size | Bronze partition size | Bronze load time |
|---|---|---|---|
| 2025-01 | 59 MB | 1,178 MB | about 5 min |
