-- Service periods used for capacity analysis. The rule that assigns a trip to a
-- period is in macros/service_period.sql.
select *
from (
    values
        (1, 'AM peak', 'Monday to Friday, 07:00 to 09:59', true),
        (2, 'PM peak', 'Monday to Friday, 16:00 to 19:59', true),
        (3, 'Late night', 'Every day, 00:00 to 04:59', false),
        (4, 'Off-peak', 'Any other time', false),
        (-1, 'Unknown', 'Pickup time missing', false)
) as periods (service_period_sk, service_period_name, service_period_rule, is_peak)
