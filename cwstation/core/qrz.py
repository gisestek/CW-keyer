"""Callsign lookup from the QRZ.com XML service (FR-CORE-08).

Login:   GET https://xmldata.qrz.com/xml/current/?username=…&password=…&agent=…  -> <Session><Key>
Lookup:  GET https://xmldata.qrz.com/xml/current/?s=<key>&callsign=<call>       -> <Callsign>…

Without a QRZ XML subscription the service answers with fewer fields (typically
name, town and country); with one it also gives the locator, photo, QSL info
and so on. Without a login at all nothing is fetched and the panel only offers
the qrz.com web page.

Lookups run on one worker thread and the answer is published on the bus as
``qrz.result``. Results (also "not found") are cached for the session so a
callsign that keeps coming up in the decoded text is fetched only once.
"""
from __future__ import annotations

import base64
import logging
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .. import APP_ID, __version__
from .bus import Bus

log = logging.getLogger(__name__)

XML_URL = "https://xmldata.qrz.com/xml/current/"
WEB_URL = "https://www.qrz.com/db/{call}"
TIMEOUT_S = 10
MAX_IMAGE_BYTES = 1_500_000
MAX_CACHE = 300
FIELDS = ("call", "fname", "name", "nickname", "name_fmt", "addr1", "addr2", "state", "zip", "country",
          "lat", "lon", "grid", "class", "email", "qslmgr", "eqsl", "lotw", "mqsl", "cqzone", "ituzone",
          "image", "url", "aliases", "xref", "born", "TimeZone")


def web_url(call: str) -> str:
    return WEB_URL.format(call=urllib.parse.quote(call.upper(), safe="/"))


def _strip_ns(root: ET.Element) -> None:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def parse(xml_bytes: bytes) -> tuple[dict, dict]:
    """Returns (session, callsign) dicts from a QRZ XML answer."""
    root = ET.fromstring(xml_bytes)
    _strip_ns(root)
    sess = root.find("Session")
    session = {c.tag: (c.text or "").strip() for c in sess} if sess is not None else {}
    cs = root.find("Callsign")
    callsign = {}
    if cs is not None:
        callsign = {c.tag: (c.text or "").strip() for c in cs if c.tag in FIELDS and (c.text or "").strip()}
    return session, callsign


class QrzClient:
    def __init__(self, bus: Bus, settings, base_url: str = XML_URL, opener=None):
        self.bus = bus
        self.settings = settings
        self.base_url = base_url
        self._open = opener or urllib.request.urlopen
        self._key = ""
        self._key_for: tuple[str, str] | None = None
        self._failed_login: tuple[str, str] | None = None   # do not retry wrong credentials (QRZ locks out)
        self._failed_msg = ""
        self.sub_exp = ""
        self._cache: dict[str, dict] = {}
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # -- settings --
    def credentials(self) -> tuple[str, str]:
        q = self.settings.get("qrz", {}) or {}
        return (q.get("username") or "").strip(), (q.get("password") or "")

    def enabled(self) -> bool:
        user, pw = self.credentials()
        return bool(user and pw)

    # -- API --
    def lookup(self, call: str, force: bool = False) -> None:
        """Asks for one callsign; the answer comes as a ``qrz.result`` message."""
        call = (call or "").strip().upper()
        if not call:
            return
        if not self.enabled():
            self.bus.publish("qrz.result", call=call, state="no_login", data={}, web=web_url(call))
            return
        with self._lock:
            hit = None if force else self._cache.get(call)
            if hit is None:
                if call in self._pending:
                    return
                self._pending.add(call)
        if hit is not None:
            self.bus.publish("qrz.result", **hit)
            return
        self.bus.publish("qrz.result", call=call, state="busy", data={}, web=web_url(call))
        self._ensure_thread()
        self._queue.put(call)

    def cached(self, call: str) -> dict | None:
        with self._lock:
            return self._cache.get((call or "").upper())

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            self._queue.put(None)
            self._thread.join(timeout=2)

    def test_login(self) -> tuple[bool, str]:
        """Settings dialog: log in with the current credentials. Returns (ok, text)."""
        self._key = ""
        self._failed_login = None
        ok, msg = self._login()
        return ok, (self.sub_exp if ok else msg)

    # -- worker --
    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="qrz", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            call = self._queue.get()
            if call is None:
                return
            try:
                result = self._fetch(call)
            except Exception as e:  # noqa: BLE001  never let the worker die
                log.exception("qrz lookup failed")
                result = {"call": call, "state": "error", "msg": str(e), "data": {}}
            result["web"] = web_url(call)
            with self._lock:
                self._pending.discard(call)
                if result["state"] in ("ok", "not_found"):
                    if len(self._cache) >= MAX_CACHE:
                        self._cache.pop(next(iter(self._cache)))
                    self._cache[call] = result
            self.bus.publish("qrz.result", **result)

    def _get(self, params: dict) -> bytes:
        url = self.base_url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": f"{APP_ID}/{__version__}"})
        with self._open(req, timeout=TIMEOUT_S) as resp:
            return resp.read(200_000)

    def _login(self) -> tuple[bool, str]:
        creds = self.credentials()
        if self._failed_login == creds:
            return False, self._failed_msg
        try:
            session, _ = parse(self._get({"username": creds[0], "password": creds[1],
                                          "agent": f"{APP_ID}-{__version__}"}))
        except (urllib.error.URLError, OSError, ET.ParseError) as e:
            return False, str(getattr(e, "reason", e))
        if session.get("Key"):
            self._key, self._key_for = session["Key"], creds
            self.sub_exp = session.get("SubExp", "")
            return True, ""
        msg = session.get("Error") or session.get("Message") or "login failed"
        self._failed_login, self._failed_msg = creds, msg
        return False, msg

    def _fetch(self, call: str) -> dict:
        for attempt in range(2):
            if not self._key or self._key_for != self.credentials():
                ok, msg = self._login()
                if not ok:
                    return {"call": call, "state": "error", "msg": msg, "data": {}}
            try:
                session, data = parse(self._get({"s": self._key, "callsign": call}))
            except (urllib.error.URLError, OSError, ET.ParseError) as e:
                return {"call": call, "state": "error", "msg": str(getattr(e, "reason", e)), "data": {}}
            err = session.get("Error", "")
            if data:
                if not session.get("Key"):
                    self._key = ""
                return {"call": call, "state": "ok", "data": data, "image_b64": self._image(data.get("image")),
                        "subscriber": "non-subscriber" not in (session.get("SubExp") or self.sub_exp).lower()}
            if err.lower().startswith("not found"):
                return {"call": call, "state": "not_found", "data": {}}
            if not session.get("Key") and attempt == 0:      # session timed out: log in again
                self._key = ""
                continue
            return {"call": call, "state": "error", "msg": err or "no data", "data": {}}
        return {"call": call, "state": "error", "msg": "session", "data": {}}

    def _image(self, url: str | None) -> str:
        if not url or not url.startswith(("http://", "https://")):
            return ""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"{APP_ID}/{__version__}"})
            with self._open(req, timeout=TIMEOUT_S) as resp:
                body = resp.read(MAX_IMAGE_BYTES + 1)
            return base64.b64encode(body).decode("ascii") if len(body) <= MAX_IMAGE_BYTES else ""
        except Exception:  # noqa: BLE001  a missing photo is not an error
            return ""
