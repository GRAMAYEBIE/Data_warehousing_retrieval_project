# Q7 evidence: the six dashboards

Generated from `services/metrics_sync/dashboards.py`, the code that builds the dashboards
after every publication. Each chart names the business question it answers and the
governed metrics it uses (definitions: `docs/metric_catalog.md`).

Files: `dashboard_<n>_<slug>.png` (full-page screenshot of each dashboard),
`dashboards_export.zip` (Superset export of the six dashboards, their charts and datasets).
6 dashboards, 67 charts placed, 57 distinct: the data-quality and last-refreshed tiles appear on every dashboard.


## 1. Executive Pulse

**Strategic question:** Are Yellow Taxi trips and revenue healthy?

| Chart | Question it answers | Type | Dataset | Metrics |
|---|---|---|---|---|
| Data quality: valid-trip rate | Is the data behind this dashboard trustworthy enough to decide? | kpi | `trips_daily` | `valid_trip_rate` |
| Last refreshed | How fresh and how complete is the data? | raw | `pipeline_status` | rows |
| Trips (weekly trend) | How are trips trending week by week? | trend_kpi | `trips_daily` | `trips` |
| Total revenue (weekly trend) | How is total revenue trending week by week? | trend_kpi | `trips_daily` | `total_revenue` |
| Average fare (weekly trend) | How is the average fare trending? | trend_kpi | `trips_daily` | `avg_fare` |
| Valid-trip rate (weekly trend) | Does the trend remain after removing invalid or suspicious records? | trend_kpi | `trips_daily` | `valid_trip_rate` |
| Trips and revenue by month | Which periods have the largest month-over-month change? | bar | `trips_daily` | `trips`, `total_revenue` |
| What drives revenue: components by month (indicative) | Is revenue rising because of fares, tolls or congestion fees? Components are reported differently by vendors: indicative only. | stacked | `trips_daily` | `fare_amount_valid`, `tip_amount_card`, `congestion_surcharge_revenue`, `congestion_fee_revenue`, `airport_fee_revenue` |
| Valid trips versus all trips (weekly) | Does the change remain after removing invalid or suspicious records? | line | `trips_daily` | `trips`, `trips_all` |
| Revenue by pickup borough and month | Which boroughs contribute most to growth or decline? | stacked | `trips_daily` | `total_revenue` |
| Trips by calendar month, one line per year | Which periods have the largest year-over-year change in trips? | line | `trips_daily` | `trips` |
| Total revenue by calendar month, one line per year | Which periods have the largest year-over-year change in revenue? | line | `trips_daily` | `total_revenue` |
| Weekly trips (bars) and valid-trip rate (line) | Does the trend hold once invalid or suspicious records are removed? | mixed | `trips_daily` | `trips`, `valid_trip_rate` |
| Total revenue: weekly and 4-week rolling mean | What is the underlying revenue trend once weekly noise is removed? | area | `trips_daily` | `total_revenue` |
| Revenue bridge: more trips or higher revenue per trip? | Is revenue changing because there are more trips or because each trip brings more? Previous month, then the volume effect and the price effect; the last bar is the latest month. | waterfall | `revenue_bridge` | `revenue_bridge_amount` |

## 2. Demand Rhythm

**Strategic question:** When should capacity and service attention increase?

| Chart | Question it answers | Type | Dataset | Metrics |
|---|---|---|---|---|
| Data quality: valid-trip rate | Is the data behind this dashboard trustworthy enough to decide? | kpi | `trips_daily` | `valid_trip_rate` |
| Last refreshed | How fresh and how complete is the data? | raw | `pipeline_status` | rows |
| Trips per active hour: hour of day by day of week | What are the busiest pickup hours by day of week? | heatmap | `trips_hourly` | `trips_per_active_hour` |
| Trips by hour: weekday, weekend and public holiday | How does weekday demand differ from weekend and holiday demand? | line | `trips_hourly` | `trips_per_active_hour` |
| Trips per active hour by borough and hour | Which hours have the highest trips per active hour, by borough? | line | `trips_hourly` | `trips_per_active_hour` |
| Trips by service period | Where are the sharpest morning, evening and late-night peaks? | bar | `trips_hourly` | `trips`, `trips_per_active_hour` |
| Airport versus city trips by hour | Are airport trips concentrated at different times from city trips? | stacked | `trips_hourly` | `trips` |
| Weekly trips (seasonality) | Which periods show unusual seasonality or falling demand? | line | `trips_hourly` | `trips` |
| Busiest pickup zones by trips per active hour | Which zones need capacity first when they are active? | hbar | `trips_hourly` | `trips_per_active_hour` |

