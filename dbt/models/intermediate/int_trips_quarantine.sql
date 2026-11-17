{{
    config(
        alias="trips_quarantine",
        materialized="incremental",
        incremental_strategy="delete+insert",
        unique_key="source_month",
        on_schema_change="fail",
    )
}}

-- Rows whose values cannot be cast to the silver types. They are kept here with their
-- bronze key so the raw values can be inspected; they are in no metric.
-- bronze rows = silver.trips rows + silver.trips_quarantine rows, month by month.
-- depends_on: {{ ref("int_trips_flagged") }}
{#
    This table is normally empty, so it cannot tell by itself which batches it has
    already checked. On an incremental run it follows silver.trips: it re-checks the
    months that silver.trips rebuilt during this dbt run.
#}
{%- if execute and is_incremental() and var("months", []) | length == 0 -%}
    {%- set rebuilt_sql -%}
        select distinct source_month
        from {{ ref("int_trips_flagged") }}
        where silver_loaded_at >= '{{ run_started_at }}'
        order by source_month
    {%- endset -%}
    {%- set months = [] -%}
    {%- for value in run_query(rebuilt_sql).columns[0].values() -%}
        {%- do months.append(value | string) -%}
    {%- endfor -%}
    {%- if months | length == 0 -%}
        {%- do months.append("1900-01-01") -%}
    {%- endif -%}
    {{ log("months to process for trips_quarantine: " ~ months | join(", "), info=true) }}
{%- else -%}
    {%- set months = months_to_process() -%}
{%- endif %}

select
    t.*,
    'value present in bronze but not castable to the silver type' as quarantine_reason,
    current_timestamp as silver_loaded_at
from {{ ref("stg_yellow_trips") }} as t
where
    t.source_month in ({{ date_literals(months) }})
    and t.has_cast_error
