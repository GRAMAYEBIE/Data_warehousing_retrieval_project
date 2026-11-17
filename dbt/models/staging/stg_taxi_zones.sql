-- Typed taxi zone lookup. "N/A" and empty values become NULL.
select
    locationid::smallint as location_id,
    nullif(nullif(trim(borough), ''), 'N/A') as borough,
    nullif(nullif(trim(zone), ''), 'N/A') as zone_name,
    nullif(nullif(trim(service_zone), ''), 'N/A') as service_zone,
    batch_id,
    ingested_at
from {{ source("bronze", "taxi_zone_raw") }}
