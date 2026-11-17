{{
    config(
        indexes=[
            {"columns": ["pickup_month"]},
            {"columns": ["pickup_zone_sk", "dropoff_zone_sk"]},
        ],
    )
}}

-- Additive monthly aggregate by route (pickup zone -> dropoff zone) and service period.
-- Valid trips only: route analysis feeds decisions, so it uses approved rows.
select
    d.month_start as pickup_month,
    f.pickup_zone_sk,
    f.dropoff_zone_sk,
    f.service_period_sk,

    count(*) as trip_count,
    count(*) filter (where f.is_airport_trip) as airport_trip_count,
    sum(f.total_amount) as sum_total_amount,
    sum(f.fare_amount) as sum_fare_amount,
    sum(f.trip_distance) as sum_trip_distance,
    sum(f.duration_min) as sum_duration_min,
    sum(f.total_amount) filter (where f.trip_distance > 0) as sum_total_amount_with_distance,
    sum(f.trip_distance) filter (where f.trip_distance > 0) as sum_trip_distance_positive
from {{ ref("fct_trip") }} as f
inner join {{ ref("dim_date") }} as d on f.pickup_date_sk = d.date_sk
where f.quality_status = 'valid' and f.pickup_date_sk <> -1
group by 1, 2, 3, 4
