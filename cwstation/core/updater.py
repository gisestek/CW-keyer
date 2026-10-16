"""Update check and one-click update from GitHub releases (FR-CORE-10).

Check:   GET https://api.github.com/repos/<REPO>/releases  -> newest release newer than __version__
         that has this platform's file (CWStation-<version>-win64.zip, -linux-x64.tar.gz, …) with a
         sha256 digest. One-click update is Windows only; elsewhere the bar opens the release page.
Update:  1. download the zip to %APPDATA%\\CWStation\\updates and verify its SHA-256
         2. unpack it next to the program folder (<folder>.new)
         3. start a small PowerShell helper and close the program normally (STOP first, SR-05)
         4. the helper waits for the program to exit, renames <folder> to <folder>.old, moves the
            new folder in place and starts it again; on any failure it puts the old folder back.

Settings live in %APPDATA%, outside the program folder, so they survive an update.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from .. import APP_ID, __version__
from .bus import Bus

log = logging.getLogger(__name__)

REPO = "gisestek/CW-keyer"
API_URL = f"https://api.github.com/repos/{REPO}/releases"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
EXE_NAME = "CWStation.exe"


def platform_asset_suffix() -> str:
    """Release file ending for this computer: 'win64.zip', 'linux-x64.tar.gz', 'linux-arm64.tar.gz'."""
    if sys.platform == "win32":
        return "win64.zip"
    import platform

    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)
    return f"linux-{arch}.tar.gz" if sys.platform.startswith("linux") else f"{sys.platform}-{arch}.zip"


ASSET_SUFFIX = platform_asset_suffix()
CHECK_EVERY_S = 24 * 3600
TIMEOUT_S = 20
CHUNK = 256 * 1024


class UpdateError(Exception):
    pass


# ---------------------------------------------------------------- versions
def parse_version(text: str) -> tuple:
    """'v0.7.0' -> (0, 7, 0, 1);  '0.7.0-rc1' -> (0, 7, 0, 0, 'rc1')  (a suffix sorts before the release)."""
    t = (text or "").strip().lstrip("vV")
    m = re.match(r"^(\d+(?:\.\d+)*)(?:[-+]?(.*))?$", t)
    if not m:
        return (0,)
    nums = [int(x) for x in m.group(1).split(".")]
    while len(nums) < 3:
        nums.append(0)
    suffix = (m.group(2) or "").strip()
    return tuple(nums) + ((0, suffix) if suffix else (1,))


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


# ---------------------------------------------------------------- check
def pick_release(releases: list[dict], current: str = __version__, prerelease: bool = True) -> dict | None:
    """Newest usable release that is newer than `current`, as a flat dict, or None."""
    best = None
    for r in releases:
        if r.get("draft") or (r.get("prerelease") and not prerelease):
            continue
        version = (r.get("tag_name") or "").lstrip("vV")
        if not is_newer(version, current):
            continue
        wanted = f"CWStation-{version}-{ASSET_SUFFIX}"       # file must match the tag, or updates would loop
        asset = next((a for a in r.get("assets") or [] if a.get("name") == wanted), None)
        if asset is None:
            continue
        url = asset.get("browser_download_url", "")
        digest = asset.get("digest") or ""
        info = {
            "version": version,
            "tag": r.get("tag_name", ""),
            "name": r.get("name") or version,
            "notes": (r.get("body") or "").strip(),
            "page": r.get("html_url") or f"https://github.com/{REPO}/releases",
            "prerelease": bool(r.get("prerelease")),
            "asset": asset.get("name", ""),
            "url": url if url.startswith(DOWNLOAD_PREFIX) else "",
            "size": int(asset.get("size") or 0),
            "sha256": digest[7:].lower() if digest.lower().startswith("sha256:") else "",
        }
        if best is None or parse_version(version) > parse_version(best["version"]):
            best = info
    return best


def fetch_releases(url: str = API_URL, opener=None) -> list[dict]:
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"{APP_ID}/{__version__}"})
    with opener(req, timeout=TIMEOUT_S) as resp:
        data = json.loads(resp.read(2_000_000).decode("utf-8"))
    if not isinstance(data, list):
        raise UpdateError(str(data.get("message", "unexpected answer")) if isinstance(data, dict) else "bad answer")
    return data


# ---------------------------------------------------------------- install location
def install_dir() -> Path | None:
    """Folder of the running CWStation.exe, or None when running from source (no one-click update)."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent


