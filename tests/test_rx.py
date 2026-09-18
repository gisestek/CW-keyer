"""RX module end-to-end with a synthetic WAV (FR-RX-02/03/04)."""
import time

import soundfile as sf

from cwstation.core.bus import Bus
from cwstation.core.resources import model_dir
from cwstation.rx.audio import LevelMeter, WavSource
from cwstation.rx.cwgen import cw_audio
from cwstation.rx.rx_module import RxModule


def test_rx_decodes_wav(tmp_path):
    wav = tmp_path / "cq.wav"
    sf.write(str(wav), cw_audio("CQ CQ DE OH2BH OH2BH K", wpm=22, fs=48000, snr_db=6, seed=2), 48000)
    bus = Bus()
    texts, levels, pend, spec = [], [], [], []
    bus.subscribe("rx.spectrum", lambda m: spec.append(m))
    bus.subscribe("rx.text", lambda m: texts.append(m))
    bus.subscribe("rx.level", lambda m: levels.append(m))
    bus.subscribe("rx.pending", lambda m: pend.append(m))
    rx = RxModule(bus, model_dir(), lambda: WavSource(wav, loop=False, realtime=False))
    rx.start()
    rx._thread.join(timeout=60)
    rx.stop()
    joined = " ".join(m["text"] for m in texts)
    assert "OH2BH" in joined and joined.startswith("CQ")
    assert all(m["t_end"] >= m["t_start"] for m in texts)
    assert levels and any(600 <= l["tone_hz"] <= 800 for l in levels)
    assert any(p["text"] for p in pend)
    assert spec and len(spec[0]["cols"][0]) > 100 and spec[0]["f0"] >= 100
    assert all(m["own_tx"] is False for m in texts)


def test_level_meter_warnings():
    import numpy as np

    m = LevelMeter(48000)
    loud = np.ones(48000, dtype=np.float32)
    assert m.add(loud)["warning"] == "clip"
    quiet = np.full(48000, 1e-4, dtype=np.float32)
    assert m.add(quiet)["warning"] == "weak"
