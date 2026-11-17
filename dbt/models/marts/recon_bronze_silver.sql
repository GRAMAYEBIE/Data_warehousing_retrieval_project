-- Bronze -> silver reconciliation, one row per source file month (exam Q3).
-- Row counts: bronze = silver + quarantine, nothing is dropped silently.
-- Amounts: the bronze total is split into what approved metrics keep (valid) and what
-- each status excludes, so every material exclusion is quantified and explained.
with manifest as (
    select distinct on (source_month)
        source_month,
        batch_id,
        row_count_file,
        row_count_bronze
    from {{ source("ops", "ingestion_manifest") }}
    where dataset = 'yellow' and status = 'loaded'
    order by source_month, finished_at desc
),

bronze as (
    select
        source_month,
        count(*) as bronze_rows,
        -- summed as exact decimals (cents), not as floating point
        sum(round(total_amount::numeric, 2)) as bronze_total_amount
    from {{ source("bronze", "yellow_trips_raw") }}
    group by source_month
),

silver as (
    select
        source_month,
        count(*) as silver_rows,
        count(*) filter (where quality_status = 'valid') as valid_rows,
        count(*) filter (where quality_status = 'suspicious') as suspicious_rows,
        count(*) filter (where quality_status = 'invalid') as invalid_rows,
        sum(total_amount) as silver_total_amount,
        sum(total_amount) filter (where quality_status = 'valid') as valid_total_amount,
        sum(total_amount) filter (where quality_status = 'suspicious')
            as suspicious_total_amount,
        sum(total_amount) filter (where quality_status = 'invalid') as invalid_total_amount,
        {% for flag in quality_flag_catalog() -%}
        count(*) filter (where is_{{ flag.code }}) as {{ flag.code }}_rows{{ "," if not loop.last }}
        {% endfor -%}
    from {{ ref("int_trips_flagged") }}
    group by source_month
),

quarantine as (
    select source_month, count(*) as quarantine_rows
    from {{ ref("int_trips_quarantine") }}
    group by source_month
)

select
    m.source_month,
    m.batch_id,
    m.row_count_file as file_rows,
    b.bronze_rows,
    coalesce(s.silver_rows, 0) as silver_rows,
    coalesce(q.quarantine_rows, 0) as quarantine_rows,
    b.bronze_rows - coalesce(s.silver_rows, 0) - coalesce(q.quarantine_rows, 0)
        as unexplained_rows,

    s.valid_rows,
    s.suspicious_rows,
    s.invalid_rows,
    round(100.0 * s.valid_rows / nullif(s.silver_rows, 0), 2) as valid_trip_rate_pct,

    b.bronze_total_amount,
    s.silver_total_amount,
    s.valid_total_amount,
    s.suspicious_total_amount,
    s.invalid_total_amount,
    -- rounding of each amount to cents in staging; expected to be 0.00
    b.bronze_total_amount - s.silver_total_amount as unexplained_amount,

    {% for flag in quality_flag_catalog() -%}
    s.{{ flag.code }}_rows{{ "," if not loop.last }}
    {% endfor -%}
from manifest as m
left join bronze as b on m.source_month = b.source_month
left join silver as s on m.source_month = s.source_month
left join quarantine as q on m.source_month = q.source_month
