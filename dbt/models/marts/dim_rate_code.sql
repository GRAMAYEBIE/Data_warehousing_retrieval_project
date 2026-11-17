-- TLC rate codes. -1 is the Unknown member (code 99 or not in this list);
-- -2 is "Not reported" (the vendor sent no rate code).
select *
from (
    values
        (1, 1, 'Standard rate', false),
        (2, 2, 'JFK', true),
        (3, 3, 'Newark', true),
        (4, 4, 'Nassau or Westchester', false),
        (5, 5, 'Negotiated fare', false),
        (6, 6, 'Group ride', false),
        (-1, null, 'Unknown', false),
        (-2, null, 'Not reported', false)
) as rate_codes (rate_code_sk, rate_code_id, rate_code_name, is_airport_rate)