## 3. Geography and Route Opportunities

**Strategic question:** Where is the value moving?

| Chart | Question it answers | Type | Dataset | Metrics |
|---|---|---|---|---|
| Data quality: valid-trip rate | Is the data behind this dashboard trustworthy enough to decide? | kpi | `trips_daily` | `valid_trip_rate` |
| Last refreshed | How fresh and how complete is the data? | raw | `pipeline_status` | rows |
| Top pickup zones by trips | Which pickup zones generate the most trips? | hbar | `trips_daily` | `trips` |
| Pickup zones: trips, revenue and average fare | Which pickup zones generate the most revenue and revenue per trip? | table | `trips_daily` | `trips`, `total_revenue`, `avg_fare`, `avg_distance` |
| Demand mix by pickup borough | How do the boroughs differ in demand mix? | pie | `trips_daily` | `trips` |
| Most common routes | What are the most common pickup-to-dropoff routes? | table | `routes_monthly` | `trips`, `total_revenue`, `revenue_per_mile`, `avg_duration` |
| High revenue per mile routes (at least 500 trips) | Which routes have high revenue but low volume, or high volume but low revenue per mile? | table | `routes_monthly` | `revenue_per_mile`, `trips`, `avg_distance` |
| Airport trips by pickup market segment | What share of trips start or end at airports, and where do they connect? | bar | `routes_monthly` | `airport_trips`, `trips` |
| Pickup zones: distance, revenue per mile and volume | Which zones combine long trips, high revenue per mile and high volume? Bubble size is the number of trips. | bubble | `trips_daily` | `avg_distance`, `revenue_per_mile`, `trips` |
| Revenue by borough and pickup zone | How concentrated is revenue across boroughs and zones? | treemap | `trips_daily` | `total_revenue` |
| Origin to destination: trips between boroughs | How do Manhattan, Brooklyn, Queens, Bronx and Staten Island exchange trips? | heatmap | `routes_monthly` | `trips` |
| Fastest-growing drop-off zones | Which drop-off zones are growing fastest? Zones with at least 500 trips in the previous month. | hbar | `dropoff_growth` | `zone_trip_change` |
| Fastest-declining drop-off zones | Which drop-off zones are declining fastest? Zones with at least 500 trips in the previous month. | hbar | `dropoff_growth` | `zone_trip_change` |

## 4. Fare, Payment and Customer Signals

**Strategic question:** What is changing in trip economics?

| Chart | Question it answers | Type | Dataset | Metrics |
|---|---|---|---|---|
| Data quality: valid-trip rate | Is the data behind this dashboard trustworthy enough to decide? | kpi | `trips_daily` | `valid_trip_rate` |
| Last refreshed | How fresh and how complete is the data? | raw | `pipeline_status` | rows |
| Average fare and average tip (card) by month | How are fares and tips changing over time? | line | `trips_daily` | `avg_fare`, `avg_tip` |
| Tip rate (card trips) by pickup borough | What is the tip rate by borough? | bar | `trips_daily` | `tip_rate` |
| Payment types by month | Are cash and card trip shares changing? | stacked | `trips_daily` | `trips` |
| Rate codes: fare, distance and duration | Which rate codes have the highest average fare, distance and duration? | table | `trips_daily` | `trips`, `avg_fare`, `avg_distance`, `avg_duration` |
| Revenue per mile by week | Is fare per mile changing independently of trip length? | line | `trips_daily` | `revenue_per_mile`, `avg_distance` |
| CBD congestion fee revenue by week | How much revenue does the congestion fee represent, and when? | bar | `trips_daily` | `congestion_fee_revenue` |
| Average fare by pickup borough | Which boroughs have the highest average fare? | hbar | `trips_daily` | `avg_fare` |
| Revenue per mile by pickup borough | Is the price per mile different between boroughs? | hbar | `trips_daily` | `revenue_per_mile` |

