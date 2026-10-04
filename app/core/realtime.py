"""A tiny in-process fan-out for live outage updates.

Sync route code publishes. The WebSocket task, which runs on the asyncio loop,
receives. Those are different threads, so we hop with call_soon_threadsafe.
"""

import asyncio


class RealtimeHub:
    def __init__(self) -> None:
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []

    def register(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
        self._subscribers.append((loop, queue))

    def unregister(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
        self._subscribers = [item for item in self._subscribers if item != (loop, queue)]

    def publish(self, message: dict) -> None:
        for loop, queue in list(self._subscribers):
            try:
                loop.call_soon_threadsafe(queue.put_nowait, message)
            except RuntimeError:
                continue


hub = RealtimeHub()
