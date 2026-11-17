{#
    Single source of truth for the data-quality flags.

    Each flag has a boolean column is_<code> in silver.trips. The severity decides the
    quality status of a trip: invalid > suspicious > valid. Flags with severity "info"
    describe the row and never change its status.

    To add a flag: add an entry here and its boolean expression in int_trips_flagged.
    The status, the flag array, the catalogue table and the tests follow automatically.
#}
{% macro quality_flag_catalog() %}
    {{ return([
        {
            "code": "negative_amount", "severity": "invalid",
            "description": "At least one monetary amount is negative (typically a reversal or a dispute).",
            "rule": "least(fare, extra, mta_tax, tip, tolls, surcharges, fees, total) < 0",
            "exam_requirement": "negative values",
        },
        {
            "code": "pickup_after_dropoff", "severity": "invalid",
            "description": "The pickup time is after the dropoff time.",
            "rule": "pickup_ts > dropoff_ts",
            "exam_requirement": "pickup-after-dropoff",
        },
        {
            "code": "duplicate", "severity": "invalid",
            "description": "Same vendor, times, zones, distance and total as another row; the first row of the file of the pickup month is kept.",
            "rule": "natural key already seen in the same file, or in the file of the pickup month",
            "exam_requirement": "duplicate detection",
        },
        {
            "code": "out_of_period", "severity": "invalid",
            "description": "The pickup date is far from the month of the source file (other year, future date).",
            "rule": "pickup_ts outside [source_month - tolerance, source_month + 1 month + tolerance)",
            "exam_requirement": "implausible dates",
        },
        {
            "code": "implausible_speed", "severity": "suspicious",
            "description": "The average speed implied by distance and duration is not plausible.",
            "rule": "trip_distance / duration_hours > max_speed_mph",
            "exam_requirement": "implausible speed",
        },
        {
            "code": "implausible_distance", "severity": "suspicious",
            "description": "The trip distance is not plausible for a taxi trip.",
            "rule": "trip_distance > max_distance_miles",
            "exam_requirement": "implausible distance",
        },
        {
            "code": "unrealistic_duration", "severity": "suspicious",
            "description": "The trip is shorter or longer than a realistic taxi trip.",
            "rule": "duration_min < min_duration_minutes or duration_min > max_duration_minutes",
            "exam_requirement": "unrealistic duration",
        },
        {
            "code": "zero_distance", "severity": "suspicious",
            "description": "No distance recorded although an amount was charged.",
            "rule": "trip_distance = 0 and total_amount > 0",
            "exam_requirement": "zero distance",
        },
        {
            "code": "null_zone", "severity": "suspicious",
            "description": "The pickup or dropoff zone is missing or is one of the Unknown / N/A zones.",
            "rule": "zone id is null or in unknown_zone_ids",
            "exam_requirement": "null zone IDs",
        },
        {
            "code": "unknown_payment", "severity": "suspicious",
            "description": "The payment type is present but is not a known TLC code.",
            "rule": "payment_type_id not in known_payment_types",
            "exam_requirement": "unknown payment codes",
        },
        {
            "code": "unknown_ratecode", "severity": "suspicious",
            "description": "The rate code is present but is not a known TLC code (99 included).",
            "rule": "rate_code_id not in known_rate_codes",
            "exam_requirement": "unknown rate codes",
        },
        {
            "code": "cross_month", "severity": "info",
            "description": "The pickup is a few days outside the month of the file (late or early row); the trip is counted on its real pickup date.",
            "rule": "pickup month <> source month, within cross_month_tolerance_days",
            "exam_requirement": "late data",
        },
        {
            "code": "not_reported", "severity": "info",
            "description": "The vendor did not report the rate code or the passenger count (payment type 0).",
            "rule": "rate_code_id is null or passenger_count is null",
            "exam_requirement": "missing coded fields",
        },
        {
            "code": "component_mismatch", "severity": "info",
            "description": "total_amount differs from the sum of the fare components. Vendors do not fill the components the same way, so this never changes the status.",
            "rule": "abs(total_amount - sum of components) > amount_tolerance",
            "exam_requirement": "gaps between fare components",
        },
    ]) }}
{% endmacro %}


{# "is_a or is_b ..." for every flag of the given severity. #}
{% macro any_flag(severity) -%}
    {%- set columns = [] -%}
    {%- for flag in quality_flag_catalog() if flag.severity == severity -%}
        {%- do columns.append("is_" ~ flag.code) -%}
    {%- endfor -%}
    ({{ columns | join(" or ") }})
{%- endmacro %}


{# valid / suspicious / invalid, from the highest severity among the raised flags. #}
{% macro quality_status() -%}
    case
        when {{ any_flag("invalid") }} then 'invalid'
        when {{ any_flag("suspicious") }} then 'suspicious'
        else 'valid'
    end
{%- endmacro %}


{# Text array of the raised flag codes, in catalogue order. #}
{% macro quality_flag_array() -%}
    array_remove(
        array[
            {%- for flag in quality_flag_catalog() %}
            case when is_{{ flag.code }} then '{{ flag.code }}' end{{ "," if not loop.last }}
            {%- endfor %}
        ]::text[],
        null
    )
{%- endmacro %}
