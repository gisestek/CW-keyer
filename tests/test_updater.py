"""Update check and one-click update (FR-CORE-10) against a local fake GitHub.

The PowerShell helper that swaps the program folder is run for real when a
PowerShell is found (`pwsh`, or the path in CWSTATION_PWSH) on a non-Windows
machine, with a shell script standing in for CWStation.exe.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cwstation.core import updater as up  # noqa: E402
from cwstation.core.bus import Bus  # noqa: E402
from cwstation.core.settings import Settings  # noqa: E402


def wait(pred, secs=5.0):
    end = time.time() + secs
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def make_zip(version="0.7.0", extra: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CWStation/CWStation.exe", f"new {version}")
        z.writestr("CWStation/_internal/lib.dll", "dll")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def release(tag, base, asset_bytes=b"", prerelease=False, draft=False, digest=True, name=None):
    asset_name = name or f"CWStation-{tag.lstrip('v')}-{up.ASSET_SUFFIX}"
    return {"tag_name": tag, "name": tag, "draft": draft, "prerelease": prerelease, "body": f"## {tag}\n- new things",
            "html_url": f"https://github.com/{up.REPO}/releases/tag/{tag}",
            "assets": [{"name": asset_name, "size": len(asset_bytes),
                        "digest": ("sha256:" + hashlib.sha256(asset_bytes).hexdigest()) if digest else None,
                        "browser_download_url": f"{base}{tag}/{asset_name}"}]}


# ---------------------------------------------------------------- versions and picking
def test_versions():
    assert up.is_newer("0.7.0", "0.6.0") and up.is_newer("v0.10.0", "0.9.9") and up.is_newer("1.0", "0.99.1")
    assert not up.is_newer("0.6.0", "0.6.0") and not up.is_newer("0.5.9", "0.6.0")
    assert up.is_newer("0.7.0", "0.7.0-rc1") and up.is_newer("0.7.0-rc1", "0.6.0")
    assert not up.is_newer("0.7.0-rc1", "0.7.0")


def test_platform_asset_names(monkeypatch):
    import platform

    monkeypatch.setattr(up.sys, "platform", "win32")
    assert up.platform_asset_suffix() == "win64.zip"
    monkeypatch.setattr(up.sys, "platform", "linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert up.platform_asset_suffix() == "linux-x64.tar.gz"
    monkeypatch.setattr(platform, "machine", lambda: "aarch64")
    assert up.platform_asset_suffix() == "linux-arm64.tar.gz"


def test_pick_release(monkeypatch):
    base = up.DOWNLOAD_PREFIX
    rels = [release("0.6.0", base), release("v0.8.0", base, draft=True), release("v0.7.1", base, prerelease=True),
            release("v0.7.0", base), release("v0.9.0", base, name="source.tar.gz")]
    best = up.pick_release(rels, "0.6.0")
    assert best["version"] == "0.7.1" and best["prerelease"] and best["sha256"] and best["url"].startswith(base)
    assert up.pick_release(rels, "0.6.0", prerelease=False)["version"] == "0.7.0"
    assert up.pick_release(rels, "0.7.1") is None
    foreign = up.pick_release([release("v0.7.0", "https://evil.example/")], "0.6.0")
    assert foreign["url"] == ""                                   # never download from elsewhere
    assert up.pick_release([release("v0.7.0", base, digest=False)], "0.6.0")["sha256"] == ""
    assert up.pick_release([release("v0.7.0", base, name=f"CWStation-0.6.0-{up.ASSET_SUFFIX}")], "0.6.0") is None


# ---------------------------------------------------------------- fake GitHub
class FakeGitHub(BaseHTTPRequestHandler):
    releases: list = []
    files: dict = {}
    hits = 0

    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        type(self).hits += 1
        if self.path.startswith("/api/releases"):
            body = json.dumps(self.releases).encode()
            ctype = "application/json"
        elif self.path in self.files:
            body, ctype = self.files[self.path], "application/zip"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def github(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), FakeGitHub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}/dl/"
    monkeypatch.setattr(up, "DOWNLOAD_PREFIX", base)
    monkeypatch.setattr(up, "__version__", "0.6.0")   # tests do not depend on the real version number
    data = make_zip()
    FakeGitHub.releases = [release("v0.7.0", base, data), release("0.6.0", base, b"x")]
    FakeGitHub.files = {f"/dl/v0.7.0/CWStation-0.7.0-{up.ASSET_SUFFIX}": data}
    FakeGitHub.hits = 0
    yield srv, base, data
    srv.shutdown()


def _updater(tmp_path, srv, folder=None):
    st = Settings(tmp_path / "s.json")
    bus = Bus()
    events = []
    bus.subscribe("update.*", events.append)
    u = up.Updater(bus, st, folder=folder, api_url=f"http://127.0.0.1:{srv.server_port}/api/releases",
                   updates_dir=tmp_path / "updates")
    return u, st, events


def test_check_offers_update_and_respects_skip_and_daily_limit(tmp_path, github):
    srv, _base, _data = github
    u, st, events = _updater(tmp_path, srv)
    assert u.check_due()
    u.check(wait=True)
    ev = events[-1]
    assert ev["type"] == "update.available" and ev["version"] == "0.7.0" and ev["notes"].startswith("## v0.7.0")
    assert ev["one_click"] is False and ev["reason"] in ("source", "platform")    # running from source here
    assert not u.check_due()                                                      # next automatic check tomorrow
    st.set("update.skip", "0.7.0")
    events.clear()
    u.check(wait=True)
    assert events == []
    u.check(manual=True, wait=True)                                               # a manual check still tells
    assert events[-1]["type"] == "update.available"
    st.set("update.auto", False)
    st.set("update.last_check", 0)
    assert not u.check_due()


def test_check_offline_and_up_to_date(tmp_path, github):
    srv, *_ = github
    u, st, events = _updater(tmp_path, srv)
    FakeGitHub.releases = [release("0.6.0", up.DOWNLOAD_PREFIX, b"x")]
    u.check(manual=True, wait=True)
    assert events[-1]["type"] == "update.none"
    u.api_url = "http://127.0.0.1:9/api/releases"
    u.check(manual=False, wait=True)
    assert events[-1]["type"] == "update.error" and events[-1]["stage"] == "check"


def test_download_verifies_checksum(tmp_path, github):
    srv, base, data = github
    info = up.pick_release(FakeGitHub.releases, "0.6.0")
    seen = []
    path = up.download(info, tmp_path / "dl", progress=lambda d, t: seen.append((d, t)))
    assert path.read_bytes() == data and seen[-1] == (len(data), len(data))
    bad = dict(info, sha256="0" * 64)
    with pytest.raises(up.UpdateError, match="checksum"):
        up.download(bad, tmp_path / "dl2")
    assert not list((tmp_path / "dl2").iterdir())                 # no half or bad file left behind
    with pytest.raises(up.UpdateError, match="checksum"):
        up.download(dict(info, sha256=""), tmp_path / "dl3")


def test_unpack_and_zip_slip(tmp_path):
    folder = tmp_path / "CWStation"
    folder.mkdir()
    z = tmp_path / "u.zip"
    z.write_bytes(make_zip())
    staged = up.unpack(z, folder)
    assert staged == tmp_path / "CWStation.new" / "CWStation" and (staged / "CWStation.exe").exists()
    z.write_bytes(make_zip(extra={"../../evil.txt": "x"}))
    with pytest.raises(up.UpdateError, match="unsafe"):
        up.unpack(z, folder)
    assert not (tmp_path.parent / "evil.txt").exists()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zz:
        zz.writestr("readme.txt", "no exe")
    z.write_bytes(buf.getvalue())
    with pytest.raises(up.UpdateError, match="not found"):
        up.unpack(z, folder)


def test_full_download_and_helper_start(tmp_path, github, monkeypatch):
    srv, *_ = github
    folder = tmp_path / "app" / "CWStation"
    folder.mkdir(parents=True)
    (folder / "CWStation.exe").write_text("old")
    monkeypatch.setattr(up, "can_self_update", lambda f: (True, ""))
    u, st, events = _updater(tmp_path, srv, folder=folder)
    u.check(manual=True, wait=True)
    assert events[-1]["one_click"] is True
    assert u.start_download()
    assert wait(lambda: events[-1]["type"] in ("update.ready", "update.error"))
    assert events[-1]["type"] == "update.ready", events[-1]
    assert any(e["type"] == "update.progress" for e in events)
    assert (tmp_path / "app" / "CWStation.new" / "CWStation" / "CWStation.exe").read_text() == "new 0.7.0"
    started = []
    monkeypatch.setattr(up.subprocess, "Popen", lambda args, **kw: started.append(args))
    u.install_and_restart(tmp_path / "cfg" / "update.log")
    args = started[0]
    assert args[0] == "powershell.exe" and "-File" in args
    script = Path(args[args.index("-File") + 1])
    assert script.read_bytes().startswith(b"\xef\xbb\xbf")        # BOM for Windows PowerShell 5
    assert args[args.index("-Install") + 1] == str(folder)
    assert args[args.index("-ProcessId") + 1] == str(os.getpid())


# ---------------------------------------------------------------- the PowerShell helper itself
PWSH = os.environ.get("CWSTATION_PWSH") or shutil.which("pwsh") or (
    "/tmp/claude-0/pwsh/pwsh" if os.path.exists("/tmp/claude-0/pwsh/pwsh") else None)
needs_pwsh = pytest.mark.skipif(not PWSH or sys.platform == "win32",
                                reason="needs PowerShell on a non-Windows machine (fake exe is a shell script)")


def _install(tmp_path, with_old=False):
    parent = tmp_path / "C"
    folder = parent / "CWStation"
    folder.mkdir(parents=True)
    marker = tmp_path / "started.txt"
    for d, label in ((folder, "old"),):
        exe = d / "CWStation.exe"
        exe.write_text(f"#!/bin/sh\necho {label} >> '{marker}'\n")
        exe.chmod(0o755)
        (d / "settings-not-here.txt").write_text(label)
    staging = parent / "CWStation.new"
    staged = staging / "CWStation"
    staged.mkdir(parents=True)
    exe = staged / "CWStation.exe"
    exe.write_text(f"#!/bin/sh\necho new >> '{marker}'\n")
    exe.chmod(0o755)
    if with_old:
        (parent / "CWStation.old").mkdir()
        (parent / "CWStation.old" / "ancient.txt").write_text("x")
    return folder, staging, staged, marker


def _run_helper(tmp_path, folder, staged, staging, pid, wait_s=10, tries=4):
    script = tmp_path / "helper.ps1"
    script.write_text(up.HELPER_PS1, encoding="utf-8-sig")
    log = tmp_path / "update.log"
    r = subprocess.run([PWSH, "-NoProfile", "-File", str(script), "-ProcessId", str(pid), "-Install", str(folder),
                        "-Staged", str(staged), "-Staging", str(staging), "-Exe", "CWStation.exe", "-Log", str(log),
                        "-WaitSeconds", str(wait_s), "-Tries", str(tries)],
                       capture_output=True, text=True, timeout=120)
    return r, (log.read_text(encoding="utf-8") if log.exists() else "")


@needs_pwsh
def test_helper_swaps_folder_after_exit_and_restarts(tmp_path):
    folder, staging, staged, marker = _install(tmp_path, with_old=True)
    proc = subprocess.Popen(["sleep", "1.5"])                    # stands in for the closing program
    threading.Thread(target=proc.wait, daemon=True).start()      # reap it, or it lingers as a zombie on Linux
    t0 = time.time()
    r, log = _run_helper(tmp_path, folder, staged, staging, proc.pid)
    assert r.returncode == 0, r.stderr + log
    assert time.time() - t0 >= 1.0                               # waited for the program to close
    assert (folder / "CWStation.exe").read_text().count("new") == 1
    assert (folder.parent / "CWStation.old" / "settings-not-here.txt").read_text() == "old"
    assert not (folder.parent / "CWStation.old" / "ancient.txt").exists()   # older backup replaced
    assert not staging.exists()
    assert wait(lambda: marker.exists() and "new" in marker.read_text(), 5)
    assert "update installed" in log


@needs_pwsh
def test_helper_restores_old_version_on_failure(tmp_path):
    folder, staging, staged, marker = _install(tmp_path)
    shutil.rmtree(staged)                                        # new version missing: the move must fail
    r, log = _run_helper(tmp_path, folder, staged, staging, 999999)
    assert r.returncode == 1
    assert (folder / "settings-not-here.txt").read_text() == "old"          # old version back in place
    assert not (folder.parent / "CWStation.old").exists()
    assert wait(lambda: marker.exists() and "old" in marker.read_text(), 5)
    assert "restoring" in log


@needs_pwsh
def test_helper_gives_up_if_program_keeps_running(tmp_path):
    folder, staging, staged, marker = _install(tmp_path)
    proc = subprocess.Popen(["sleep", "30"])
    try:
        r, log = _run_helper(tmp_path, folder, staged, staging, proc.pid, wait_s=1)
    finally:
        proc.kill()
    assert r.returncode == 1 and "did not close" in log
    assert (folder / "settings-not-here.txt").exists() and staged.exists()  # nothing touched
    assert not marker.exists()                                   # and no second copy started


# ---------------------------------------------------------------- GUI
@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    from cwstation.core import i18n

    app = QApplication.instance() or QApplication([])
    i18n.load("en")
    return app


def test_gui_update_bar(qapp, tmp_path, github, monkeypatch):
    from cwstation.app import Station
    from cwstation.gui.main_window import MainWindow

    srv, *_ = github
    folder = tmp_path / "app" / "CWStation"
    folder.mkdir(parents=True)
    st = Settings(tmp_path / "s.json")
    st.set("log.folder", str(tmp_path / "logs"))
    station = Station(st)
    station.updater = up.Updater(station.bus, st, folder=folder,
                                 api_url=f"http://127.0.0.1:{srv.server_port}/api/releases",
                                 updates_dir=tmp_path / "updates")
    win = MainWindow(station)
    win.show()
    assert not win.update_bar.isVisible()

    # running from source: the bar only offers the download page
    station.updater.check(wait=True)
    qapp.processEvents()
    assert win.update_bar.isVisible() and "0.7.0" in win.update_label.text()
    assert win.update_btn.text() == "Download page"
    win.update_close_btn.click()
    assert not win.update_bar.isVisible()

    # installed program: one click downloads, then the window closes for the helper
    monkeypatch.setattr(up, "can_self_update", lambda f: (True, ""))
    station.updater.check(manual=True, wait=True)
    qapp.processEvents()
    assert win.update_btn.text() == "Update and restart"
    win._tx_busy = True
    win.update_btn.click()
    assert win._update_state == "offered"                        # not while transmitting
    win._tx_busy = False
    installed = []
    monkeypatch.setattr(station.updater, "install_and_restart", lambda log_path: installed.append(log_path))
    win.update_btn.click()
    assert win._update_state == "downloading" and win.update_progress.isVisible()
    end = time.time() + 8
    while time.time() < end and not installed:
        qapp.processEvents()
        time.sleep(0.02)
    assert installed and installed[0].name == "update.log"
    assert not win.isVisible()                                   # closed: STOP sent, settings saved

    st.set("update.skip", "")
