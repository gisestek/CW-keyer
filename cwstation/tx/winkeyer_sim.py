"""WinKeyer simulator: enough of the host mode protocol to develop and test
`winkeyer_client.py` without the hardware.

It looks like a serial port (`write`, `read`, `close`, `dtr`, `rts`) and behaves
like a WinKeyer: answers the host open command with a revision byte, keys the
text at the set speed, echoes every character back once it has been sent, and
reports busy/idle with status bytes. `0x0A` clears the buffer immediately.

License: AGPL-3.0-or-later.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from .winkeyer_client import (
    ADMIN, ADMIN_CLOSE, ADMIN_OPEN, CMD_CLEAR, CMD_KEY_IMMEDIATE, CMD_MERGE, CMD_MODE,
    CMD_SPEED, CMD_WEIGHT, ST_BUSY, ST_KEYDOWN, STATUS_TAG,
)

REVISION = 23          # WinKeyer2 v2.3
BUFFER_LIMIT = 128


class WinkeyerSim:
    """Serial-like WinKeyer. `sent` collects everything it has keyed."""

    def __init__(self, revision: int = REVISION, speed_factor: float = 20.0):
        """speed_factor > 1 runs the Morse faster than real time, for quick tests."""
        self.revision = revision
        self.speed_factor = speed_factor
        self.wpm = 20
        self.weight = 50
        self.mode = 0
        self.opened = False
        self.closed = False
        self.dtr = False
        self.rts = True
        self.sent: list[str] = []          # characters actually keyed
        self.cleared = 0                   # how many times the buffer was cleared
        self._out = deque()                # bytes towards the host
        self._buf: deque[str] = deque()    # characters waiting to be keyed
        self._pending = bytearray()        # incomplete command
        self._lock = threading.RLock()
        self._busy = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="winkeyer-sim", daemon=True)
        self._thread.start()

    # -- serial-like interface --
    def write(self, data: bytes) -> int:
        if self.closed:
            raise OSError("port is closed")       # like pyserial when the cable is pulled
        with self._lock:
            self._pending += bytes(data)
            self._parse()
        return len(data)

    def read(self, n: int = 1) -> bytes:
        if self.closed:
            raise OSError("port is closed")
        deadline = time.time() + 0.2
        out = bytearray()
        while len(out) < n:
            with self._lock:
                while self._out and len(out) < n:
                    out.append(self._out.popleft())
            if len(out) >= n or time.time() > deadline:
                break
            time.sleep(0.005)
        return bytes(out)

    def reset_input_buffer(self) -> None:
        with self._lock:
            self._out.clear()

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True
        self._stop.set()

    # -- protocol --
    def _parse(self) -> None:
        while self._pending:
            b = self._pending[0]
            if b == ADMIN:
                if len(self._pending) < 2:
                    return
                sub = self._pending[1]
                del self._pending[:2]
                if sub == ADMIN_OPEN:
                    self.opened = True
                    self._out.append(self.revision)
                elif sub == ADMIN_CLOSE:
                    self.opened = False
                    self._buf.clear()
                continue
            if b in (CMD_SPEED, CMD_WEIGHT, CMD_MODE, CMD_KEY_IMMEDIATE):
                if len(self._pending) < 2:
                    return
                value = self._pending[1]
                del self._pending[:2]
                if b == CMD_SPEED:
                    self.wpm = value
                elif b == CMD_WEIGHT:
                    self.weight = value
                elif b == CMD_MODE:
                    self.mode = value
                continue
            if b == CMD_MERGE:
                if len(self._pending) < 3:
                    return
                pair = self._pending[1:3].decode("ascii", "ignore")
                del self._pending[:3]
                self._queue(f"<{pair}>")
                continue
            if b == CMD_CLEAR:
                del self._pending[:1]
                self._buf.clear()
                self.cleared += 1
                continue
            if b < 0x20:                      # any other command byte: ignore it
                del self._pending[:1]
                continue
            ch = chr(b)
            del self._pending[:1]
            self._queue(ch)

    def _queue(self, item: str) -> None:
        if len(self._buf) < BUFFER_LIMIT:
            self._buf.append(item)

    def _status(self, busy: bool, key: bool = False) -> None:
        self._out.append(STATUS_TAG | (ST_BUSY if busy else 0) | (ST_KEYDOWN if key else 0))

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                item = self._buf.popleft() if self._buf else None
                if item is not None and not self._busy:
                    self._busy = True
                    self._status(True)
                elif item is None and self._busy:
                    self._busy = False
                    self._status(False)
            if item is None:
                time.sleep(0.005)
                continue
            # PARIS timing: a character plus its space is about 7 dit units
            unit = 1.2 / max(5, self.wpm) / max(1.0, self.speed_factor)
            time.sleep(unit * (14 if item == " " else 7 * len(item.strip("<>"))))
            with self._lock:
                self.sent.append(item)
                for ch in (item if len(item) == 1 else item.strip("<>")):
                    self._out.append(ord(ch))     # serial echoback

    # -- helpers for tests --
    def text(self) -> str:
        return "".join(self.sent)

    def wait_idle(self, timeout: float = 5.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                if not self._buf and not self._busy:
                    return True
            time.sleep(0.01)
        return False
