{{
    config(
        indexes=[
            {"columns": ["source_month"]},
            {"columns": ["pickup_date_sk"]},
        ],
    )
}}

-- Data-quality aggregate: per source file month, pickup day, vendor, pickup zone and
-- payment type, the number of trips per status and the number of trips raising each
-- flag. Additive: any rate (suspicious rate, flag rate) is a ratio of sums at read time.
select
    f.source_month,
    f.pickup_date_sk,
    f.vendor_sk,
    f.pickup_zone_sk,
    f.payment_type_sk,

    count(*) as trip_count,
    count(*) filter (where f.quality_status = 'valid') as valid_trip_count,
    count(*) filter (where f.quality_status = 'suspicious') as suspicious_trip_count,
    count(*) filter (where f.quality_status = 'invalid') as invalid_trip_count,
    sum(f.total_amount) as sum_total_amount,
    sum(f.total_amount) filter (where f.quality_status = 'valid') as sum_total_amount_valid,

    {% for flag in quality_flag_catalog() -%}
    count(*) filter (where q.is_{{ flag.code }}) as {{ flag.code }}_trip_count{{ "," if not loop.last }}
    {% endfor -%}
from {{ ref("fct_trip") }} as f
inner join {{ ref("dim_trip_quality") }} as q on f.trip_quality_sk = q.trip_quality_sk
group by 1, 2, 3, 4, 5
