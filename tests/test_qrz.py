"""QRZ.com lookup (FR-CORE-08): XML client against a local fake server, locator maths, callsign panel."""
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cwstation.core.bus import Bus  # noqa: E402
from cwstation.core.geo import distance_bearing, grid_to_latlon  # noqa: E402
from cwstation.core.qrz import QrzClient, parse, web_url  # noqa: E402
from cwstation.core.settings import Settings  # noqa: E402

NS = 'xmlns="http://xmldata.qrz.com" version="1.34"'


def _xml(session: str, callsign: str = "") -> bytes:
    return f'<?xml version="1.0" ?><QRZDatabase {NS}>{callsign}<Session>{session}</Session></QRZDatabase>'.encode()


class FakeQrz(BaseHTTPRequestHandler):
    logins = 0
    lookups = 0
    expire_next = False
    subexp = "non-subscriber"

    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        cls = type(self)
        if "username" in q:
            cls.logins += 1
            if q.get("password") != "secret":
                body = _xml("<Error>Username/password incorrect</Error>")
            else:
                body = _xml(f"<Key>K{cls.logins}</Key><SubExp>{cls.subexp}</SubExp>")
        elif cls.expire_next:
            cls.expire_next = False
            body = _xml("<Error>Session Timeout</Error>")
        else:
            cls.lookups += 1
            call = q.get("callsign", "").upper()
            if call == "OH2BH":
                body = _xml(f"<Key>{q['s']}</Key>",
                            "<Callsign><call>OH2BH</call><fname>MARTTI J</fname><name>LAINE</name>"
                            "<addr2>ESPOO</addr2><country>Finland</country><grid>KP20ke</grid>"
                            "<lotw>1</lotw><cqzone>15</cqzone></Callsign>")
            else:
                body = _xml(f"<Key>{q['s']}</Key><Error>Not found: {call}</Error>")
        self.send_response(200)
        self.send_header("Content-Type", "text/xml")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    FakeQrz.logins = FakeQrz.lookups = 0
    FakeQrz.expire_next = False
    srv = HTTPServer(("127.0.0.1", 0), FakeQrz)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def _client(tmp_path, srv, password="secret"):
    st = Settings(tmp_path / "s.json")
    st.set("qrz.username", "OH0TEST")
    st.set("qrz.password", password)
    bus = Bus()
    events = []
    bus.subscribe("qrz.result", events.append)
    c = QrzClient(bus, st, base_url=f"http://127.0.0.1:{srv.server_port}/xml/current/")
    return c, events


def _wait(pred, secs=5):
    end = time.time() + secs
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_parse_strips_namespace():
    session, cs = parse(_xml("<Key>abc</Key>", "<Callsign><call>K1ABC</call><bogus>x</bogus></Callsign>"))
    assert session["Key"] == "abc" and cs == {"call": "K1ABC"}


def test_lookup_found_cached_and_not_found(tmp_path, server):
    c, events = _client(tmp_path, server)
    c.lookup("oh2bh")
    assert _wait(lambda: any(e["state"] == "ok" for e in events))
    ok = [e for e in events if e["state"] == "ok"][0]
    assert events[0]["state"] == "busy"
    assert ok["data"]["fname"] == "MARTTI J" and ok["data"]["grid"] == "KP20ke"
    assert ok["subscriber"] is False and ok["web"] == "https://www.qrz.com/db/OH2BH"
    c.lookup("OH2BH")                                   # second time from the cache, no request
    assert events[-1]["state"] == "ok" and FakeQrz.lookups == 1 and FakeQrz.logins == 1
    c.lookup("OH9XXX")
    assert _wait(lambda: events[-1]["state"] == "not_found")
    c.stop()


