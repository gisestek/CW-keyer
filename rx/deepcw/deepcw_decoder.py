"""DeepCW-mallin kääre ja reaaliaikainen (striimaava) dekoodaus.

Malli ja spektrogrammi: e04/deepcw-engine (AGPL-3.0-only).
Striimauslogiikka mukailee e04/web-deep-cw-decoder -sovelluksen
useStreamingDecode-algoritmia: puskuroitu ääni dekoodataan noin kerran
sekunnissa, tulos näytetään esikatseluna, ja teksti vahvistetaan viimeisen
sanavälin kohdalta, joka on riittävän kaukana puskurin lopusta.

Lisenssi: AGPL-3.0-or-later.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import onnxruntime as ort


# ---------------------------------------------------------------------------
# Malli
# ---------------------------------------------------------------------------
@dataclass
class CharSpan:
    char: str
    start_frame: int
    end_frame: int


@dataclass
class DecodeResult:
    text: str                      # CTC-purettu teksti
    char_spans: list[CharSpan]     # merkki per span (sisältää välilyönnit)
    space_spans: list[tuple[int, int]]  # sanavälien kehysvälit
    frames: int


class DeepCWModel:
    def __init__(self, model_path: Path, metadata_path: Path, threads: int = 0):
        with open(metadata_path, "r", encoding="utf-8") as f:
            self.meta = json.load(f)
        m = self.meta
        self.sample_rate = int(m["sample_rate"])
        self.fft = int(m["fft_length"])
        self.hop = int(m["hop_length"])
        self.chars: list[str] = list(m["chars"])
        self.blank = int(m["blank_index"])
        self.space = self.chars.index(" ")
        bin_hz = self.sample_rate / self.fft
        self.bin_start = int(math.ceil(float(m["spectrogram_min_freq_hz"]) / bin_hz))
        self.bin_stop = int(math.floor(float(m["spectrogram_max_freq_hz"]) / bin_hz)) + 1
        if self.bin_stop - self.bin_start != int(m["spectrogram_frequency_bins"]):
            raise ValueError("metadata frequency bins mismatch")
        if m.get("normalization") != "log1p":
            raise ValueError("unsupported normalization")
        self.window = np.hanning(self.fft + 1)[:-1].astype(np.float32)
        opts = ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])
        self.in_name = m["onnx_input_name"]
        self.out_name = m["onnx_output_name"]

    @property
    def seconds_per_frame(self) -> float:
        return self.hop / self.sample_rate

    def spectrogram(self, audio: np.ndarray) -> np.ndarray:
        """[1, 1, time, freq] float32, sama laskenta kuin deepcw-enginen esimerkissä."""
        pad = self.fft // 2
        x = np.pad(audio.astype(np.float32, copy=False), (pad, pad), mode="reflect")
        frames = 1 + (len(x) - self.fft) // self.hop
        idx = np.arange(self.fft)[None, :] + self.hop * np.arange(frames)[:, None]
        spec = np.abs(np.fft.rfft(x[idx] * self.window, n=self.fft, axis=1))[:, self.bin_start:self.bin_stop]
        spec = np.log1p(spec.astype(np.float32))
        return spec[np.newaxis, np.newaxis, :, :]

    def decode(self, audio: np.ndarray) -> DecodeResult:
        if len(audio) < self.fft:
            return DecodeResult("", [], [], 0)
        spec = self.spectrogram(audio)
        logp = self.session.run([self.out_name], {self.in_name: spec})[0][0]
        best = logp.argmax(axis=-1)
        return self._ctc(best)

    def _ctc(self, best: np.ndarray) -> DecodeResult:
        spans: list[CharSpan] = []
        spaces: list[tuple[int, int]] = []
        prev = None
        space_start = -1
        for f, i in enumerate(best.tolist()):
            if i == self.space:
                if space_start < 0:
                    space_start = f
            elif space_start >= 0:
                spaces.append((space_start, f - 1))
                space_start = -1
            if i == self.blank:
                prev = None
                continue
            if i == prev:
                spans[-1].end_frame = f
                continue
            prev = i
            spans.append(CharSpan(self.chars[i], f, f))
        if space_start >= 0:
            spaces.append((space_start, len(best) - 1))
        text = "".join(s.char for s in spans)
        return DecodeResult(text, spans, spaces, len(best))


def normalize_text(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Striimaus
# ---------------------------------------------------------------------------
@dataclass
class StreamConfig:
    max_segment_s: float = 20.0      # pisin kerralla dekoodattava pätkä
    tail_guard_s: float = 1.25       # näin lähellä loppua olevaa sanaväliä ei vahvisteta
    min_pending_s: float = 2.0       # dekoodataan vasta, kun ääntä on näin paljon
    min_confirmed_s: float = 2.0     # lyhyin vahvistettava pätkä
    interval_s: float = 1.0          # dekoodausväli
    preroll_s: float = 1.5           # vahvistetun osan loppua pidetään mukana kontekstina


@dataclass
class StreamEvent:
    kind: str                # "final" tai "pending"
    text: str
    audio_start_s: float     # pätkän alku striimin aikajanalla (s)
    audio_end_s: float
    infer_ms: float = 0.0


class StreamingDecoder:
    """Syötä ääntä (mallin näytetaajuudella) feed()-metodilla; palauttaa tapahtumat."""

    def __init__(self, model: DeepCWModel, cfg: StreamConfig | None = None):
        self.m = model
        self.cfg = cfg or StreamConfig()
        sr = model.sample_rate
        self._max = int(self.cfg.max_segment_s * sr)
        self._guard = int(self.cfg.tail_guard_s * sr)
        self._min_pending = int(self.cfg.min_pending_s * sr)
        self._min_conf = int(self.cfg.min_confirmed_s * sr)
        self._interval = int(self.cfg.interval_s * sr)
        self._preroll = int(self.cfg.preroll_s * sr)
        self._skip = 0                # puskurin alusta näin monta näytettä on jo vahvistettu (konteksti)
        self._buf = np.zeros(0, dtype=np.float32)
        self._offset = 0              # puskurin alun paikka striimissä (näytteinä)
        self._since_decode = 0
        self.last_pending = ""
        self.infer_ms_total = 0.0
        self.infer_audio_s_total = 0.0
        self.infer_calls = 0

    def feed(self, samples: np.ndarray) -> list[StreamEvent]:
        self._buf = np.concatenate([self._buf, samples.astype(np.float32, copy=False)])
        self._since_decode += len(samples)
        events: list[StreamEvent] = []
        # Jos puskuri kasvaa yli maksimin (esim. hidas kone), dekoodataan heti.
        while len(self._buf) - self._skip >= self._min_pending and (
            self._since_decode >= self._interval or len(self._buf) > self._max
        ):
            self._since_decode = 0
            events.extend(self._step(force_all=False))
            if len(self._buf) <= self._max:
                break
        return events

    def flush(self) -> list[StreamEvent]:
        """Vahvista kaikki jäljellä oleva (esim. WAV-tiedoston lopussa)."""
        if len(self._buf) - self._skip < self.m.fft:
            return []
        return self._step(force_all=True)

    # -- sisäinen --
    def _time(self, sample: int) -> float:
        return (self._offset + sample) / self.m.sample_rate

    def _frame_to_sample(self, frame: float) -> int:
        return int(round(frame * self.m.hop))  # kehys f keskittyy näytteeseen f*hop

    def _step(self, force_all: bool) -> list[StreamEvent]:
        import time

        n = min(len(self._buf), self._max)
        audio = self._buf[:n]
        t0 = time.perf_counter()
        res = self.m.decode(audio)
        dt = (time.perf_counter() - t0) * 1000
        self.infer_ms_total += dt
        self.infer_audio_s_total += n / self.m.sample_rate
        self.infer_calls += 1

        events: list[StreamEvent] = []
        skip_frame = self._skip / self.m.hop
        new_spans = [c for c in res.char_spans if c.start_frame >= skip_frame]
        pending_text = normalize_text("".join(c.char for c in new_spans))
        if pending_text != self.last_pending:
            self.last_pending = pending_text
            events.append(StreamEvent("pending", pending_text, self._time(self._skip), self._time(n), dt))

        if force_all:
            split_sample, end_frame = n, res.frames
        else:
            split = self._find_split(res, n, allow_near_end=False)
            if split is None and len(self._buf) >= self._max:
                split = self._find_split(res, n, allow_near_end=True)
                if split is None:
                    split = (n, res.frames)  # ei sanaväliä: vahvistetaan kaikki
            if split is None:
                return events
            split_sample, end_frame = split

        text = normalize_text("".join(c.char for c in new_spans if c.end_frame <= end_frame))
        if text:
            events.append(StreamEvent("final", text, self._time(self._skip), self._time(split_sample), dt))
        new_start = max(0, split_sample - self._preroll) if not force_all else split_sample
        self._buf = self._buf[new_start:]
        self._offset += new_start
        self._skip = split_sample - new_start
        self.last_pending = ""
        return events

    def _find_split(self, res: DecodeResult, n: int, allow_near_end: bool):
        min_sample = self._skip + self._min_conf
        max_sample = n if allow_near_end else max(min_sample, n - self._guard)
        for start, end in reversed(res.space_spans):
            s = self._frame_to_sample((start + end) / 2)
            if min_sample <= s <= max_sample:
                return s, end
        return None