def can_self_update(folder: Path | None) -> tuple[bool, str]:
    if folder is None:
        return False, "source"
    if sys.platform != "win32":
        return False, "platform"
    try:
        probe = folder.parent / f".{APP_ID}-write-test"
        probe.write_text("x")
        probe.unlink()
    except OSError:
        return False, "readonly"
    return True, ""


# ---------------------------------------------------------------- download and unpack
def download(info: dict, dest: Path, progress=None, cancel: threading.Event | None = None, opener=None) -> Path:
    """Downloads the release zip and verifies its SHA-256. Returns the zip path."""
    if not info.get("url"):
        raise UpdateError("no download address")
    if not info.get("sha256"):
        raise UpdateError("the release has no checksum")
    opener = opener or urllib.request.urlopen
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / info["asset"]
    part = target.with_suffix(".part")
    h = hashlib.sha256()
    done = 0
    req = urllib.request.Request(info["url"], headers={"User-Agent": f"{APP_ID}/{__version__}"})
    try:
        with opener(req, timeout=TIMEOUT_S) as resp, open(part, "wb") as f:
            total = int(resp.headers.get("Content-Length") or info.get("size") or 0)
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("cancelled")
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if info.get("size") and done != info["size"]:
            raise UpdateError(f"download incomplete ({done} of {info['size']} bytes)")
        if h.hexdigest() != info["sha256"]:
            raise UpdateError("checksum does not match – the download is broken or not the published file")
        part.replace(target)
        return target
    finally:
        if part.exists():
            part.unlink()


def unpack(zip_path: Path, folder: Path) -> Path:
    """Unpacks next to `folder` into '<folder>.new' and returns the new program folder inside it."""
    staging = folder.parent / (folder.name + ".new")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    root = staging.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            out = (staging / member.filename).resolve()
            if root not in out.parents and out != root:          # zip slip: nothing outside the staging folder
                raise UpdateError(f"unsafe path in the zip: {member.filename}")
        z.extractall(staging)
    exes = [p for p in staging.rglob(EXE_NAME) if len(p.relative_to(staging).parts) <= 2]
    if not exes:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"{EXE_NAME} not found in the zip")
    return exes[0].parent


HELPER_PS1 = r"""# CW Station updater: replaces the program folder once the program has closed.
param([int]$ProcessId, [string]$Install, [string]$Staged, [string]$Staging, [string]$Exe, [string]$Log,
      [int]$WaitSeconds = 90, [int]$Tries = 40)
$ErrorActionPreference = "Stop"
function Log($m) { try { Add-Content -LiteralPath $Log -Value ("{0:u} {1}" -f (Get-Date), $m) -Encoding UTF8 } catch {} }
function Retry([scriptblock]$Action) {
    for ($i = 0; $i -lt $Tries; $i++) { try { & $Action; return $true } catch { Start-Sleep -Milliseconds 500 } }
    return $false
}
function StartProgram($dir) { try { Start-Process -FilePath (Join-Path $dir $Exe) -WorkingDirectory $dir } catch { Log "could not start: $_" } }

Log "waiting for process $ProcessId to close"
try { Wait-Process -Id $ProcessId -Timeout $WaitSeconds -ErrorAction SilentlyContinue } catch {}
if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) { Log "the program did not close, update cancelled"; exit 1 }

$old = "$Install.old"
if (Test-Path -LiteralPath $old) {
    if (-not (Retry { Remove-Item -LiteralPath $old -Recurse -Force })) { $old = "$Install.old-" + (Get-Date -Format "yyyyMMddHHmmss") }
}
if (-not (Retry { Rename-Item -LiteralPath $Install -NewName (Split-Path $old -Leaf) })) {
    Log "could not move the old version away (a file is in use?), update cancelled"
    StartProgram $Install
    exit 1
}
if (-not (Retry { Move-Item -LiteralPath $Staged -Destination $Install })) {
    Log "could not move the new version in place, restoring the old one"
    Retry { Rename-Item -LiteralPath $old -NewName (Split-Path $Install -Leaf) } | Out-Null
    StartProgram $Install
    exit 1
}
try { Remove-Item -LiteralPath $Staging -Recurse -Force } catch {}
Log "update installed, old version kept in $old"
StartProgram $Install
"""


