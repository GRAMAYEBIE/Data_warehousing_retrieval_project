{#
    Service period key of a trip from its pickup timestamp (see dim_service_period).
    Late night wins over the peaks; peaks apply Monday to Friday only.
#}
{% macro service_period_sk(pickup_ts) -%}
    case
        when {{ pickup_ts }} is null then -1
        when extract(hour from {{ pickup_ts }}) < 5 then 3
        when extract(isodow from {{ pickup_ts }}) <= 5
            and extract(hour from {{ pickup_ts }}) between 7 and 9 then 1
        when extract(isodow from {{ pickup_ts }}) <= 5
            and extract(hour from {{ pickup_ts }}) between 16 and 19 then 2
        else 4
    end
{%- endmacro %}
