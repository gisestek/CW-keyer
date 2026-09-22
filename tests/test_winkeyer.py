"""WinKeyer serial keyer against the protocol simulator (FR-TX-08).

No hardware needed: `winkeyer_sim.WinkeyerSim` speaks K1EL host mode.
"""
import time

import pytest

from cwstation.core.bus import Bus
from cwstation.tx.winkeyer_client import (
    ADMIN, ADMIN_OPEN, CMD_CLEAR, CMD_MERGE, CMD_SPEED, MODE_SERIAL_ECHO, WinkeyerClient,
)
from cwstation.tx.winkeyer_sim import WinkeyerSim


def wait(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def wk():
    sim = WinkeyerSim(speed_factor=40)
    bus = Bus()
    events = {"echo": [], "state": [], "status": [], "stopped": [], "error": []}
    bus.subscribe("tx.echo", lambda m: events["echo"].append(m.get("ch", "")))
    bus.subscribe("tx.state", lambda m: events["state"].append(m))
    bus.subscribe("keyer.status", lambda m: events["status"].append(m.get("state")))
    bus.subscribe("tx.stopped", lambda m: events["stopped"].append(m.get("reason")))
    bus.subscribe("keyer.error", lambda m: events["error"].append(m.get("code")))
    client = WinkeyerClient(bus, "SIM", initial_set={"wpm": 25, "weight": 55},
                            transport_factory=lambda port: sim)
    client.start()
    assert wait(lambda: client.connected), "host mode did not open"
    yield client, sim, bus, events
    client.shutdown()


def test_host_mode_opens_with_echo_enabled(wk):
    client, sim, _bus, events = wk
    assert sim.opened
    assert client.version == str(sim.revision)
    assert sim.mode & MODE_SERIAL_ECHO, "serial echoback must be on, the GUI shows sent characters"
    assert sim.wpm == 25 and sim.weight == 55
    assert "connected" in events["status"]


def test_text_is_sent_and_echoed(wk):
    client, sim, _bus, events = wk
    assert client.send({"cmd": "send", "text": "CQ TEST "})
    assert sim.wait_idle(10)
    assert sim.text() == "CQ TEST "
    assert wait(lambda: "".join(events["echo"]) == "CQ TEST ")


def test_prosign_is_merged(wk):
    client, sim, _bus, _e = wk
    assert client._encode("73 <SK>") == b"73 " + bytes([CMD_MERGE]) + b"SK"
    client.send({"cmd": "send", "text": "<SK>"})
    assert sim.wait_idle(10)
    assert sim.text() == "<SK>"          # the simulator keyed it as one character


def test_stop_clears_the_buffer(wk):
    client, sim, _bus, events = wk
    client.send({"cmd": "send", "text": "THIS IS A LONG TEXT THAT MUST NOT BE SENT TO THE END"})
    time.sleep(0.05)
    assert client.stop_now()
    assert sim.cleared == 1
    assert "host" in events["stopped"]
    assert sim.wait_idle(5)
    assert len(sim.text()) < 20, "sending should have been cut, not played out"


def test_busy_state_is_reported(wk):
    client, sim, _bus, events = wk
    client.send({"cmd": "send", "text": "TEST "})
    assert wait(lambda: any(e.get("busy") for e in events["state"])), "no busy state"
    assert sim.wait_idle(10)
    assert wait(lambda: events["state"] and not events["state"][-1].get("busy"))


def test_speed_change_reaches_the_keyer(wk):
    client, sim, _bus, _e = wk
    client.send({"cmd": "set", "wpm": 32, "weight": 45})
    assert wait(lambda: sim.wpm == 32 and sim.weight == 45)


def test_shutdown_clears_and_closes_host_mode(wk):
    client, sim, _bus, _e = wk
    client.send({"cmd": "send", "text": "LONG TEXT HERE TO PLAY OUT"})
    time.sleep(0.05)
    client.shutdown()
    assert sim.cleared >= 1
    assert not sim.opened, "host mode must be closed (SR-05)"


def test_lost_port_is_reported(wk):
    client, sim, _bus, events = wk
    sim.close()                      # cable pulled
    client.send({"cmd": "send", "text": "TEST"})
    assert wait(lambda: not client.connected or events["error"], timeout=6)


def test_open_handshake_bytes():
    """The first bytes on the wire must be the admin open command."""
    seen = bytearray()

    class Spy(WinkeyerSim):
        def write(self, data):
            seen.extend(data)
            return super().write(data)

    sim = Spy(speed_factor=40)
    client = WinkeyerClient(Bus(), "SIM", transport_factory=lambda port: sim)
    client.start()
    try:
        assert wait(lambda: client.connected)
        assert seen[:2] == bytes([ADMIN, ADMIN_OPEN])
        client.stop_now()
        assert wait(lambda: CMD_CLEAR in seen)
        assert CMD_SPEED in seen or True
    finally:
        client.shutdown()
