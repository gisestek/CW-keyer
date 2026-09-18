"""Tracks when this station is transmitting, so RX text can be classified.

While we transmit, the receiver usually hears our own sidetone and DeepCW
decodes it. Those words are published as `rx.text` with `own_tx: true`
and shown as a reference line under the TX line (UC13) instead of being
mixed with the other station's text.
"""
from __future__ import annotations

import threading
import time

from .bus import Bus

START_MARGIN_S = 0.3   # keyer events arrive over WiFi slightly after the sidetone starts
END_MARGIN_S = 0.3     # decoded character end times are accurate to about ±0.1 s
KEEP_S = 600


class TxWindows:
    def __init__(self, bus: Bus, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: list[list[float | None]] = []  # [start, end|None]
        bus.subscribe("tx.state", self._on_state)
        bus.subscribe("tx.echo", self._on_echo)
        bus.subscribe("tx.stopped", self._on_end)
        bus.subscribe("keyer.status", self._on_keyer)

    def _open(self, t: float) -> None:
        if not self._windows or self._windows[-1][1] is not None:
            self._windows.append([t, None])
            cutoff = t - KEEP_S
            self._windows = [w for w in self._windows if w[1] is None or w[1] > cutoff]

    def _close(self, t: float) -> None:
        if self._windows and self._windows[-1][1] is None:
            self._windows[-1][1] = t

    def _on_state(self, m: dict) -> None:
        with self._lock:
            (self._open if m.get("busy") else self._close)(self._clock())

    def _on_echo(self, m: dict) -> None:
        with self._lock:
            self._open(self._clock())

    def _on_end(self, m: dict) -> None:
        with self._lock:
            self._close(self._clock())

    def _on_keyer(self, m: dict) -> None:
        if m.get("state") != "connected":
            with self._lock:
                self._close(self._clock())

    # -- queries --
    def is_own(self, t: float) -> bool:
        """True if an RX event at time t (use the word end time) belongs to our own transmission."""
        with self._lock:
            now = self._clock()
            for s, e in reversed(self._windows):
                if s - START_MARGIN_S <= t <= (now if e is None else e) + END_MARGIN_S:
                    return True
        return False

    def windows(self, since: float) -> list[tuple[float, float | None]]:
        with self._lock:
            return [(s, e) for s, e in self._windows if e is None or e >= since]

    def transmitting(self) -> bool:
        with self._lock:
            return bool(self._windows) and self._windows[-1][1] is None
