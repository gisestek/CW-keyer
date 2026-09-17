"""TX module: turns user requests into keyer commands.

Subscribes:
  tx.send   {text}              raw text; macros like {MYCALL} are expanded here
  tx.stop   {reason}            STOP (GUI button, Esc, shutdown)
  tx.set    {wpm?, weight?}     live speed / weight (FR-TX-04)
Publishes:
  tx.queued  {text}             text accepted for sending (exact characters that will echo)
  tx.warning {code, detail}     not_connected | dropped_chars | no_callsign
  tx.stopped {reason}           also published locally if the keyer is unreachable
"""
from __future__ import annotations

import logging
import time

from ..core import macros
from ..core.bus import Bus
from .keyer_client import KeyerClient

log = logging.getLogger(__name__)


class TxModule:
    def __init__(self, bus: Bus, settings, client: KeyerClient):
        self.bus = bus
        self.settings = settings
        self.client = client
        bus.subscribe("tx.send", self._on_send)
        bus.subscribe("tx.stop", self._on_stop)
        bus.subscribe("tx.set", self._on_set)

    def _on_send(self, msg: dict) -> None:
        raw = msg.get("text", "")
        vars_ = macros.station_variables(self.settings)
        if "{MYCALL}" in raw.upper() and not vars_["MYCALL"]:
            self.bus.publish("tx.warning", code="no_callsign", detail="")
            return
        text, dropped = macros.sanitize(macros.expand(raw, vars_))
        if dropped:
            self.bus.publish("tx.warning", code="dropped_chars", detail="".join(sorted(set(dropped))))
        if not text.strip():
            return
        text = text.strip() + " "  # word space between successive sends
        if not self.client.send({"cmd": "send", "text": text}):
            self.bus.publish("tx.warning", code="not_connected", detail="")
            return
        self.bus.publish("tx.queued", text=text)

    def _on_stop(self, msg: dict) -> None:
        t0 = time.perf_counter()
        ok = self.client.stop_now()
        log.info("STOP (%s) sent=%s in %.1f ms", msg.get("reason", ""), ok, (time.perf_counter() - t0) * 1000)
        if not ok:
            # keyer unreachable: it stops by itself (heartbeat); clear local state anyway
            self.bus.publish("tx.stopped", reason="local")

    def _on_set(self, msg: dict) -> None:
        payload = {k: int(msg[k]) for k in ("wpm", "weight") if k in msg}
        if not payload:
            return
        for k, v in payload.items():
            self.settings.set(f"keyer.{k}", v)
        self.client.initial_set.update(payload)
        self.client.send({"cmd": "set", **payload})
