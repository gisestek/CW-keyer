"""CQ repeat (FR-TX-07): sends the CQ macro at intervals until someone answers."""
from __future__ import annotations

import threading
import time

from ..core.bus import Bus


class CqRepeater:
    def __init__(self, bus: Bus, settings):
        self.bus = bus
        self.settings = settings
        self.active = False
        self._sending = False
        self._busy = False
        self._busy_evt = threading.Event()
        self._idle_evt = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        bus.subscribe("tx.state", self._on_state)
        bus.subscribe("tx.send", self._on_send)
        bus.subscribe("tx.stop", lambda m: self.stop("stop"))
        bus.subscribe("rx.text", self._on_rx)

    # -- events --
    def _on_state(self, m: dict) -> None:
        self._busy = bool(m.get("busy"))
        (self._busy_evt if self._busy else self._idle_evt).set()

    def _on_send(self, m: dict) -> None:
        if self.active and not self._sending:
            self.stop("manual")          # the operator typed something: stop calling CQ

    def _on_rx(self, m: dict) -> None:
        if self.active and not m.get("own_tx") and m.get("text", "").strip():
            self.stop("answer")          # somebody is answering

    # -- control --
    def toggle(self) -> bool:
        self.stop("toggle") if self.active else self.start()
        return self.active

    def start(self) -> None:
        if self.active:
            return
        self.active = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="cq", daemon=True)
        self._thread.start()
        self.bus.publish("cq.state", active=True, reason="start")

    def stop(self, reason: str = "") -> None:
        if not self.active:
            return
        self.active = False
        self._stop.set()
        self.bus.publish("cq.state", active=False, reason=reason)

    # -- worker --
    def _run(self) -> None:
        macro_key = self.settings.get("cq.macro", "F1")
        while self.active and not self._stop.is_set():
            text = ((self.settings.get(f"macros.{macro_key}") or {}).get("text") or "").strip()
            if not text:
                self.stop("no_macro")
                return
            self._busy_evt.clear()
            self._idle_evt.clear()
            self._sending = True
            self.bus.publish("tx.send", text=text)
            self._sending = False
            # wait for the transmission to start and end
            self._busy_evt.wait(3)
            while self.active and self._busy and not self._idle_evt.wait(0.2):
                pass
            interval = float(self.settings.get("cq.interval_s", 8))
            end = time.time() + interval
            while self.active and time.time() < end:
                self._stop.wait(0.1)
