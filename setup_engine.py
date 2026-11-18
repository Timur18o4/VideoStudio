"""One-click local setup, pinned sources and resumable verified model downloads."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from engine import CREATE_FLAGS, atomic_json, check_engine, engine_python

BLOCK = 8 * 1024 * 1024
STREAM_THRESHOLD = 128 * 1024 * 1024


def fetch(url, headers=None, timeout=75):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "VideoStudio/0.1", **(headers or {})}), timeout=timeout)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(item, dest, update):
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = item["size"]
    if dest.is_file() and dest.stat().st_size == size:
        update(f"Prüfe {dest.name} …")
        if digest(dest) == item["sha256"]:
            return
        dest.rename(dest.with_name(dest.name + f".beschaedigt-{time.time_ns()}"))
    partial = dest.with_name(dest.name + ".download")
    have = partial.stat().st_size if partial.exists() else 0
    if have > size:
        have = 0

    def part(url, start, end):
        for attempt in range(5):
            try:
                with fetch(url, {"Range": f"bytes={start}-{end}"}) as response:
                    if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{size}":
                        raise OSError("Der Downloadserver hat keinen gültigen Dateiblock geliefert.")
                    data = response.read(end - start + 2)
                    if len(data) != end - start + 1:
                        raise OSError("Ein Dateiblock war unvollständig.")
                    return data
            except (OSError, urllib.error.URLError):
                if attempt == 4:
                    raise
                time.sleep(min(2 ** attempt, 8))

    update(f"Lade {dest.name} herunter …", round(have / size * 100))
    if size <= STREAM_THRESHOLD:
        # GitHub's source archives do not support byte-range requests. They must
        # also work after an interrupted download, when Range is ignored.
        for attempt in range(5):
            try:
                with fetch(item["url"], {"Range": f"bytes={have}-"} if have else None) as response:
                    if response.status == 200:
                        have = 0
                    elif response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {have}-"):
                        raise OSError("Der Download konnte nicht fortgesetzt werden.")
                    with partial.open("r+b" if partial.exists() else "w+b") as stream:
                        stream.truncate(have)
                        stream.seek(have)
                        while True:
                            block = response.read(1024 * 1024)
                            if not block:
                                break
                            stream.write(block)
                            have = stream.tell()
                            if have > size:
                                raise OSError("Die heruntergeladene Datei hat eine unerwartete Größe.")
                            update(f"{dest.name}: {have / 1e6:.0f} von {size / 1e6:.0f} MB", round(have / size * 100))
                if have != size:
                    raise OSError("Der Download ist unvollständig.")
                break
            except (OSError, urllib.error.URLError):
                if attempt == 4:
                    raise RuntimeError("Der Download wurde unterbrochen. Prüfe die Internetverbindung und starte die Einrichtung erneut.")
                time.sleep(min(2 ** attempt, 8))
    else:
        with partial.open("r+b" if partial.exists() else "w+b") as stream, ThreadPoolExecutor(max_workers=4) as pool:
            stream.truncate(have)
            stream.seek(have)
            while have < size:
                # Resolve a fresh signed CDN URL each batch; keep authentication out of logs.
                with fetch(item["url"]) as redirect:
                    source = redirect.url
                starts = range(have, min(size, have + BLOCK * 16), BLOCK)
                # Four workers, four blocks at a time: bounded memory on consumer PCs.
                starts = list(starts)
                for offset in range(0, len(starts), 4):
                    futures = [pool.submit(part, source, start, min(start + BLOCK, size) - 1) for start in starts[offset:offset+4]]
                    for future in futures:
                        stream.write(future.result())
                        stream.flush()
                        have = stream.tell()
                        update(f"{dest.name}: {have / 1e9:.2f} von {size / 1e9:.2f} GB", round(have / size * 100))
    update(f"Prüfe {dest.name} …")
    if partial.stat().st_size != size or digest(partial) != item["sha256"]:
        partial.rename(partial.with_name(partial.name + f".beschaedigt-{time.time_ns()}"))
        raise RuntimeError("Eine heruntergeladene Datei war beschädigt. Starte die Einrichtung erneut.")
    partial.replace(dest)


def extract_zip(archive, destination, strip_root=False):
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            parts = Path(entry.filename.replace("\\", "/")).parts
            if strip_root:
                parts = parts[1:]
            if not parts:
                continue
            target = destination.joinpath(*parts).resolve()
            if not target.is_relative_to(root):
                raise ValueError("Ungültiger Pfad im Programmarchiv.")
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as incoming, target.open("wb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)


def hardware_check():
    if os.name != "nt":
        raise RuntimeError("Diese Version ist für Windows mit NVIDIA-Grafikkarte vorgesehen.")
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=20, creationflags=CREATE_FLAGS)
        sizes = [int(line.rsplit(",", 1)[1]) for line in result.stdout.splitlines() if "," in line]
        if result.returncode or not sizes:
            raise OSError()
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Keine nutzbare NVIDIA-Grafikkarte erkannt. Prüfe die Grafikkarte und den NVIDIA-Treiber.") from exc
    if max(sizes) < 8000:
        raise RuntimeError("Diese Version benötigt eine NVIDIA-Grafikkarte mit mindestens 8 GB Grafikspeicher.")
    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(name, ctypes.c_ulonglong) for name in ("total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]
    memory = Memory()
    memory.length = ctypes.sizeof(memory)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)) and memory.total < 30 * 1024**3:
        raise RuntimeError("Diese Version ist für PCs mit mindestens 32 GB Arbeitsspeicher vorgesehen.")


def install(engine, data, manifest, update):
    hardware_check()
    from app import RESOURCES
    cache = data / "einrichtung"
    cache.mkdir(exist_ok=True)
    fresh = not engine_python(engine).is_file()
    remaining = sum(item["size"] for item in manifest["models"] if not (engine / "ckpts" / item["path"]).is_file())
    required = remaining + (25 * 1024**3 if fresh else 2 * 1024**3)
    engine.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(engine).free < required:
        raise RuntimeError(f"Nicht genug freier Speicher. Benötigt werden noch ungefähr {required / 1e9:.0f} GB.")
    log_path = data / "einrichtung-details.log"
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", UV_PYTHON_INSTALL_DIR=str(data / "python"), UV_CACHE_DIR=str(cache / "uv-cache"), UV_NO_PROGRESS="1", UV_LINK_MODE="copy")
    # A frozen executable can set these for its own bundled interpreter.
    for name in ("PYTHONHOME", "PYTHONPATH", "HF_HUB_OFFLINE"):
        env.pop(name, None)

    def run(command, cwd=None):
        with log_path.open("a", encoding="utf-8") as log:
            result = subprocess.run([str(x) for x in command], cwd=cwd, env=env, stdout=log, stderr=log, creationflags=CREATE_FLAGS)
        if result.returncode:
            raise RuntimeError("Die Einrichtung wurde unterbrochen. Prüfe Internet und NVIDIA-Treiber und starte sie erneut. Details stehen im Einrichtungsprotokoll.")

    if fresh:
        archive = cache / "wangp.zip"
        download(manifest["engine"], archive, update)
        update("Die Videoberechnung wird eingerichtet …")
        extract_zip(archive, engine, strip_root=True)
        uv_zip = cache / "uv.zip"
        download(manifest["uv"], uv_zip, update)
        extract_zip(uv_zip, cache / "uv")
        uv = next((cache / "uv").rglob("uv.exe"))
        update("Python wird automatisch eingerichtet …")
        run([uv, "python", "install", "3.11.14"])
        run([uv, "venv", "--python", "3.11.14", engine / ".venv"])
        update("Die Videoberechnung wird installiert. Das kann einige Zeit dauern …")
        run([uv, "pip", "sync", "--python", engine_python(engine), "--index-strategy", "unsafe-best-match", RESOURCES / "requirements-engine.lock"])
        run([engine_python(engine), "-c", "import torch; assert torch.cuda.is_available(), 'NVIDIA/CUDA nicht bereit'; print(torch.cuda.get_device_name())"], engine)
        atomic_json(engine / "wgp_config.json", {"attention_mode": "sdpa", "profile": 4, "video_profile": 4,
                   "transformer_types": ["ltx2_22B_distilled_gguf_q4_k_m"], "text_encoder_quantization": "int8",
                   "checkpoints_paths": ["ckpts", "."], "save_path": "outputs", "compile": "disabled",
                   "metadata_type": "metadata", "UI_theme": "default"})
        (engine / "video-studio-runtime-ready").write_text(manifest["engine_commit"], encoding="utf-8")
    elif not (engine / "video-studio-runtime-ready").is_file() and engine.is_relative_to(data):
        # An interrupted package install leaves python.exe behind; resume the package phase.
        uv = next((cache / "uv").rglob("uv.exe"), None)
        if uv is None:
            raise RuntimeError("Die Einrichtung ist unvollständig. Das Einrichtungsprotokoll enthält die Details.")
        update("Die unterbrochene Installation wird fortgesetzt …")
        run([uv, "pip", "sync", "--python", engine_python(engine), "--index-strategy", "unsafe-best-match", RESOURCES / "requirements-engine.lock"])
        run([engine_python(engine), "-c", "import torch; assert torch.cuda.is_available()"], engine)
        atomic_json(engine / "wgp_config.json", {"attention_mode": "sdpa", "profile": 4, "video_profile": 4, "checkpoints_paths": ["ckpts", "."], "text_encoder_quantization": "int8", "save_path": "outputs", "compile": "disabled"})
        (engine / "video-studio-runtime-ready").write_text(manifest["engine_commit"], encoding="utf-8")
    ffmpeg = engine / "ffmpeg_bins"
    if not all((ffmpeg / (name + ".exe")).is_file() for name in ("ffmpeg", "ffprobe", "ffplay")):
        archive = cache / "ffmpeg.zip"
        download(manifest["ffmpeg"], archive, update)
        update("Bild und Ton werden vorbereitet …")
        ffmpeg.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as source:
            for entry in source.infolist():
                if "/bin/" in entry.filename and Path(entry.filename).suffix.lower() in (".exe", ".dll"):
                    with source.open(entry) as incoming, (ffmpeg / Path(entry.filename).name).open("wb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
    for item in manifest["models"]:
        download(item, engine / "ckpts" / item["path"], update)
    if check_engine(engine, manifest):
        raise RuntimeError("Die KI-Dateien sind noch unvollständig. Starte die Einrichtung erneut.")
    update("Die KI ist bereit.", 100)
