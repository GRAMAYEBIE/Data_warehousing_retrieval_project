-- Business assertion: no row is lost between bronze and silver.
-- For every loaded month: bronze rows = silver.trips rows + silver.trips_quarantine rows.
-- Returns the months where this does not hold.
--
-- It reads gold.recon_bronze_silver, built from the manifest, bronze, silver and the
-- quarantine. Depending on that single model makes the orchestrator run this test after
-- silver is built: when it read the sources directly, Cosmos attached it to the manifest
-- source and ran it before silver contained the new month.
select
    source_month,
    bronze_rows,
    silver_rows,
    quarantine_rows,
    unexplained_rows
from {{ ref("recon_bronze_silver") }}
where unexplained_rows <> 0 or bronze_rows is null
