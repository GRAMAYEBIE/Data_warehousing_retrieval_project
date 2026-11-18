{{
    config(
        alias="trips",
        materialized="incremental",
        incremental_strategy="delete+insert",
        unique_key="source_month",
        on_schema_change="fail",
        indexes=[
            {"columns": ["source_month", "file_row_number"], "unique": true},
            {"columns": ["pickup_ts"], "type": "brin"},
        ],
        pre_hook=[
            "set work_mem = '64MB'",
            "set max_parallel_workers_per_gather = 1",
        ],
    )
}}

{#
    Memory of the pre_hook: each sort or hash may use work_mem, in every parallel worker.
    128 MB with two workers contributed to a PostgreSQL backend crash on the 4 GB
    development host while Airflow was running (see docs/evidence/q05).

    Silver trips: one row per bronze row that could be parsed, with derived fields,
    one boolean per quality flag, the flag list and the quality status.

    Nothing is deleted or corrected: approved metrics filter on quality_status = 'valid',
    and every excluded row stays visible with the reason of its exclusion.

    Built month by month (delete+insert on source_month), see macros/months_to_process.sql.
#}
{%- set months = months_to_process() -%}
{%- set tolerance = var("cross_month_tolerance_days") -%}
{%- set natural_key = [
    "vendor_id", "pickup_ts", "dropoff_ts", "pickup_location_id", "dropoff_location_id",
    "trip_distance", "total_amount"
] -%}

with trips as (
    select
        t.*,
        date_trunc('month', t.pickup_ts)::date as pickup_month,
        (extract(epoch from (t.dropoff_ts - t.pickup_ts)) / 60.0)::numeric(12, 2) as duration_min,
        coalesce(t.fare_amount, 0) + coalesce(t.extra_amount, 0) + coalesce(t.mta_tax, 0)
        + coalesce(t.tip_amount, 0) + coalesce(t.tolls_amount, 0)
        + coalesce(t.improvement_surcharge, 0) + coalesce(t.congestion_surcharge, 0)
        + coalesce(t.airport_fee, 0) + coalesce(t.cbd_congestion_fee, 0) as components_amount
    from {{ ref("stg_yellow_trips") }} as t
    where
        t.source_month in ({{ date_literals(months) }})
        and not t.has_cast_error
),

positioned as (
    select
        *,
        (
            {{ safe_divide("trip_distance", "duration_min / 60.0") }}
        )::numeric(12, 2) as speed_mph,
        -- rank of the row among rows of the same file sharing its natural key
        row_number() over (
            partition by source_month, {{ natural_key | join(", ") }}
            order by file_row_number
        ) as rank_in_file,
        pickup_month <> source_month
        and pickup_ts >= source_month - interval '{{ tolerance }} days'
        and pickup_ts < source_month + interval '1 month' + interval '{{ tolerance }} days'
            as is_cross_month,
        pickup_ts is null
        or pickup_ts < source_month - interval '{{ tolerance }} days'
        or pickup_ts >= source_month + interval '1 month' + interval '{{ tolerance }} days'
            as is_out_of_period
    from trips
),

-- Late or early rows: the same trip may also be in the file of its pickup month.
-- That file wins; the copy in the neighbouring file is the duplicate.
-- Only a handful of rows per file are concerned. They are read with literal date
-- ranges (a few days around each month boundary) so PostgreSQL knows they are few.
cross_month_candidates as (
    {% for month in months %}
    select
        c.source_month,
        c.file_row_number,
        date_trunc('month', c.pickup_ts)::date as pickup_month,
        {{ natural_key | join(", ") }}
    from {{ ref("stg_yellow_trips") }} as c
    where
        c.source_month = '{{ month }}'::date
        and not c.has_cast_error
        and (
            (
                c.pickup_ts >= '{{ month }}'::date - interval '{{ tolerance }} days'
                and c.pickup_ts < '{{ month }}'::date
            )
            or (
                c.pickup_ts >= '{{ month }}'::date + interval '1 month'
                and c.pickup_ts
                < '{{ month }}'::date + interval '1 month' + interval '{{ tolerance }} days'
            )
        )
    {{ "union all" if not loop.last }}
    {% endfor %}
),

-- Rows of the neighbouring files whose pickup falls in the same boundary days:
-- the only rows a late or early copy can duplicate.
home_rows as (
    {% for month in months %}
    select
        home.source_month,
        {{ natural_key | join(", ") }}
    from {{ ref("stg_yellow_trips") }} as home
    where
        (
            home.source_month = ('{{ month }}'::date - interval '1 month')::date
            and home.pickup_ts >= '{{ month }}'::date - interval '{{ tolerance }} days'
            and home.pickup_ts < '{{ month }}'::date
        )
        or (
            home.source_month = ('{{ month }}'::date + interval '1 month')::date
            and home.pickup_ts >= '{{ month }}'::date + interval '1 month'
            and home.pickup_ts
            < '{{ month }}'::date + interval '1 month' + interval '{{ tolerance }} days'
        )
    {{ "union all" if not loop.last }}
    {% endfor %}
),

cross_month_copies as (
    select distinct
        c.source_month,
        c.file_row_number
    from cross_month_candidates as c
    inner join home_rows as home
        on
            home.source_month = c.pickup_month
            and home.pickup_ts = c.pickup_ts
            and home.dropoff_ts = c.dropoff_ts
            and home.total_amount = c.total_amount
            and home.trip_distance = c.trip_distance
            and home.vendor_id is not distinct from c.vendor_id
            and home.pickup_location_id is not distinct from c.pickup_location_id
            and home.dropoff_location_id is not distinct from c.dropoff_location_id
),

flagged as (
    select
        p.*,

        -- invalid
        coalesce(
            least(
                p.fare_amount, p.extra_amount, p.mta_tax, p.tip_amount, p.tolls_amount,
                p.improvement_surcharge, p.congestion_surcharge, p.airport_fee,
                p.cbd_congestion_fee, p.total_amount
            ) < 0,
            false
        ) as is_negative_amount,
        coalesce(p.pickup_ts > p.dropoff_ts, false) as is_pickup_after_dropoff,
        p.rank_in_file > 1 or x.file_row_number is not null as is_duplicate,

        -- suspicious
        coalesce(p.speed_mph > {{ var("max_speed_mph") }}, false) as is_implausible_speed,
        coalesce(p.trip_distance > {{ var("max_distance_miles") }}, false)
            as is_implausible_distance,
        coalesce(
            p.duration_min < {{ var("min_duration_minutes") }}
            or p.duration_min > {{ var("max_duration_minutes") }},
            true
        ) as is_unrealistic_duration,
        coalesce(p.trip_distance = 0 and p.total_amount > 0, false) as is_zero_distance,
        p.pickup_location_id is null
        or p.dropoff_location_id is null
        or p.pickup_location_id in ({{ var("unknown_zone_ids") | join(", ") }})
        or p.dropoff_location_id in ({{ var("unknown_zone_ids") | join(", ") }})
            as is_null_zone,
        coalesce(
            p.payment_type_id not in ({{ var("known_payment_types") | join(", ") }}), false
        ) as is_unknown_payment,
        coalesce(
            p.rate_code_id not in ({{ var("known_rate_codes") | join(", ") }}), false
        ) as is_unknown_ratecode,

        -- info
        p.rate_code_id is null or p.passenger_count is null as is_not_reported,
        coalesce(
            abs(p.total_amount - p.components_amount) > {{ var("amount_tolerance") }}, false
        ) as is_component_mismatch
    from positioned as p
    left join cross_month_copies as x
        on p.source_month = x.source_month and p.file_row_number = x.file_row_number
)

select
    -- identifiers and lineage
    source_month,
    file_row_number,
    batch_id,
    source_file,
    ingested_at,

    -- coded fields
    vendor_id,
    rate_code_id,
    payment_type_id,
    pickup_location_id,
    dropoff_location_id,
    passenger_count,
    store_and_fwd_flag,

    -- time
    pickup_ts,
    dropoff_ts,
    pickup_month,
    duration_min,

    -- distance and speed
    trip_distance,
    speed_mph,

    -- amounts
    fare_amount,
    extra_amount,
    mta_tax,
    tip_amount,
    tolls_amount,
    improvement_surcharge,
    congestion_surcharge,
    airport_fee,
    cbd_congestion_fee,
    total_amount,
    components_amount,

    -- quality
    {% for flag in quality_flag_catalog() -%}
    is_{{ flag.code }},
    {% endfor -%}
    {{ quality_flag_array() }} as quality_flags,
    {{ quality_status() }} as quality_status,

    current_timestamp as silver_loaded_at
from flagged
