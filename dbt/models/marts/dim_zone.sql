-- TLC taxi zones, plus the Unknown member (-1) for trips without a zone id.
-- dim_pickup_zone and dim_dropoff_zone are role-playing views of this table.
select
    z.location_id::integer as zone_sk,
    z.location_id,
    coalesce(z.zone_name, 'Unknown') as zone_name,
    coalesce(z.borough, 'Unknown') as borough,
    coalesce(z.service_zone, 'Unknown') as service_zone,
    z.location_id in ({{ var("airport_zone_ids") | join(", ") }}) as is_airport,
    -- Proxy for the Manhattan core: Manhattan zones served as "Yellow Zone".
    coalesce(z.borough = 'Manhattan' and z.service_zone = 'Yellow Zone', false)
        as is_manhattan_core,
    case
        when z.location_id in ({{ var("airport_zone_ids") | join(", ") }}) then 'Airport'
        when z.borough = 'Manhattan' and z.service_zone = 'Yellow Zone' then 'Manhattan core'
        when z.borough is null or z.borough = 'Unknown' then 'Unknown'
        else 'Outer boroughs and upper Manhattan'
    end as market_segment,
    z.location_id in ({{ var("unknown_zone_ids") | join(", ") }}) as is_unknown_zone
from {{ ref("stg_taxi_zones") }} as z

union all

select
    -1 as zone_sk,
    null::smallint as location_id,
    'Unknown' as zone_name,
    'Unknown' as borough,
    'Unknown' as service_zone,
    false as is_airport,
    false as is_manhattan_core,
    'Unknown' as market_segment,
    true as is_unknown_zone
