"""Local WanGP adapter. The browser never supplies paths or engine arguments."""
from __future__ import annotations

import json
import copy
import os
import re
import shutil
import subprocess
import threading
import time
import sys
import secrets
from pathlib import Path

MODEL = "ltx2_22B_distilled_gguf_q4_k_m"
WINDOW_FRAMES = 193
WINDOW_OVERLAP = 17
CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_engine_launch_lock = threading.RLock()


def atomic_json(path: Path, value):
    temporary = path.with_name(path.name + '.' + secrets.token_hex(4) + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def compose_prompt(scene: str, speech: str, sounds: str, direct_prompt=True, has_end_image=False):
    if direct_prompt:
        # Keep the user's scene verbatim. Only explicitly completed audio fields
        # add text; there is no language model rewriting this description.
        prompt = scene
        if speech.strip():
            prompt += "\n\nSpoken dialogue in German, with synchronized lip movement: " + json.dumps(speech.strip(), ensure_ascii=False)
        if sounds.strip():
            prompt += "\n\nSound design: " + sounds.strip()
        return prompt
    prompt = (
        "A single continuous photorealistic live-action shot. Preserve the identity, face, "
        "body proportions, clothing and visual appearance of the person in the starting image. "
        "Natural realistic anatomy, coherent motion, consistent facial identity.\n"
        f"Scene and actions (the user's instructions):\n{scene.strip()}\n"
    )
    if has_end_image:
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
    return prompt


def build_settings(scene: str, speech: str, sounds: str, images: list[Path], seconds: int, seed: int, direct_prompt=True, profile=None):
    from PIL import Image
    with Image.open(images[0]) as image:
        width, height = image.size
    resolution = "512x896" if height > width * 1.15 else "896x512" if width > height * 1.15 else "640x640"
    fps = profile['fps'] if profile else 24
    frames = round(seconds * fps)
    if profile:
        resolution = 'x'.join(str(max(32, round(profile[key] / 32) * 32)) for key in ('width', 'height'))
    prompt = compose_prompt(scene, speech, sounds, direct_prompt, len(images) == 2)
    result = {
        "model_type": MODEL, "prompt": prompt, "resolution": resolution,
        "video_length": ((frames + 7) // 8) * 8 + 1, "num_inference_steps": 8,
        "seed": seed, "prompt_enhancer": "", "image_prompt_type": "SE" if len(images) == 2 else "S",
        "image_start": str(images[0].resolve()), "audio_prompt_type": "",
        "audio_guide": None,
        "repeat_generation": 1, "batch_size": 1,
        "multi_prompts_gen_type": "FG",
        "sliding_window_size": WINDOW_FRAMES,
        "sliding_window_overlap": WINDOW_OVERLAP,
    }
    if profile:
        result['force_fps'] = str(fps)
    if len(images) == 2:
        result["image_end"] = str(images[1].resolve())
    return result


def engine_python(engine: Path):
    return engine / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def engine_environment(environ=None, bundle=None):
    env = dict(os.environ if environ is None else environ)
    for key in list(env):
        if key.upper() in ('PYTHONHOME', 'PYTHONPATH', 'PYTHONUSERBASE', '_MEIPASS2') or key.startswith('_PYI_'):
            env.pop(key, None)
    if bundle:
        root = os.path.normcase(os.path.abspath(bundle))
        def outside_bundle(value):
            path = os.path.normcase(os.path.abspath(value.strip('"')))
            return path != root and not path.startswith(root + os.sep)
        env['PATH'] = os.pathsep.join(value for value in env.get('PATH', '').split(os.pathsep) if value and outside_bundle(value))
        for key in ('LD_LIBRARY_PATH', 'LIBPATH'):
            if key + '_ORIG' in env:
                env[key] = env[key + '_ORIG']
            else:
                env.pop(key, None)
    env.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', GRADIO_ANALYTICS_ENABLED='False', DO_NOT_TRACK='1')
    return env


def engine_command(engine, preview, arguments):
    worker = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'preview_worker.py'
    # -I excludes the packaged script's directory and ignores Python environment
    # variables. Otherwise a bundled 3.12 .pyd can shadow a 3.11 stdlib module.
    # -X utf8 also applies when -I ignores PYTHONIOENCODING/PYTHONUTF8.
    return [str(engine_python(engine)), '-I', '-X', 'utf8', '-u', str(worker), str(engine), str(preview), *arguments]


def popen_engine(command, engine):
    bundle = getattr(sys, '_MEIPASS', None)
    env = engine_environment(bundle=bundle)
    with _engine_launch_lock:
        kernel = None
        if os.name == 'nt' and getattr(sys, 'frozen', False):
            import ctypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetDllDirectoryW.argtypes = (ctypes.c_uint32, ctypes.c_wchar_p)
            kernel.GetDllDirectoryW.restype = ctypes.c_uint32
            kernel.SetDllDirectoryW.argtypes = (ctypes.c_wchar_p,)
            kernel.SetDllDirectoryW.restype = ctypes.c_bool
            length = kernel.GetDllDirectoryW(0, None)
            buffer = ctypes.create_unicode_buffer(max(1, length + 1))
            kernel.GetDllDirectoryW(len(buffer), buffer)
            previous = buffer.value or None
            if not kernel.SetDllDirectoryW(None):
                raise ctypes.WinError(ctypes.get_last_error())
        try:
            return subprocess.Popen(command, cwd=engine, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=CREATE_FLAGS)
        finally:
            if kernel is not None:
                kernel.SetDllDirectoryW(previous)


def check_engine_start(engine, report, settings=None):
    """Exercise the actual bundled-worker launch; never generate a video."""
    result = {'ok': False, 'frontend_python': sys.version.split()[0], 'frozen': bool(getattr(sys, 'frozen', False))}
    report.parent.mkdir(parents=True, exist_ok=True)
    process = None
    try:
        process = popen_engine(engine_command(engine, report.with_suffix('.jpg'), ['--studio-startup-check']), engine)
        output = process.communicate(timeout=90)[0].decode('utf-8', errors='replace')
        if process.returncode:
            raise RuntimeError(output[-12000:])
        result['engine'] = json.loads(output)
        if settings:
            command = engine_command(engine, report.with_suffix('.jpg'), ['--offline', '--profile', '4', '--no-mcp-webui',
                '--attention', 'sdpa', '--process', str(settings.resolve()), '--dry-run', '--output-dir', str(report.parent / 'dry-run-output')])
            process = popen_engine(command, engine)
            output = process.communicate(timeout=240)[0].decode('utf-8', errors='replace')
            report.with_suffix('.log').write_text(output, encoding='utf-8')
            if process.returncode:
                raise RuntimeError(output[-12000:])
            result['dry_run'] = True
        result['ok'] = True
    except Exception as exc:
        if process and process.poll() is None:
            Runner.stop_process(process)
            process.communicate()
        result['error'] = str(exc)
    atomic_json(report, result)
    return result


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
                    status['live_preview'] = None
                    for shot in status.get('shots', []):
                        if shot['state'] in ('queued', 'running'):
                            shot['state'] = 'interrupted'
                    atomic_json(file, status)
                if self.last is None:
                    self.last = status
            except (ValueError, KeyError, OSError):
                continue

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.current or self.last)

    def update(self, **values):
        with self.lock:
            self.current.update(values)
            atomic_json(self.data / "jobs" / self.current["id"] / "status.json", self.current)

    def start(self, job_id, settings, audible):
        from media import resolve_profile
        from PIL import Image
        job = self.data / 'jobs' / job_id
        if (job / 'export.json').is_file():
            profile = json.loads((job / 'export.json').read_text(encoding='utf-8'))
            seconds = json.loads((job / 'eingaben.json').read_text(encoding='utf-8'))['seconds']
        else:
            with Image.open(settings['image_start']) as image:
                profile = resolve_profile(None, image.size)
            seconds = (settings['video_length'] - 1) / int(settings.get('force_fps', 24))
        plan = [{'kind': 'generate', 'settings': settings, 'audible': audible,
                 'seconds': seconds, 'frames': round(seconds * profile['fps'])}]
        return self.start_plan(job_id, profile, plan)

    def start_plan(self, job_id, profile, plan, title=None):
        with self.lock:
            if self.busy:
                raise ValueError("Ein Video wird bereits erstellt. Bitte warte oder brich es ab.")
            missing = check_engine(self.engine, self.manifest) if any(shot['kind'] == 'generate' for shot in plan) else []
            if missing:
                raise ValueError("Die KI ist noch nicht vollständig eingerichtet. Starte zuerst die Einrichtung.")
            job = self.data / "jobs" / job_id
            for index, shot in enumerate(plan, 1):
                folder = job / 'shots' / f'{index:03}'
                folder.mkdir(parents=True, exist_ok=True)
                if shot.get('settings'):
                    atomic_json(folder / 'settings.json', shot['settings'])
            atomic_json(job / 'plan.json', {'output': profile, 'shots': plan})
            self.current = {"id": job_id, "state": "queued", "message": "Die KI wird gestartet …", "progress": None,
                            "created": time.time(), "seconds": sum(shot['frames'] for shot in plan) / profile['fps'],
                            "title": title, 'output': profile, 'shot_index': 0,
                            'shots': [{'state': 'queued', 'seconds': shot['seconds'], 'kind': shot['kind']} for shot in plan],
                            "submitted_prompt": '\n\n'.join(f"Szene {i+1}:\n{shot['settings']['prompt']}" for i, shot in enumerate(plan) if shot.get('settings'))}
            self.update()
            self.busy = True
            threading.Thread(target=self.run, args=(job, profile, plan), daemon=True).start()
            return self.snapshot()

    def cancelled(self):
        with self.lock:
            if self.current['state'] == 'cancelling':
                raise RuntimeError('Erstellung abgebrochen.')

    def shot_update(self, index, **values):
        with self.lock:
            self.current['shots'][index].update(values)
            self.update()

    def run(self, job, profile, plan):
        from media import binary, final_command, normalize_command
        try:
            audible = any(shot['audible'] for shot in plan)
            for index, shot in enumerate(plan):
                folder = job / 'shots' / f'{index+1:03}'
                with self.lock:
                    self.cancelled()
                    self.update(state='running', shot_index=index, progress=index / len(plan) * 95,
                                live_preview=None, message=f'Szene {index+1} von {len(plan)} wird vorbereitet …')
                self.shot_update(index, state='running')
                source = Path(shot['source']) if shot['kind'] == 'clip' else self.render_shot(folder)
                self.cancelled()
                self.update(message=f'Szene {index+1} von {len(plan)} wird gespeichert …')
                self.postprocess(normalize_command(self.engine, source, folder / 'video.mp4', profile,
                                 shot['frames'], audible, shot.get('start', 0), shot['audible']), job)
                self.cancelled()
                if index == 0 and not (job / 'bild-1.jpg').is_file():
                    self.postprocess([binary(self.engine, 'ffmpeg'), '-v', 'error', '-nostdin', '-y', '-i',
                                      str(folder / 'video.mp4'), '-frames:v', '1', '-vf',
                                      'scale=512:512:force_original_aspect_ratio=decrease', str(job / 'bild-1.jpg')], job)
                self.shot_update(index, state='done', video=f'/media/{job.name}/shots/{index+1:03}/video.mp4')
                self.update(progress=(index+1) / len(plan) * 95)
            self.cancelled()
            self.update(message='Die Szenen werden zur Episode zusammengesetzt …', progress=96, live_preview=None)
            concat = job / 'szenen.txt'
            concat.write_text(''.join(f"file 'shots/{index+1:03}/video.mp4'\n" for index in range(len(plan))), encoding='utf-8')
            command = [binary(self.engine, 'ffmpeg'), '-v', 'warning', '-nostdin', '-y', '-copyts', '-f', 'concat', '-safe', '1',
                       '-i', str(concat), '-c', 'copy', '-movflags', '+faststart', str(job / 'video.mp4')]
            self.postprocess(command, job)
            container = profile['container']
            if container == 'webm':
                self.update(message='WebM-Datei wird erstellt …', progress=98)
                self.postprocess(final_command(self.engine, job / 'video.mp4', job / 'video.webm', container), job)
            with self.lock:
                self.cancelled()
                self.update(state='done', message='Deine Episode ist fertig.' if len(plan)>1 else 'Dein Video ist fertig.',
                            progress=100, video=f'/media/{job.name}/video.{container}')
        except Exception as exc:
            with self.lock:
                cancelled = self.current['state'] == 'cancelling'
                for shot in self.current['shots']:
                    if shot['state'] in ('queued', 'running'):
                        shot['state'] = 'cancelled' if cancelled else 'interrupted'
            self.update(state='cancelled' if cancelled else 'error', progress=None,
                        message='Erstellung abgebrochen. Fertige Szenen bleiben erhalten.' if cancelled else str(exc))
        finally:
            # An unexpected log/export error must not leave a child rendering.
            proc = self.proc
            if proc and proc.poll() is None:
                self.stop_process(proc)
            if proc and proc.stdout:
                proc.stdout.close()
            with self.lock:
                self.proc = None
                self.last = copy.deepcopy(self.current)
                self.busy = False

    def render_shot(self, folder):
        self.cancelled()
        command = engine_command(self.engine, folder / 'live-preview.jpg',
                                ["--offline", "--profile", "4", "--no-mcp-webui", "--attention", "sdpa",
                                 "--process", str(folder / "settings.json"), "--output-dir", str(folder / "render")])
        with self.lock:
            self.cancelled()
            process = popen_engine(command, self.engine)
            self.proc = process
        job = folder.parents[1]
        with (job / "diagnose.log").open("a", encoding="utf-8") as log:
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
                    if '[STUDIO_PREVIEW]' in line:
                        self.update(live_preview=f'/media/{job.name}/shots/{folder.name}/live-preview.jpg?v={time.time_ns()}')
                    elif '[STUDIO_PREVIEW_UNAVAILABLE]' in line:
                        self.update(preview_note='Die Zwischenbildvorschau ist hier nicht verfügbar. Fertige Szenen erscheinen unten.')
                    buffer.clear()
                else:
                    buffer.extend(chunk)
            if buffer:
                log.write(buffer.decode("utf-8", errors="replace"))
        code = process.wait()
        process.stdout.close()
        self.cancelled()
        outputs = sorted((folder / "render").rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
        if code != 0 or not outputs:
            raise RuntimeError(self.friendly_error(job / "diagnose.log"))
        return outputs[-1]

    def postprocess(self, command, job):
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
            index = self.current.get('shot_index', 0)
            shots = self.current.get('shots', [{'seconds': self.current['seconds']}])
            overall = (index + value / 100) / len(shots) * 95
            self.update(message=f'Szene {index+1} von {len(shots)}: ' + ("Video wird berechnet …" if total == 8 else "Details werden verfeinert …"), progress=None if shots[index]['seconds'] > 8 else overall)
        elif "Encoding Text Prompt" in line:
            self.update(message="Die KI liest deine Szenenbeschreibung …", progress=None)
        elif "VAE Decoding" in line or "Encoding Video" in line:
            self.update(message="Bild und Ton werden gespeichert …")

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
            self.stop_process(proc)

    @staticmethod
    def stop_process(proc):
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True, creationflags=CREATE_FLAGS)
        else:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
