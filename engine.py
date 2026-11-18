"""Local WanGP adapter. The browser never supplies paths or engine arguments."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

MODEL = "ltx2_22B_distilled_gguf_q4_k_m"
WINDOW_FRAMES = 193
WINDOW_OVERLAP = 17
CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def atomic_json(path: Path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def build_settings(scene: str, speech: str, sounds: str, images: list[Path], seconds: int, seed: int):
    from PIL import Image
    with Image.open(images[0]) as image:
        width, height = image.size
    resolution = "512x896" if height > width * 1.15 else "896x512" if width > height * 1.15 else "640x640"
    prompt = (
        "A single continuous photorealistic live-action shot. Preserve the identity, face, "
        "body proportions, clothing and visual appearance of the person in the starting image. "
        "Natural realistic anatomy, coherent motion, consistent facial identity.\n"
        f"Scene and actions (the user's instructions):\n{scene.strip()}\n"
    )
    if len(images) == 2:
        prompt += "The shot ends with the framing and pose in the provided ending image.\n"
    if speech.strip():
        # The model generates speech jointly with video; no cloud TTS or extra model.
        prompt += (
            "The on-screen person speaks in German, clearly and naturally, with synchronized "
            f"lip movement. Spoken words, verbatim: {json.dumps(speech.strip(), ensure_ascii=False)}.\n"
        )
    else:
        prompt += "No spoken dialogue.\n"
    prompt += f"Sound design: {sounds.strip()}.\n" if sounds.strip() else "Quiet natural ambient sound, no music.\n"
    result = {
        "model_type": MODEL, "prompt": prompt, "resolution": resolution,
        "video_length": seconds * 24 + 1, "num_inference_steps": 8,
        "seed": seed, "prompt_enhancer": "", "image_prompt_type": "SE" if len(images) == 2 else "S",
        "image_start": str(images[0].resolve()), "audio_prompt_type": "",
        "audio_guide": None,
        "repeat_generation": 1, "batch_size": 1,
        "sliding_window_size": WINDOW_FRAMES,
        "sliding_window_overlap": WINDOW_OVERLAP,
    }
    if len(images) == 2:
        result["image_end"] = str(images[1].resolve())
    return result


def engine_python(engine: Path):
    return engine / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def check_engine(engine: Path, manifest: dict):
    missing = []
    if not (engine / "wgp.py").is_file() or not engine_python(engine).is_file():
        return ["Videoberechnung"]
    for item in manifest["models"]:
        path = engine / "ckpts" / item["path"]
        if not path.is_file() or path.stat().st_size != item["size"]:
            missing.append(Path(item["path"]).name)
    return missing


class Runner:
    def __init__(self, engine: Path, data: Path, manifest: dict):
        self.engine, self.data, self.manifest = engine, data, manifest
        self.lock = threading.RLock()
        self.proc = None
        self.current = None
        self.last = None
        self.busy = False
        for file in sorted((data / "jobs").glob("*/status.json"), reverse=True):
            try:
                status = json.loads(file.read_text(encoding="utf-8"))
                if status["state"] in ("queued", "running", "cancelling"):
                    status.update(state="interrupted", message="Die Erstellung wurde unterbrochen. Du kannst ein neues Video starten.")
                    atomic_json(file, status)
                if self.last is None:
                    self.last = status
            except (ValueError, KeyError, OSError):
                continue

    def snapshot(self):
        with self.lock:
            return dict(self.current or self.last) if self.current or self.last else None

    def update(self, **values):
        with self.lock:
            self.current.update(values)
            atomic_json(self.data / "jobs" / self.current["id"] / "status.json", self.current)

    def start(self, job_id, settings, audible):
        with self.lock:
            if self.busy:
                raise ValueError("Ein Video wird bereits erstellt. Bitte warte oder brich es ab.")
            missing = check_engine(self.engine, self.manifest)
            if missing:
                raise ValueError("Die KI ist noch nicht vollständig eingerichtet. Starte zuerst die Einrichtung.")
            job = self.data / "jobs" / job_id
            atomic_json(job / "settings.json", settings)
            self.current = {"id": job_id, "state": "queued", "message": "Die KI wird gestartet …", "progress": None,
                            "created": time.time(), "seconds": (settings["video_length"] - 1) // 24}
            self.update()
            self.busy = True
            threading.Thread(target=self.run, args=(job, audible), daemon=True).start()
            return dict(self.current)

    def run(self, job, audible):
        process = None
        try:
            env = os.environ.copy()
            env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1",
                       HF_HUB_DISABLE_TELEMETRY="1", GRADIO_ANALYTICS_ENABLED="False", DO_NOT_TRACK="1")
            env.pop("PYTHONHOME", None)
            env.pop("PYTHONPATH", None)
            command = [str(engine_python(self.engine)), "-u", "wgp.py", "--offline", "--profile", "4",
                       "--no-mcp-webui", "--attention", "sdpa", "--process", str(job / "settings.json"),
                       "--output-dir", str(job / "render")]
            with self.lock:
                if self.current["state"] == "cancelling":
                    self.update(state="cancelled", message="Erstellung abgebrochen.")
                    return
                self.update(state="running", message="Die KI lädt die Bilder und bereitet das Video vor …")
                process = subprocess.Popen(command, cwd=self.engine, env=env, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, creationflags=CREATE_FLAGS)
                self.proc = process
            with (job / "diagnose.log").open("w", encoding="utf-8") as log:
                # tqdm writes carriage-return progress. Read bounded chunks, not only newlines.
                buffer = bytearray()
                while True:
                    chunk = process.stdout.read(1)
                    if not chunk:
                        break
                    if chunk in (b"\r", b"\n") or len(buffer) > 16000:
                        line = buffer.decode("utf-8", errors="replace")
                        log.write(line + "\n")
                        log.flush()
                        self.parse_progress(line)
                        buffer.clear()
                    else:
                        buffer.extend(chunk)
                if buffer:
                    log.write(buffer.decode("utf-8", errors="replace"))
            code = process.wait()
            with self.lock:
                if self.current["state"] == "cancelling":
                    self.update(state="cancelled", message="Erstellung abgebrochen.", progress=None)
                    return
            outputs = sorted((job / "render").rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
            if code != 0 or not outputs:
                raise RuntimeError(self.friendly_error(job / "diagnose.log"))
            source = outputs[-1]
            target = job / "video.mp4"
            if audible:
                shutil.copyfile(source, target)
            else:
                ffmpeg = self.engine / "ffmpeg_bins" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
                command = [str(ffmpeg), "-y", "-i", str(source), "-c:v", "copy", "-an", "-movflags", "+faststart", str(target)]
                self.postprocess(command, job)
            self.update(state="done", message="Dein Video ist fertig.", progress=100, video=f"/media/{job.name}/video.mp4")
        except Exception as exc:
            with self.lock:
                cancelled = self.current["state"] == "cancelling"
            self.update(state="cancelled" if cancelled else "error", progress=None,
                        message="Erstellung abgebrochen." if cancelled else str(exc))
        finally:
            with self.lock:
                self.proc = None
                self.last = dict(self.current)
                self.busy = False

    def postprocess(self, command, job):
        self.update(message="Das Video wird gespeichert …", progress=99)
        with self.lock, (job / "diagnose.log").open("a", encoding="utf-8") as log:
            if self.current["state"] == "cancelling":
                raise RuntimeError("Erstellung abgebrochen.")
            process = subprocess.Popen(command, stdout=log, stderr=log, creationflags=CREATE_FLAGS)
            self.proc = process
        if process.wait() != 0:
            raise RuntimeError("Das Video konnte nicht gespeichert werden. Details findest du unter Hilfe.")

    def parse_progress(self, line):
        if "cancelling" == self.snapshot()["state"]:
            return
        match = re.search(r"(\d+)%\|.*?\|\s*(\d+)/(\d+)", line)
        if match:
            total = int(match[3])
            if total not in (8, 3):
                return
            fraction = int(match[2]) / total
            value = round(15 + fraction * 60) if total == 8 else round(75 + fraction * 20)
            self.update(message="Dein Video wird berechnet …" if total == 8 else "Bewegung und Details werden verfeinert …", progress=None if self.current["seconds"] > 8 else value)
        elif "Encoding Text Prompt" in line:
            self.update(message="Die KI liest deine Szenenbeschreibung …", progress=None)
        elif "VAE Decoding" in line or "Encoding Video" in line:
            self.update(message="Bild und Ton werden gespeichert …", progress=None if self.current["seconds"] > 8 else 97)

    @staticmethod
    def friendly_error(log):
        text = log.read_text(encoding="utf-8", errors="replace")[-20000:]
        if "out of memory" in text.lower():
            return "Der Grafikspeicher reicht gerade nicht aus. Schließe andere KI-Programme oder Spiele und versuche es erneut."
        if "is missing" in text or "not found locally" in text:
            return "Eine KI-Datei fehlt. Öffne Hilfe und wähle ‚KI-Dateien prüfen und ergänzen‘."
        if "CUDA" in text and any(word in text.lower() for word in ("driver", "no kernel", "not available")):
            return "Die Grafikkarte ist nicht bereit. Prüfe den NVIDIA-Treiber. Details findest du unter Hilfe."
        return "Das Video konnte nicht erstellt werden. Deine Eingaben bleiben erhalten. Unter Hilfe kannst du das Fehlerprotokoll öffnen."

    def cancel(self):
        with self.lock:
            if not self.current or self.current["state"] not in ("queued", "running", "cancelling"):
                return
            self.update(state="cancelling", message="Die Erstellung wird abgebrochen …")
            proc = self.proc
        if proc and proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=CREATE_FLAGS)
            else:
                proc.terminate()
