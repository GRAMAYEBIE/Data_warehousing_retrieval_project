-- Business assertion: no row is lost between bronze and silver.
-- For every loaded month: bronze rows = silver.trips rows + silver.trips_quarantine rows.
-- Returns the months where this does not hold.
with bronze as (
    select
        source_month,
        row_count_bronze as bronze_rows
    from (
        select distinct on (source_month)
            source_month,
            row_count_bronze
        from {{ source("ops", "ingestion_manifest") }}
        where dataset = 'yellow' and status = 'loaded'
        order by source_month, finished_at desc
    ) as latest
),

silver as (
    select source_month, count(*) as silver_rows
    from {{ ref("int_trips_flagged") }}
    group by source_month
),

quarantine as (
    select source_month, count(*) as quarantine_rows
    from {{ ref("int_trips_quarantine") }}
    group by source_month
)

select
    b.source_month,
    b.bronze_rows,
    coalesce(s.silver_rows, 0) as silver_rows,
    coalesce(q.quarantine_rows, 0) as quarantine_rows
from bronze as b
left join silver as s on b.source_month = s.source_month
left join quarantine as q on b.source_month = q.source_month
where b.bronze_rows <> coalesce(s.silver_rows, 0) + coalesce(q.quarantine_rows, 0)
