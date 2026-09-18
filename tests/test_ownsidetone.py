"""Own-transmission reference line (UC13 layout) and waterfall data."""
import os
import time

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cwstation.core.bus import Bus  # noqa: E402
from cwstation.core.textlog import TextLog  # noqa: E402
from cwstation.core.txwindows import TxWindows  # noqa: E402
from cwstation.rx.deepcw import StreamEvent  # noqa: E402
from cwstation.rx.rx_module import RxModule  # noqa: E402
from cwstation.rx.waterfall import SpectrumProcessor  # noqa: E402


class Clock:
    def __init__(self, t=1_789_650_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_txwindows_marks_own_time_range():
    bus, clk = Bus(), Clock()
    tw = TxWindows(bus, clock=clk)
    t_start = clk.t
    bus.publish("tx.state", busy=True)
    clk.t += 5
    assert tw.is_own(clk.t - 1) and tw.transmitting()
    bus.publish("tx.state", busy=False)
    assert tw.is_own(t_start + 5.2)
    assert not tw.is_own(t_start + 7)
    assert not tw.is_own(t_start - 1)


def test_rx_splits_own_and_other_by_character_time():
    """'K' of our transmission and the other station's first word glued together by the decoder."""
    bus, clk = Bus(), Clock(1000.0)
    tw = TxWindows(bus, clock=clk)
    bus.publish("tx.state", busy=True)
    clk.t = 1010.0
    bus.publish("tx.state", busy=False)
    rx = RxModule(bus, model_dir=".", source_factory=None, tx_windows=tw)
    got = []
    bus.subscribe("rx.text", got.append)
    # stream time line starts at t_origin=1000
    chars = [("O", 1.0, 1.2), ("K", 9.5, 9.9), ("O", 10.8, 11.0), ("H", 11.1, 11.3), (" ", 11.4, 11.6),
             ("D", 12.0, 12.2), ("E", 12.3, 12.5)]
    ev = StreamEvent("final", "OKOH DE", 0, 13, chars=chars)
    rx._publish_final(ev, t_origin=1000.0)
    assert [(m["text"], m["own_tx"]) for m in got] == [("OK", True), ("OH DE", False)]
    assert got[1]["words"][0][0] == "OH"


def test_textlog_ref_after_tx_and_late_rx(tmp_path):
    bus, clk = Bus(), Clock()
    log = TextLog(bus, tmp_path, clock=clk)
    bus.publish("rx.text", text="CQ DE OH2BH", t_start=clk.t, t_end=clk.t + 3, own_tx=False)
    clk.t += 4
    tx_start = clk.t
    for ch in "OH2BH DE OH0X K":
        bus.publish("tx.echo", ch=ch)
        clk.t += 0.3
        if ch == "D":  # the other station's final "K" is decoded only now
            bus.publish("rx.text", text="K", t_start=tx_start - 1.0, t_end=tx_start - 0.8, own_tx=False)
    bus.publish("rx.text", text="OH2BH DE OH0X K", t_start=tx_start, t_end=clk.t, own_tx=True)
    clk.t += 5
    bus.publish("rx.text", text="R R 599", t_start=clk.t, t_end=clk.t + 2, own_tx=False)
    log.flush()
    rows = [l.split("\t")[1:] for l in next(tmp_path.glob("cw-*.txt")).read_text().splitlines()]
    assert ["TX", "OH2BH DE OH0X K"] in rows
    assert rows[rows.index(["TX", "OH2BH DE OH0X K"]) + 1] == ["REF", "OH2BH DE OH0X K"]
    assert ["RX", "K"] in rows and rows[-1] == ["RX", "R R 599"]


def test_spectrum_processor_finds_tone():
    sp = SpectrumProcessor(3200)
    t = np.arange(3200) / 3200
    t0, cols = sp.feed((0.3 * np.sin(2 * np.pi * 700 * t)).astype(np.float32))
    assert cols.shape[1] == sp.bins and len(cols) > 50
    peak_hz = sp.f0 + np.argmax(cols[len(cols) // 2]) * sp.df
    assert abs(peak_hz - 700) <= sp.df
    assert -20 < cols[len(cols) // 2].max() < 0  # dBFS-ish scale


def test_silent_tail_confirms_quickly():
    import soxr

    from cwstation.core.resources import model_dir
    from cwstation.rx.cwgen import cw_audio
    from cwstation.rx.deepcw import DeepCWModel, StreamingDecoder

    m = DeepCWModel(model_dir() / "model.onnx", model_dir() / "model.onnx.json")
    fs = 48000
    sig = cw_audio("CQ DE OH2BH K", wpm=22, fs=fs, snr_db=None, seed=1) * 0.5
    audio = np.concatenate([sig, np.zeros(fs * 12, np.float32)])
    audio += np.random.default_rng(0).normal(0, 0.02, len(audio)).astype(np.float32)
    a3 = soxr.resample(audio, fs, 3200)
    sd = StreamingDecoder(m)
    end_of_signal = len(sig) / fs
    final_at = None
    text = ""
    for i in range(0, len(a3), 160):
        for ev in sd.feed(a3[i:i + 160]):
            if ev.kind == "final":
                text += " " + ev.text
                if text.strip().endswith("K") and final_at is None:
                    final_at = (i + 160) / 3200
    assert text.split() == ["CQ", "DE", "OH2BH", "K"]
    assert final_at is not None and final_at - end_of_signal < 3.0


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    from cwstation.core import i18n

    app = QApplication.instance() or QApplication([])
    i18n.load("en")
    return app


def test_gui_ref_line_under_tx_line(qapp, tmp_path):
    from cwstation.app import Station
    from cwstation.core.settings import Settings
    from cwstation.gui.main_window import MainWindow

    st = Settings(tmp_path / "s.json")
    st.set("log.folder", str(tmp_path / "logs"))
    station = Station(st)          # not started: messages are injected directly
    win = MainWindow(station)
    now = time.time()
    win._on_message({"type": "rx.text", "text": "CQ DE OH2BH", "t_start": now - 6, "t_end": now - 2})
    for ch in "OH2BH DE OH0X":
        win._on_message({"type": "tx.echo", "ch": ch})
    win._on_message({"type": "rx.text", "text": "K", "t_start": now - 1.8, "t_end": now - 1.5})  # late RX
    win._on_message({"type": "rx.text", "text": "OH2BH DE", "own_tx": True, "t_start": now, "t_end": now + 1})
    for ch in " K":
        win._on_message({"type": "tx.echo", "ch": ch})
    win._on_message({"type": "rx.text", "text": "OH0X K", "own_tx": True, "t_start": now + 1, "t_end": now + 2})
    win._on_message({"type": "rx.text", "text": "R R", "t_start": now + 20, "t_end": now + 21})
    lines = win.stream.toPlainText().splitlines()
    assert lines[0].endswith("RX  CQ DE OH2BH K")
    assert lines[1].endswith("TX  OH2BH DE OH0X K")
    assert lines[2].strip() == "ref  OH2BH DE OH0X K"
    assert lines[3].endswith("RX  R R")
    # waterfall accepts data and paints
    win.waterfall.add_spectrum({"t0": now, "dt": 0.015, "f0": 100.0, "df": 6.25,
                                "cols": (np.random.default_rng(0).normal(-80, 5, (40, 224)) * 2).astype(int).tolist()})
    win.waterfall._refresh()
    assert not win.waterfall.grab().isNull()
    win.close()
