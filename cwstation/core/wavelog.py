"""Sending QSOs to Wavelog (FR-CORE-06).

POST <url>/api/qso  {"key": …, "station_profile_id": …, "type": "adif", "string": "<call:5>…<EOR>"}

If the server or the network is down the QSO is kept in a queue file and
retried, so a contact is never lost (NFR-02).
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .bus import Bus

log = logging.getLogger(__name__)
RETRY_S = 30
TIMEOUT_S = 15


class WavelogClient:
    def __init__(self, bus: Bus, settings, queue_path: Path):
        self.bus = bus
        self.settings = settings
        self.queue_path = Path(queue_path)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- queue file --
    def _load(self) -> list[dict]:
        if not self.queue_path.exists():
            return []
        rows = []
        for line in self.queue_path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows

    def _save(self, rows: list[dict]) -> None:
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        self.queue_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    def pending(self) -> int:
        with self._lock:
            return len(self._load())

    # -- API --
    def enabled(self) -> bool:
        w = self.settings.get("wavelog", {}) or {}
        return bool(w.get("enabled") and w.get("url") and w.get("key"))

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="wavelog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=3)

    def send(self, adif: str, call: str = "") -> None:
        """Queue one QSO; it is sent right away if possible."""
        with self._lock:
            rows = self._load()
            rows.append({"adif": adif, "call": call, "queued_utc": time.time()})
            self._save(rows)
        self.bus.publish("wavelog.status", state="queued", pending=len(rows), call=call)
        self._wake.set()

    # -- worker --
    def _run(self) -> None:
        while not self._stop.is_set():
            if self.enabled():
                self._flush()
            self._wake.wait(RETRY_S)
            self._wake.clear()

    def _flush(self) -> None:
        with self._lock:
            rows = self._load()
        while rows and not self._stop.is_set():
            row = rows[0]
            ok, msg = self.post(row["adif"])
            if not ok:
                self.bus.publish("wavelog.status", state="error", pending=len(rows),
                                 call=row.get("call", ""), msg=msg)
                return
            with self._lock:
                rows = self._load()[1:]
                self._save(rows)
            self.bus.publish("wavelog.status", state="sent", pending=len(rows), call=row.get("call", ""))

    def post(self, adif: str) -> tuple[bool, str]:
        w = self.settings.get("wavelog", {}) or {}
        url = (w.get("url") or "").rstrip("/") + "/api/qso"
        payload = json.dumps({
            "key": w.get("key", ""),
            "station_profile_id": str(w.get("station_profile_id", "")),
            "type": "adif",
            "string": adif,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "CWStation"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                body = resp.read(2000).decode("utf-8", "replace")
                if resp.status >= 300:
                    return False, f"HTTP {resp.status}: {body[:200]}"
                if '"status":"failed"' in body.replace(" ", "") or "error" in body.lower():
                    return False, body[:200]
                return True, body[:200]
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code}: {e.read(200).decode('utf-8', 'replace')}"
        except Exception as e:  # noqa: BLE001  (network, DNS, TLS, timeout…)
            return False, str(e)
