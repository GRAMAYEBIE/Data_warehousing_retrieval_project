-- The data-quality flag catalogue as a table, generated from macros/quality_flags.sql.
-- Read by the trip-quality dimension, the data dictionary and Dashboard 5. Stored in gold
-- (reference data for decisions) so the publication step can expose it to end users.
{{ config(schema="gold") }}
{% for flag in quality_flag_catalog() %}
select
    {{ loop.index }} as flag_order,
    '{{ flag.code }}' as flag_code,
    'is_{{ flag.code }}' as flag_column,
    '{{ flag.severity }}' as severity,
    '{{ flag.description | replace("'", "''") }}' as description,
    '{{ flag.rule | replace("'", "''") }}' as rule_summary,
    '{{ flag.exam_requirement }}' as exam_requirement
{{ "union all" if not loop.last }}
{% endfor %}
