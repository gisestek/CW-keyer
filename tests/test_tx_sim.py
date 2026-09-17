"""TX module + keyer client against the protocol simulator."""
import threading
import time

import pytest

from cwstation.core.bus import Bus
from cwstation.core.settings import Settings
from cwstation.tx import keyer_sim
from cwstation.tx.keyer_client import KeyerClient
from cwstation.tx.tx_module import TxModule


class Recorder:
    def __init__(self, bus):
        self.msgs = []
        self.lock = threading.Lock()
        bus.subscribe("*", self.add)

    def add(self, m):
        with self.lock:
            self.msgs.append(m)

    def of(self, t):
        with self.lock:
            return [m for m in self.msgs if m["type"] == t]

    def wait(self, pred, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            if pred():
                return True
            time.sleep(0.02)
        return False


@pytest.fixture
def rig(tmp_path):
    holder = keyer_sim.start_in_thread()
    bus = Bus()
    rec = Recorder(bus)
    st = Settings(tmp_path / "s.json")
    st.set("station.callsign", "OH0TEST")
    client = KeyerClient(bus, f"ws://127.0.0.1:{holder['port']}/", initial_set={"wpm": 40}, simulated=True)
    tx = TxModule(bus, st, client)
    client.start()
    assert rec.wait(lambda: client.connected, 8), "no connection to simulator"
    yield bus, rec, client, holder["sim"], st
    client.shutdown()


def test_send_echoes_characters_in_order(rig):
    bus, rec, client, sim, st = rig
    bus.publish("tx.send", text="cq de {MYCALL}")
    assert rec.wait(lambda: any(not m["busy"] for m in rec.of("tx.state")) and len(rec.of("tx.echo")) >= 14, 15)
    echoed = "".join(m["ch"] for m in rec.of("tx.echo"))
    assert echoed == "CQ DE OH0TEST "
    assert rec.of("tx.queued")[0]["text"] == "CQ DE OH0TEST "


def test_stop_clears_queue_quickly(rig):
    bus, rec, client, sim, st = rig
    bus.publish("tx.send", text="TEST " * 20)
    assert rec.wait(lambda: len(rec.of("tx.echo")) >= 3)
    t0 = time.perf_counter()
    bus.publish("tx.stop", reason="test")
    assert rec.wait(lambda: rec.of("tx.stopped"), 2)
    assert (time.perf_counter() - t0) < 0.05, "STOP round trip over 50 ms (SR-01)"
    n = len(rec.of("tx.echo"))
    time.sleep(0.5)
    assert len(rec.of("tx.echo")) == n, "keyer kept sending after STOP"
    assert not sim.busy and not sim.queue


def test_not_connected_is_refused(tmp_path):
    bus = Bus()
    rec = Recorder(bus)
    st = Settings(tmp_path / "s.json")
    client = KeyerClient(bus, "ws://127.0.0.1:9/")  # nothing listens
    TxModule(bus, st, client)
    bus.publish("tx.send", text="CQ")
    assert rec.of("tx.warning")[0]["code"] == "not_connected"
    assert not rec.of("tx.queued")


def test_mycall_required(rig):
    bus, rec, client, sim, st = rig
    st.set("station.callsign", "")
    bus.publish("tx.send", text="DE {MYCALL}")
    assert rec.of("tx.warning")[-1]["code"] == "no_callsign"


def test_unsupported_chars_dropped(rig):
    bus, rec, client, sim, st = rig
    bus.publish("tx.send", text="HÄLLÖ #1")
    assert rec.of("tx.warning")[-1] == {**rec.of("tx.warning")[-1], "code": "dropped_chars"}
    assert rec.of("tx.queued")[-1]["text"] == "HLL 1 "


def test_disconnect_stops_keyer(rig):
    """SR-04: when the program disappears the keyer stops sending."""
    bus, rec, client, sim, st = rig
    bus.publish("tx.send", text="PARIS " * 30)
    assert rec.wait(lambda: sim.busy)
    client.shutdown()
    assert rec.wait(lambda: not sim.busy, 5)


def test_wpm_set_reaches_keyer(rig):
    bus, rec, client, sim, st = rig
    bus.publish("tx.set", wpm=33)
    assert rec.wait(lambda: sim.cfg["wpm"] == 33, 3)
    assert st.get("keyer.wpm") == 33
