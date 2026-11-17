{{ config(materialized="view") }}

-- Role-playing view of dim_zone for the pickup location.
select
    zone_sk as pickup_zone_sk,
    location_id as pickup_location_id,
    zone_name as pickup_zone,
    borough as pickup_borough,
    service_zone as pickup_service_zone,
    is_airport as is_pickup_airport,
    is_manhattan_core as is_pickup_manhattan_core,
    market_segment as pickup_market_segment
from {{ ref("dim_zone") }}
