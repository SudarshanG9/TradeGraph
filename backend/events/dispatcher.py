"""Bounded in-process handoff; intentionally no durable outbox."""
import asyncio


class Dispatcher:
    def __init__(self, capacity):
        self.queue = asyncio.Queue(capacity)
        self.failure = None

    def check_capacity(self, count):
        if self.failure or count > self.queue.maxsize - self.queue.qsize():
            raise RuntimeError('Event pipeline unhealthy or full')

    def publish(self, events):
        for event in events:
            self.queue.put_nowait(event)
