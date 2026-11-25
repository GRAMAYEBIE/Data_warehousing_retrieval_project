-- Business assertion: a trip with status 'valid' is usable in approved metrics.
-- It has a non-negative total, a pickup before its dropoff, a duration and a distance
-- inside the agreed thresholds, known zones, and it is not a duplicate.
-- Returns the valid rows that break one of these guarantees. In a monthly run, only the
-- months that run changed are read (macros/test_scope.sql).
select
    source_month,
    file_row_number,
    quality_flags
from {{ ref("int_trips_flagged") }}
where
    quality_status = 'valid'
    and {{ test_scope() }}  -- the loaded month and its neighbours in a monthly run
    and (
        total_amount < 0
        or pickup_ts >= dropoff_ts
        or duration_min < {{ var("min_duration_minutes") }}
        or duration_min > {{ var("max_duration_minutes") }}
        or trip_distance > {{ var("max_distance_miles") }}
        or speed_mph > {{ var("max_speed_mph") }}
        or pickup_location_id is null
        or dropoff_location_id is null
        or is_duplicate
    )
