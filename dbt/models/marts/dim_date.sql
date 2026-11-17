-- One row per calendar day of the analysis window, plus the Unknown member (-1)
-- used by trips whose pickup date is missing or far outside the window.
with days as (
    select generate_series(
        '{{ var("calendar_start") }}'::date, '{{ var("calendar_end") }}'::date, interval '1 day'
    )::date as date_day
),

calendar as (
    select
        to_char(d.date_day, 'YYYYMMDD')::integer as date_sk,
        d.date_day,
        extract(year from d.date_day)::smallint as year_number,
        extract(quarter from d.date_day)::smallint as quarter_number,
        extract(month from d.date_day)::smallint as month_number,
        trim(to_char(d.date_day, 'Month')) as month_name,
        date_trunc('month', d.date_day)::date as month_start,
        date_trunc('week', d.date_day)::date as week_start,
        extract(isodow from d.date_day)::smallint as day_of_week,
        trim(to_char(d.date_day, 'Day')) as day_name,
        extract(isodow from d.date_day) in (6, 7) as is_weekend,
        h.holiday_date is not null as is_holiday,
        h.holiday_name,
        case
            when h.holiday_date is not null then 'Public holiday'
            when extract(isodow from d.date_day) in (6, 7) then 'Weekend'
            else 'Weekday'
        end as day_type
    from days as d
    left join {{ ref("us_ny_holidays") }} as h on d.date_day = h.holiday_date
)

select * from calendar

union all

select
    -1 as date_sk,
    null::date as date_day,
    null::smallint as year_number,
    null::smallint as quarter_number,
    null::smallint as month_number,
    'Unknown' as month_name,
    null::date as month_start,
    null::date as week_start,
    null::smallint as day_of_week,
    'Unknown' as day_name,
    false as is_weekend,
    false as is_holiday,
    null::text as holiday_name,
    'Unknown' as day_type
