{{ config(materialized="table", schema="gold") }}

-- Daily time spine required by MetricFlow (one row per day, no gap, no NULL).
select generate_series(
    '{{ var("calendar_start") }}'::date, '{{ var("calendar_end") }}'::date, interval '1 day'
)::date as date_day
