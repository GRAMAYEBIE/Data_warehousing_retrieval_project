{#
    Casts that return NULL instead of failing. A value that is present in bronze but
    cannot be cast makes the row "unparsable": it goes to quarantine, not to silver.
#}

{# Whole number between 0 and 32767 -> smallint. #}
{% macro safe_smallint(column) -%}
    case
        when {{ column }} between 0 and 32767 and {{ column }} = trunc({{ column }})
            then {{ column }}::smallint
    end
{%- endmacro %}


{# Finite number that fits numeric(12, 2). #}
{% macro safe_amount(column) -%}
    case
        when abs({{ column }}) < 9999999999 then round({{ column }}::numeric, 2)::numeric(12, 2)
    end
{%- endmacro %}


{# True when at least one of the columns holds a value that its safe cast rejects. #}
{% macro has_cast_error(smallint_columns, amount_columns) -%}
    (
        {%- for column in smallint_columns %}
        ({{ column }} is not null and ({{ safe_smallint(column) }}) is null) or
        {%- endfor %}
        {%- for column in amount_columns %}
        ({{ column }} is not null and ({{ safe_amount(column) }}) is null){{ " or" if not loop.last }}
        {%- endfor %}
    )
{%- endmacro %}


{# Division that returns NULL when the denominator is zero or NULL. #}
{% macro safe_divide(numerator, denominator) -%}
    ({{ numerator }}) / nullif({{ denominator }}, 0)
{%- endmacro %}