def test_session_timeout_logs_in_again(tmp_path, server):
    c, events = _client(tmp_path, server)
    c.lookup("OH9AAA")
    assert _wait(lambda: events[-1]["state"] == "not_found")
    FakeQrz.expire_next = True
    c.lookup("OH2BH")
    assert _wait(lambda: events[-1]["state"] == "ok")
    assert FakeQrz.logins == 2
    c.stop()


def test_wrong_password_is_not_retried(tmp_path, server):
    c, events = _client(tmp_path, server, password="wrong")
    c.lookup("OH2BH")
    assert _wait(lambda: events[-1]["state"] == "error")
    assert "incorrect" in events[-1]["msg"]
    c.lookup("OH9AAA")
    assert _wait(lambda: events[-1]["state"] == "error" and events[-1]["call"] == "OH9AAA")
    assert FakeQrz.logins == 1                          # QRZ locks out repeated bad logins
    c.stop()


def test_no_login_only_offers_web_page(tmp_path):
    st = Settings(tmp_path / "s.json")
    bus = Bus()
    events = []
    bus.subscribe("qrz.result", events.append)
    QrzClient(bus, st).lookup("OH2BH/P")
    assert events[-1]["state"] == "no_login" and events[-1]["web"] == web_url("OH2BH/P")
    assert web_url("oh2bh/p") == "https://www.qrz.com/db/OH2BH/P"


def test_locator_distance():
    assert grid_to_latlon("KP20") == (60.5, 25.0)
    lat, lon = grid_to_latlon("KP20le")
    assert abs(lat - 60.1875) < 0.01 and abs(lon - 24.9583) < 0.01
    assert grid_to_latlon("ZZ99") is None and grid_to_latlon("") is None
    km, deg = distance_bearing(grid_to_latlon("KP20le"), grid_to_latlon("JO65hq"))   # Helsinki -> Copenhagen
    assert 870 < km < 900 and 235 < deg < 250


def test_gui_click_shows_panel_and_fills_qso(tmp_path, server):
    from PySide6.QtWidgets import QApplication

    from cwstation.app import Station
    from cwstation.core import i18n
    from cwstation.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    i18n.load("en")
    st = Settings(tmp_path / "s.json")
    st.set("station.callsign", "OH0TEST")
    st.set("station.locator", "KP20le")
    st.set("log.folder", str(tmp_path / "logs"))
    st.set("qrz.username", "OH0TEST")
    st.set("qrz.password", "secret")
    station = Station(st)
    station.qrz.base_url = f"http://127.0.0.1:{server.server_port}/xml/current/"
    win = MainWindow(station)
    win.show()
    assert win.call_panel.isVisible()

    class _Ev:
        def pos(self):
            return None

    win.stream.anchorAt = lambda pos: "call:OH2BH"                 # click on a callsign link
    win.stream.mouseReleaseEvent = lambda ev: None
    from PySide6.QtWidgets import QTextEdit
    orig = QTextEdit.mouseReleaseEvent
    QTextEdit.mouseReleaseEvent = lambda *a: None
    try:
        win._stream_clicked(_Ev())
    finally:
        QTextEdit.mouseReleaseEvent = orig
    assert station.qso.fields()["call"] == "OH2BH"
    end = time.time() + 5
    while time.time() < end and win.call_panel.rows["name"].text() == "":
        app.processEvents()
        time.sleep(0.02)
    p = win.call_panel
    assert p.title.text() == "OH2BH"
    assert p.rows["name"].text() == "Martti J Laine" and p.rows["qth"].text() == "Espoo"
    assert p.rows["qsl"].text() == "LoTW" and "km" in p.rows["dist"].text()
    assert p.use_btn.isEnabled()
    p.use_btn.click()
    app.processEvents()
    f = station.qso.fields()
    assert f["name"] == "Martti" and f["qth"] == "Espoo" and f["gridsquare"] == "KP20KE"
    assert win.qso_fields["name"].text() == "Martti"
    win.close()
    assert st.get("ui.call_splitter") and st.get("ui.call_panel") is True
