"""Signed per-user updates. Rendering, model weights and user data stay separate."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from engine import CREATE_FLAGS, atomic_json
from version import VERSION

REPOSITORY = "Timur18o4/VideoStudio"
API = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
MAX_PACKAGE = 96 * 1024**2
MAX_EXPANDED = 180 * 1024**2
CHECK_INTERVAL = 6 * 3600
ROOT_FILES = {"VideoStudio.exe", "README.md", "CHANGELOG.md", "LICENSE.md", "THIRD_PARTY_NOTICES.md"}


def version_key(value):
    if not isinstance(value, str):
        raise ValueError("Ungültige Update-Version.")
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-(preview|beta|rc)(?:\.(\d+))?)?", value)
    if not match:
        raise ValueError("Ungültige Update-Version.")
    return (*(int(match[i]) for i in (1, 2, 3)), {"preview":0, "beta":1, "rc":2, None:3}[match[4]], int(match[5] or 0))


def canonical(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def verify_manifest(envelope, public_key=None):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
        raise ValueError("Ungültige Update-Information.")
    if public_key is None:
        public_key = json.loads((RESOURCE_ROOT / "update-trust.json").read_text(encoding="utf-8"))["public_key"]
    try:
        signature = base64.b64decode(envelope["signature"], validate=True)
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
        key.verify(signature, canonical(envelope["payload"]))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise ValueError("Die Herausgeber-Signatur des Updates ist ungültig.") from exc
    payload = envelope["payload"]
    try:
        if payload["schema"] != 1 or payload["repository"] != REPOSITORY:
            raise ValueError("Falsches Update-Format.")
        version_key(payload["version"])
        version_key(payload["min_version"])
        package = payload["package"]
        expected_name = f"VideoStudio-Update-{payload['version']}.zip"
        expected_url = f"https://github.com/{REPOSITORY}/releases/download/v{payload['version']}/{expected_name}"
        if package["name"] != expected_name or package["url"] != expected_url:
            raise ValueError("Unzulässige Downloadadresse.")
        if type(package["size"]) is not int or not 0 < package["size"] <= MAX_PACKAGE:
            raise ValueError("Unzulässige Update-Größe.")
        if not re.fullmatch(r"[0-9a-f]{64}", package["sha256"]):
            raise ValueError("Ungültige Update-Prüfsumme.")
    except (KeyError, TypeError) as exc:
        raise ValueError("Unvollständige Update-Information.") from exc
    return payload


def request(url):
    response = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "VideoStudio-Updater/" + VERSION, "Accept": "application/vnd.github+json"}), timeout=25)
    final = urlsplit(response.url)
    if final.scheme != "https" or final.hostname not in {"api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}:
        response.close()
        raise ValueError("Unzulässige Download-Weiterleitung.")
    return response


def fetch_json(url, limit=64 * 1024):
    with request(url) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Update-Information zu groß.")
    return json.loads(data)


def verify_package(package, payload):
    if package.stat().st_size != payload["package"]["size"]:
        raise ValueError("Die Update-Datei ist unvollständig.")
    with package.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != payload["package"]["sha256"]:
            raise ValueError("Die Update-Datei hat eine ungültige Prüfsumme.")
    with zipfile.ZipFile(package) as archive:
        names, total = set(), 0
        for item in archive.infolist():
            name = item.filename
            pieces = name.split("/")
            if (not name or "\\" in name or ":" in name or name.startswith("/") or
                    any(piece in ("", ".", "..") for piece in pieces) or name.casefold() in names or
                    item.is_dir() or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError("Unzulässiger Pfad im Update.")
            if name not in ROOT_FILES and not (pieces[0] == "licenses" and len(pieces) > 1):
                raise ValueError("Das Update enthält unzulässige Dateien.")
            total += item.file_size
            if total > MAX_EXPANDED:
                raise ValueError("Das entpackte Update ist zu groß.")
            names.add(name.casefold())
        if "videostudio.exe" not in names:
            raise ValueError("Im Update fehlt das Programm.")
        if archive.read("VideoStudio.exe")[:2] != b"MZ":
            raise ValueError("Das Update enthält keine Windows-Programmdatei.")


def stop_process(process):
    if process and process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, creationflags=CREATE_FLAGS)
        else:
            process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Das fehlgeschlagene Update konnte nicht beendet werden.")


def launch_program(target, data, port, token):
    args = [str(target / "VideoStudio.exe"), "--data", str(data), "--port", str(port), "--no-browser", "--skip-update-once", "--update-token", token]
    return subprocess.Popen(args, cwd=target, creationflags=CREATE_FLAGS)


def health_check(process, data, version, token, timeout=60):
    path = data / "updates" / f"health-{token}.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["version"] == version and record["token"] == token:
                url = f"http://127.0.0.1:{int(record['port'])}/api/health"
                with urllib.request.urlopen(url, timeout=2) as response:
                    state = json.load(response)
                if state.get("version") == version and state.get("update_token") == token:
                    return True
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.4)
    return False


def apply_package(package, payload, target, data, port, launch=launch_program, healthy=health_check):
    """Replace allowlisted files, verify startup, restore the preceding files on failure."""
    target, data = target.resolve(), data.resolve()
    marker = target / "installation.json"
    installed = json.loads(marker.read_text(encoding="utf-8"))
    if installed.get("app") != "VideoStudioEinfach" or "VideoStudio.exe" not in installed.get("files", []):
        raise ValueError("Der Installationsordner ist nicht gültig.")
    verify_package(package, payload)
    backup = target / (".update-backup-" + payload["version"])
    backup.mkdir(exist_ok=False)
    changed = []
    process = None
    try:
        with zipfile.ZipFile(package) as archive:
            items = archive.infolist()
            for item in items:
                destination = (target / item.filename).resolve()
                if not destination.is_relative_to(target):
                    raise ValueError("Der Update-Pfad verlässt den Programmordner.")
                # License files can be nested, but existing junctions may not escape.
                old = backup / item.filename
                existed = destination.is_file()
                if existed:
                    old.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(destination, old)
                changed.append((destination, old, existed))
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(destination.name + ".update-new")
                with archive.open(item) as incoming, temporary.open("wb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                temporary.replace(destination)
        token = secrets.token_hex(12)
        process = launch(target, data, port, token)
        if not healthy(process, data, payload["version"], token):
            raise RuntimeError("Die neue Version startet nicht zuverlässig.")
        installed["files"] = sorted(set(installed["files"]) | {item.filename for item in items})
        atomic_json(marker, installed)
        if os.name == "nt":
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\VideoStudioEinfach", 0, winreg.KEY_SET_VALUE) as key:
                    # Only alter this installation's registered entry.
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\VideoStudioEinfach") as readable:
                        location = winreg.QueryValueEx(readable, "InstallLocation")[0]
                    if Path(location).resolve() == target:
                        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, payload["version"])
            except OSError:
                pass
        atomic_json(data / "updates" / "status.json", {"state":"installed", "version":payload["version"], "message":"Update automatisch installiert."})
        return True
    except Exception as exc:
        stop_process(process)
        for destination, old, existed in reversed(changed):
            if existed:
                shutil.copyfile(old, destination)
            else:
                destination.unlink(missing_ok=True)
        atomic_json(data / "updates" / "status.json", {"state":"rolled_back", "failed_version":payload["version"], "message":"Das Update ist fehlgeschlagen. Die vorherige Version wurde wiederhergestellt.", "details":str(exc)})
        token = secrets.token_hex(12)
        launch(target, data, port, token)
        return False


def wait_for_pids(pids, timeout=90):
    deadline = time.monotonic() + timeout
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        for pid in pids:
            handle = kernel.OpenProcess(0x00100000, False, int(pid))
            if handle:
                try:
                    remaining = max(0, int((deadline - time.monotonic()) * 1000))
                    if kernel.WaitForSingleObject(handle, remaining) != 0:
                        raise RuntimeError("Das bisherige Programm ist noch geöffnet.")
                finally:
                    kernel.CloseHandle(handle)


def apply_plan(plan_path):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    data = Path(plan["data"]).resolve()
    if not plan_path.resolve().is_relative_to(data / "updates"):
        raise ValueError("Ungültiger Updateauftrag.")
    payload = verify_manifest(plan["manifest"])
    if version_key(payload["version"]) <= version_key(VERSION) or version_key(payload["min_version"]) > version_key(VERSION):
        raise ValueError("Diese Update-Version kann nicht installiert werden.")
    package = Path(plan["package"]).resolve()
    if not package.is_relative_to(data / "updates"):
        raise ValueError("Ungültige Update-Datei.")
    verify_package(package, payload)
    wait_for_pids(plan["pids"])
    apply_package(package, payload, Path(plan["target"]), data, int(plan["port"]))


class Updater:
    def __init__(self, studio, enabled=None):
        self.studio = studio
        self.root = Path(sys.executable).resolve().parent
        self.cache = studio.data / "updates"
        self.cache.mkdir(exist_ok=True)
        self.enabled = bool(getattr(sys, "frozen", False) and os.name == "nt" and (self.root / "installation.json").is_file()) if enabled is None else enabled
        self.lock = threading.Lock()
        self.checking = False
        self.prepared = None
        self.shutdown = threading.Event()
        self.state = {"state":"idle", "message":"Automatische Updates aktiv." if self.enabled else "Updates im Quellcodebetrieb nicht aktiv."}
        status = self.cache / "status.json"
        try:
            self.state = json.loads(status.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    def start(self, skip_initial=False):
        if self.enabled:
            threading.Thread(target=self.loop, args=(skip_initial,), daemon=True).start()

    def loop(self, skip_initial=False):
        if not skip_initial:
            self.check()
        last = time.monotonic()
        while not self.shutdown.wait(2):
            self.install_when_idle()
            if time.monotonic() - last > CHECK_INTERVAL:
                self.check()
                last = time.monotonic()

    def check_async(self):
        if self.enabled:
            threading.Thread(target=self.check, daemon=True).start()

    def check(self):
        with self.lock:
            if self.checking or self.prepared or self.studio.updating:
                return
            self.checking = True
        try:
            self.state = {"state":"checking", "message":"Suche nach Updates …"}
            releases = fetch_json(API, 1024 * 1024)
            candidates = []
            for release in releases:
                if release.get("draft"):
                    continue
                try:
                    key = version_key(release["tag_name"])
                    if key <= version_key(VERSION):
                        continue
                    asset = next((asset for asset in release.get("assets", []) if asset["name"] == "update.json"), None)
                    if asset and asset["browser_download_url"] == f"https://github.com/{REPOSITORY}/releases/download/{release['tag_name']}/update.json":
                        candidates.append((key, asset["browser_download_url"]))
                except (KeyError, TypeError, ValueError):
                    continue
            previous = {}
            try:
                previous = json.loads((self.cache / "status.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            for _, url in sorted(candidates, reverse=True):
                envelope = fetch_json(url)
                payload = verify_manifest(envelope)
                if previous.get("failed_version") == payload["version"]:
                    self.state = previous
                    return
                if version_key(payload["version"]) <= version_key(VERSION):
                    continue
                if version_key(payload["min_version"]) > version_key(VERSION):
                    self.state = {"state":"manual", "message":"Eine neue Version benötigt einen neuen Installer."}
                    return
                self.stage(envelope, payload)
                return
            self.state = {"state":"current", "message":"Video Studio ist aktuell."}
        except Exception as exc:
            (self.cache / "pruefung.log").write_text(str(exc), encoding="utf-8")
            self.state = {"state":"unavailable", "message":"Updateprüfung derzeit nicht möglich. Du kannst lokal weiterarbeiten."}
        finally:
            with self.lock:
                self.checking = False

    def stage(self, envelope, payload):
        self.state = {"state":"downloading", "message":f"Update {payload['version']} wird geladen …"}
        package = self.cache / payload["package"]["name"]
        temporary = package.with_suffix(".download")
        with request(payload["package"]["url"]) as response, temporary.open("wb") as output:
            have = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                have += len(block)
                if have > payload["package"]["size"]:
                    raise ValueError("Die Update-Datei ist zu groß.")
                output.write(block)
        verify_package(temporary, payload)
        temporary.replace(package)
        self.prepared = (envelope, payload, package)
        self.state = {"state":"ready", "message":"Update bereit. Installation, sobald kein Video erstellt wird."}

    def install_when_idle(self):
        if not self.prepared or not self.enabled:
            return False
        studio = self.studio
        with studio.setup_lock, studio.runner.lock:
            if studio.runner.busy or (studio.setup and studio.setup.get("state") == "running") or studio.updating:
                return False
            envelope, payload, package = self.prepared
            studio.updating = True
            self.state = {"state":"installing", "message":"Update wird installiert. Video Studio startet gleich neu …"}
            helper = self.cache / f"update-helper-{secrets.token_hex(6)}.exe"
            plan_path = self.cache / "auftrag.json"
            atomic_json(plan_path, {"manifest":envelope, "package":str(package), "target":str(self.root), "data":str(studio.data),
                                   "port":studio.server.server_port, "pids":[os.getpid(), os.getppid()]})
            try:
                shutil.copyfile(sys.executable, helper)
                subprocess.Popen([str(helper), "--apply-update", str(plan_path)], cwd=self.cache, creationflags=CREATE_FLAGS)
            except Exception:
                studio.updating = False
                self.state = {"state":"error", "message":"Das Update konnte nicht gestartet werden. Die bisherige Version läuft weiter."}
                self.prepared = None
                return False
            studio.server.shutdown()
            return True
