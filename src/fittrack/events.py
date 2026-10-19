"""Thread-to-async SSE bridge, adapted from BrushGraft's MIT event bus."""

import asyncio
import threading


class EventBus:
    def __init__(self):
        self.loop = None
        self.closed = False
        self.lock = threading.RLock()
        self.subscribers: dict[str, set[asyncio.Queue]] = {}

    def bind(self, loop):
        self.loop = loop
        self.closed = False

    def subscribe(self, uid):
        queue = asyncio.Queue(maxsize=128)
        with self.lock:
            self.subscribers.setdefault(uid, set()).add(queue)
        return queue

    def unsubscribe(self, uid, queue):
        with self.lock:
            self.subscribers.get(uid, set()).discard(queue)

    def publish(self, uid, event):
        if self.loop is None or self.loop.is_closed():
            return
        with self.lock:
            queues = list(self.subscribers.get(uid, set()))

        def deliver():
            for queue in queues:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(event)

        try:
            self.loop.call_soon_threadsafe(deliver)
        except RuntimeError:
            # Shutdown can close the loop between the check and this call.
            pass

    def close(self):
        self.closed = True
        with self.lock:
            users = list(self.subscribers)
        for uid in users:
            self.publish(uid, None)
