#!/usr/bin/env python3
"""CW keyer – WebSocket-testiasiakas (M0-kokeilut ESP8266-keyerille).

Asennus:  pip install websockets
Käyttö:   python ws_keyer.py [ws://cwkeyer.local:81/] [--no-ping]

Kirjoita teksti ja paina Enter -> lähetetään CW:nä.
  (tyhjä rivi)   STOP
  /tune 5        kantoaalto 5 s
  /wpm 25        nopeus
  /weight 55     painotuscq test
  
  /status        tila
  /hb off|on     heartbeat-pingit pois/päälle (SR-04-testi)
  /raw {...}     lähetä JSON sellaisenaan
  /quit          lopetus (lähettää STOPin)
Ctrl+C lähettää aina STOPin ennen lopetusta.
"""
import asyncio
import json
import sys
import threading
import time

import websockets

COLORS = {"echo": "\033[92m", "fault": "\033[91m", "error": "\033[91m",
          "stopped": "\033[93m", "reset": "\033[0m"}


def fmt(ev: dict) -> str:
    kind = ev.get("ev", "?")
    if kind == "echo":
        return f"{COLORS['echo']}{ev['ch']}{COLORS['reset']}"
    col = COLORS.get(kind, "")
    return f"\n{col}<< {json.dumps(ev, ensure_ascii=False)}{COLORS['reset'] if col else ''}\n"


async def main(url: str, ping: bool) -> None:
    lines: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    state = {"ping": ping}

    def reader():
        for line in sys.stdin:
            loop.call_soon_threadsafe(lines.put_nowait, line.rstrip("\r\n"))
        loop.call_soon_threadsafe(lines.put_nowait, "/quit")

    threading.Thread(target=reader, daemon=True).start()

    async with websockets.connect(url, ping_interval=None) as ws:
        async def tx(obj):
            await ws.send(json.dumps(obj))

        await tx({"cmd": "hello", "client": "ws_keyer.py"})

        async def rx():
            async for msg in ws:
                try:
                    ev = json.loads(msg)
                except ValueError:
                    print(f"\n<< {msg}")
                    continue
                print(fmt(ev), end="", flush=True)

        async def pinger():
            while True:
                await asyncio.sleep(1.0)
                if state["ping"]:
                    await tx({"cmd": "ping", "t": int(time.time() * 1000)})

        async def commands():
            while True:
                line = await lines.get()
                if line == "":
                    await tx({"cmd": "stop"})
                elif line.startswith("/"):
                    parts = line[1:].split(maxsplit=1)
                    cmd, arg = parts[0], (parts[1] if len(parts) > 1 else "")
                    if cmd == "quit":
                        await tx({"cmd": "stop"})
                        return
                    elif cmd == "tune":
                        await tx({"cmd": "tune", "ms": int(float(arg or 5) * 1000)})
                    elif cmd in ("wpm", "weight"):
                        await tx({"cmd": "set", cmd: int(arg)})
                    elif cmd == "status":
                        await tx({"cmd": "status"})
                    elif cmd == "hb":
                        state["ping"] = arg != "off"
                        print(f"heartbeat {'päällä' if state['ping'] else 'POIS'}")
                    elif cmd == "raw":
                        await ws.send(arg)
                    else:
                        print("tuntematon komento")
                else:
                    await tx({"cmd": "send", "text": line.upper() + " "})

        tasks = [asyncio.create_task(rx()), asyncio.create_task(pinger())]
        try:
            await commands()
        finally:
            for t in tasks:
                t.cancel()
            try:
                await ws.send(json.dumps({"cmd": "stop"}))
            except Exception:
                pass


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    url = args[0] if args else "ws://cwkeyer.local:81/"
    print(f"Yhdistetään {url} ... (tyhjä rivi = STOP, /quit = lopetus)")
    try:
        asyncio.run(main(url, "--no-ping" not in sys.argv))
    except KeyboardInterrupt:
        print("\nSTOP lähetetty, lopetus.")
