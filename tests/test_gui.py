"""GUI smoke tests (offscreen): STOP button, Esc from the input field, shutdown sends STOP."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cwstation.app import Station  # noqa: E402
from cwstation.core import i18n  # noqa: E402
from cwstation.core.settings import Settings  # noqa: E402
from cwstation.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    i18n.load("en")
    yield app


def pump(app, secs):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait(app, pred, secs=8):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def gui(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    st = Settings(tmp_path / "s.json")
    st.set("station.callsign", "OH0TEST")
    st.set("log.folder", str(tmp_path / "logs"))
    station = Station(st, sim_keyer=True)
    station.rx.start = lambda: None  # audio not needed here
    win = MainWindow(station)
    station.start()
    win.show()
    assert wait(qapp, lambda: station.keyer.connected)
    stops = []
    station.bus.subscribe("tx.stop", stops.append)
    yield qapp, station, win, stops
    win.close()


def sim(station):
    return station._sim["sim"]


def test_enter_sends_and_echo_shows(gui):
    app, station, win, stops = gui
    QTest.keyClicks(win.input, "cq de {mycall}")
    QTest.keyClick(win.input, Qt.Key_Return)
    assert wait(app, lambda: "OH0TEST" in win.stream.toPlainText(), 15)
    assert win.input.text() == ""


def test_esc_in_input_field_stops(gui):
    app, station, win, stops = gui
    station.bus.publish("tx.send", text="PARIS " * 20)
    assert wait(app, lambda: sim(station).busy)
    win.input.setFocus()
    QTest.keyClicks(win.input, "typing")
    QTest.keyClick(win.input, Qt.Key_Escape)
    assert wait(app, lambda: not sim(station).busy, 2)
    assert stops and stops[-1]["reason"] == "esc"
    assert win.queue_label.text() == ""


def test_stop_button(gui):
    app, station, win, stops = gui
    station.bus.publish("tx.send", text="PARIS " * 20)
    assert wait(app, lambda: sim(station).busy)
    QTest.mouseClick(win.stop_btn, Qt.LeftButton)
    assert wait(app, lambda: not sim(station).busy, 2)


def test_f1_macro(gui):
    app, station, win, stops = gui
    queued = []
    station.bus.subscribe("tx.queued", queued.append)
    QTest.keyClick(win, Qt.Key_F1)
    assert wait(app, lambda: queued, 3)
    assert queued[0]["text"].startswith("CQ CQ CQ DE OH0TEST OH0TEST K")


def test_close_window_sends_stop_first(gui):
    """SR-05: closing during transmission stops the keyer."""
    app, station, win, stops = gui
    station.bus.publish("tx.send", text="PARIS " * 20)
    assert wait(app, lambda: sim(station).busy)
    s = sim(station)
    win.close()
    assert wait(app, lambda: not s.busy, 3)
    assert stops and stops[-1]["reason"] == "shutdown"
