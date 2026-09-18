"""RX module: audio source -> resample -> DeepCW streaming decoder -> bus.

Publishes (docs/messages.md):
  rx.status   {state: "running"|"stopped"|"error", source, msg}
  rx.level    {rms_dbfs, peak_dbfs, tone_hz, warning}
  rx.pending  {text}
  rx.text     {text, t_start, t_end, own_tx, words:[[text, t_start, t_end], ...]}
  rx.spectrum {t0, dt, f0, df, cols:[[dB*2 as int, ...], ...]}   waterfall columns, ~10 messages/s
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import numpy as np

from ..core.bus import Bus
from .audio import AudioSource, LevelMeter

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

    def _publish_final(self, ev, t_origin: float) -> None:
        """Publish decoded text, split into runs of own-sidetone / other-station text.

        Classification is per character (by its end time), because the decoder
        can glue our last "K" and the other station's first word into one word
        when there is no gap between the transmissions.
        """
        chars = [(c, t_origin + a, t_origin + b) for c, a, b in ev.chars]
        if not chars:
            chars = [(ev.text, t_origin + ev.audio_start_s, t_origin + ev.audio_end_s)]
        runs: list[tuple[bool, list]] = []
        own = False
        for c in chars:
            if c[0] != " ":
                own = bool(self.tx_windows and self.tx_windows.is_own(c[2]))
            if runs and runs[-1][0] == own:
                runs[-1][1].append(c)
            elif c[0] != " ":
                runs.append((own, [c]))
        for own, cs in runs:
            words, cur, t0 = [], "", 0.0
            for ch, a, b in cs + [(" ", 0.0, 0.0)]:
                if ch == " ":
                    if cur:
                        words.append([cur, round(t0, 3), round(t1, 3)])
                    cur = ""
                    continue
                if not cur:
                    t0 = a
                cur, t1 = cur + ch, b
            if words:
                self.bus.publish("rx.text", text=" ".join(w[0] for w in words), t_start=words[0][1],
                                 t_end=words[-1][2], own_tx=own, words=words)
