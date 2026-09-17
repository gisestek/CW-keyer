"""In-process event bus.

Every message is a JSON-serialisable dict with a "type" field (see
docs/messages.md). Modules talk only through the bus so they can later be
moved to separate processes or machines (NFR-04) by forwarding the same
messages over a socket.

Delivery is synchronous on the publisher's thread. Subscribers must be
thread-safe; the GUI subscribes through a Qt signal bridge that hops to the
GUI thread.
"""
from __future__ import annotations

import datetime as _dt
import logging
import threading
from collections import defaultdict
from typing import Callable

log = logging.getLogger(__name__)

Handler = Callable[[dict], None]


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Bus:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, pattern: str, handler: Handler) -> None:
        """pattern: exact type ("rx.text"), prefix ("rx.*") or "*"."""
        with self._lock:
            self._subs[pattern].append(handler)

    def unsubscribe(self, pattern: str, handler: Handler) -> None:
        with self._lock:
            if handler in self._subs.get(pattern, []):
                self._subs[pattern].remove(handler)

    def publish(self, type_: str, **payload) -> dict:
        msg = {"type": type_, "utc": payload.pop("utc", None) or utc_now_iso(), **payload}
        prefix = type_.split(".", 1)[0] + ".*"
        with self._lock:
            handlers = list(self._subs.get(type_, [])) + list(self._subs.get(prefix, [])) + list(self._subs.get("*", []))
        for h in handlers:
            try:
                h(msg)
            except Exception:  # a broken subscriber must never break safety paths
                log.exception("bus handler failed for %s", type_)
        return msg
