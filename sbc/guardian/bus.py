"""Pub-sub internal sederhana di atas asyncio.

- `on(topic, handler)`: handler sync atau async dipanggil di event loop setiap publish.
- `subscribe(topic)`: asyncio.Queue untuk konsumen (mis. WebSocket). Antrean penuh -> pesan tertua dibuang.
- `publish_threadsafe`: dipanggil dari thread lain (stream, detector, MQTT, GPS, tombol).
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger(__name__)


class Bus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[Any], Any]]] = defaultdict(list)
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._tagged: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def on(self, topic: str, handler: Callable[[Any], Any]) -> None:
        self._handlers[topic].append(handler)

    def subscribe(self, topic: str, maxsize: int = 200) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._queues[topic].append(q)
        return q

    def unsubscribe(self, topic: str, q: asyncio.Queue) -> None:
        if q in self._queues[topic]:
            self._queues[topic].remove(q)

    def subscribe_tagged(self, topics: list[str], maxsize: int = 200) -> asyncio.Queue:
        """Satu antrean untuk beberapa topik; item berupa (topic, msg)."""
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        for t in topics:
            self._tagged[t].append(q)
        return q

    def unsubscribe_tagged(self, q: asyncio.Queue) -> None:
        for lst in self._tagged.values():
            if q in lst:
                lst.remove(q)

    def publish(self, topic: str, msg: Any = None) -> None:
        """Harus dipanggil dari thread event loop."""
        for h in list(self._handlers[topic]):
            try:
                res = h(msg)
                if asyncio.iscoroutine(res):
                    task = asyncio.ensure_future(res)
                    task.add_done_callback(_log_task_error)
            except Exception:
                log.exception("handler bus gagal untuk topik %s", topic)
        for q in list(self._queues[topic]):
            _put_drop_oldest(q, msg)
        for q in list(self._tagged[topic]):
            _put_drop_oldest(q, (topic, msg))

    def publish_threadsafe(self, topic: str, msg: Any = None) -> None:
        if self.loop is None or self.loop.is_closed():
            return
        self.loop.call_soon_threadsafe(self.publish, topic, msg)


def _put_drop_oldest(q: asyncio.Queue, item: Any) -> None:
    if q.full():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    q.put_nowait(item)


def _log_task_error(task: asyncio.Future) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("task handler gagal: %r", exc, exc_info=exc)
