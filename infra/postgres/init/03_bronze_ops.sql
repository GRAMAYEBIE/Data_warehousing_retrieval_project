-- Bronze tables and the ingestion manifest. Owned by loader so that it can
-- create and replace monthly partitions; nobody else can write them.
SET ROLE loader;

-- One row per ingestion attempt (exam Q2.4).
CREATE TABLE ops.ingestion_manifest (
    batch_id          uuid PRIMARY KEY,
    dataset           text        NOT NULL CHECK (dataset IN ('yellow', 'taxi_zone')),
    source_month      date,                       -- first day of the month; NULL for taxi_zone
    source_url        text        NOT NULL,
    object_key        text,                       -- key in the landing bucket
    source_etag       text,
    file_size_bytes   bigint,
    sha256            text,
    schema_version    text,                       -- contract version used (v2024, v2025, ...)
    schema_hash       text,                       -- SHA-256 of sorted "name:type" of the file
    drift_report      jsonb,                      -- unknown / missing / mistyped columns
    row_count_file    bigint,
    row_count_bronze  bigint,
    status            text        NOT NULL
        CHECK (status IN ('pending', 'landed', 'loaded', 'failed', 'skipped_unchanged')),
    forced            boolean     NOT NULL DEFAULT false,
    error_message     text,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz
);
CREATE INDEX ingestion_manifest_month_idx
    ON ops.ingestion_manifest (dataset, source_month, started_at DESC);
COMMENT ON TABLE ops.ingestion_manifest IS
    'One row per ingestion attempt: status, checksums, schema hash, row counts and errors.';

-- Source-aligned Yellow Taxi rows. Column names are the source names lower-cased.
-- Types are wide enough to hold every value the Parquet file can carry, so raw
-- values stay recoverable; business typing happens in dbt staging.
CREATE TABLE bronze.yellow_trips_raw (
    -- technical identifier: position of the row in its source file (deterministic on re-run)
    source_month           date             NOT NULL,
    file_row_number        bigint           NOT NULL,
    -- source columns
    vendorid               numeric,
    tpep_pickup_datetime   timestamp,       -- New York local time, no time zone (as published)
    tpep_dropoff_datetime  timestamp,
    passenger_count        numeric,
    trip_distance          double precision,
    ratecodeid             numeric,
    store_and_fwd_flag     text,
    pulocationid           numeric,
    dolocationid           numeric,
    payment_type           numeric,
    fare_amount            double precision,
    extra                  double precision,
    mta_tax                double precision,
    tip_amount             double precision,
    tolls_amount           double precision,
    improvement_surcharge  double precision,
    total_amount           double precision,
    congestion_surcharge   double precision,
    airport_fee            double precision,
    cbd_congestion_fee     double precision, -- absent before 2025-01 (contract v2024) => NULL
    -- columns present in the file but unknown to the contract (schema drift)
    extra_columns          jsonb,
    -- ingestion metadata
    batch_id               uuid             NOT NULL,
    source_file            text             NOT NULL,
    schema_hash            text             NOT NULL,
    ingested_at            timestamptz      NOT NULL,
    PRIMARY KEY (source_month, file_row_number)
) PARTITION BY LIST (source_month);
COMMENT ON TABLE bronze.yellow_trips_raw IS
    'Immutable Yellow Taxi rows as published by TLC, one partition per source file month. Never updated: a re-run replaces the whole partition.';

CREATE TABLE bronze.taxi_zone_raw (
    locationid    text,
    borough       text,
    zone          text,
    service_zone  text,
    batch_id      uuid        NOT NULL,
    source_file   text        NOT NULL,
    ingested_at   timestamptz NOT NULL
);
COMMENT ON TABLE bronze.taxi_zone_raw IS 'TLC taxi zone lookup, loaded as text, fully replaced on each run.';

RESET ROLE;
