"""RX module: audio source -> resample -> DeepCW streaming decoder -> bus.

Publishes (docs/messages.md):
  rx.status   {state: "running"|"stopped"|"error", source, msg}
  rx.level    {rms_dbfs, peak_dbfs, tone_hz, warning}
  rx.pending  {text}
  rx.text     {text, t_start, t_end, own_tx, words:[[text, t_start, t_end], ...],
               wpm, tone_hz, delta_hz, station, snr_db, rst}
  rx.signal   {wpm, tone_hz, delta_hz, own_tone_hz, station, snr_db, rst}
              other station's speed, pitch and signal strength
  rx.spectrum {t0, dt, f0, df, cols:[[dB*2 as int, ...], ...]}   waterfall columns, ~10 messages/s
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from ..core.bus import Bus
from .audio import AudioSource, LevelMeter
from .signal_info import (
    StationTracker, despeckle, median_tone, rst_from_snr, smooth_tones, snr_db, wpm_from_chars,
)

log = logging.getLogger(__name__)


class RxModule:
    def __init__(self, bus: Bus, model_dir: Path, source_factory, tx_windows=None):
        """source_factory() -> AudioSource (called on every (re)start).
        tx_windows: core.txwindows.TxWindows used to mark our own sidetone (own_tx)."""
        self.bus = bus
        self.tx_windows = tx_windows
        self.model_dir = Path(model_dir)
        self.source_factory = source_factory
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._model = None
        self.source: AudioSource | None = None
        self.stations = StationTracker()
        # our own sidetone pitch (reference for delta_hz); a median over recent
        # transmissions, so one misclassified run cannot move the reference
        self._own_tones: deque[float] = deque(maxlen=9)

    def _load_model(self):
        if self._model is None:
            from .deepcw import DeepCWModel

            path = self.model_dir / "model.onnx"
            if not path.exists():
                raise FileNotFoundError(str(path))
            self._model = DeepCWModel(path, self.model_dir / "model.onnx.json", threads=2)
        return self._model

    def start(self) -> None:
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="rx", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=3)
        self._thread = None

    def restart(self) -> None:
        self.start()

    def _run(self) -> None:
        import soxr

        from .deepcw import StreamConfig, StreamingDecoder
        from .waterfall import SpectrumProcessor

        try:
            model = self._load_model()
        except FileNotFoundError as e:
            self.bus.publish("rx.status", state="error", source="", msg=f"model_missing:{e}")
            return
        except Exception as e:  # noqa: BLE001
            log.exception("model load failed")
            self.bus.publish("rx.status", state="error", source="", msg=str(e))
            return

        try:
            src = self.source_factory()
            src.start()
        except Exception as e:  # noqa: BLE001
            log.exception("audio start failed")
            self.bus.publish("rx.status", state="error", source="", msg=str(e))
            return
        self.source = src
        self.bus.publish("rx.status", state="running", source=src.name, msg="")

        decoder = StreamingDecoder(model, StreamConfig())
        resampler = soxr.ResampleStream(src.samplerate, model.sample_rate, 1, dtype="float32")
        meter = LevelMeter(src.samplerate)
        spectrum = SpectrumProcessor(model.sample_rate)
        spec_cols: list[np.ndarray] = []
        spec_t0 = None
        spec_last_pub = 0.0
        t_origin = time.time()      # wall-clock time of stream sample 0
        samples_in = 0
        last_pending = None
        try:
            while not self._stop.is_set():
                block = src.read(timeout=0.2)
                if block is None:
                    if src.finished:
                        break
                    continue
                if samples_in == 0:
                    t_origin = time.time() - len(block) / src.samplerate
                samples_in += len(block)
                level = meter.add(block)
                if level is not None:
                    self.bus.publish("rx.level", **level)
                chunk = resampler.resample_chunk(block)
                t_first, cols = spectrum.feed(chunk)
                if len(cols):
                    if spec_t0 is None:
                        spec_t0 = t_origin + t_first
                    spec_cols.append(cols)
                now = time.monotonic()
                if spec_cols and now - spec_last_pub >= 0.1:
                    allc = np.concatenate(spec_cols)
                    self.bus.publish("rx.spectrum", t0=spec_t0, dt=spectrum.dt, f0=spectrum.f0, df=spectrum.df,
                                     cols=np.clip(np.round(allc * 2), -32000, 32000).astype(int).tolist())
                    spec_cols, spec_t0, spec_last_pub = [], None, now
                for ev in decoder.feed(chunk):
                    if ev.kind == "pending":
                        if ev.text != last_pending:
                            last_pending = ev.text
                            self.bus.publish("rx.pending", text=ev.text)
                    else:
                        last_pending = None
                        self.bus.publish("rx.pending", text="")
                        self._publish_final(ev, t_origin)
        except Exception as e:  # noqa: BLE001
            log.exception("rx loop failed")
            self.bus.publish("rx.status", state="error", source=src.name, msg=str(e))
        finally:
            try:
                for ev in decoder.flush():
                    if ev.kind == "final":
                        self._publish_final(ev, t_origin)
            except Exception:  # noqa: BLE001
                pass
            src.stop()
            self.source = None
            if self._stop.is_set():
                self.bus.publish("rx.status", state="stopped", source=src.name, msg="")

    def own_tone(self) -> float | None:
        """Pitch of our own sidetone: the median of the last transmissions."""
        if not self._own_tones:
            return None
        return round(float(np.median(list(self._own_tones))), 1)

    def _snr(self, ev, t_origin: float, chars, tone: float | None) -> float | None:
        """Signal strength of one station's run, measured from the audio it was decoded from."""
        audio = getattr(ev, "audio", None)
        if audio is None or not tone or not len(chars) or self._model is None:
            return None
        fs = self._model.sample_rate
        margin = int(0.05 * fs)
        a = int((chars[0][1] - t_origin - ev.audio_t0) * fs) - margin
        b = int((chars[-1][2] - t_origin - ev.audio_t0) * fs) + margin
        a, b = max(0, a), min(len(audio), b)
        if b - a < fs // 4:
            return None
        return snr_db(audio, fs, tone, a, b)

    def _publish_final(self, ev, t_origin: float) -> None:
        """Publish decoded text, split into runs of own-sidetone / other-station text.

        Classification is per character (by its end time), because the decoder
        can glue our last "K" and the other station's first word into one word
        when there is no gap between the transmissions. Characters are also
        grouped by pitch, so two stations in the same filter end up on separate
        lines (FR-RX-08).
        """
        tones = list(ev.char_tones) + [None] * max(0, len(ev.chars) - len(ev.char_tones))
        tones = smooth_tones(tones[:len(ev.chars)])
        chars = [(c, t_origin + a, t_origin + b, tone)
                 for (c, a, b), tone in zip(ev.chars, tones)]
        if not chars:
            chars = [(ev.text, t_origin + ev.audio_start_s, t_origin + ev.audio_end_s, None)]

        # own sidetone / other station per character, then the station for the others
        owns, idx = [], []
        own = False
        for i, c in enumerate(chars):
            if c[0] != " ":
                own = bool(self.tx_windows and self.tx_windows.is_own(c[2]))
                if not own:
                    idx.append(i)
            owns.append(own)
        assigned = despeckle([self.stations.assign(chars[i][3], chars[i][2]) if chars[i][3] else None
                              for i in idx])
        stations = [-1] * len(chars)
        for i, st in zip(idx, assigned):
            stations[i] = st

        runs: list[tuple[bool, int, list]] = []
        own, station = False, 0
        for c, own_c, st in zip(chars, owns, stations):
            if c[0] != " ":
                own, station = own_c, st
            if runs and runs[-1][0] == own and runs[-1][1] == station:
                runs[-1][2].append(c)
            elif c[0] != " ":
                runs.append((own, station, [c]))
        for own, station, cs in runs:
            words, cur, t0 = [], "", 0.0
            for ch, a, b, _tone in cs + [(" ", 0.0, 0.0, None)]:
                if ch == " ":
                    if cur:
                        words.append([cur, round(t0, 3), round(t1, 3)])
                    cur = ""
                    continue
                if not cur:
                    t0 = a
                cur, t1 = cur + ch, b
            if not words:
                continue
            tone = median_tone(c[3] for c in cs)
            wpm = wpm_from_chars([(c[0], c[1], c[2]) for c in cs])
            snr = self._snr(ev, t_origin, cs, tone) if not own else None
            rst = rst_from_snr(snr)
            if own and tone:
                self._own_tones.append(tone)
            own_tone = self.own_tone()
            delta = round(tone - own_tone, 1) if tone and own_tone and not own else None
            self.bus.publish("rx.text", text=" ".join(w[0] for w in words), t_start=words[0][1],
                             t_end=words[-1][2], own_tx=own, words=words,
                             wpm=wpm, tone_hz=tone, delta_hz=delta, station=station,
                             snr_db=snr, rst=rst)
            if not own and (wpm or tone):
                self.bus.publish("rx.signal", wpm=wpm, tone_hz=tone, delta_hz=delta,
                                 own_tone_hz=own_tone, station=station, snr_db=snr, rst=rst)
