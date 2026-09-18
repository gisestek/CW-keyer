"""Waterfall (spectrogram) display like DeepCW's: time runs left to right, frequency upwards.

Shows 100–1500 Hz, marks the band the decoder uses (400–1200 Hz), our own
transmissions (red bar at the bottom) and the current strongest tone.
"""
from __future__ import annotations

import colorsys
import datetime as dt
import time
from collections import deque

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

DECODE_MIN_HZ = 400
DECODE_MAX_HZ = 1200
RANGE_DB = 45.0
MAX_SECONDS = 30


def build_lut() -> np.ndarray:
    """256-entry colour map, same formula as the DeepCW web app (blue -> red/yellow)."""
    lut = np.zeros((256, 4), dtype=np.uint8)
    for v in range(256):
        t = (v / 255) ** 2.2
        r, g, b = colorsys.hls_to_rgb((220 * (1 - t)) / 360, 0.15 + 0.75 * t, 1.0)
        lut[v] = (int(b * 255), int(g * 255), int(r * 255), 255)  # QImage.Format_RGB32 is BGRA in memory
    return lut


class WaterfallWidget(QWidget):
    def __init__(self, tx_windows=None, seconds: int = 12, parent=None):
        super().__init__(parent)
        self.tx_windows = tx_windows
        self.seconds = seconds
        self.setMinimumHeight(80)
        self._lut = build_lut()
        self._cols: deque[np.ndarray] = deque()
        self._times: deque[float] = deque()
        self._dt = 0.015
        self._f0 = 100.0
        self._df = 6.25
        self._floor = -90.0
        self._tone_hz: int | None = None
        self._tone_t = 0.0
        self._image: QImage | None = None
        self._dirty = False
        self._timer = QTimer(self, interval=66)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self.setToolTip("Waterfall: 100–1500 Hz. Dashed lines = decoder band 400–1200 Hz. Red bar = your transmission.")

    # -- data --
    def add_spectrum(self, m: dict) -> None:
        cols = np.asarray(m.get("cols", []), dtype=np.float32) / 2.0
        if cols.size == 0:
            return
        self._dt, self._f0, self._df = float(m["dt"]), float(m["f0"]), float(m["df"])
        t0 = float(m["t0"])
        for i, c in enumerate(cols):
            self._cols.append(c)
            self._times.append(t0 + i * self._dt)
        max_cols = int(MAX_SECONDS / self._dt) + 10
        while len(self._cols) > max_cols:
            self._cols.popleft()
            self._times.popleft()
        # slow noise-floor tracker (20th percentile of the newest columns)
        recent = cols[-min(len(cols), 20):]
        floor = float(np.percentile(recent, 20))
        self._floor += 0.1 * (floor - self._floor)
        self._dirty = True

    def set_tone(self, hz: int | None) -> None:
        self._tone_hz, self._tone_t = hz, time.time()

    def set_seconds(self, seconds: int) -> None:
        self.seconds = seconds
        self._dirty = True

    def clear(self) -> None:
        self._cols.clear()
        self._times.clear()
        self._dirty = True

    # -- drawing --
    def _refresh(self) -> None:
        if self._dirty:
            self._build_image()
        self.update()  # repaint anyway: the TX bar and time axis move

    def _build_image(self) -> None:
        self._dirty = False
        n = int(self.seconds / self._dt)
        if not self._cols:
            self._image = None
            return
        cols = list(self._cols)[-n:]
        data = np.stack(cols, axis=1)  # [bins, time]
        vals = np.clip((data - self._floor + 6) / RANGE_DB * 255, 0, 255).astype(np.uint8)
        vals = vals[::-1, :]  # high frequencies on top
        if vals.shape[1] < n:  # pad the left side (older than available data) with background
            pad = np.zeros((vals.shape[0], n - vals.shape[1]), dtype=np.uint8)
            vals = np.concatenate([pad, vals], axis=1)
        rgba = np.ascontiguousarray(self._lut[vals])
        h, w = rgba.shape[:2]
        self._image = QImage(rgba.data, w, h, 4 * w, QImage.Format_RGB32).copy()

    def _y_for_hz(self, hz: float, rect: QRectF, bins: int) -> float:
        frac = (hz - self._f0) / (bins * self._df)
        return rect.bottom() - frac * rect.height()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        r = QRectF(self.rect())
        axis_w = 38
        plot = QRectF(r.left() + axis_w, r.top(), r.width() - axis_w, r.height() - 14)
        p.fillRect(r, QColor(12, 13, 16))
        bins = len(self._cols[0]) if self._cols else int((1500 - 100) / self._df)
        if self._image is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawImage(plot, self._image)

        now = self._times[-1] + self._dt if self._times else time.time()
        t_left = now - self.seconds
        x_of = lambda t: plot.left() + (t - t_left) / self.seconds * plot.width()

        # decoder band
        pen = QPen(QColor(255, 255, 255, 110), 1, Qt.DashLine)
        p.setPen(pen)
        for hz in (DECODE_MIN_HZ, DECODE_MAX_HZ):
            y = self._y_for_hz(hz, plot, bins)
            p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

        # frequency labels
        p.setPen(QColor(190, 190, 190))
        f = p.font()
        f.setPointSize(8)
        p.setFont(f)
        for hz in (400, 800, 1200):
            y = self._y_for_hz(hz, plot, bins)
            p.drawText(QRectF(r.left(), y - 7, axis_w - 4, 14), Qt.AlignRight | Qt.AlignVCenter, str(hz))

        # own transmissions
        if self.tx_windows is not None:
            for s, e in self.tx_windows.windows(t_left):
                x0 = max(plot.left(), x_of(s))
                x1 = min(plot.right(), x_of(e if e is not None else now))
                if x1 > x0:
                    p.fillRect(QRectF(x0, plot.bottom() - 5, x1 - x0, 5), QColor(231, 76, 60))
                    p.fillRect(QRectF(x0, plot.top(), x1 - x0, plot.height() - 5), QColor(231, 76, 60, 28))

        # time ticks every 5 s
        p.setPen(QColor(170, 170, 170))
        step = 5 if self.seconds <= 18 else 10
        first = int(t_left // step + 1) * step
        for t in range(first, int(now) + 1, step):
            x = x_of(t)
            p.drawLine(int(x), int(plot.bottom()), int(x), int(plot.bottom() + 3))
            label = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%H:%M:%S")
            p.drawText(QRectF(x - 30, plot.bottom() + 1, 60, 13), Qt.AlignCenter, label)

        # strongest tone marker
        if self._tone_hz and time.time() - self._tone_t < 2 and 100 <= self._tone_hz <= 1500:
            y = self._y_for_hz(self._tone_hz, plot, bins)
            p.setPen(QPen(QColor(255, 255, 255), 2))
            p.drawLine(int(plot.right() - 8), int(y), int(plot.right()), int(y))
        p.end()
