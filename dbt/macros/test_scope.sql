{#
    Tests of the trip tables read the months a run changed, not the whole history.

    The trip tables (bronze, silver, fact) hold every loaded month: tens of millions of
    rows. Loading source month M rebuilds M and, through the cross-month duplicate flags,
    re-evaluates M-1 and M+1 in silver (months_to_process). Testing the other months again
    proves nothing new: a first version that did took more than an hour and a half for
    fct_trip alone. The month comes from the variable test_month:

    - "YYYY-MM" (set by the Airflow DAG to the month it loads): that month, also when it
      is an older month loaded again (a correction or a backfill);
    - "" (default, e.g. a manual `dbt build`): the latest month loaded (ingestion manifest);
    - "all": every month (`dbt test --vars '{test_month: all}'`).

    Scope per table: fct_trip, the month itself (its keys depend on the month only;
    uniqueness across months holds by construction, the key starts with the month);
    bronze and silver trips, the month and its neighbours. The bound matches the leading
    column of their indexes and partitions, so a test reads one to three months.

    get_where_subquery is dbt's hook for the "where" of generic tests (the built-in
    behaviour plus the scope); test_scope() is used by the singular tests.
#}

{% macro scoped_month() -%}
    {%- set month = var("test_month", "") -%}
    {%- if month -%}
        '{{ month }}-01'::date
    {%- else -%}
        (select max(source_month) from ops.ingestion_manifest
         where dataset = 'yellow' and status = 'loaded')
    {%- endif -%}
{%- endmacro %}


{% macro test_scope(column="source_month", neighbours=true) -%}
    {%- if var("test_month", "") == "all" -%}
        true
    {%- elif neighbours -%}
        {{ column }} between {{ scoped_month() }} - interval '1 month'
                        and {{ scoped_month() }} + interval '1 month'
    {%- else -%}
        {{ column }} = {{ scoped_month() }}
    {%- endif -%}
{%- endmacro %}


{% macro get_where_subquery(relation) -%}
    {%- set where = config.get("where") -%}
    {%- set name = relation.identifier -%}
    {%- if name == "fct_trip" -%}
        {%- set scope = test_scope(neighbours=false) -%}
    {%- elif name in ["yellow_trips_raw", "int_trips_flagged", "int_trips_quarantine"] -%}
        {%- set scope = test_scope() -%}
    {%- else -%}
        {%- set scope = "" -%}
    {%- endif -%}
    {%- if scope and scope != "true" -%}
        {%- set where = "(" ~ where ~ ") and " ~ scope if where else scope -%}
    {%- endif -%}
    {%- if where -%}
        {%- set filtered -%}
            (select * from {{ relation }} where {{ where }}) dbt_subquery
        {%- endset -%}
        {%- do return(filtered) -%}
    {%- else -%}
        {%- do return(relation) -%}
    {%- endif -%}
{%- endmacro %}
