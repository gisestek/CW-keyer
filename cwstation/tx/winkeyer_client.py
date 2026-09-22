"""Serial client for K1EL WinKeyer (and compatible keyers such as K3NG in
WinKeyer emulation), so the program can be tried with hardware people already own.

Host mode, as described in K1EL's Winkeyer2 datasheet and interface guide:
1200 baud, 8 data bits, no parity, 2 stop bits, DTR on and RTS off (the lines
power the chip in some interfaces). The host opens the interface with
`00 02`, the keyer answers with its firmware revision byte, and after that
characters written to the port are sent as Morse.

Bytes coming back are identified by their two or three top bits:
  110x xxxx  status byte (WAIT, KEYDOWN, BUSY, BREAKIN, XOFF)
  10xx xxxx  speed potentiometer position
  0xxx xxxx  a character that has just been sent (serial echoback)

Published on the bus, the same events as the WiFi keyer client:
  keyer.status {state, url, host, fw, version, simulated}
  keyer.error  {code, msg}
  tx.echo      {ch}
  tx.state     {busy, key, pending}
  tx.stopped   {reason}

SAFETY (SR-04): WinKeyer has no heartbeat. If this program stops talking to it,
the keyer still sends whatever is in its 128 character buffer — up to about a
minute of carrier at 20 WPM. The program clears the buffer on STOP, on closing
and when the port disappears, but it cannot protect against its own crash. The
WiFi keyer in `firmware/cwkeyer-esp8266/` stops within 3 seconds in that case.

License: AGPL-3.0-or-later.
"""
from __future__ import annotations

import logging
import threading
import time

from ..core.bus import Bus

log = logging.getLogger(__name__)

BAUD = 1200
RECONNECT_S = 3.0
OPEN_TIMEOUT_S = 3.0

# host mode commands
ADMIN = 0x00
ADMIN_OPEN = 0x02
ADMIN_CLOSE = 0x03
CMD_SPEED = 0x02          # <02><wpm 5..99>
CMD_WEIGHT = 0x03         # <03><10..90>
CMD_CLEAR = 0x0A          # clears the buffer and cuts the character being sent
CMD_MODE = 0x0E           # <0E><mode register>
CMD_KEY_IMMEDIATE = 0x0B  # <0B><1|0> tune
CMD_MERGE = 0x1B          # <1B><c1><c2> prosign: two letters sent as one

MODE_SERIAL_ECHO = 0x04   # bit 2: send every character back after it has been keyed
MODE_DEFAULT = MODE_SERIAL_ECHO   # iambic B, paddle watchdog on, no autospace

STATUS_MASK = 0xC0
STATUS_TAG = 0xC0
POT_TAG = 0x80
ST_KEYDOWN = 0x08
ST_BUSY = 0x04
ST_BREAKIN = 0x02


def open_serial(port: str):
    """Default transport: a real serial port (pyserial imported only when needed)."""
    try:
        import serial
    except ImportError as e:  # pragma: no cover - only without the dependency
        raise OSError("pyserial is not installed (pip install pyserial)") from e

    return serial.Serial(port=port, baudrate=BAUD, bytesize=8, parity="N", stopbits=2,
                         timeout=0.2, dsrdtr=False, rtscts=False)


def list_ports() -> list[str]:
    try:
        from serial.tools import list_ports as lp
    except Exception:  # noqa: BLE001  pyserial missing
        return []
    return [f"{p.device} – {p.description}" if p.description else p.device for p in lp.comports()]


