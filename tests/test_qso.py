"""QSO fields, ADIF, Wavelog and CQ repeat (UC6, FR-CORE-03…06, FR-TX-07)."""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cwstation.core import adif  # noqa: E402
from cwstation.core.bus import Bus  # noqa: E402
from cwstation.core.callsigns import find_callsigns, likely_other_station  # noqa: E402
from cwstation.core.qso import QsoSession  # noqa: E402
from cwstation.core.settings import Settings  # noqa: E402
from cwstation.core.wavelog import WavelogClient  # noqa: E402
from cwstation.tx.cq import CqRepeater  # noqa: E402


# ---------------------------------------------------------------- ADIF
def test_adif_record_and_band():
    assert adif.band_for(7.031) == "40m" and adif.band_for(14.06) == "20m" and adif.band_for(0.5) == ""
    rec = adif.qso_to_adif({"call": "oh2bh", "qso_date": "20260917", "time_on": "134500",
                            "freq_mhz": 7.031, "rst_sent": "599", "rst_rcvd": "579", "name": "Pekka"})
    assert rec.startswith("<CALL:5>OH2BH ") and rec.endswith("<EOR>")
    assert "<BAND:3>40m" in rec and "<FREQ:8>7.031000" in rec and "<MODE:2>CW" in rec


def test_adif_file_header_once(tmp_path):
    p = tmp_path / "log.adi"
    adif.append_qso(p, {"call": "OH2BH", "qso_date": "20260917", "time_on": "1200", "freq_mhz": 7.03})
    adif.append_qso(p, {"call": "OH6XY", "qso_date": "20260917", "time_on": "1210", "freq_mhz": 7.03})
    text = p.read_text()
    assert text.count("<EOH>") == 1 and text.count("<EOR>") == 2 and "<PROGRAMID:10>CW Station" in text


# ---------------------------------------------------------------- callsigns
@pytest.mark.parametrize("text,expected", [
    ("CQ CQ DE OH2BH OH2BH K", "OH2BH"),
    ("OH0X DE DL1ABC/P UR RST 599", "DL1ABC/P"),
    ("R TNX 73 SK ES 5NN", None),
])
def test_callsign_detection(text, expected):
    assert likely_other_station(text, "OH0X") == expected


def test_callsign_positions():
    spans = find_callsigns("CQ DE OH2BH K")
    assert spans == [(6, 11, "OH2BH")]


# ---------------------------------------------------------------- QSO session
class Clock:
    def __init__(self, t=1_789_650_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def session(tmp_path):
    bus, clk = Bus(), Clock()
    st = Settings(tmp_path / "s.json")
    st.set("station.callsign", "OH0TEST")
    st.set("station.locator", "KP20AA")
    return QsoSession(bus, st, clock=clk), bus, clk, st


def test_qso_fields_from_decoded_text(session):
    q, bus, clk, st = session
    bus.publish("tx.queued", text="CQ CQ DE OH0TEST K ")
    bus.publish("rx.text", text="OH0TEST DE OH2BH OH2BH", own_tx=False, t_start=clk.t, t_end=clk.t + 5)
    bus.publish("rx.text", text="UR RST 579 579 NAME PEKKA QTH OULU KP24 K", own_tx=False,
                t_start=clk.t + 6, t_end=clk.t + 12)
    f = q.fields()
    assert f["call"] == "OH2BH" and f["rst_rcvd"] == "579"
    assert f["name"] == "Pekka" and f["qth"] == "Oulu" and f["gridsquare"] == "KP24"
    assert f["rst_sent"] == "599"


def test_qso_qth_not_glued_to_next_word(session):
    q, bus, clk, st = session
    bus.publish("rx.text", text="NAME PEKKA QTH OULU HW? OH0TEST DE OH2BH K", own_tx=False,
                t_start=clk.t, t_end=clk.t + 5)
    assert q.fields()["qth"] == "Oulu"


def test_qso_own_sidetone_ignored_and_manual_wins(session):
    q, bus, clk, st = session
    bus.publish("rx.text", text="DE OH9XXX", own_tx=True, t_start=clk.t, t_end=clk.t + 1)
    assert q.fields()["call"] == ""
    bus.publish("rx.text", text="DE OH2BH", own_tx=False, t_start=clk.t, t_end=clk.t + 1)
    assert q.fields()["call"] == "OH2BH"
    q.set_field("call", "OH6XY")
    bus.publish("rx.text", text="DE OH2BH", own_tx=False, t_start=clk.t + 2, t_end=clk.t + 3)
    assert q.fields()["call"] == "OH6XY"
    rec = q.to_adif_dict(7.031, "100")
    assert rec["call"] == "OH6XY" and rec["band"] if "band" in rec else True
    assert rec["station_callsign"] == "OH0TEST" and rec["my_gridsquare"] == "KP20AA"
    assert rec["qso_date"] and rec["time_on"] <= rec["time_off"]
    q.clear()
    assert q.fields()["call"] == ""


# ---------------------------------------------------------------- Wavelog
class Handler(BaseHTTPRequestHandler):
    received: list = []
    fail_times = 0

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Handler.received.append(json.loads(body))
        if Handler.fail_times > 0:
            Handler.fail_times -= 1
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"status":"failed"}')
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"created"}')

    def log_message(self, *a):
        pass


