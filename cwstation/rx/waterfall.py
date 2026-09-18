"""Short-time spectrum for the waterfall display (rx.spectrum messages)."""
from __future__ import annotations

import numpy as np

F_MIN_HZ = 100.0
F_MAX_HZ = 1500.0


class SpectrumProcessor:
    """Consumes audio at `fs` (the model rate, 3200 Hz) and yields dB columns.

    Window 256 samples (80 ms, same as the DeepCW model) zero-padded to 512
    for a smoother picture; hop 48 samples = 15 ms per column (≈67 columns/s).
    """

    def __init__(self, fs: int = 3200, win: int = 256, nfft: int = 512, hop: int = 48):
        self.fs, self.win, self.nfft, self.hop = fs, win, nfft, hop
        self.window = np.hanning(win + 1)[:-1].astype(np.float32)
        self.df = fs / nfft
        self.b0 = int(np.ceil(F_MIN_HZ / self.df))
        self.b1 = int(np.floor(F_MAX_HZ / self.df)) + 1
        self.f0 = self.b0 * self.df
        self._buf = np.zeros(0, dtype=np.float32)
        self._consumed = 0  # samples before _buf[0] (for column times)
        self._norm = 20 * np.log10(self.window.sum() / 2)

    @property
    def bins(self) -> int:
        return self.b1 - self.b0

    @property
    def dt(self) -> float:
        return self.hop / self.fs

    def feed(self, x: np.ndarray) -> tuple[float, np.ndarray]:
        """Returns (time_of_first_column_s, columns[n, bins] in dBFS)."""
        self._buf = np.concatenate([self._buf, x.astype(np.float32, copy=False)])
        n = 0 if len(self._buf) < self.win else 1 + (len(self._buf) - self.win) // self.hop
        if n == 0:
            return 0.0, np.zeros((0, self.bins), dtype=np.float32)
        idx = np.arange(self.win)[None, :] + self.hop * np.arange(n)[:, None]
        spec = np.abs(np.fft.rfft(self._buf[idx] * self.window, n=self.nfft, axis=1))[:, self.b0:self.b1]
        db = 20 * np.log10(spec + 1e-9) - self._norm
        t_first = (self._consumed + self.win / 2) / self.fs
        drop = n * self.hop
        self._buf = self._buf[drop:]
        self._consumed += drop
        return t_first, db.astype(np.float32)
