"""QSO session: collects the fields of the contact in progress from the decoded text (FR-CORE-04).

Everything is a suggestion: the operator sees the fields in the QSO window and
can edit them before the contact is logged (UC6).
"""
from __future__ import annotations

import datetime as dt
import re
import threading
import time

from .bus import Bus
from .callsigns import likely_other_station

GRID_RE = re.compile(r"\b[A-R]{2}[0-9]{2}(?:[A-X]{2})?\b")
RST_RE = re.compile(r"\b(?:RST|UR|URS)\s+(5NN|[1-5][1-9][1-9])\b")
RST_ANY_RE = re.compile(r"\b(5NN|[1-5][1-9][1-9])\b")
NAME_RE = re.compile(r"\b(?:NAME|OP|OM)\s+([A-Z]{2,12})\b")
QTH_RE = re.compile(r"\bQTH\s+([A-Z]{2,15}(?:\s+[A-Z]{2,15})?)\b")
# words that follow the QTH but are not part of it
QTH_STOP = {"HW", "HR", "K", "KN", "BK", "PSE", "UR", "RST", "NAME", "OP", "QTH", "DE", "ES", "TNX",
            "TU", "SK", "AR", "WX", "RIG", "ANT", "PWR", "QSL", "VY", "FB", "CUL", "AGN", "R", "73"}
KEEP_S = 1800


def _rst(value: str) -> str:
    return "599" if value == "5NN" else value


class QsoSession:
    """Keeps the running text of both stations and the suggested QSO fields."""

    FIELDS = ("call", "name", "qth", "gridsquare", "rst_sent", "rst_rcvd", "comment")

    def __init__(self, bus: Bus, settings, clock=time.time):
        self.bus = bus
        self.settings = settings
        self._clock = clock
        self._lock = threading.RLock()
        self.manual: dict[str, str] = {}
        self.auto: dict[str, str] = {}
        self.rx_text = ""
        self.tx_text = ""
        self.rst_hint = ""        # report suggested from the measured signal strength (FR-CORE-07)
        self.t_first: float | None = None
        self.t_last: float | None = None
        bus.subscribe("rx.text", self._on_rx)
        bus.subscribe("tx.queued", self._on_tx)

    # -- collecting --
    def _on_rx(self, msg: dict) -> None:
        if msg.get("own_tx"):
            return
        text = msg.get("text", "").strip()
        if not text:
            return
        with self._lock:
            if msg.get("rst") and int(msg.get("station") or 0) == 0:
                self.rst_hint = str(msg["rst"])
            self.rx_text = " ".join((self.rx_text + " " + text).split())[-600:]
            t = msg.get("t_start") or self._clock()
            self.t_first = self.t_first or t
            self.t_last = max(self.t_last or 0, msg.get("t_end") or t)
            self._reparse()

    def _on_tx(self, msg: dict) -> None:
        with self._lock:
            self.tx_text = " ".join((self.tx_text + " " + msg.get("text", "")).split())[-600:]
            t = self._clock()
            self.t_first = self.t_first or t
            self.t_last = max(self.t_last or 0, t)
            self._reparse()

    def _reparse(self) -> None:
        my_call = (self.settings.get("station.callsign") or "").upper()
        auto: dict[str, str] = {}
        call = likely_other_station(self.rx_text, my_call)
        if call:
            auto["call"] = call
        m = RST_RE.search(self.rx_text) or RST_ANY_RE.search(self.rx_text)
        if m:
            auto["rst_rcvd"] = _rst(m.group(1))
        m = NAME_RE.search(self.rx_text)
        if m:
            auto["name"] = m.group(1).title()
        m = QTH_RE.search(self.rx_text)
        if m:
            words = [w for w in m.group(1).split() if w not in QTH_STOP]
            if words:
                auto["qth"] = " ".join(words).title()
        m = GRID_RE.search(self.rx_text)
        if m:
            auto["gridsquare"] = m.group(0)
        m = RST_RE.search(self.tx_text) or RST_ANY_RE.search(self.tx_text)
        auto["rst_sent"] = _rst(m.group(1)) if m else (self.rst_hint or "599")
        if auto != self.auto:
            self.auto = auto
            self.bus.publish("qso.update", fields=self.fields())

    # -- API --
    def fields(self) -> dict[str, str]:
        with self._lock:
            out = {f: self.auto.get(f, "") for f in self.FIELDS}
            out.update({k: v for k, v in self.manual.items() if k in self.FIELDS})
            return out

    def set_field(self, name: str, value: str) -> None:
        with self._lock:
            self.manual[name] = value
        self.bus.publish("qso.update", fields=self.fields())

    def clear(self) -> None:
        with self._lock:
            self.manual, self.auto = {}, {}
            self.rx_text = self.tx_text = ""
            self.rst_hint = ""
            self.t_first = self.t_last = None
        self.bus.publish("qso.update", fields=self.fields())

    def to_adif_dict(self, freq_mhz: float | None, tx_pwr: str = "") -> dict:
        with self._lock:
            f = self.fields()
            t0 = dt.datetime.fromtimestamp(self.t_first or self._clock(), dt.timezone.utc)
            t1 = dt.datetime.fromtimestamp(self.t_last or self._clock(), dt.timezone.utc)
            st = self.settings.get("station", {}) or {}
            return {
                "call": f.get("call", ""),
                "qso_date": t0.strftime("%Y%m%d"),
                "time_on": t0.strftime("%H%M%S"),
                "time_off": t1.strftime("%H%M%S"),
                "freq_mhz": freq_mhz,
                "mode": "CW",
                "rst_sent": f.get("rst_sent") or "599",
                "rst_rcvd": f.get("rst_rcvd") or "599",
                "name": f.get("name", ""),
                "qth": f.get("qth", ""),
                "gridsquare": f.get("gridsquare", ""),
                "tx_pwr": tx_pwr or self.settings.get("qso.tx_pwr", ""),
                "comment": f.get("comment", ""),
                "station_callsign": st.get("callsign", ""),
                "operator": st.get("callsign", ""),
                "my_gridsquare": st.get("locator", ""),
            }
