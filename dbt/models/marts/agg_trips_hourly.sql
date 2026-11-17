{{
    config(
        indexes=[
            {"columns": ["pickup_date_sk", "pickup_hour"]},
            {"columns": ["pickup_zone_sk"]},
        ],
    )
}}

-- Additive hourly aggregate for demand analysis. An "active hour" is a distinct
-- (pickup_date_sk, pickup_hour) with at least one trip in the selection, counted at
-- read time: trips per active hour = sum(trip_count) / count(distinct date and hour).
select
    pickup_date_sk,
    (pickup_time_sk / 100)::smallint as pickup_hour,
    pickup_zone_sk,
    service_period_sk,
    is_airport_trip,
    quality_status,

    count(*) as trip_count,
    sum(total_amount) as sum_total_amount,
    sum(trip_distance) as sum_trip_distance,
    sum(duration_min) as sum_duration_min
from {{ ref("fct_trip") }}
where pickup_time_sk >= 0
group by 1, 2, 3, 4, 5, 6
