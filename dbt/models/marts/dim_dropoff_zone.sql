{{ config(materialized="view") }}

-- Role-playing view of dim_zone for the dropoff location.
select
    zone_sk as dropoff_zone_sk,
    location_id as dropoff_location_id,
    zone_name as dropoff_zone,
    borough as dropoff_borough,
    service_zone as dropoff_service_zone,
    is_airport as is_dropoff_airport,
    is_manhattan_core as is_dropoff_manhattan_core,
    market_segment as dropoff_market_segment
from {{ ref("dim_zone") }}
