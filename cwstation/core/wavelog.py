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
OK, DUPLICATE, REJECTED, RETRY = "ok", "duplicate", "rejected", "retry"
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
            outcome, msg = self.post(row["adif"])
            call = row.get("call", "")
            if outcome == RETRY:
                self.bus.publish("wavelog.status", state="error", pending=len(rows), call=call, msg=msg)
                return
            if outcome == REJECTED:
                # this one record is refused for good: keep it aside so it cannot block the QSOs behind it
                self._reject(row, msg)
            with self._lock:
                rows = self._load()[1:]
                self._save(rows)
            state = {OK: "sent", DUPLICATE: "duplicate", REJECTED: "rejected"}[outcome]
            self.bus.publish("wavelog.status", state=state, pending=len(rows), call=call, msg=msg)

    def _reject(self, row: dict, msg: str) -> None:
        path = self.queue_path.with_name("wavelog-rejected.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({**row, "reason": msg, "rejected_utc": time.time()}, ensure_ascii=False) + "\n")
        log.warning("Wavelog rejected %s: %s (kept in %s)", row.get("call", ""), msg, path)

    def test(self) -> tuple[bool, str]:
        """Settings dialog: checks address, API key and station profile with Wavelog's dry run.

        Nothing is written to the log (the old test logged a QSO with TEST, which was a
        duplicate from the second try on).
        """
        outcome, msg = self.post("<CALL:4>TEST<QSO_DATE:8>19700101<TIME_ON:6>000000<BAND:3>40m"
                                 "<MODE:2>CW<RST_SENT:3>599<RST_RCVD:3>599<EOR>", dryrun=True)
        return outcome == OK, msg

    def post(self, adif: str, dryrun: bool = False) -> tuple[str, str]:
        """Sends one record. Returns (outcome, message), outcome = OK | DUPLICATE | REJECTED | RETRY.

        Wavelog answers 201 {"status": "created", …, "adif_errors": 0, "messages": [...]} on success,
        400 {"status": "abort", …, "messages": [...]} when the record is refused (a duplicate among
        others), 401 {"status": "failed", "reason": …} for a wrong key or station profile.
        """
        w = self.settings.get("wavelog", {}) or {}
        url = (w.get("url") or "").rstrip("/") + "/api/qso" + ("/true" if dryrun else "")
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
                return self._outcome(resp.status, resp.read(4000).decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            return self._outcome(e.code, e.read(4000).decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001  (network, DNS, TLS, timeout…)
            return RETRY, str(getattr(e, "reason", e))

    @staticmethod
    def _outcome(code: int, body: str) -> tuple[str, str]:
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            # not Wavelog's JSON: wrong address, a proxy or login page – keep the QSO and retry
            return (RETRY, f"HTTP {code}: unexpected answer – check the Wavelog address ({body[:120].strip()})")
        status = str(data.get("status", "")).lower()
        messages = data.get("messages") or []
        if not isinstance(messages, list):
            messages = [messages]
        text = "; ".join(str(m) for m in messages if m) or str(data.get("reason", "")) or body[:200]
        if 200 <= code < 300 and status in ("created", "ok", "success"):
            return OK, "; ".join(str(m) for m in messages if m)
        if status == "abort" or code == 400:
            if "duplicate" in text.lower():
                return DUPLICATE, text         # already in Wavelog: nothing left to do
            return REJECTED, f"HTTP {code}: {text}"
        return RETRY, f"HTTP {code}: {text}"    # wrong key / station profile, server trouble: keep the queue
