{{
    config(
        materialized="incremental",
        incremental_strategy="delete+insert",
        unique_key="source_month",
        on_schema_change="fail",
        indexes=[
            {"columns": ["source_month"]},
            {"columns": ["pickup_ts"], "type": "brin"},
        ],
    )
}}

{#
    Fact table, grain: one completed taxi trip (one row of a TLC file).

    trip_sk is deterministic and readable: YYYYMM of the source file followed by the
    0-based row number in that file on 8 digits. Trip 20250100001204 is row 1204 of
    yellow_tripdata_2025-01.parquet, in every layer and after every re-run.

    Indexes: only source_month (the incremental delete of a month) and a BRIN on pickup_ts.
    Nothing reads single trips from this table in production: aggregates scan it and BI
    and AI read analytics. Three b-tree indexes on 7 million rows (trip_sk, date, zone)
    made a two-month rebuild exceed two hours on the development host.

    Every row of silver is kept, whatever its quality status; approved metrics filter
    on quality_status = 'valid'. Unknown or missing codes point to the Unknown member
    (-1) of their dimension, so every foreign key resolves.
#}
{%- set months = months_to_process() %}

-- trip_quality_sk is computed here (hash of the flag list), so no ref() ties this model
-- to dim_trip_quality. Without this declaration, a new month with new flag combinations
-- was tested against a dimension not yet rebuilt (relationships test failed, 2025-02).
-- depends_on: {{ ref("dim_trip_quality") }}

with trips as (
    select t.*
    from {{ ref("int_trips_flagged") }} as t
    where t.source_month in ({{ date_literals(months) }})
)

select
    -- keys
    (
        to_char(t.source_month, 'YYYYMM')::bigint * 100000000 + t.file_row_number
    ) as trip_sk,
    coalesce(d.date_sk, -1) as pickup_date_sk,
    case
        when t.pickup_ts is null then -1
        else extract(hour from t.pickup_ts)::integer * 100
            + extract(minute from t.pickup_ts)::integer
    end as pickup_time_sk,
    coalesce(pz.zone_sk, -1) as pickup_zone_sk,
    coalesce(dz.zone_sk, -1) as dropoff_zone_sk,
    coalesce(pt.payment_type_sk, -1) as payment_type_sk,
    case
        when t.rate_code_id is null then -2
        else coalesce(rc.rate_code_sk, -1)
    end as rate_code_sk,
    coalesce(v.vendor_sk, -1) as vendor_sk,
    {{ service_period_sk("t.pickup_ts") }} as service_period_sk,
    md5(array_to_string(t.quality_flags, ',')) as trip_quality_sk,

    -- degenerate and technical identifiers (lineage back to the raw file)
    t.source_month,
    t.file_row_number,
    t.batch_id,
    t.source_file,

    -- timestamps (New York local time)
    t.pickup_ts,
    t.dropoff_ts,

    -- measures
    t.passenger_count,
    t.trip_distance,
    t.duration_min,
    t.speed_mph,
    t.fare_amount,
    t.extra_amount,
    t.mta_tax,
    t.tip_amount,
    t.tolls_amount,
    t.improvement_surcharge,
    t.congestion_surcharge,
    t.airport_fee,
    t.cbd_congestion_fee,
    t.total_amount,

    -- attributes used by governed metrics
    (
        coalesce(pz.is_airport, false)
        or coalesce(dz.is_airport, false)
        or coalesce(t.rate_code_id in ({{ var("airport_rate_codes") | join(", ") }}), false)
    ) as is_airport_trip,
    coalesce(pt.is_tip_recorded, false) as is_tip_recorded,
    t.quality_status,
    t.quality_flags,

    current_timestamp as gold_loaded_at
from trips as t
left join {{ ref("dim_date") }} as d on t.pickup_ts::date = d.date_day
left join {{ ref("dim_zone") }} as pz on t.pickup_location_id = pz.location_id
left join {{ ref("dim_zone") }} as dz on t.dropoff_location_id = dz.location_id
left join {{ ref("dim_payment_type") }} as pt on t.payment_type_id = pt.payment_type_id
left join {{ ref("dim_rate_code") }} as rc on t.rate_code_id = rc.rate_code_id
left join {{ ref("dim_vendor") }} as v on t.vendor_id = v.vendor_id
