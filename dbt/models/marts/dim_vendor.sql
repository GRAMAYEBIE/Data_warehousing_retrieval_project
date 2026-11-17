-- Technology providers that report the trips. -1 is the Unknown member.
select *
from (
    values
        (1, 1, 'Creative Mobile Technologies'),
        (2, 2, 'Curb Mobility'),
        (6, 6, 'Myle Technologies'),
        (7, 7, 'Helix'),
        (-1, null, 'Unknown')
) as vendors (vendor_sk, vendor_id, vendor_name)
