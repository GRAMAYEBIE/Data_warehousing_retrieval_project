-- TLC payment types. Tips are recorded for card payments only, so tip metrics
-- use is_tip_recorded. -1 is the Unknown member (code missing or not in this list).
select *
from (
    values
        (0, 0, 'Flex Fare / not reported', false),
        (1, 1, 'Credit card', true),
        (2, 2, 'Cash', false),
        (3, 3, 'No charge', false),
        (4, 4, 'Dispute', false),
        (5, 5, 'Unknown', false),
        (6, 6, 'Voided trip', false),
        (-1, null, 'Unknown', false)
) as payment_types (payment_type_sk, payment_type_id, payment_type_name, is_tip_recorded)
