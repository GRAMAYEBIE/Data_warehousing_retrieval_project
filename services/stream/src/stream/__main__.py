"""Streaming of the current month (wave 8, profile stream).

    python -m stream topics                         # create the topics (idempotent)
    python -m stream produce --month 2025-06        # replay a month into Kafka
    python -m stream consume                        # Kafka -> stream.yellow_trips

Environment: KAFKA_BOOTSTRAP (kafka:9092); PGHOST, PGDATABASE, PGUSER (streamer),
STREAMER_PASSWORD; STREAM_CACHE (where the monthly file is kept).
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from stream.contract import DEAD_LETTERS, TOPIC

log = logging.getLogger("stream")


def bootstrap() -> str:
    return os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")


def topics() -> None:
    """trips.yellow.raw: 3 partitions keyed by pickup zone, 3 days kept; the dead letters:
    one partition, 30 days."""
    from confluent_kafka.admin import AdminClient, NewTopic

    admin = AdminClient({"bootstrap.servers": bootstrap()})
    wanted = [
        NewTopic(TOPIC, num_partitions=3, replication_factor=1,
                 config={"retention.ms": str(3 * 86_400_000), "compression.type": "producer"}),
        NewTopic(DEAD_LETTERS, num_partitions=1, replication_factor=1,
                 config={"retention.ms": str(30 * 86_400_000)}),
    ]  # fmt: skip
    existing = set(admin.list_topics(timeout=30).topics)
    new = [t for t in wanted if t.topic not in existing]
    for name, future in (admin.create_topics(new) if new else {}).items():
        future.result()
        log.info("topic %s created", name)
    log.info("topics ready: %s", ", ".join(t.topic for t in wanted))


def producer():
    from confluent_kafka import Producer

    return Producer(
        {
            "bootstrap.servers": bootstrap(),
            "compression.type": "lz4",
            "linger.ms": 50,
            "batch.size": 1_000_000,
            "enable.idempotence": True,  # no duplicate on a producer retry
            "queue.buffering.max.messages": 500_000,
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stream", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("topics", help="create the topics")
    produce = commands.add_parser("produce", help="replay a month into Kafka")
    produce.add_argument("--month", required=True, help="YYYY-MM")
    produce.add_argument("--speed", type=float, default=4320.0,
                         help="simulated seconds per second (0: as fast as possible)")  # fmt: skip
    produce.add_argument("--limit", type=int, help="stop after this many trips")
    commands.add_parser("consume", help="Kafka -> stream.yellow_trips")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s"
    )

    topics()
    if args.command == "produce":
        from stream.producer import fetch, replay

        path = fetch(args.month, Path(os.environ.get("STREAM_CACHE", "/cache")))
        log.info("replaying %s at %.0fx", path.name, args.speed)
        replay(producer(), args.month, path, args.speed, args.limit)
    elif args.command == "consume":
        import psycopg
        from confluent_kafka import Consumer

        from stream.consumer import run

        consumer = Consumer(
            {
                "bootstrap.servers": bootstrap(),
                "group.id": "stream-to-postgres",
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
            }
        )
        consumer.subscribe([TOPIC])
        conn = psycopg.connect(
            host=os.environ.get("PGHOST", "postgres"),
            dbname=os.environ["PGDATABASE"],
            user=os.environ.get("PGUSER", "streamer"),
            password=os.environ["STREAMER_PASSWORD"],
            application_name="stream_consumer",
        )
        log.info("consuming %s into stream.yellow_trips", TOPIC)
        run(consumer, producer(), conn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
