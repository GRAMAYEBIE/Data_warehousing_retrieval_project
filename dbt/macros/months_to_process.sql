{#
    Source months a monthly incremental model must (re)build.

    - var "months" given        -> exactly those months (manual backfill / re-run)
    - first build / full refresh -> every month loaded in bronze
    - incremental run            -> months whose latest loaded batch is not the one
                                    already in the model, plus their neighbours:
                                    a row can sit in the file of the month before or
                                    after its pickup month, so loading month M can
                                    change duplicate flags in M-1 and M+1.

    months_to_process_sql()  returns the query (one column source_month).
    months_to_process()      runs it and returns a list of 'YYYY-MM-DD' strings.

    Models use the list as SQL literals. With literal dates PostgreSQL prunes the
    bronze partitions at plan time and estimates date-range filters from statistics;
    with a subquery it can do neither and picks very slow plans.
#}
{% macro months_to_process_sql() %}
    {%- set months = var("months", []) -%}
    with latest_batch as (
        select distinct on (source_month)
            source_month,
            batch_id
        from {{ source("ops", "ingestion_manifest") }}
        where dataset = 'yellow' and status = 'loaded'
        order by source_month, finished_at desc
    )
    {% if months | length > 0 %}
    select source_month
    from latest_batch
    where source_month in (
        {%- for month in months %}'{{ month }}'::date{{ ", " if not loop.last }}{%- endfor -%}
    )
    order by source_month
    {% elif is_incremental() %}
    , changed as (
        select l.source_month
        from latest_batch as l
        left join (select distinct source_month, batch_id from {{ this }}) as built
            on l.source_month = built.source_month
        where built.batch_id is distinct from l.batch_id
    )
    select distinct l.source_month
    from latest_batch as l
    inner join changed as c
        on l.source_month between c.source_month - interval '1 month'
                              and c.source_month + interval '1 month'
    order by l.source_month
    {% else %}
    select source_month from latest_batch order by source_month
    {% endif %}
{% endmacro %}


{% macro months_to_process() %}
    {# At parse time nothing is executed: a sentinel month keeps the SQL valid. #}
    {%- if not execute -%}
        {{ return(["1900-01-01"]) }}
    {%- endif -%}
    {%- set result = run_query(months_to_process_sql()) -%}
    {%- set months = [] -%}
    {%- for value in result.columns[0].values() -%}
        {%- do months.append(value | string) -%}
    {%- endfor -%}
    {# Nothing to do: the sentinel matches no partition, the model inserts no row. #}
    {%- if months | length == 0 -%}
        {%- do months.append("1900-01-01") -%}
    {%- endif -%}
    {{ log("months to process for " ~ this.identifier ~ ": " ~ months | join(", "), info=true) }}
    {{ return(months) }}
{% endmacro %}


{# 'YYYY-MM-DD'::date, 'YYYY-MM-DD'::date, ... #}
{% macro date_literals(dates) -%}
    {%- for value in dates -%}
        '{{ value }}'::date{{ ", " if not loop.last }}
    {%- endfor -%}
{%- endmacro %}
