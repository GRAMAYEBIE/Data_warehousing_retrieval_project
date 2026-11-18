-- Junk dimension: one row per combination of quality flags observed in silver.
-- The key is the hash of the flag list, so it is stable from one build to the next.
--
-- Built from the single quality_flags column (the array holds exactly the raised flags)
-- instead of a DISTINCT over fourteen boolean columns: grouping 10 million rows on one
-- column is far cheaper (the first version took more than two hours on the dev host).
with combinations as (
    select
        quality_flags,
        max(quality_status) as quality_status
    from {{ ref("int_trips_flagged") }}
    group by quality_flags
)

select
    md5(array_to_string(quality_flags, ',')) as trip_quality_sk,
    quality_status,
    array_to_string(quality_flags, ', ') as quality_flags_label,
    cardinality(quality_flags) as flag_count,
    {% for flag in quality_flag_catalog() -%}
    '{{ flag.code }}' = any(quality_flags) as is_{{ flag.code }}{{ "," if not loop.last }}
    {% endfor -%}
from combinations
