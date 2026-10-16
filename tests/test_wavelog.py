"""Wavelog (FR-CORE-05) against a fake that answers like the real Wavelog API (application/controllers/Api.php).

201 {"status":"created", ..., "adif_count":1, "adif_errors":0, "messages":[]}
400 {"status":"abort", ..., "adif_errors":1, "messages":["... Duplicate for OH0TEST"]}
401 {"status":"failed", "reason":"missing or wrong api key"}
POST /api/qso/true = dry run: key and station profile checked, nothing stored.
"""
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from cwstation.core.bus import Bus
from cwstation.core.settings import Settings
from cwstation.core.wavelog import DUPLICATE, OK, REJECTED, RETRY, WavelogClient


class FakeWavelog(BaseHTTPRequestHandler):
    logbook: set = set()
    posts: list = []
    down = False

    def log_message(self, *a):
        pass

    def _reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        if FakeWavelog.down:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(b"<html>Bad gateway</html>")
            return
        obj = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeWavelog.posts.append((self.path, obj))
        if obj.get("key") != "SECRET":
            return self._reply(401, {"status": "failed", "reason": "missing or wrong api key"})
        if obj.get("station_profile_id") != "3":
            return self._reply(401, {"status": "failed", "reason": "station id does not belong to the API key owner."})
        adif = obj["string"]
        base = {"type": "adif", "string": adif}
        if self.path.endswith("/api/qso/true"):
            return self._reply(201, {"status": "created", **base, "adif_count": 0, "adif_errors": 0,
                                     "messages": ["Dryrun works"]})
        call = re.search(r"<CALL:\d+>([^<\s]+)", adif, re.I)
        band = re.search(r"<BAND:\d+>([^<\s]+)", adif, re.I)
        date = re.search(r"<QSO_DATE:\d+>(\d+)", adif, re.I)
        if not call or not date:
            return self._reply(400, {"status": "abort", **base, "adif_count": 0, "adif_errors": 1,
                                     "messages": ["Date/Time not given"]})
        key = (call.group(1), band.group(1) if band else "", date.group(1))
        if key in FakeWavelog.logbook:
            return self._reply(400, {"status": "abort", **base, "adif_count": 0, "adif_errors": 1,
                                     "messages": [f"Date/Time: {date.group(1)} Callsign: {key[0]} Band: {key[1]} "
                                                  "Duplicate for OH0TEST"]})
        FakeWavelog.logbook.add(key)
        return self._reply(201, {"status": "created", **base, "adif_count": 1, "adif_errors": 0, "messages": []})


@pytest.fixture
def wavelog():
    FakeWavelog.logbook, FakeWavelog.posts, FakeWavelog.down = set(), [], False
    srv = HTTPServer(("127.0.0.1", 0), FakeWavelog)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def qso(call, date="20261016", band="40m"):
    return f"<CALL:{len(call)}>{call} <QSO_DATE:8>{date} <TIME_ON:6>150000 <BAND:{len(band)}>{band} <MODE:2>CW <EOR>"


def client(tmp_path, srv, key="SECRET", profile="3"):
    st = Settings(tmp_path / "s.json")
    st.set("wavelog.enabled", True)
    st.set("wavelog.url", f"http://127.0.0.1:{srv.server_port}/index.php")
    st.set("wavelog.key", key)
    st.set("wavelog.station_profile_id", profile)
    bus = Bus()
    events = []
    bus.subscribe("wavelog.status", events.append)
    return WavelogClient(bus, st, tmp_path / "wavelog-queue.jsonl"), events


def test_created_answer_with_adif_errors_field_is_success(tmp_path, wavelog):
    """The bug: the success answer contains the word 'adif_errors', which was taken as a failure."""
    c, events = client(tmp_path, wavelog)
    assert c.post(qso("OH2BH")) == (OK, "")
    c.send(qso("OH6XY"), "OH6XY")
    c._flush()
    assert c.pending() == 0 and events[-1]["state"] == "sent"
    assert len(FakeWavelog.posts) == 2                       # each QSO sent once, no retry


def test_queue_stuck_behind_duplicate_recovers(tmp_path, wavelog):
    """The situation at the station: the first QSO is already in Wavelog, the rest waits behind it."""
    FakeWavelog.logbook.add(("OH2BH", "40m", "20261016"))
    c, events = client(tmp_path, wavelog)
    for call in ("OH2BH", "OH6XY", "SM5ABC"):
        c.send(qso(call), call)
    c._flush()
    assert c.pending() == 0
    assert [e["state"] for e in events if e["state"] != "queued"] == ["duplicate", "sent", "sent"]
    assert ("SM5ABC", "40m", "20261016") in FakeWavelog.logbook


def test_refused_record_is_put_aside_and_does_not_block(tmp_path, wavelog):
    c, events = client(tmp_path, wavelog)
    c.send("<CALL:5>OH2BH <EOR>", "OH2BH")                   # no date: Wavelog refuses it
    c.send(qso("OH6XY"), "OH6XY")
    c._flush()
    assert c.pending() == 0
    rejected = (tmp_path / "wavelog-rejected.jsonl").read_text(encoding="utf-8").splitlines()
    row = json.loads(rejected[0])
    assert row["call"] == "OH2BH" and "Date/Time not given" in row["reason"]
    assert [e["state"] for e in events if e["state"] != "queued"] == ["rejected", "sent"]


@pytest.mark.parametrize("key,profile,reason", [("WRONG", "3", "wrong api key"), ("SECRET", "9", "station id")])
def test_wrong_key_or_profile_keeps_queue(tmp_path, wavelog, key, profile, reason):
    c, events = client(tmp_path, wavelog, key=key, profile=profile)
    c.send(qso("OH2BH"), "OH2BH")
    c._flush()
    assert c.pending() == 1 and events[-1]["state"] == "error" and reason in events[-1]["msg"]


def test_server_trouble_keeps_queue(tmp_path, wavelog):
    FakeWavelog.down = True
    c, events = client(tmp_path, wavelog)
    c.send(qso("OH2BH"), "OH2BH")
    c._flush()
    assert c.pending() == 1 and "HTTP 502" in events[-1]["msg"]
    FakeWavelog.down = False
    c._flush()
    assert c.pending() == 0


def test_connection_test_is_a_dry_run(tmp_path, wavelog):
    c, _ = client(tmp_path, wavelog)
    assert c.test() == (True, "Dryrun works")
    assert c.test()[0] is True                               # again: no duplicate, nothing was stored
    assert FakeWavelog.logbook == set()
    assert all(path.endswith("/api/qso/true") for path, _ in FakeWavelog.posts)
    bad, _ = client(tmp_path, wavelog, key="WRONG")
    ok, msg = bad.test()
    assert not ok and "wrong api key" in msg


def test_offline_answer_is_retry(tmp_path):
    st = Settings(tmp_path / "s.json")
    st.set("wavelog.url", "http://127.0.0.1:9")
    st.set("wavelog.key", "X")
    c = WavelogClient(Bus(), st, tmp_path / "q.jsonl")
    assert c.post(qso("OH2BH"))[0] == RETRY
    assert {OK, DUPLICATE, REJECTED, RETRY} == {"ok", "duplicate", "rejected", "retry"}


def test_worker_thread_sends(tmp_path, wavelog):
    c, events = client(tmp_path, wavelog)
    c.start()
    c.send(qso("OH2BH"), "OH2BH")
    end = time.time() + 5
    while time.time() < end and not any(e["state"] == "sent" for e in events):
        time.sleep(0.05)
    c.stop()
    assert c.pending() == 0
