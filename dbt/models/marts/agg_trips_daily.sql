{{
    config(
        indexes=[
            {"columns": ["pickup_date_sk"]},
            {"columns": ["pickup_zone_sk"]},
        ],
    )
}}

-- Additive daily aggregate: sums and counts only. Averages and ratios are computed
-- at read time from these columns, so they stay correct at any level of grouping.
-- All quality statuses are kept (quality_status is a dimension): approved metrics
-- filter on 'valid', and "valid versus all rows" comparisons remain possible.
select
    pickup_date_sk,
    pickup_zone_sk,
    payment_type_sk,
    rate_code_sk,
    vendor_sk,
    quality_status,

    count(*) as trip_count,
    count(*) filter (where is_airport_trip) as airport_trip_count,

    sum(total_amount) as sum_total_amount,
    sum(fare_amount) as sum_fare_amount,
    sum(extra_amount) as sum_extra_amount,
    sum(mta_tax) as sum_mta_tax,
    sum(tolls_amount) as sum_tolls_amount,
    sum(improvement_surcharge) as sum_improvement_surcharge,
    sum(congestion_surcharge) as sum_congestion_surcharge,
    sum(airport_fee) as sum_airport_fee,
    sum(cbd_congestion_fee) as sum_cbd_congestion_fee,
    sum(tip_amount) as sum_tip_amount,

    -- tips are recorded for card payments only: numerators and denominators of tip metrics
    count(*) filter (where is_tip_recorded) as tip_recorded_trip_count,
    sum(tip_amount) filter (where is_tip_recorded) as sum_tip_amount_recorded,
    sum(fare_amount) filter (where is_tip_recorded) as sum_fare_amount_tip_recorded,

    sum(trip_distance) as sum_trip_distance,
    sum(duration_min) as sum_duration_min,

    -- revenue per mile is defined on trips with a positive distance
    sum(total_amount) filter (where trip_distance > 0) as sum_total_amount_with_distance,
    sum(trip_distance) filter (where trip_distance > 0) as sum_trip_distance_positive,

    count(passenger_count) as passenger_reported_trip_count,
    sum(passenger_count) as sum_passenger_count
from {{ ref("fct_trip") }}
group by 1, 2, 3, 4, 5, 6
