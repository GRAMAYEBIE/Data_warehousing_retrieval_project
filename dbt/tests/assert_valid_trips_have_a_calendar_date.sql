-- Business assertion: every valid trip of the loaded months has a date in the calendar.
-- A trip dated outside dim_date gets the Unknown date (-1): it still passes the
-- relationships test (the Unknown member exists) but disappears from every dashboard and
-- answer, which read the published views by date. Observed: with the calendar ending in
-- January 2026, the months loaded after it lost their dates. This test makes such a gap
-- block the publication instead. Returns the source months with valid trips and no date.
select
    source_month,
    count(*) as trips_without_date
from {{ ref("fct_trip") }}
where
    quality_status = 'valid'
    and pickup_date_sk = -1
    and {{ test_scope(neighbours=false) }}  -- the month a run loads (macros/test_scope.sql)
group by source_month
