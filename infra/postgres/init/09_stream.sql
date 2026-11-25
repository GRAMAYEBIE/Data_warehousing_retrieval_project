-- Streaming (wave 8, Compose profile stream): the provisional trips of the current month,
-- received through Kafka before the official monthly file. Passwords come from the
-- container environment. Idempotent: it runs on the first start of a new volume and can be
-- applied by hand to an existing warehouse (README, "Streaming").
--
-- Provisional rows live in their own schema: they never enter silver, fct_trip or a
-- governed measure. Once the official file of the month is published, the readers ignore
-- them (the published month wins) and they can be purged.
\getenv streamer_pw STREAMER_PASSWORD
\getenv warehouse_db POSTGRES_DB

SELECT format('CREATE ROLE streamer LOGIN PASSWORD %L', :'streamer_pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'streamer') \gexec

CREATE SCHEMA IF NOT EXISTS stream;
COMMENT ON SCHEMA stream IS 'Provisional trips received through Kafka before the official '
    'monthly file. Never governed: excluded from silver, gold, analytics and the metrics.';

-- One row per trip event, keyed like bronze (source month, row of the file): a replayed or
-- redelivered message is ignored (at-least-once delivery, exactly-once rows).
CREATE TABLE IF NOT EXISTS stream.yellow_trips (
    source_month     date             NOT NULL,
    file_row_number  bigint           NOT NULL,
    vendor_id        smallint,
    pickup_ts        timestamp        NOT NULL,
    dropoff_ts       timestamp        NOT NULL,
    pu_location_id   smallint         NOT NULL,
    do_location_id   smallint         NOT NULL,
    passenger_count  smallint,
    trip_distance    double precision NOT NULL,
    payment_type     smallint,
    fare_amount      double precision,
    tip_amount       double precision,
    total_amount     double precision NOT NULL,
    kafka_partition  integer          NOT NULL,
    kafka_offset     bigint           NOT NULL,
    received_at      timestamptz      NOT NULL DEFAULT now(),
    is_provisional   boolean          NOT NULL DEFAULT true,
    PRIMARY KEY (source_month, file_row_number)
);
CREATE INDEX IF NOT EXISTS yellow_trips_pickup_idx ON stream.yellow_trips (pickup_ts);

-- Messages that break the contract (also sent to the dead-letter topic), with the reason.
CREATE TABLE IF NOT EXISTS stream.yellow_trips_rejects (
    received_at      timestamptz NOT NULL DEFAULT now(),
    source_month     date,
    kafka_partition  integer     NOT NULL,
    kafka_offset     bigint      NOT NULL,
    reason           text        NOT NULL,
    message          text        NOT NULL,
    PRIMARY KEY (kafka_partition, kafka_offset)
);

GRANT CONNECT ON DATABASE :"warehouse_db" TO streamer;
GRANT USAGE ON SCHEMA stream TO streamer;
GRANT SELECT, INSERT ON stream.yellow_trips, stream.yellow_trips_rejects TO streamer;

-- The interface reads the stream next to the forecast (live view of the month).
GRANT USAGE ON SCHEMA stream TO ai_reader, superset_reader;
GRANT SELECT ON stream.yellow_trips, stream.yellow_trips_rejects TO ai_reader, superset_reader;
