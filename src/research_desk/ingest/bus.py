"""Message bus. Kafka API (Redpanda) in deployment; an in-memory queue for tests and laptops."""
import json
from collections import defaultdict, deque
from collections.abc import Iterator
from typing import Protocol

RAW_DOCS = "raw-docs"   # {cik, ticker, form, accession, filing_date, report_date, primary_doc}
PARSED = "parsed"       # one chunk dict per message


class Bus(Protocol):
    def publish(self, topic: str, key: str, value: dict) -> None: ...
    def consume(self, topic: str, group: str, idle_timeout: float = 5.0) -> Iterator[dict]: ...
    def flush(self) -> None: ...


class MemoryBus:
    def __init__(self):
        self.topics: dict[str, deque] = defaultdict(deque)

    def publish(self, topic: str, key: str, value: dict) -> None:
        # round-trip through JSON so tests catch values Kafka couldn't carry
        self.topics[topic].append(json.loads(json.dumps(value)))

    def consume(self, topic: str, group: str, idle_timeout: float = 5.0) -> Iterator[dict]:
        q = self.topics[topic]
        while q:
            yield q.popleft()

    def flush(self) -> None:
        pass


class KafkaBus:
    def __init__(self, bootstrap: str):
        from confluent_kafka import Producer

        self.bootstrap = bootstrap
        self.producer = Producer({"bootstrap.servers": bootstrap, "linger.ms": 50,
                                  "compression.type": "zstd"})

    def publish(self, topic: str, key: str, value: dict) -> None:
        self.producer.produce(topic, key=key.encode(), value=json.dumps(value).encode())
        self.producer.poll(0)

    def consume(self, topic: str, group: str, idle_timeout: float = 5.0) -> Iterator[dict]:
        """Yield messages until the topic stays empty for idle_timeout seconds.

        Offsets are committed after the caller has processed each message (at-least-once).
        """
        from confluent_kafka import Consumer

        c = Consumer({"bootstrap.servers": self.bootstrap, "group.id": group,
                      "auto.offset.reset": "earliest", "enable.auto.commit": False})
        c.subscribe([topic])
        try:
            while True:
                msg = c.poll(idle_timeout)
                if msg is None:
                    return
                if msg.error():
                    raise RuntimeError(msg.error())
                yield json.loads(msg.value())
                c.commit(msg, asynchronous=False)
        finally:
            c.close()

    def flush(self) -> None:
        self.producer.flush()


def make_bus(kind: str, bootstrap: str) -> Bus:
    return KafkaBus(bootstrap) if kind == "kafka" else MemoryBus()
