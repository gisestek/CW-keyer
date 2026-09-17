"""Audio sources for the RX module: sound card (sounddevice) or WAV file (development)."""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


def _sd():
    import sounddevice as sd  # imported lazily: PortAudio may be missing on a dev machine

    return sd


def list_input_devices() -> list[str]:
    """Labels 'Device name (Host API)' for every input-capable device."""
    try:
        sd = _sd()
        apis = sd.query_hostapis()
        out = []
        for d in sd.query_devices():
            if d["max_input_channels"] > 0:
                out.append(f"{d['name']} ({apis[d['hostapi']]['name']})")
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("cannot list audio devices: %s", e)
        return []


def resolve_device(label: str):
    """Return a sounddevice device index for a stored label, or None for the default device."""
    if not label:
        return None
    sd = _sd()
    apis = sd.query_hostapis()
    devices = list(sd.query_devices())
    labels = [f"{d['name']} ({apis[d['hostapi']]['name']})" for d in devices]
    for i, (lab, d) in enumerate(zip(labels, devices)):
        if lab == label and d["max_input_channels"] > 0:
            return i
    name = label.rsplit(" (", 1)[0].lower()
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0 and name in d["name"].lower():
            return i
    raise ValueError(f"audio device not found: {label}")


class AudioSource:
    """Delivers mono float32 blocks through `read(timeout)`."""

    samplerate: int
    name: str

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def read(self, timeout: float) -> np.ndarray | None: ...
    overflows: int = 0
    finished: bool = False  # True when a non-looping file source has ended


class SoundCardSource(AudioSource):
    def __init__(self, device_label: str, samplerate: int = 48000, channel: int = 0):
        self.device_label = device_label
        self.samplerate = samplerate
        self.channel = channel
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=400)
        self._stream = None
        self.overflows = 0
        self.name = device_label or "default"

    def start(self) -> None:
        sd = _sd()
        dev = resolve_device(self.device_label)
        info = sd.query_devices(dev, "input")
        channels = max(1, min(int(info["max_input_channels"]), self.channel + 1))
        self.name = info["name"]
        ch = min(self.channel, channels - 1)

        def cb(indata, frames, time_info, status):
            if status:
                self.overflows += 1
            try:
                self._q.put_nowait(indata[:, ch].copy())
            except queue.Full:
                self.overflows += 1

        self._stream = sd.InputStream(device=dev, channels=channels, samplerate=self.samplerate,
                                      dtype="float32", blocksize=self.samplerate // 20, callback=cb)
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    def read(self, timeout: float) -> np.ndarray | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None


class WavSource(AudioSource):
    """Plays a WAV file in real time (loops). For development without a radio."""

    def __init__(self, path: Path, loop: bool = True, realtime: bool = True):
        import soundfile as sf

        self.path = Path(path)
        self._data, self.samplerate = sf.read(str(self.path), dtype="float32", always_2d=True)
        self._data = self._data[:, 0]
        self.loop = loop
        self.realtime = realtime
        self.name = f"WAV: {self.path.name}"
        self._pos = 0
        self._t0 = 0.0
        self._sent = 0
        self._running = False

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._sent = 0
        self._running = True

    def stop(self) -> None:
        self._running = False

    def read(self, timeout: float) -> np.ndarray | None:
        if not self._running:
            return None
        block = self.samplerate // 20
        if self.realtime:
            due = self._t0 + self._sent / self.samplerate
            wait = due - time.monotonic()
            if wait > timeout:
                time.sleep(timeout)
                return None
            if wait > 0:
                time.sleep(wait)
        if self._pos >= len(self._data):
            if not self.loop:
                self._running = False
                self.finished = True
                return None
            self._pos = 0
        out = self._data[self._pos:self._pos + block]
        self._pos += len(out)
        self._sent += len(out)
        return out


class LevelMeter:
    """RMS/peak in dBFS and strongest tone 300–1500 Hz over ~0.25 s windows (FR-RX-04)."""

    CLIP_DBFS = -1.0
    WEAK_DBFS = -50.0

    def __init__(self, samplerate: int, window_s: float = 0.25):
        self.fs = samplerate
        self.window = int(samplerate * window_s)
        self._blocks: list[np.ndarray] = []
        self._n = 0
        self._hist = np.zeros(8192, dtype=np.float32)

    def add(self, x: np.ndarray) -> dict | None:
        self._blocks.append(x)
        self._n += len(x)
        if self._n < self.window:
            return None
        data = np.concatenate(self._blocks)
        self._blocks, self._n = [], 0
        self._hist = np.concatenate([self._hist, data])[-8192:]
        peak = float(np.max(np.abs(data)))
        rms = float(np.sqrt(np.mean(np.square(data, dtype=np.float64))))
        spec = np.abs(np.fft.rfft(self._hist * np.hanning(len(self._hist))))
        freqs = np.fft.rfftfreq(len(self._hist), 1 / self.fs)
        band = (freqs >= 300) & (freqs <= 1500)
        tone = int(round(float(freqs[band][np.argmax(spec[band])])))
        db = lambda v: round(20 * float(np.log10(max(v, 1e-9))), 1)
        level = {"rms_dbfs": db(rms), "peak_dbfs": db(peak), "tone_hz": tone, "warning": ""}
        if level["peak_dbfs"] > self.CLIP_DBFS:
            level["warning"] = "clip"
        elif level["rms_dbfs"] < self.WEAK_DBFS:
            level["warning"] = "weak"
        elif not 400 <= tone <= 1200:
            level["warning"] = "tone"
        return level