def start_helper(folder: Path, staged: Path, log_path: Path, pid: int | None = None) -> Path:
    """Writes the helper script and starts it detached. The caller then closes the program."""
    script = log_path.parent / "cwstation-update.ps1"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(HELPER_PS1, encoding="utf-8-sig")       # BOM: Windows PowerShell 5 reads UTF-8 correctly
    args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
            "-File", str(script), "-ProcessId", str(pid or os.getpid()), "-Install", str(folder),
            "-Staged", str(staged), "-Staging", str(folder.parent / (folder.name + ".new")),
            "-Exe", EXE_NAME, "-Log", str(log_path)]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(args, cwd=str(script.parent), creationflags=flags, close_fds=True)
    return script


# ---------------------------------------------------------------- bus-facing worker
class Updater:
    """Publishes:
      update.available {version, name, notes, page, size, one_click, reason}
      update.none      {manual}                    (only answers to a manual check)
      update.error     {msg, manual, stage}         stage = check | download | unpack
      update.progress  {done, total}
      update.ready     {version}                   downloaded and unpacked: the window may restart
    """

    def __init__(self, bus: Bus, settings, folder: Path | None = None, api_url: str = API_URL,
                 opener=None, updates_dir: Path | None = None, clock=time.time):
        self.bus = bus
        self.settings = settings
        self.folder = folder if folder is not None else install_dir()
        self.api_url = api_url
        self._open = opener
        self.updates_dir = updates_dir
        self._clock = clock
        self.info: dict | None = None
        self.staged: Path | None = None
        self._cancel = threading.Event()
        self._busy = threading.Lock()

    def check_due(self) -> bool:
        if not self.settings.get("update.auto", True):
            return False
        last = float(self.settings.get("update.last_check") or 0)
        return self._clock() - last >= CHECK_EVERY_S

    def check(self, manual: bool = False, wait: bool = False) -> None:
        t = threading.Thread(target=self._check, args=(manual,), name="update-check", daemon=True)
        t.start()
        if wait:
            t.join(TIMEOUT_S + 5)

    def _check(self, manual: bool) -> None:
        try:
            releases = fetch_releases(self.api_url, self._open)
        except Exception as e:  # noqa: BLE001  offline at the station is normal
            log.info("update check failed: %s", e)
            self.bus.publish("update.error", msg=str(getattr(e, "reason", e)), manual=manual, stage="check")
            return
        self.settings.set("update.last_check", int(self._clock()))
        info = pick_release(releases, __version__, bool(self.settings.get("update.prerelease", True)))
        if info is None or (not manual and info["version"] == self.settings.get("update.skip")):
            if manual:
                self.bus.publish("update.none", manual=True, version=__version__)
            return
        self.info = info
        ok, reason = can_self_update(self.folder)
        if ok and not (info["url"] and info["sha256"]):
            ok, reason = False, "no_checksum"
        log.info("update available: %s (one-click %s %s)", info["version"], ok, reason)
        self.bus.publish("update.available", version=info["version"], name=info["name"], notes=info["notes"][:4000],
                         page=info["page"], size=info["size"], one_click=ok, reason=reason, manual=manual)

    def start_download(self) -> bool:
        if self.info is None or not self._busy.acquire(blocking=False):
            return False
        self._cancel.clear()
        threading.Thread(target=self._download, name="update-download", daemon=True).start()
        return True

    def cancel(self) -> None:
        self._cancel.set()

    def _download(self) -> None:
        stage = "download"
        try:
            dest = self.updates_dir or (Path(os.environ.get("APPDATA", Path.home())) / APP_ID / "updates")
            last = [0.0]

            def progress(done, total):
                now = time.monotonic()
                if now - last[0] > 0.2 or done == total:
                    last[0] = now
                    self.bus.publish("update.progress", done=done, total=total)

            zip_path = download(self.info, Path(dest), progress, self._cancel, self._open)
            stage = "unpack"
            self.staged = unpack(zip_path, self.folder)
            try:
                zip_path.unlink()
            except OSError:
                pass
            self.bus.publish("update.ready", version=self.info["version"])
        except Exception as e:  # noqa: BLE001
            log.warning("update %s failed: %s", stage, e)
            self.bus.publish("update.error", msg=str(e), manual=True, stage=stage)
        finally:
            self._busy.release()

    def install_and_restart(self, log_path: Path) -> None:
        """Starts the helper. The caller closes the window right after this."""
        if self.staged is None or self.folder is None:
            raise UpdateError("nothing to install")
        start_helper(self.folder, self.staged, log_path)
