"""TX module: turns user requests into keyer commands.

Subscribes:
  tx.send   {text}              raw text; macros like {MYCALL} are expanded here
  tx.stop   {reason}            STOP (GUI button, Esc, shutdown)
  tx.set    {wpm?, weight?}     live speed / weight (FR-TX-04)
  tx.tune   {seconds?}          key down for tuning (FR-TX-08); default keyer.tune_s
Publishes:
  tx.queued  {text}             text accepted for sending (exact characters that will echo)
  tx.warning {code, detail}     not_connected | dropped_chars | no_callsign | tune_busy
  tx.tuning  {ms}               TUNE was started
  tx.stopped {reason}           also published locally if the keyer is unreachable
"""
from __future__ import annotations

import logging
import time

from ..core import macros
from ..core.bus import Bus
from .keyer_client import KeyerClient

log = logging.getLogger(__name__)
TUNE_MAX_S = 10


class TxModule:
    def __init__(self, bus: Bus, settings, client: KeyerClient, qso=None):
        self.bus = bus
        self.settings = settings
        self.client = client
        self.qso = qso   # core.qso.QsoSession: provides {CALL} {NAME} {RST} {RSTR}
        bus.subscribe("tx.send", self._on_send)
        bus.subscribe("tx.stop", self._on_stop)
        bus.subscribe("tx.set", self._on_set)
        bus.subscribe("tx.tune", self._on_tune)
        bus.subscribe("tx.state", self._on_state)
        self._busy = False

    def _on_state(self, msg: dict) -> None:
        self._busy = bool(msg.get("busy"))

    def _on_send(self, msg: dict) -> None:
        raw = msg.get("text", "")
        vars_ = macros.station_variables(self.settings)
        if self.qso is not None:
            f = self.qso.fields()
            vars_.update({"CALL": f.get("call", ""), "NAME": (f.get("name", "") or "").upper(),
                          "QTH": (f.get("qth", "") or "").upper(),
                          "RST": f.get("rst_sent", "") or "599", "RSTR": f.get("rst_rcvd", "") or ""})
        if "{MYCALL}" in raw.upper() and not vars_["MYCALL"]:
            self.bus.publish("tx.warning", code="no_callsign", detail="")
            return
        if "{CALL}" in raw.upper() and not vars_.get("CALL"):
            self.bus.publish("tx.warning", code="no_call", detail="")
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

    def _on_tune(self, msg: dict) -> None:
        secs = msg.get("seconds") or self.settings.get("keyer.tune_s", 5) or 5
        ms = int(max(1.0, min(TUNE_MAX_S, float(secs))) * 1000)
        if self._busy:
            self.bus.publish("tx.warning", code="tune_busy", detail="")
            return
        if not self.client.tune(ms):
            self.bus.publish("tx.warning", code="not_connected" if not self.client.connected else "tune_busy",
                             detail="")
            return
        log.info("TUNE %d ms", ms)
        self.bus.publish("tx.tuning", ms=ms)

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
