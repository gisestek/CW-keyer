import json

from cwstation.core import macros
from cwstation.core.bus import Bus
from cwstation.core.settings import DEFAULTS, Settings
from cwstation.core.textlog import TextLog


def test_settings_roundtrip_and_defaults(tmp_path):
    p = tmp_path / "s.json"
    s = Settings(p)
    assert s.get("keyer.wpm") == DEFAULTS["keyer"]["wpm"]
    s.set("station.callsign", "OH0X")
    s.save()
    data = json.loads(p.read_text())
    assert data["station"]["callsign"] == "OH0X"
    # a partial / older file gets new defaults merged in
    p.write_text(json.dumps({"station": {"callsign": "OH1Y"}}))
    s2 = Settings(p)
    assert s2.get("station.callsign") == "OH1Y" and s2.get("keyer.heartbeat_ms") == 3000


def test_settings_corrupt_file_falls_back(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json")
    assert Settings(p).get("keyer.wpm") == 20


def test_macro_expand_and_sanitize():
    assert macros.expand("CQ DE {mycall} {MYCALL} K", {"MYCALL": "OH0X"}) == "CQ DE OH0X OH0X K"
    assert macros.expand("{UNKNOWN}X", {}) == "X"
    assert macros.sanitize("tu 73  <sk>") == ("TU 73 <SK>", "")
    assert macros.sanitize("äö #cq") == (" CQ", "ÄÖ#")
    clean, dropped = macros.sanitize("CQ <AR")
    assert clean == "CQ AR" and "<" in dropped


class Clock:
    def __init__(self):
        self.t = 1_789_650_000.0

    def __call__(self):
        return self.t


def test_textlog_lines_break_on_direction_and_pause(tmp_path):
    bus, clk = Bus(), Clock()
    log = TextLog(bus, tmp_path, line_pause_s=3.0, clock=clk)
    bus.publish("rx.text", text="CQ CQ", t_start=clk.t, t_end=clk.t + 2)
    bus.publish("rx.text", text="DE OH2BH", t_start=clk.t + 2.5, t_end=clk.t + 5)
    clk.t += 6
    for ch in "OH2BH DE OH0X ":
        bus.publish("tx.echo", ch=ch)
        clk.t += 0.2
    clk.t += 10
    bus.publish("rx.text", text="R TNX", t_start=clk.t, t_end=clk.t + 1)
    log.flush()
    lines = next(tmp_path.glob("cw-*.txt")).read_text().splitlines()
    assert [l.split("\t")[1:] for l in lines] == [["RX", "CQ CQ DE OH2BH"], ["TX", "OH2BH DE OH0X"], ["RX", "R TNX"]]
    assert lines[0].split("\t")[0].endswith("Z")


def test_textlog_marks_stop(tmp_path):
    bus, clk = Bus(), Clock()
    log = TextLog(bus, tmp_path, clock=clk)
    for ch in "CQ C":
        bus.publish("tx.echo", ch=ch)
    bus.publish("tx.stopped", reason="host")
    log.flush()
    assert next(tmp_path.glob("cw-*.txt")).read_text().strip().endswith("TX\tCQ C [STOP]")


def test_bus_handler_error_does_not_break_others():
    bus = Bus()
    got = []
    bus.subscribe("tx.stop", lambda m: 1 / 0)
    bus.subscribe("tx.*", got.append)
    bus.publish("tx.stop", reason="x")
    assert got and got[0]["reason"] == "x" and got[0]["utc"].endswith("Z")
