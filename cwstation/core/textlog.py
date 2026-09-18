"""Time-stamped RX/TX text log (FR-CORE-02).

One file per UTC day: <folder>/cw-YYYY-MM-DD.txt
Line format:  2026-09-17T12:34:56Z<TAB>RX<TAB>CQ CQ DE OH2BH K

Directions: RX (other stations), TX (what the keyer sent), REF (our own
sidetone as decoded by the receiver, written right after its TX line).

A new line starts when the direction changes or when the same direction has
been silent longer than `line_pause_s`. Lines are written when they close,
and flushed on shutdown so nothing is lost when the window closes.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from pathlib import Path

from .bus import Bus

IDLE_CLOSE_S = 8.0


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TextLog:
    def __init__(self, bus: Bus, folder: Path, line_pause_s: float = 3.0, clock=time.time):
        self.folder = folder
        self.line_pause_s = line_pause_s
        self._clock = clock
        self._lock = threading.Lock()
        self._dir: str | None = None
        self._start = 0.0
        self._last = 0.0
        self._text = ""
        self._ref_text = ""
        self._ref_start = 0.0
        self._arrival = 0.0
        bus.subscribe("rx.text", self._on_rx)
        bus.subscribe("tx.echo", self._on_echo)
        bus.subscribe("tx.stopped", self._on_tx_stopped)

    # -- events --
    def _on_rx(self, msg: dict) -> None:
        text = msg.get("text", "").strip()
        if text and msg.get("own_tx"):
            with self._lock:
                t0 = msg.get("t_start") or self._clock()
                if self._dir == "TX":
                    if not self._ref_text:
                        self._ref_start = t0
                    self._ref_text = (self._ref_text + " " + text).strip()
                else:  # TX line already closed: decoded sidetone arrived late
                    self._write(t0, "REF", text)
            return
        if text:
            t0 = msg.get("t_start") or self._clock()
            t1 = msg.get("t_end") or t0
            with self._lock:
                late = self._dir == "TX" and t1 <= self._start + 0.5
                if late:  # decoded after our TX started but heard before it: don't split the TX line
                    self._write(t0, "RX", text)
                    return
            self._append("RX", text, t0, sep=" ", t_end=t1)

    def _on_echo(self, msg: dict) -> None:
        ch = msg.get("ch", "")  # "<" and ">" kept: prosigns are logged as <SK>
        self._append("TX", ch, self._clock(), sep="")

    def _on_tx_stopped(self, msg: dict) -> None:
        with self._lock:
            if self._dir == "TX" and self._text:
                self._text += " [STOP]"
                self._close_line()

    def _append(self, direction: str, text: str, t: float, sep: str, t_end: float | None = None) -> None:
        with self._lock:
            if self._dir is not None and (direction != self._dir or t - self._last > self.line_pause_s):
                self._close_line()
            if self._dir is None:
                self._dir, self._start, self._text, self._last = direction, t, "", t
                text = text.lstrip()
            if text:
                self._text = (self._text + sep + text) if (self._text and sep) else self._text + text
            self._last = max(self._last, t_end if t_end is not None else t)
            self._arrival = self._clock()

    def tick(self) -> None:
        """Close an idle line (call about once per second)."""
        with self._lock:
            # Decoded text arrives 1–6 s after it was heard, so an open line is only
            # closed after nothing has been added for a while; line breaks inside the
            # conversation are decided in _append from the audio time stamps.
            limit = max(self.line_pause_s, IDLE_CLOSE_S)
            if self._dir is not None and self._clock() - max(self._last, self._arrival) > limit:
                self._close_line()

    def flush(self) -> None:
        with self._lock:
            if self._dir is not None:
                self._close_line()

    def _close_line(self) -> None:
        text = " ".join(self._text.split())
        if text:
            self._write(self._start, self._dir, text)
        if self._dir == "TX" and self._ref_text:
            self._write(self._ref_start, "REF", self._ref_text)
        self._dir, self._text, self._ref_text = None, "", ""

    def _write(self, t: float, direction: str, text: str) -> None:
        path = self.folder / f"cw-{dt.datetime.fromtimestamp(t, dt.timezone.utc):%Y-%m-%d}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{_iso(t)}\t{direction}\t{text}\n")

    def current_path(self) -> Path:
        return self.folder / f"cw-{dt.datetime.now(dt.timezone.utc):%Y-%m-%d}.txt"
