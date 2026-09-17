"""WebSocket client for the CW keyer (firmware/cwkeyer-esp8266/PROTOCOL.md, v1).

Runs its own asyncio loop in a background thread. Keeps the connection alive,
sends a ping every second (the keyer stops transmitting if pings stop,
SR-04), and republishes keyer events on the bus:

  keyer.status  {state: "connecting"|"connected"|"disconnected", url, fw, version, controller, simulated}
  keyer.error   {code, msg}
  tx.echo       {ch}
  tx.state      {busy, key, pending}
  tx.stopped    {reason}
  tx.fault      {code}
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from urllib.parse import urlparse

from ..core.bus import Bus

log = logging.getLogger(__name__)

PING_INTERVAL_S = 1.0
RECONNECT_S = 2.0


class KeyerClient:
    def __init__(self, bus: Bus, url: str, initial_set: dict | None = None, simulated: bool = False):
        self.bus = bus
        self.url = url
        self.initial_set = dict(initial_set or {})
        self.simulated = simulated
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ws = None
        self._running = False
        self._connected = threading.Event()
        self._outq: asyncio.Queue | None = None
        self.fw = ""
        self.version = ""
        self.cfg: dict = {}
        self.last_rtt_ms: float | None = None
        self._paused = False  # set when another client takes control; cleared by reconnect()

    # ------------------------------------------------------------------ API (thread-safe)
    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def host(self) -> str:
        return urlparse(self.url).hostname or self.url

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._thread_main, name="keyer", daemon=True)
        self._thread.start()

    def send(self, obj: dict) -> bool:
        """Queue a command. Returns False (and drops it) if the keyer is not connected."""
        if not self.connected or self._loop is None or self._outq is None:
            return False
        self._loop.call_soon_threadsafe(self._outq.put_nowait, obj)
        return True

    def stop_now(self, timeout: float = 0.5) -> bool:
        """STOP with priority: bypasses the queue and waits until it is on the wire (SR-01)."""
        if not self.connected or self._loop is None:
            return False
        fut = asyncio.run_coroutine_threadsafe(self._send_stop(), self._loop)
        try:
            return bool(fut.result(timeout=timeout))
        except Exception:  # noqa: BLE001
            return False

    def set_url(self, url: str) -> None:
        if url != self.url:
            self.url = url
            self._reconnect()

    def reconnect(self) -> None:
        """Reconnect now (also after another client took control)."""
        self._paused = False
        self._reconnect()

    def shutdown(self) -> None:
        """Send STOP, close the connection and stop the thread (SR-05). Safe to call twice."""
        if self._thread is None or not self._thread.is_alive():
            self._running = False
            return
        self.stop_now()
        self._running = False
        try:
            if self._loop is not None and self._ws is not None:
                asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
        except RuntimeError:
            pass
        self._thread.join(timeout=3)

    # ------------------------------------------------------------------ internals
    def _reconnect(self) -> None:
        try:
            if self._loop is not None and self._ws is not None:
                asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
        except RuntimeError:
            pass

    def _status(self, state: str) -> None:
        self.bus.publish("keyer.status", state=state, url=self.url, host=self.host, fw=self.fw,
                         version=self.version, simulated=self.simulated)

    async def _send_stop(self) -> bool:
        if self._ws is None:
            return False
        if self._outq is not None:
            while not self._outq.empty():
                self._outq.get_nowait()
        await self._ws.send(json.dumps({"cmd": "stop"}))
        return True

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        finally:
            self._loop.close()

    async def _main(self) -> None:
        import websockets

        self._outq = asyncio.Queue()
        while self._running:
            if self._paused:
                await asyncio.sleep(0.5)
                continue
            self._status("connecting")
            try:
                async with websockets.connect(self.url, ping_interval=None, open_timeout=4,
                                              close_timeout=1, max_queue=256) as ws:
                    self._ws = ws
                    await self._session(ws)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.info("keyer connection: %s", e)
            finally:
                was = self.connected
                self._connected.clear()
                self._ws = None
                if was:
                    # The keyer stops by itself when the controller disconnects;
                    # tell the rest of the program so the TX queue view clears.
                    self.bus.publish("tx.stopped", reason="connection_lost")
                self._status("disconnected")
            if self._running:
                await asyncio.sleep(RECONNECT_S)

    async def _session(self, ws) -> None:
        await ws.send(json.dumps({"cmd": "hello", "client": "cwstation"}))
        # wait for the hello that confirms we are the controller
        deadline = time.monotonic() + 4
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.monotonic()))
            msg = json.loads(raw)
            if msg.get("ev") == "hello" and msg.get("controller"):
                self.fw, self.version = msg.get("fw", ""), msg.get("version", "")
                self.cfg = msg.get("cfg", {})
                break
        while not self._outq.empty():  # never send text typed while disconnected
            self._outq.get_nowait()
        await ws.send(json.dumps({"cmd": "stop"}))  # clean state after (re)connect
        if self.initial_set:
            await ws.send(json.dumps({"cmd": "set", **self.initial_set}))
        self._connected.set()
        self._status("connected")

        async def reader():
            async for raw in ws:
                try:
                    self._dispatch(json.loads(raw))
                except ValueError:
                    log.warning("bad message from keyer: %r", raw)

        async def writer():
            while True:
                obj = await self._outq.get()
                if obj.get("cmd") == "set":
                    self.initial_set.update({k: v for k, v in obj.items() if k != "cmd"})
                await ws.send(json.dumps(obj))

        async def pinger():
            while True:
                await asyncio.sleep(PING_INTERVAL_S)
                await ws.send(json.dumps({"cmd": "ping", "t": int(time.time() * 1000)}))

        tasks = [asyncio.create_task(c()) for c in (reader, writer, pinger)]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if t.exception():
                    log.info("keyer session ended: %s", t.exception())
        finally:
            for t in tasks:
                t.cancel()

    def _dispatch(self, msg: dict) -> None:
        ev = msg.get("ev")
        if ev == "echo":
            self.bus.publish("tx.echo", ch=msg.get("ch", ""))
        elif ev == "state":
            self.bus.publish("tx.state", busy=bool(msg.get("busy")), key=bool(msg.get("key")),
                             pending=msg.get("pending", 0))
        elif ev == "stopped":
            self.bus.publish("tx.stopped", reason=msg.get("reason", ""))
        elif ev == "fault":
            self.bus.publish("tx.fault", code=msg.get("code", ""))
        elif ev == "config":
            self.cfg = msg.get("cfg", {})
            self.bus.publish("keyer.config", cfg=self.cfg)
        elif ev == "pong":
            try:
                self.last_rtt_ms = time.time() * 1000 - float(msg.get("t"))
            except (TypeError, ValueError):
                pass
        elif ev == "control" and msg.get("owner") is False:
            self.bus.publish("keyer.error", code="CONTROL_LOST", msg="another client took control")
            self._paused = True
            self._reconnect()
        elif ev == "error":
            self.bus.publish("keyer.error", code=msg.get("code", ""), msg=msg.get("msg", ""))
