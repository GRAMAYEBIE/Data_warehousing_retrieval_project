-- One row per minute of the day (1,440 rows) plus the Unknown member (-1).
with minutes as (
    select generate_series(0, 1439) as minute_of_day
)

select
    (minute_of_day / 60) * 100 + minute_of_day % 60 as time_sk,
    make_time(minute_of_day / 60, minute_of_day % 60, 0) as time_of_day,
    (minute_of_day / 60)::smallint as hour_of_day,
    (minute_of_day % 60)::smallint as minute_of_hour,
    to_char(make_time(minute_of_day / 60, 0, 0), 'HH24:MI') as hour_label,
    case
        when minute_of_day / 60 < 5 then 'Late night (00-05)'
        when minute_of_day / 60 < 10 then 'Morning (05-10)'
        when minute_of_day / 60 < 16 then 'Midday (10-16)'
        when minute_of_day / 60 < 20 then 'Evening (16-20)'
        else 'Night (20-24)'
    end as day_part
from minutes

union all

select
    -1 as time_sk,
    null::time as time_of_day,
    null::smallint as hour_of_day,
    null::smallint as minute_of_hour,
    'Unknown' as hour_label,
    'Unknown' as day_part
