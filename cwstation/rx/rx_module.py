"""RX module: audio source -> resample -> DeepCW streaming decoder -> bus.

Publishes (docs/messages.md):
  rx.status   {state: "running"|"stopped"|"error", source, msg}
  rx.level    {rms_dbfs, peak_dbfs, tone_hz, warning}
  rx.pending  {text}
  rx.text     {text, t_start, t_end}
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
    def __init__(self, bus: Bus, model_dir: Path, source_factory):
        """source_factory() -> AudioSource (called on every (re)start)."""
        self.bus = bus
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
                for ev in decoder.feed(resampler.resample_chunk(block)):
                    if ev.kind == "pending":
                        if ev.text != last_pending:
                            last_pending = ev.text
                            self.bus.publish("rx.pending", text=ev.text)
                    else:
                        last_pending = None
                        self.bus.publish("rx.pending", text="")
                        self.bus.publish("rx.text", text=ev.text,
                                         t_start=t_origin + ev.audio_start_s,
                                         t_end=t_origin + ev.audio_end_s)
        except Exception as e:  # noqa: BLE001
            log.exception("rx loop failed")
            self.bus.publish("rx.status", state="error", source=src.name, msg=str(e))
        finally:
            try:
                for ev in decoder.flush():
                    if ev.kind == "final":
                        self.bus.publish("rx.text", text=ev.text, t_start=t_origin + ev.audio_start_s,
                                         t_end=t_origin + ev.audio_end_s)
            except Exception:  # noqa: BLE001
                pass
            src.stop()
            self.source = None
            if self._stop.is_set():
                self.bus.publish("rx.status", state="stopped", source=src.name, msg="")
