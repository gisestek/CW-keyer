"""TX module: turns user requests into keyer commands.

Subscribes:
  tx.send   {text}              raw text; macros like {MYCALL} are expanded here
  tx.stop   {reason}            STOP (GUI button, Esc, shutdown)
  tx.set    {wpm?, weight?}     live speed / weight (FR-TX-04)
  tx.tune   {seconds?}          key down for tuning (FR-TX-08); default keyer.tune_s
Publishes:
  tx.queued  {text}             text accepted for sending (exact characters that will echo)
  tx.warning {code, detail}     not_connected | dropped_chars | no_callsign | no_call | tune_busy |
                                too_long (+ seconds, limit, wpm: the text was not sent)
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
MESSAGE_MIN_S, MESSAGE_MAX_S = 15, 100   # range of the keyer.max_message_s setting


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

    def message_limit_s(self) -> float:
        """Longest single message on air. Stays 10 s under the WiFi keyer's own TX limit, so this clean
        refusal always comes before the keyer's emergency stop."""
        lim = float(self.settings.get("keyer.max_message_s", 60) or 60)
        lim = max(MESSAGE_MIN_S, min(MESSAGE_MAX_S, lim))
        if self.settings.get("keyer.type", "wifi") != "winkeyer":
            tx_max = float(self.settings.get("keyer.tx_max_ms", 120000) or 120000) / 1000
            lim = min(lim, max(5.0, tx_max - 10))
        return lim

    def prepare(self, raw: str, wpm: float | None = None) -> dict:
        """Expand and sanitise `raw` exactly as it would be sent, and time it. No side effects
        (the input field's airtime counter uses this too).

        Returns {text, dropped, seconds, limit, wpm, error}; error is None, "no_callsign" or "no_call".
        """
        vars_ = macros.station_variables(self.settings)
        if self.qso is not None:
            f = self.qso.fields()
            vars_.update({"CALL": f.get("call", ""), "NAME": (f.get("name", "") or "").upper(),
                          "QTH": (f.get("qth", "") or "").upper(),
                          "RST": f.get("rst_sent", "") or "599", "RSTR": f.get("rst_rcvd", "") or ""})
        error = None
        if "{MYCALL}" in raw.upper() and not vars_["MYCALL"]:
            error = "no_callsign"
        elif "{CALL}" in raw.upper() and not vars_.get("CALL"):
            error = "no_call"
        text, dropped = macros.sanitize(macros.expand(raw, vars_))
        text = text.strip()
        wpm = float(wpm or self.settings.get("keyer.wpm", 20) or 20)
        return {"text": text, "dropped": dropped, "seconds": macros.airtime_s(text, wpm),
                "limit": self.message_limit_s(), "wpm": wpm, "error": error}

    def _on_send(self, msg: dict) -> None:
        p = self.prepare(msg.get("text", ""))
        if p["error"]:
            self.bus.publish("tx.warning", code=p["error"], detail="")
            return
        if p["seconds"] > p["limit"]:
            log.info("refused %.0f s message (limit %.0f s at %.0f WPM)", p["seconds"], p["limit"], p["wpm"])
            self.bus.publish("tx.warning", code="too_long", detail="", seconds=p["seconds"],
                             limit=p["limit"], wpm=p["wpm"])
            return
        text, dropped = p["text"], p["dropped"]
        if dropped:
            self.bus.publish("tx.warning", code="dropped_chars", detail="".join(sorted(set(dropped))))
        if not text:
            return
        text = text + " "  # word space between successive sends
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