class WinkeyerClient:
    """Same interface as tx.keyer_client.KeyerClient, but over a serial WinKeyer."""

    def __init__(self, bus: Bus, port: str, initial_set: dict | None = None,
                 simulated: bool = False, transport_factory=None):
        self.bus = bus
        self.url = port or ""
        self.initial_set = dict(initial_set or {})
        self.simulated = simulated
        self._factory = transport_factory or open_serial
        self._ser = None
        self._lock = threading.RLock()     # guards writes to the port
        self._connected = threading.Event()
        self._running = False
        self._thread: threading.Thread | None = None
        self._busy = False
        self.fw = "winkeyer"
        self.version = ""
        self.cfg: dict = {}
        self.last_rtt_ms: float | None = None

    # ------------------------------------------------------------------ API
    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def host(self) -> str:
        return (self.url or "").split(" ")[0]

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._thread_main, name="winkeyer", daemon=True)
        self._thread.start()

    def send(self, obj: dict) -> bool:
        """Accepts the same commands as the WiFi keyer: send / stop / set / tune."""
        cmd = obj.get("cmd")
        if cmd == "stop":
            return self.stop_now()
        if not self.connected:
            return False
        try:
            if cmd == "send":
                return self._write(self._encode(obj.get("text", "")))
            if cmd == "set":
                out = bytearray()
                if "wpm" in obj:
                    out += bytes([CMD_SPEED, max(5, min(99, int(obj["wpm"])))])
                if "weight" in obj:
                    out += bytes([CMD_WEIGHT, max(10, min(90, int(obj["weight"])))])
                return self._write(bytes(out)) if out else True
            if cmd == "tune":
                on = 1 if obj.get("on", obj.get("seconds", 0)) else 0
                return self._write(bytes([CMD_KEY_IMMEDIATE, on]))
            if cmd == "ping":
                return True          # no equivalent; the keyer has no heartbeat
        except Exception as e:  # noqa: BLE001
            log.warning("winkeyer write failed: %s", e)
            self._drop(str(e))
        return False

    def stop_now(self, timeout: float = 0.5) -> bool:
        """STOP: clear the buffer, which also cuts the character being sent (SR-01)."""
        if not self.connected:
            return False
        ok = self._write(bytes([CMD_CLEAR]))
        if ok:
            self._busy = False
            self.bus.publish("tx.stopped", reason="host")
            self.bus.publish("tx.state", busy=False, key=False, pending=0)
        return ok

    def set_url(self, port: str) -> None:
        if port != self.url:
            self.url = port
            self._close_port()

    def reconnect(self) -> None:
        self._close_port()

    def shutdown(self) -> None:
        """Clear the buffer, close host mode, stop the thread (SR-05)."""
        if self._thread is None or not self._thread.is_alive():
            self._running = False
            self._close_port()
            return
        if self.connected:
            self._write(bytes([CMD_CLEAR]))
            self._write(bytes([ADMIN, ADMIN_CLOSE]))
        self._running = False
        self._close_port()
        self._thread.join(timeout=3)

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _encode(text: str) -> bytes:
        """Text to WinKeyer bytes; <SK> and other two letter prosigns are merged."""
        out = bytearray()
        i = 0
        up = text.upper()
        while i < len(up):
            ch = up[i]
            if ch == "<":
                end = up.find(">", i)
                if end > i:
                    inner = up[i + 1:end]
                    if len(inner) == 2:
                        out += bytes([CMD_MERGE]) + inner.encode("ascii", "ignore")
                    else:
                        out += inner.encode("ascii", "ignore")
                    i = end + 1
                    continue
            if ch == ">":
                i += 1
                continue
            out += ch.encode("ascii", "ignore")
            i += 1
        return bytes(out)

    def _write(self, data: bytes) -> bool:
        with self._lock:
            ser = self._ser
            if ser is None or not data:
                return bool(data) is False
            try:
                ser.write(data)
                flush = getattr(ser, "flush", None)
                if flush:
                    flush()
                return True
            except Exception as e:  # noqa: BLE001
                log.warning("winkeyer write failed: %s", e)
                self._drop(str(e))
                return False

    def _drop(self, msg: str) -> None:
        self._connected.clear()
        self._close_port()
        self.bus.publish("keyer.error", code="PORT_LOST", msg=msg)

    def _close_port(self) -> None:
        with self._lock:
            ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass

    def _status(self, state: str) -> None:
        self.bus.publish("keyer.status", state=state, url=self.url, host=self.host, fw=self.fw,
                         version=self.version, simulated=self.simulated)

    def _thread_main(self) -> None:
        while self._running:
            if not self.url:
                time.sleep(RECONNECT_S)
                continue
            self._status("connecting")
            try:
                ser = self._factory(self.host)
            except Exception as e:  # noqa: BLE001
                log.info("winkeyer open failed: %s", e)
                self.bus.publish("keyer.error", code="PORT_ERROR", msg=str(e))
                self._status("disconnected")
                time.sleep(RECONNECT_S)
                continue
            with self._lock:
                self._ser = ser
            try:
                if not self._open_host_mode(ser):
                    raise OSError("no answer to host open")
                self._connected.set()
                self._status("connected")
                self._read_loop(ser)
            except Exception as e:  # noqa: BLE001
                log.info("winkeyer session ended: %s", e)
                self.bus.publish("keyer.error", code="PORT_ERROR", msg=str(e))
            finally:
                self._connected.clear()
                self._close_port()
                self.bus.publish("tx.state", busy=False, key=False, pending=0)
                self._status("disconnected")
            if self._running:
                time.sleep(RECONNECT_S)

    def _open_host_mode(self, ser) -> bool:
        for name, value in (("dtr", True), ("rts", False)):
            try:
                setattr(ser, name, value)
            except Exception:  # noqa: BLE001  not all transports have the lines
                pass
        time.sleep(0.05)
        try:
            ser.reset_input_buffer()
        except Exception:  # noqa: BLE001
            pass
        ser.write(bytes([ADMIN, ADMIN_OPEN]))
        deadline = time.time() + OPEN_TIMEOUT_S
        while time.time() < deadline:
            data = ser.read(1)
            if data:
                self.version = str(data[0])
                break
            time.sleep(0.05)
        else:
            return False
        ser.write(bytes([CMD_MODE, MODE_DEFAULT]))
        wpm = self.initial_set.get("wpm")
        weight = self.initial_set.get("weight")
        if wpm:
            ser.write(bytes([CMD_SPEED, max(5, min(99, int(wpm)))]))
        if weight:
            ser.write(bytes([CMD_WEIGHT, max(10, min(90, int(weight)))]))
        self.cfg = {"fw": self.version, "wpm": wpm, "weight": weight, "protocol": "winkeyer"}
        self.bus.publish("keyer.config", cfg=self.cfg)
        return True

    def _read_loop(self, ser) -> None:
        while self._running and self._ser is ser:
            data = ser.read(1)
            if not data:
                continue
            b = data[0]
            if (b & STATUS_MASK) == STATUS_TAG:
                busy = bool(b & ST_BUSY)
                key = bool(b & ST_KEYDOWN)
                if busy != self._busy or key:
                    self._busy = busy
                    self.bus.publish("tx.state", busy=busy, key=key, pending=0)
                if b & ST_BREAKIN:
                    self.bus.publish("keyer.error", code="BREAKIN", msg="paddle break-in")
            elif (b & STATUS_MASK) == POT_TAG:
                continue                      # speed pot position: not used
            elif 0x20 <= b < 0x80:
                self.bus.publish("tx.echo", ch=chr(b))
