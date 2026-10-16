"""TUNE (FR-TX-08) on both keyers and 'worked before' from the ADIF log (FR-CORE-09)."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cwstation.core.adif import append_qso, read_records  # noqa: E402
from cwstation.core.bus import Bus  # noqa: E402
from cwstation.core.settings import Settings  # noqa: E402
from cwstation.core.worked import WorkedIndex, base_call  # noqa: E402
from cwstation.tx.winkeyer_client import WinkeyerClient  # noqa: E402
from cwstation.tx.winkeyer_sim import WinkeyerSim  # noqa: E402


def wait(pred, secs=5.0):
    end = time.time() + secs
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def _qso(call, date, time_on, band, name="", rst="599"):
    return {"call": call, "qso_date": date, "time_on": time_on, "time_off": time_on, "band": band,
            "mode": "CW", "rst_sent": rst, "rst_rcvd": "579", "name": name}


# ---------------------------------------------------------------- worked before
def test_adif_round_trip_with_non_ascii(tmp_path):
    path = tmp_path / "log.adi"
    append_qso(path, _qso("OH2BH", "20260920", "183200", "40m", name="Jyrki Ähtäri"))
    append_qso(path, _qso("DL1ABC", "20261001", "070500", "20m"))
    recs = read_records(path)
    assert [r["call"] for r in recs] == ["OH2BH", "DL1ABC"]
    assert recs[0]["name"] == "Jyrki Ähtäri" and recs[0]["band"] == "40m" and recs[1]["rst_rcvd"] == "579"


def test_read_records_other_programs(tmp_path):
    path = tmp_path / "wavelog.adi"
    path.write_text("Exported by Wavelog\n<ADIF_VER:5>3.1.4\n<EOH>\n"
                    "<call:5>oh2bh<band:3>20M<qso_date:8>20250101<time_on:4>1200<mode:2>CW<eor>\n"
                    "<CALL:6>OH2ABC <BAND:2>2m <QSO_DATE:8:D>20250202 <EOR>\n", encoding="utf-8")
    recs = read_records(path)
    assert recs[0]["call"] == "oh2bh" and recs[0]["band"] == "20M"
    assert recs[1]["qso_date"] == "20250202"


@pytest.mark.parametrize("call,base", [("OH2BH", "OH2BH"), ("OH2BH/P", "OH2BH"), ("DL/OH2BH", "OH2BH"),
                                       ("OH2BH/MM", "OH2BH"), ("VP2V/W1AW", "W1AW"), ("", "")])
def test_base_call(call, base):
    assert base_call(call) == base


def test_worked_index_two_files_and_refresh(tmp_path):
    own, extra = tmp_path / "own.adi", tmp_path / "wavelog.adi"
    append_qso(own, _qso("OH2BH", "20260920", "183200", "40m", name="Martti"))
    append_qso(extra, _qso("OH2BH", "20260920", "183259", "40m"))          # same QSO, other file
    append_qso(extra, _qso("OH2BH/P", "20250610", "120000", "20m"))
    idx = WorkedIndex(lambda: [own, extra, tmp_path / "missing.adi"])
    qsos = idx.lookup("oh2bh")
    assert [(q["date"], q["band"]) for q in qsos] == [("20260920", "40m"), ("20250610", "20m")]
    assert idx.lookup("OH9NEW") == []
    time.sleep(0.01)
    append_qso(own, _qso("OH2BH", "20261016", "150000", "30m"))
    assert idx.lookup("OH2BH")[0]["band"] == "30m"                          # file changed: re-read


# ---------------------------------------------------------------- TUNE, WiFi keyer (simulator)
@pytest.fixture
def station(tmp_path):
    from cwstation.app import Station

    st = Settings(tmp_path / "s.json")
    st.set("station.callsign", "OH0TEST")
    st.set("log.folder", str(tmp_path / "logs"))
    s = Station(st, sim_keyer=True)
    s.rx.start = lambda: None
    s.start()
    assert wait(lambda: s.keyer.connected)
    yield s
    s.shutdown()


def test_tune_keys_for_the_set_time(station):
    sim = station._sim["sim"]
    started, states = [], []
    station.bus.subscribe("tx.tuning", started.append)
    station.bus.subscribe("tx.state", states.append)
    station.bus.publish("tx.tune", seconds=1)
    assert started and started[0]["ms"] == 1000
    assert wait(lambda: sim.key, 2)
    assert wait(lambda: not sim.busy, 3)
    assert 950 <= sim.keyed_ms <= 1100
    assert any(s["busy"] for s in states) and not states[-1]["busy"]
    station.textlog.flush()
    assert "[TUNE 1 s]" in station.textlog.current_path().read_text(encoding="utf-8")


def test_stop_ends_tune(station):
    sim = station._sim["sim"]
    station.bus.publish("tx.tune", seconds=8)
    assert wait(lambda: sim.key, 2)
    t0 = time.time()
    station.bus.publish("tx.stop", reason="esc")
    assert wait(lambda: not sim.key, 1)
    assert time.time() - t0 < 0.5


def test_tune_refused_while_sending_and_capped(station):
    sim = station._sim["sim"]
    warnings = []
    station.bus.subscribe("tx.warning", warnings.append)
    station.bus.publish("tx.send", text="PARIS " * 10)
    assert wait(lambda: station.tx._busy, 3)
    station.bus.publish("tx.tune", seconds=2)
    assert warnings and warnings[-1]["code"] == "tune_busy"
    station.bus.publish("tx.stop", reason="esc")
    assert wait(lambda: not station.tx._busy, 2)
    started = []
    station.bus.subscribe("tx.tuning", started.append)
    station.bus.publish("tx.tune", seconds=60)
    assert started[-1]["ms"] == 10000                          # never more than 10 s from here
    station.bus.publish("tx.stop", reason="esc")
    assert wait(lambda: not sim.key, 1)


# ---------------------------------------------------------------- TUNE, WinKeyer
@pytest.fixture
def wk():
    sim = WinkeyerSim(speed_factor=40)
    bus = Bus()
    states = []
    bus.subscribe("tx.state", states.append)
    client = WinkeyerClient(bus, "SIM", transport_factory=lambda port: sim)
    client.start()
    assert wait(lambda: client.connected)
    yield client, sim, states
    client.shutdown()


def test_winkeyer_tune_released_by_timer(wk):
    client, sim, states = wk
    assert client.tune(300)
    assert wait(lambda: sim.key_immediate, 1)
    assert wait(lambda: not sim.key_immediate, 2)
    assert states[-1]["busy"] is False


def test_winkeyer_stop_and_shutdown_release_tune(wk):
    client, sim, _ = wk
    assert client.tune(10000)
    assert wait(lambda: sim.key_immediate, 1)
    client.stop_now()
    assert wait(lambda: not sim.key_immediate, 0.5)
    assert client._tune_timer is None
    assert client.tune(99999)                      # capped to 10 s
    assert wait(lambda: sim.key_immediate, 1)
    client.shutdown()
    assert not sim.key_immediate


# ---------------------------------------------------------------- GUI
@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    from cwstation.core import i18n

    app = QApplication.instance() or QApplication([])
    i18n.load("en")
    return app


def pump(app, secs):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def test_gui_worked_before_and_tune_button(qapp, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from cwstation.app import Station
    from cwstation.gui.main_window import MainWindow

    st = Settings(tmp_path / "s.json")
    st.set("station.callsign", "OH0TEST")
    st.set("log.folder", str(tmp_path / "logs"))
    st.set("qso.freq_mhz", 14.03)
    append_qso(tmp_path / "logs" / "cwstation.adi", _qso("OH2BH", "20260920", "183200", "40m", name="Martti"))
    station = Station(st, sim_keyer=True)
    station.rx.start = lambda: None
    win = MainWindow(station)
    station.start()
    win.show()
    assert wait(lambda: station.keyer.connected)

    station.qrz.lookup("OH2BH")                    # no QRZ login: only the callsign, plus the own log
    qapp.processEvents()
    text = win.call_panel.worked.text()
    assert "Worked 1×" in text and "New on 20m" in text and "2026-09-20" in text and "Martti" in text
    win.freq.setValue(7.03)
    assert "New on" not in win.call_panel.worked.text()
    station.qrz.lookup("OH9NEW")
    qapp.processEvents()
    assert "New station" in win.call_panel.worked.text()

    sim = station._sim["sim"]
    win.tune_btn.click()                           # first click only arms it
    assert win._tune_state == "armed" and win.tune_btn.text() == "Sure?"
    pump(qapp, 0.3)
    assert not sim.key
    win._tune_arm_timer.timeout.emit()             # not confirmed in time: back to idle
    assert win._tune_state == "idle" and win.tune_btn.text() == "TUNE"
    win.tune_btn.click()
    QTest.keyClick(win.input, Qt.Key_Escape)       # Esc disarms too
    assert win._tune_state == "idle"
    win.tune_btn.click()
    win.tune_btn.click()                           # second click: carrier
    assert win._tune_state == "on"
    assert wait(lambda: sim.key, 2)
    win.tune_btn.click()                           # while tuning one click stops it
    assert wait(lambda: not sim.key, 1)
    assert win._tune_state == "idle"
    assert win.tune_btn.parentWidget() is win.freq.parentWidget()   # in the top bar next to the frequency
    win.close()
