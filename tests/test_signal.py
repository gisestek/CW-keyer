"""Speed, pitch, station separation and signal strength (FR-RX-08, FR-RX-09, FR-CORE-07)."""
import os

import numpy as np
import pytest

from cwstation.core.bus import Bus
from cwstation.core.resources import model_dir
from cwstation.rx.cwgen import cw_audio
from cwstation.rx.deepcw import DeepCWModel
from cwstation.rx.signal_info import (
    StationTracker, char_units, despeckle, median_tone, smooth_tones, tone_hz, wpm_from_chars,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def ideal_chars(text: str, wpm: float, t0: float = 10.0):
    """Character timings exactly as a perfect keyer would send them."""
    unit = 1.2 / wpm
    out, t = [], t0
    for i, ch in enumerate(text):
        if ch == " ":
            out.append((" ", t, t))
            t += 4 * unit
            continue
        u = char_units(ch)
        out.append((ch, t, t + u * unit))
        t += (u + 3) * unit
    return out


@pytest.mark.parametrize("wpm", [13, 20, 28, 35])
def test_wpm_from_ideal_timing(wpm):
    chars = ideal_chars("CQ DE OH2BH K", wpm)
    assert wpm_from_chars(chars) == pytest.approx(wpm, rel=0.02)


def test_wpm_needs_enough_characters():
    assert wpm_from_chars(ideal_chars("E", 20)) is None


def test_wpm_rejects_random_timing():
    rng = np.random.default_rng(1)
    chars = [(c, float(t), float(t) + 0.05)
             for c, t in zip("CQDEOH2BHK", np.cumsum(rng.uniform(0.05, 1.5, 10)))]
    assert wpm_from_chars(chars) is None


def test_tone_of_pure_signal():
    fs = 3200
    t = np.arange(fs) / fs
    x = np.sin(2 * np.pi * 734.0 * t).astype(np.float32)
    assert tone_hz(x, fs, 0, len(x)) == pytest.approx(734.0, abs=2.0)


def test_tone_of_noise_is_none():
    rng = np.random.default_rng(3)
    x = rng.normal(0, 0.1, 3200).astype(np.float32)
    assert tone_hz(x, 3200, 0, 3200) is None


def test_station_tracker_groups_by_pitch():
    tr = StationTracker()
    assert tr.assign(600.0, 100.0) == 0
    assert tr.assign(604.0, 101.0) == 0      # same station, small drift
    assert tr.assign(820.0, 102.0) == 1      # another pitch, another station
    assert tr.assign(601.0, 103.0) == 0
    assert len(tr.tones()) == 2


def test_smooth_and_despeckle_ignore_single_outliers():
    assert smooth_tones([600.0, 601.0, 980.0, 599.0, 600.0])[2] == pytest.approx(600.0, abs=2)
    assert despeckle([0, 0, 0, 1, 0, 0, 0]) == [0] * 7
    assert despeckle([0, 0, 0, 1, 1, 1, 1]) == [0, 0, 0, 1, 1, 1, 1]
    assert despeckle([0, 0, 0, None, 0, 0]) == [0] * 6


def test_median_tone_ignores_missing():
    assert median_tone([None, 700.0, 702.0, None]) == pytest.approx(701.0)


def test_decoder_measures_speed_and_pitch():
    """The model's character marks give the speed, the audio gives the pitch."""
    model = DeepCWModel(model_dir() / "model.onnx", model_dir() / "model.onnx.json")
    import soxr

    audio = cw_audio("OH2BH DE SM5QRS K", wpm=24, fs=48000, tone_hz=740.0, snr_db=6, seed=11)
    x = soxr.resample(audio, 48000, model.sample_rate).astype(np.float32)
    res = model.decode(x)
    spf = model.seconds_per_frame
    chars = [(c.char, c.start_frame * spf, (c.end_frame + 1) * spf) for c in res.char_spans]
    assert wpm_from_chars(chars) == pytest.approx(24, rel=0.05)
    tones = [tone_hz(x, model.sample_rate, int(c.start_frame * spf * model.sample_rate),
                     int((c.end_frame + 1) * spf * model.sample_rate), 2 * model.hop)
             for c in res.char_spans if c.char != " "]
    assert median_tone(tones) == pytest.approx(740.0, abs=5.0)


def test_two_stations_end_up_on_separate_lines(tmp_path):
    """Two stations on different pitches inside the same filter (FR-RX-08)."""
    import soundfile as sf

    from cwstation.rx.audio import WavSource
    from cwstation.rx.rx_module import RxModule

    fs = 48000
    a = cw_audio("CQ CQ DE OH2BH K", wpm=22, fs=fs, tone_hz=620.0, snr_db=6, seed=3)
    b = cw_audio("OH2BH DE SM5QRS K", wpm=28, fs=fs, tone_hz=830.0, snr_db=6, seed=4)
    wav = tmp_path / "two.wav"
    sf.write(str(wav), np.concatenate([a, np.zeros(int(1.5 * fs), np.float32), b,
                                       np.zeros(int(2.0 * fs), np.float32)]), fs)
    bus = Bus()
    texts = []
    bus.subscribe("rx.text", texts.append)
    rx = RxModule(bus, model_dir(), lambda: WavSource(wav, loop=False, realtime=False))
    rx.start()
    rx._thread.join(timeout=120)
    rx.stop()

    first = [m for m in texts if m["station"] == 0]
    second = [m for m in texts if m["station"] == 1]
    assert first and second
    assert all(600 <= m["tone_hz"] <= 650 for m in first if m["tone_hz"])
    assert all(810 <= m["tone_hz"] <= 860 for m in second if m["tone_hz"])
    assert "OH2BH" in " ".join(m["text"] for m in first)
    assert "SM5QRS" in " ".join(m["text"] for m in second)
    speeds = [m["wpm"] for m in second if m["wpm"]]
    assert speeds and speeds[0] == pytest.approx(28, rel=0.08)


def signal_with_snr(text: str, wpm: float, tone: float, snr500_db: float, fs: int = 48000, seed: int = 1):
    """CW where the key-down power against 500 Hz of noise is exactly `snr500_db`."""
    from cwstation.rx.cwgen import keying_envelope

    rng = np.random.default_rng(seed)
    env = keying_envelope(text, wpm, fs, rng=rng)
    t = np.arange(len(env)) / fs
    sig = (env * np.sin(2 * np.pi * tone * t)).astype(np.float32)
    key_down_power = 0.5
    noise_500 = key_down_power / (10 ** (snr500_db / 10))
    var = noise_500 * (fs / 2) / 500.0
    return (sig + rng.normal(0, np.sqrt(var), len(sig))).astype(np.float32)


@pytest.mark.parametrize("truth", [30, 20, 12, 6, 0])
def test_snr_estimate(truth):
    import soxr

    from cwstation.rx.signal_info import snr_db

    audio = signal_with_snr("CQ CQ DE OH2BH OH2BH K TEST", 22, 700.0, truth, seed=4)
    x = soxr.resample(audio, 48000, 3200).astype(np.float32)
    assert snr_db(x, 3200, 700.0) == pytest.approx(truth, abs=3.0)


def test_snr_of_noise_only():
    from cwstation.rx.signal_info import snr_db

    rng = np.random.default_rng(7)
    x = rng.normal(0, 0.05, 3200 * 3).astype(np.float32)
    value = snr_db(x, 3200, 700.0)
    assert value is None or value < 3.0


@pytest.mark.parametrize("snr,rst", [(35, "599"), (30, "599"), (20, "579"), (12, "569"),
                                     (6, "559"), (0, "449"), (-6, "339"), (-12, "229")])
def test_rst_from_snr(snr, rst):
    from cwstation.rx.signal_info import rst_from_snr

    assert rst_from_snr(snr) == rst
    assert rst_from_snr(None) is None


def test_qso_uses_measured_report_as_default(tmp_path):
    """The suggested report becomes RST_SENT until we actually send one (FR-CORE-07)."""
    from cwstation.core.qso import QsoSession
    from cwstation.core.settings import Settings

    bus = Bus()
    st = Settings(tmp_path / "s.json")
    st.set("station.callsign", "OH0TEST")
    qso = QsoSession(bus, st)
    bus.publish("rx.text", text="CQ DE OH2BH K", own_tx=False, station=0, t_start=1.0, t_end=2.0,
                rst="569", snr_db=13.0)
    assert qso.fields()["rst_sent"] == "569"
    bus.publish("tx.queued", text="OH2BH DE OH0TEST UR RST 599 K")
    assert qso.fields()["rst_sent"] == "599"     # what we really sent wins
    qso.clear()
    bus.publish("rx.text", text="TEST DE OH6XY K", own_tx=False, station=0, t_start=9.0, t_end=10.0,
                rst=None, snr_db=None)
    assert qso.fields()["rst_sent"] == "599"     # hint forgotten with the rest of the QSO
