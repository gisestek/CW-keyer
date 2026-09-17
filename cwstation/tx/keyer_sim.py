"""Software keyer simulator implementing PROTOCOL.md v1 on localhost.

For development and tests without the ESP8266 keyer: same messages, same
timing (PARIS), same safety limits (heartbeat, TX limit, STOP). Nothing is
keyed. Run standalone:  python -m cwstation.tx.keyer_sim --port 8181
"""
from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....",
    "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.",
    "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..", "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.", ".": ".-.-.-", ",": "--..--",
    "?": "..--..", "/": "-..-.", "=": "-...-", "+": ".-.-.", "-": "-....-", "(": "-.--.", ")": "-.--.-",
    '"': ".-..-.", "'": ".----.", ":": "---...", ";": "-.-.-.", "@": ".--.-.", "!": "-.-.--",
}

LIMITS_MAX = {"keydown_max_ms": 10500, "tune_max_ms": 10000, "tx_max_ms": 120000, "heartbeat_ms": 3000}
LIMITS_MIN = {"keydown_max_ms": 1000, "tune_max_ms": 500, "tx_max_ms": 10000, "heartbeat_ms": 500}


class KeyerSim:
    def __init__(self):
        self.cfg = {"wpm": 20, "weight": 50, **LIMITS_MAX}
        self.queue: list[str] = []
        self.busy = False
        self.key = False
        self.controller = None
        self.clients: set = set()
        self.last_host = time.monotonic()
        self.tx_since = time.monotonic()
        self._worker: asyncio.Task | None = None
        self.keyed_ms = 0.0  # total simulated key-down time (for tests)

    # -- messaging --
    async def _send(self, ws, obj):
        try:
            await ws.send(json.dumps(obj))
        except Exception:  # noqa: BLE001
            pass

    async def broadcast(self, obj):
        for ws in list(self.clients):
            await self._send(ws, obj)

    def hello(self, ws):
        return {"ev": "hello", "fw": "cwkeyer-sim", "version": "0.1.0", "proto": 1,
                "caps": ["cw", "tune", "echo"], "controller": ws is self.controller, "cfg": dict(self.cfg)}

    # -- keying --
    async def stop(self, reason: str, fault: str | None = None):
        self.queue.clear()
        if self._worker and not self._worker.done():
            self._worker.cancel()
        self.key = False
        was_busy = self.busy
        self.busy = False
        if fault:
            await self.broadcast({"ev": "fault", "code": fault})
        await self.broadcast({"ev": "stopped", "reason": fault or reason})
        if was_busy:
            await self.broadcast({"ev": "state", "busy": False, "key": False, "pending": 0, "controller": 0})

    def ensure_worker(self):
        if not self._worker or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(self._run())

    async def _elem(self, ms: float, key: bool):
        self.key = key
        if key:
            self.keyed_ms += ms
        await asyncio.sleep(ms / 1000)

    async def _run(self):
        self.busy = True
        await self.broadcast({"ev": "state", "busy": True, "key": False, "pending": len(self.queue), "controller": 0})
        prosign = False
        try:
            while self.queue:
                ch = self.queue.pop(0)
                dit = 1200 / self.cfg["wpm"]
                adj = dit * (self.cfg["weight"] - 50) / 50
                if ch == "<":
                    prosign = True
                    await self.broadcast({"ev": "echo", "ch": "<"})
                    continue
                if ch == ">":
                    prosign = False
                    await self.broadcast({"ev": "echo", "ch": ">"})
                    await self._elem(2 * dit, False)
                    continue
                if ch == " ":
                    await self.broadcast({"ev": "echo", "ch": " "})
                    await self._elem(4 * dit, False)
                    continue
                code = MORSE.get(ch)
                if not code:
                    continue
                await self.broadcast({"ev": "echo", "ch": ch})
                for sym in code:
                    await self._elem((dit if sym == "." else 3 * dit) + adj, True)
                    await self._elem(dit - adj, False)
                if not prosign:
                    await self._elem(2 * dit, False)
        finally:
            self.key = False
            if self.busy:
                self.busy = False
                await self.broadcast({"ev": "state", "busy": False, "key": False, "pending": 0, "controller": 0})

    async def watchdog(self):
        while True:
            await asyncio.sleep(0.05)
            now = time.monotonic()
            if self.busy and (now - self.last_host) * 1000 > self.cfg["heartbeat_ms"]:
                await self.stop("", fault="HEARTBEAT_LOST")
            elif self.busy and (now - self.tx_since) * 1000 > self.cfg["tx_max_ms"]:
                await self.stop("", fault="TX_LIMIT")

    # -- connection --
    async def handler(self, ws):
        self.clients.add(ws)
        await self._send(ws, self.hello(ws))
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    await self._send(ws, {"ev": "error", "code": "BAD_JSON", "msg": ""})
                    continue
                await self.command(ws, msg)
        except Exception:  # noqa: BLE001
            pass
        finally:
            self.clients.discard(ws)
            if ws is self.controller:
                self.controller = None
                if self.busy:
                    await self.stop("controller_lost")

    async def command(self, ws, msg):
        cmd = msg.get("cmd", "")
        if ws is self.controller:
            self.last_host = time.monotonic()
        if cmd == "hello":
            if self.controller is not None and self.controller is not ws:
                if self.busy:
                    await self.stop("controller_changed")
                await self._send(self.controller, {"ev": "control", "owner": False})
            self.controller = ws
            self.last_host = time.monotonic()
            await self._send(ws, self.hello(ws))
        elif cmd == "ping":
            await self._send(ws, {"ev": "pong", "t": msg.get("t")})
        elif cmd == "status":
            await self._send(ws, {"ev": "state", "busy": self.busy, "key": self.key,
                                  "pending": len(self.queue), "controller": 0})
        elif cmd == "stop":
            await self.stop("host")
        elif ws is not self.controller:
            await self._send(ws, {"ev": "error", "code": "NOT_CONTROLLER", "msg": "send hello first"})
        elif cmd == "send":
            text = str(msg.get("text", ""))
            self.queue.extend(text)
            self.tx_since = time.monotonic()
            await self._send(ws, {"ev": "queued", "accepted": len(text), "pending": len(self.queue)})
            self.ensure_worker()
        elif cmd == "set":
            if "wpm" in msg:
                self.cfg["wpm"] = max(5, min(50, int(msg["wpm"])))
            if "weight" in msg:
                self.cfg["weight"] = max(25, min(75, int(msg["weight"])))
            for k in LIMITS_MAX:
                if k in msg:
                    self.cfg[k] = max(LIMITS_MIN[k], min(LIMITS_MAX[k], int(msg[k])))
            await self.broadcast({"ev": "config", "cfg": dict(self.cfg)})
        elif cmd == "tune":
            await self._send(ws, {"ev": "error", "code": "UNKNOWN_CMD", "msg": "tune not simulated"})
        else:
            await self._send(ws, {"ev": "error", "code": "UNKNOWN_CMD", "msg": cmd})


async def serve(host: str = "127.0.0.1", port: int = 0, ready: threading.Event | None = None, holder: dict | None = None):
    import websockets

    sim = KeyerSim()
    async with websockets.serve(sim.handler, host, port) as server:
        actual = server.sockets[0].getsockname()[1]
        if holder is not None:
            holder["port"] = actual
            holder["sim"] = sim
            holder["loop"] = asyncio.get_running_loop()
        if ready:
            ready.set()
        await sim.watchdog()


def start_in_thread(port: int = 0) -> dict:
    """Start the simulator in a daemon thread. Returns {'port', 'sim', 'loop'}."""
    ready = threading.Event()
    holder: dict = {}
    t = threading.Thread(target=lambda: asyncio.run(serve("127.0.0.1", port, ready, holder)),
                         name="keyer-sim", daemon=True)
    t.start()
    ready.wait(5)
    return holder


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8181)
    a = ap.parse_args()
    print(f"keyer simulator on ws://127.0.0.1:{a.port}/")
    asyncio.run(serve("127.0.0.1", a.port))