## 5. Service Efficiency and Anomalies

**Strategic question:** Where should leaders look closer?

| Chart | Question it answers | Type | Dataset | Metrics |
|---|---|---|---|---|
| Data quality: valid-trip rate | Is the data behind this dashboard trustworthy enough to decide? | kpi | `trips_daily` | `valid_trip_rate` |
| Last refreshed | How fresh and how complete is the data? | raw | `pipeline_status` | rows |
| Valid trips | What share of trips can support decisions? | kpi | `quality_daily` | `valid_share` |
| Suspicious trips | What share of trips needs review? | kpi | `quality_daily` | `suspicious_share` |
| Invalid trips | What share of trips is excluded? | kpi | `quality_daily` | `invalid_share` |
| Suspicious-trip share by vendor and week | Is the suspicious-trip rate changing by vendor or month? | line | `quality_daily` | `suspicious_share` |
| Quality flags (share of trips) | Which records imply implausible speeds, negative amounts, missing zones or pickup after dropoff? | table | `quality_daily` | `negative_amount_share`, `implausible_speed_share`, `unrealistic_duration_share`, `zero_distance_share`, `null_zone_share`, `pickup_after_dropoff_share`, `unknown_ratecode_share`, `not_reported_share` |
| Average duration by hour (valid trips) | Which hours have the longest average trip duration? | line | `trips_hourly` | `avg_duration` |
| Source months: rows and reconciliation | Which ingestion batches or source months have unexpected row counts? | raw | `source_reconciliation` | rows |
| Pipeline signals of each run | Which runs had warnings, and should decisions be paused? | raw | `pipeline_health` | rows |
| Invalid-trip share by pickup borough | Is the rejected-trip rate different by borough? | hbar | `quality_daily` | `invalid_share` |
| Suspicious-trip share by payment type | Is the suspicious-trip rate different by payment type? | hbar | `quality_daily` | `suspicious_share` |
| Routes with the biggest gap between usual and current duration | Which routes show the biggest gap between normal and current duration? Latest month versus earlier months, by service period (at least 100 trips in both). Score above 3: an unusual slowdown compared with all routes. | raw | `route_duration_anomaly` | rows |

## 6. City and Airport Strategy

**Strategic question:** What action should we take next?

| Chart | Question it answers | Type | Dataset | Metrics |
|---|---|---|---|---|
| Data quality: valid-trip rate | Is the data behind this dashboard trustworthy enough to decide? | kpi | `trips_daily` | `valid_trip_rate` |
| Last refreshed | How fresh and how complete is the data? | raw | `pipeline_status` | rows |
| Airport trips by hour and day type | How does airport demand change by weekday and hour? | line | `trips_hourly` | `trips` |
| Market mix by month: airport, Manhattan core, outer boroughs | What is the mix of airport, Manhattan core and outer-borough trips? | stacked | `trips_daily` | `trips` |
| Demand versus revenue by month | Where do demand increases not come with similar revenue growth? | line | `trips_daily` | `trips`, `total_revenue` |
| Least-served zones (trip volume as a demand proxy) | Which zones appear underserved using trip volume as a demand proxy? | table | `trips_daily` | `trips`, `avg_fare` |
| Estimated CO2 by pickup borough (ESTIMATE) | What is an estimated distance-based emissions indicator by borough? 0.400 kg CO2 per mile (US EPA typical passenger vehicle); estimate only. | bar | `trips_daily` | `est_co2_kg` |

