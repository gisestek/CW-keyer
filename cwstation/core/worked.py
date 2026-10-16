"""'Worked before' from the station's own ADIF log (FR-CORE-09).

The index is rebuilt only when a log file changes, so asking about a callsign
every time one is clicked costs a dictionary lookup.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Iterable

from .adif import read_records

log = logging.getLogger(__name__)


def base_call(call: str) -> str:
    """OH2BH/P, DL/OH2BH and OH2BH/MM all count as OH2BH: the longest part with a digit."""
    parts = [p for p in (call or "").upper().split("/") if p]
    with_digit = [p for p in parts if any(c.isdigit() for c in p) and any(c.isalpha() for c in p)]
    pool = with_digit or parts
    return max(reversed(pool), key=len) if pool else ""      # a tie goes to the part after the prefix


class WorkedIndex:
    def __init__(self, paths: Callable[[], Iterable[Path]]):
        self._paths = paths
        self._lock = threading.Lock()
        self._sig: tuple = ()
        self._index: dict[str, list[dict]] = {}

    def _signature(self, paths: list[Path]) -> tuple:
        sig = []
        for p in paths:
            try:
                st = p.stat()
                sig.append((str(p), st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((str(p), 0, 0))
        return tuple(sig)

    def _refresh(self) -> None:
        paths = [Path(p) for p in self._paths() if p]
        sig = self._signature(paths)
        if sig == self._sig:
            return
        index: dict[str, list[dict]] = {}
        seen = set()
        for p in paths:
            if not p.is_file():
                continue
            try:
                records = read_records(p)
            except OSError:
                log.exception("could not read %s", p)
                continue
            for r in records:
                call = (r.get("call") or "").upper()
                if not call:
                    continue
                key = (call, r.get("qso_date", ""), r.get("time_on", "")[:4], (r.get("band") or "").lower())
                if key in seen:                     # same QSO in two files (own log + Wavelog export)
                    continue
                seen.add(key)
                index.setdefault(base_call(call), []).append({
                    "call": call,
                    "date": r.get("qso_date", ""),
                    "time": r.get("time_on", ""),
                    "band": (r.get("band") or "").lower(),
                    "mode": (r.get("mode") or "").upper(),
                    "rst_sent": r.get("rst_sent", ""),
                    "rst_rcvd": r.get("rst_rcvd", ""),
                    "name": r.get("name", ""),
                })
        for qsos in index.values():
            qsos.sort(key=lambda q: (q["date"], q["time"]), reverse=True)
        self._index, self._sig = index, sig

    def lookup(self, call: str) -> list[dict]:
        """Earlier QSOs with this station, newest first."""
        with self._lock:
            self._refresh()
            return list(self._index.get(base_call(call), []))
