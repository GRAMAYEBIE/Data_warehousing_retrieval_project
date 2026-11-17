{#
    Typed, renamed view of bronze. No row is removed and no value is corrected here.
    A value that cannot be cast is returned as NULL and the row is marked
    has_cast_error: it goes to quarantine instead of silver.
#}
{%- set smallint_columns = [
    "vendorid", "passenger_count", "ratecodeid", "pulocationid", "dolocationid", "payment_type"
] -%}
{%- set amount_columns = [
    "trip_distance", "fare_amount", "extra", "mta_tax", "tip_amount", "tolls_amount",
    "improvement_surcharge", "total_amount", "congestion_surcharge", "airport_fee",
    "cbd_congestion_fee"
] -%}

select
    -- technical identifiers and ingestion metadata
    source_month,
    file_row_number,
    batch_id,
    source_file,
    ingested_at,

    -- coded fields
    {{ safe_smallint("vendorid") }} as vendor_id,
    {{ safe_smallint("ratecodeid") }} as rate_code_id,
    {{ safe_smallint("payment_type") }} as payment_type_id,
    {{ safe_smallint("pulocationid") }} as pickup_location_id,
    {{ safe_smallint("dolocationid") }} as dropoff_location_id,
    {{ safe_smallint("passenger_count") }} as passenger_count,
    nullif(trim(store_and_fwd_flag), '') as store_and_fwd_flag,

    -- timestamps: New York local time, as published (no time zone conversion)
    tpep_pickup_datetime as pickup_ts,
    tpep_dropoff_datetime as dropoff_ts,

    -- distance (miles) and monetary amounts (USD)
    {{ safe_amount("trip_distance") }} as trip_distance,
    {{ safe_amount("fare_amount") }} as fare_amount,
    {{ safe_amount("extra") }} as extra_amount,
    {{ safe_amount("mta_tax") }} as mta_tax,
    {{ safe_amount("tip_amount") }} as tip_amount,
    {{ safe_amount("tolls_amount") }} as tolls_amount,
    {{ safe_amount("improvement_surcharge") }} as improvement_surcharge,
    {{ safe_amount("congestion_surcharge") }} as congestion_surcharge,
    {{ safe_amount("airport_fee") }} as airport_fee,
    {{ safe_amount("cbd_congestion_fee") }} as cbd_congestion_fee,
    {{ safe_amount("total_amount") }} as total_amount,

    {{ has_cast_error(smallint_columns, amount_columns) }} as has_cast_error

from {{ source("bronze", "yellow_trips_raw") }}