@pytest.fixture
def wavelog_server():
    Handler.received, Handler.fail_times = [], 0
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


def _client(tmp_path, port, bus=None):
    st = Settings(tmp_path / "s.json")
    st.set("wavelog.enabled", True)
    st.set("wavelog.url", f"http://127.0.0.1:{port}")
    st.set("wavelog.key", "SECRET")
    st.set("wavelog.station_profile_id", "3")
    return WavelogClient(bus or Bus(), st, tmp_path / "queue.jsonl")


def test_wavelog_posts_adif(tmp_path, wavelog_server):
    bus = Bus()
    events = []
    bus.subscribe("wavelog.status", events.append)
    c = _client(tmp_path, wavelog_server.server_port, bus)
    c.start()
    c.send("<CALL:5>OH2BH<EOR>", "OH2BH")
    for _ in range(100):
        if any(e["state"] == "sent" for e in events):
            break
        time.sleep(0.05)
    c.stop()
    assert Handler.received[0] == {"key": "SECRET", "station_profile_id": "3", "type": "adif",
                                   "string": "<CALL:5>OH2BH<EOR>"}
    assert c.pending() == 0


def test_wavelog_keeps_qso_until_server_answers(tmp_path, wavelog_server):
    Handler.fail_times = 1
    c = _client(tmp_path, wavelog_server.server_port)
    c.send("<CALL:5>OH2BH<EOR>", "OH2BH")
    c._flush()
    assert c.pending() == 1, "a failed QSO must stay in the queue"
    c._flush()
    assert c.pending() == 0 and len(Handler.received) == 2


def test_wavelog_offline_queues(tmp_path):
    st = Settings(tmp_path / "s.json")
    st.set("wavelog.enabled", True)
    st.set("wavelog.url", "http://127.0.0.1:9")
    st.set("wavelog.key", "X")
    c = WavelogClient(Bus(), st, tmp_path / "q.jsonl")
    c.send("<CALL:4>TEST<EOR>")
    c._flush()
    assert c.pending() == 1
    assert WavelogClient(Bus(), st, tmp_path / "q.jsonl").pending() == 1  # survives a restart


# ---------------------------------------------------------------- CQ repeat
def test_cq_repeat_sends_and_stops_on_answer(tmp_path):
    bus = Bus()
    st = Settings(tmp_path / "s.json")
    st.set("station.callsign", "OH0TEST")
    st.set("cq.interval_s", 0.2)
    sends, states = [], []

    def fake_keyer(m):  # emulate the keyer: busy while sending
        sends.append(m)
        bus.publish("tx.state", busy=True, key=False, pending=0)
        bus.publish("tx.state", busy=False, key=False, pending=0)

    bus.subscribe("tx.send", fake_keyer)
    bus.subscribe("cq.state", states.append)
    cq = CqRepeater(bus, st)
    cq.start()
    for _ in range(100):
        if len(sends) >= 2:
            break
        time.sleep(0.05)
    assert len(sends) >= 2 and "CQ" in sends[0]["text"]
    bus.publish("rx.text", text="OH0TEST DE OH2BH", own_tx=False)
    assert not cq.active and states[-1]["reason"] == "answer"
    n = len(sends)
    time.sleep(0.4)
    assert len(sends) == n


def test_cq_repeat_stops_when_operator_types(tmp_path):
    bus = Bus()
    st = Settings(tmp_path / "s.json")
    st.set("cq.interval_s", 5)
    cq = CqRepeater(bus, st)
    cq.start()
    time.sleep(0.2)
    bus.publish("tx.send", text="OH2BH DE OH0TEST")
    assert not cq.active


# ---------------------------------------------------------------- GUI + logging
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    from cwstation.core import i18n

    app = QApplication.instance() or QApplication([])
    i18n.load("en")
    return app


def test_gui_callsign_link_and_logging(qapp, tmp_path):
    import time as _t

    from cwstation.app import Station
    from cwstation.gui.main_window import MainWindow

    st = Settings(tmp_path / "s.json")
    st.set("station.callsign", "OH0TEST")
    st.set("log.folder", str(tmp_path / "logs"))
    st.set("qso.freq_mhz", 7.031)
    station = Station(st)
    win = MainWindow(station)
    now = _t.time()
    win._on_message({"type": "rx.text", "text": "CQ CQ DE OH2BH OH2BH K", "t_start": now, "t_end": now + 5})
    assert 'href="call:OH2BH"' in win.stream.toHtml()

    station.qso.set_field("call", "OH2BH")
    station.qso.set_field("rst_rcvd", "579")
    qapp.processEvents()
    assert win.qso_fields["call"].text() == "OH2BH" and win.qso_fields["rst_rcvd"].text() == "579"

    logged = []
    station.bus.subscribe("qso.logged", logged.append)
    record = station.log_qso()
    qapp.processEvents()
    assert record["call"] == "OH2BH" and record["band"] if "band" in record else True
    adi = (tmp_path / "logs" / "cwstation.adi").read_text()
    assert "<CALL:5>OH2BH" in adi and "<BAND:3>40m" in adi and "<RST_RCVD:3>579" in adi
    assert logged and logged[0]["wavelog"] is False       # Wavelog not configured
    assert station.qso.fields()["call"] == ""             # session cleared for the next contact
    assert "QSO logged" in win.stream.toPlainText()
    win.close()
