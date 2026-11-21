import asyncio
import json
import logging
from typing import AsyncGenerator, Dict, Any, Set

logger = logging.getLogger("jobpilot.events")


class EventBroadcaster:
    def __init__(self):
        self._subscribers: Set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        logger.debug("New SSE client subscribed. Total clients: %d", len(self._subscribers))
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._subscribers:
            self._subscribers.remove(q)
            logger.debug("SSE client unsubscribed. Total clients: %d", len(self._subscribers))

    async def broadcast(self, event_type: str, data: Dict[str, Any]):
        """Broadcasts an event to all connected SSE clients."""
        payload = {
            "type": event_type,
            "data": data
        }
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("Subscriber queue full; dropping message")
            except Exception as e:
                logger.error("Error broadcasting to subscriber: %s", e)

    def broadcast_sync(self, event_type: str, data: Dict[str, Any]):
        """Synchronous wrapper to broadcast from background threads."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self.broadcast(event_type, data), loop)
            else:
                loop.run_until_complete(self.broadcast(event_type, data))
        except Exception:
            # If no running event loop in thread, silent or log
            pass

    async def event_generator(self, q: asyncio.Queue) -> AsyncGenerator[str, None]:
        """Yields SSE formatted strings for FastAPI StreamingResponse."""
        try:
            while True:
                try:
                    # Wait for message with 15s timeout for keep-alive ping
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    evt_type = msg.get("type", "message")
                    data_str = json.dumps(msg.get("data", {}))
                    yield f"event: {evt_type}\ndata: {data_str}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat comment
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            self.unsubscribe(q)


event_broadcaster = EventBroadcaster()

