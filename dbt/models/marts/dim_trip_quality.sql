-- Junk dimension: one row per combination of quality flags observed in silver.
-- The key is the hash of the flag list, so it is stable from one build to the next.
select
    md5(array_to_string(quality_flags, ',')) as trip_quality_sk,
    quality_status,
    array_to_string(quality_flags, ', ') as quality_flags_label,
    cardinality(quality_flags) as flag_count,
    {% for flag in quality_flag_catalog() -%}
    is_{{ flag.code }}{{ "," if not loop.last }}
    {% endfor -%}
from (
    select distinct
        quality_status,
        quality_flags,
        {% for flag in quality_flag_catalog() -%}
        is_{{ flag.code }}{{ "," if not loop.last }}
        {% endfor -%}
    from {{ ref("int_trips_flagged") }}
) as combinations
