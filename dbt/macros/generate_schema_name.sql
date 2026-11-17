{#
    Use the configured schema name as it is (silver, gold) instead of dbt's default
    "<target schema>_<custom schema>". The warehouse schemas are created and granted
    by infra/postgres/init, dbt must write exactly there.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
