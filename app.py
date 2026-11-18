"""Small loopback-only web frontend, with no cloud inference or external UI assets."""
from __future__ import annotations

import argparse
import base64
import io
import json
import mimetypes
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote

from engine import CREATE_FLAGS, Runner, atomic_json, check_engine
from version import VERSION

RESOURCES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
MAX_REQUEST = 38 * 1024 * 1024


def normalize_image(value, destination):
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not isinstance(value, str) or len(value) > 18 * 1024 * 1024:
        raise ValueError("Ein Bild darf höchstens 12 MB groß sein.")
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) > 12 * 1024 * 1024:
            raise ValueError("Ein Bild darf höchstens 12 MB groß sein.")
        with Image.open(io.BytesIO(raw)) as original:
            if original.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError("Bitte lade ein JPG-, PNG- oder WebP-Bild hoch.")
            if original.width * original.height > 40_000_000:
                raise ValueError("Das Bild ist zu groß. Verwende ein Bild mit höchstens 40 Megapixeln.")
            image = ImageOps.exif_transpose(original).convert("RGB")
            if min(image.size) < 256:
                raise ValueError("Das Bild ist zu klein. Beide Seiten müssen mindestens 256 Pixel haben.")
            image.thumbnail((2048, 2048))
            image.save(destination, "JPEG", quality=95)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, base64.binascii.Error) as exc:
        raise ValueError("Das Bild konnte nicht gelesen werden. Verwende JPG, PNG oder WebP.") from exc


class Studio:
    def __init__(self, data, engine=None):
        self.data = data.resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "jobs").mkdir(exist_ok=True)
        self.config_path = self.data / "config.json"
        self.config = json.loads(self.config_path.read_text(encoding="utf-8")) if self.config_path.exists() else {}
        if engine:
            self.config["engine"] = str(engine.resolve())
            atomic_json(self.config_path, self.config)
        self.engine = Path(self.config.get("engine", self.data / "engine"))
        self.manifest = json.loads((RESOURCES / "models.lock.json").read_text(encoding="utf-8"))
        self.runner = Runner(self.engine, self.data, self.manifest)
        from episodes import Library
        self.library = Library(self)
        self.token = secrets.token_urlsafe(32)
        self.setup_lock = threading.Lock()
        self.setup = None
        self.server = None
        self.updating = False
        self.update_token = ""
        from updater import Updater
        self.updater = Updater(self)

    def state(self):
        missing = check_engine(self.engine, self.manifest)
        return {"version": VERSION, "ready": not missing, "job": self.runner.snapshot(), "setup": self.setup,
                "update": {**self.updater.state, "enabled":self.updater.enabled},
                "download_gb": round(sum(i["size"] for i in self.manifest["models"]) / 1e9, 1)}

    def prompt_inputs(self, values, require_scene=True):
        scene = values.get("scene", "")
        speech = values.get("speech", "")
        sounds = values.get("sounds", "")
        if not all(isinstance(text, str) for text in (scene, speech, sounds)):
            raise ValueError("Bitte überprüfe die Texteingaben.")
        if require_scene and not scene.strip():
            raise ValueError("Beschreibe zuerst, was im Video passieren soll.")
        if len(scene) > 4000 or len(speech) > 8000 or len(sounds) > 600:
            raise ValueError("Die Beschreibung ist zu lang. Kürze sie bitte etwas.")
        direct_prompt = values.get("direct_prompt", True)
        if type(direct_prompt) is not bool:
            raise ValueError("Die Einstellung für die direkte Beschreibung ist ungültig.")
        return scene, speech, sounds, direct_prompt

    def preview_prompt(self, values):
        from engine import compose_prompt
        scene, speech, sounds, direct_prompt = self.prompt_inputs(values, require_scene=False)
        has_end = values.get("has_end_image", False)
        if type(has_end) is not bool:
            raise ValueError("Die Einstellung für das Schlussbild ist ungültig.")
        return {"prompt":compose_prompt(scene, speech, sounds, direct_prompt, has_end)}

    def create(self, values):
        from engine import build_settings
        from media import export_options, resolve_profile, prepare_reference
        from PIL import Image
        scene, speech, sounds, direct_prompt = self.prompt_inputs(values)
        options = export_options(values.get('output'))
        images = values.get("images")
        if not isinstance(images, list) or not 1 <= len(images) <= 2:
            raise ValueError("Lade ein oder zwei Bilder hoch.")
        seconds = values.get("seconds", 8)
        if type(seconds) is not int or seconds < 1 or seconds > (2**53 - 9) // options['fps']:
            raise ValueError("Gib eine positive ganze Zahl für die Videolänge in Sekunden ein.")
        with self.setup_lock, self.runner.lock:
            if self.runner.busy:
                raise ValueError('Eine Erstellung läuft bereits. Warte oder brich sie ab.')
            if self.updating:
                raise ValueError("Das Programm wird gerade aktualisiert. Warte kurz auf den Neustart.")
            if self.setup and self.setup.get("state") == "running":
                raise ValueError("Die Einrichtung läuft noch. Bitte warte kurz.")
            job_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(4)
            directory = self.data / "jobs" / job_id
            directory.mkdir()
            paths = []
            for index, value in enumerate(images):
                path = directory / f"bild-{index + 1}.jpg"
                normalize_image(value, path)
                paths.append(path)
            with Image.open(paths[0]) as image:
                profile = resolve_profile(options, image.size)
            for path in paths:
                prepare_reference(path, path, profile)
            settings = build_settings(scene, speech, sounds, paths, seconds, secrets.randbelow(2**31), direct_prompt, profile)
            atomic_json(directory / 'export.json', profile)
            atomic_json(directory / "eingaben.json", {"scene": scene, "speech": speech, "sounds": sounds, "seconds": seconds, "direct_prompt":direct_prompt, 'output': options})
            return self.runner.start(job_id, settings, bool(speech.strip() or sounds.strip()))

    def create_episode(self, values):
        recipe = self.library.recipe(values)
        with self.setup_lock, self.runner.lock:
            if self.runner.busy or self.updating or (self.setup and self.setup.get('state') == 'running'):
                raise ValueError('Warte auf die laufende Erstellung, Einrichtung oder Aktualisierung.')
            if any(shot['kind'] == 'generate' for shot in recipe['shots']) and check_engine(self.engine, self.manifest):
                raise ValueError('Richte zuerst die Video-KI ein.')
            job_id = time.strftime('%Y%m%d-%H%M%S-') + secrets.token_hex(4)
            directory = self.data / 'jobs' / job_id
            directory.mkdir()
            atomic_json(directory / 'episode.json', recipe)
            profile, plan = self.library.plan(recipe, directory)
            return self.runner.start_plan(job_id, profile, plan, recipe['title'])

    def begin_setup(self):
        from setup_engine import install
        with self.setup_lock:
            if self.updating:
                raise ValueError("Video Studio wird gerade aktualisiert.")
            if self.setup and self.setup.get("state") == "running":
                return
            job = self.runner.snapshot()
            if job and job["state"] in ("running", "queued", "cancelling"):
                raise ValueError("Warte, bis das aktuelle Video fertig ist.")
            self.setup = {"state": "running", "message": "Dein PC wird geprüft …", "progress": None}
            def update(message, progress=None):
                self.setup = {"state": "running", "message": message, "progress": progress}
            def run():
                try:
                    install(self.engine, self.data, self.manifest, update)
                    self.setup = {"state": "done", "message": "Die KI ist bereit.", "progress": 100}
                except Exception as exc:
                    import traceback
                    (self.data / "einrichtung.log").write_text(traceback.format_exc(), encoding="utf-8")
                    self.setup = {"state": "error", "message": str(exc), "progress": None}
            threading.Thread(target=run, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoStudio"

    @property
    def studio(self):
        return self.server.studio

    def log_message(self, *_):
        pass

    def same_origin(self):
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin == "http://" + expected

    def authenticated(self):
        supplied = self.headers.get("X-Studio-Token", "")
        return self.same_origin() and secrets.compare_digest(supplied, self.studio.token)

    def send_headers(self, code, content_type, size, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def respond(self, value, code=200):
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_headers(code, "application/json; charset=utf-8", len(raw))
        self.wfile.write(raw)

    def do_GET(self):
        if not self.same_origin():
            return self.respond({"error": "Zugriff verweigert."}, 403)
        path = urlsplit(self.path).path
        if path == "/api/health":
            return self.respond({"version": VERSION, "update_token": self.studio.update_token})
        if path == "/api/session":
            return self.respond({"token": self.studio.token})
        if path == "/api/state":
            if not self.authenticated():
                return self.respond({"error": "Bitte lade die Seite neu."}, 403)
            return self.respond(self.studio.state())
        if path == "/api/history":
            if not self.authenticated():
                return self.respond({"error": "Zugriff verweigert."}, 403)
            result = []
            for file in sorted((self.studio.data / "jobs").glob("*/status.json"), reverse=True):
                try:
                    status = json.loads(file.read_text(encoding="utf-8"))
                    if status["state"] == "done" and (file.parent / "video.mp4").is_file():
                        result.append(status)
                except (OSError, ValueError, KeyError):
                    continue
                if len(result) == 12:
                    break
            return self.respond(result)
        if path == '/api/library':
            if not self.authenticated():
                return self.respond({'error': 'Zugriff verweigert.'}, 403)
            return self.respond({'characters': self.studio.library.records('characters'),
                                 'episodes': self.studio.library.records('episodes'), 'clips': self.studio.library.clips()})
        media = re.fullmatch(r"/media/(\d{8}-\d{6}-[0-9a-f]{8})/((?:shots/[0-9]{3}/)?(?:video\.(?:mp4|webm)|bild-[12]\.jpg|live-preview\.jpg))", path)
        if media:
            return self.send_file(self.studio.data / "jobs" / media[1] / media[2], download="download" in urlsplit(self.path).query)
        library = re.fullmatch(r'/library/(images|clips)/([0-9a-f]{32})\.(jpg|mp4)', path)
        if library and (library[1], library[3]) in (('images', 'jpg'), ('clips', 'mp4')):
            return self.send_file(self.studio.data / library[1] / (library[2]+'.'+library[3]))
        static = {"/": "index.html", "/app.js": "app.js", '/episodes.js': 'episodes.js', "/style.css": "style.css", "/favicon.svg": "favicon.svg"}
        if path in static:
            return self.send_file(RESOURCES / "web" / static[path])
        return self.respond({"error": "Nicht gefunden."}, 404)

    def send_file(self, file, download=False):
        if not file.is_file():
            return self.respond({"error": "Datei nicht gefunden."}, 404)
        size = file.stat().st_size
        start, end, code = 0, size - 1, 200
        extra = {"Accept-Ranges": "bytes"}
        if download:
            extra["Content-Disposition"] = f'attachment; filename="Mein-KI-Video{file.suffix}"'
        value = self.headers.get("Range")
        if value:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
            if not match or not any(match.groups()):
                self.send_headers(416, "text/plain", 0, {"Content-Range": f"bytes */{size}"})
                return
            if not match[1]:
                start = max(0, size - int(match[2]))
            else:
                start = int(match[1])
                end = min(end, int(match[2])) if match[2] else end
            if start > end or start >= size:
                self.send_headers(416, "text/plain", 0, {"Content-Range": f"bytes */{size}"})
                return
            code = 206
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        self.send_headers(code, mimetypes.guess_type(file.name)[0] or "application/octet-stream", end - start + 1, extra)
        try:
            with file.open("rb") as stream:
                stream.seek(start)
                left = end - start + 1
                while left:
                    block = stream.read(min(left, 256 * 1024))
                    if not block:
                        break
                    self.wfile.write(block)
                    left -= len(block)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if not self.authenticated():
            return self.respond({"error": "Die Sitzung ist abgelaufen. Lade die Seite neu."}, 403)
        if urlsplit(self.path).path == '/api/import-clip':
            return self.import_clip()
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.respond({"error": "Ungültige Anfrage."}, 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST:
                return self.respond({"error": "Die Bilder sind zu groß. Höchstens 12 MB pro Bild."}, 413)
            self.connection.settimeout(60)
            values = json.loads(self.rfile.read(length))
            if not isinstance(values, dict):
                raise ValueError("Ungültige Eingaben.")
            path = urlsplit(self.path).path
            if path == "/api/generate":
                return self.respond(self.studio.create(values), 202)
            if path == "/api/preview-prompt":
                return self.respond(self.studio.preview_prompt(values))
            if path == '/api/images':
                return self.respond(self.studio.library.image(values.get('image')))
            if path == '/api/characters':
                return self.respond(self.studio.library.character(values))
            if path == '/api/frame':
                return self.respond(self.studio.library.frame(values))
            if path == '/api/save-episode':
                return self.respond(self.studio.library.save(values))
            if path == '/api/generate-episode':
                return self.respond(self.studio.create_episode(values), 202)
            if path == "/api/cancel":
                self.studio.runner.cancel()
            elif path == "/api/check-updates":
                self.studio.updater.check_async()
            elif path == "/api/setup":
                self.studio.begin_setup()
            elif path == "/api/open-folder":
                if os.name == "nt":
                    os.startfile(self.studio.data / "jobs")
            elif path == "/api/open-log":
                job = self.studio.runner.snapshot()
                if self.studio.setup and self.studio.setup.get("state") == "error":
                    log = self.studio.data / "einrichtung-details.log"
                    if not log.is_file():
                        log = self.studio.data / "einrichtung.log"
                else:
                    log = self.studio.data / "jobs" / job["id"] / "diagnose.log" if job else self.studio.data / "einrichtung.log"
                if not log.is_file():
                    raise ValueError("Es liegt noch kein Fehlerprotokoll vor.")
                if os.name == "nt":
                    subprocess.Popen(["notepad.exe", str(log)], creationflags=CREATE_FLAGS)
            elif path == "/api/quit":
                if self.studio.setup and self.studio.setup.get("state") == "running":
                    raise ValueError("Die Einrichtung läuft. Warte bitte, bis sie fertig ist.")
                job = self.studio.runner.snapshot()
                if job and job["state"] in ("running", "queued", "cancelling"):
                    raise ValueError("Brich zuerst die laufende Erstellung ab.")
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                return self.respond({"error": "Nicht gefunden."}, 404)
            return self.respond({"ok": True})
        except (ValueError, TypeError, KeyError, TimeoutError) as exc:
            return self.respond({"error": str(exc)}, 400)
        except Exception:
            import traceback
            (self.studio.data / "frontend-fehler.log").write_text(traceback.format_exc(), encoding="utf-8")
            return self.respond({"error": "Die Anfrage konnte nicht verarbeitet werden. Versuche es erneut."}, 500)

    def import_clip(self):
        # Stream the body to disk; large videos never occupy a single RAM buffer.
        target = None
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1024**3:
                return self.respond({'error': 'Ein importierter Clip darf höchstens 1 GB groß sein.'}, 413)
            identifier = secrets.token_hex(16)
            target = self.studio.data / 'clips' / (identifier + '.mp4')
            self.connection.settimeout(60)
            with target.open('wb') as stream:
                left = length
                while left:
                    block = self.rfile.read(min(left, 256 * 1024))
                    if not block:
                        raise ValueError('Der Upload wurde unterbrochen.')
                    stream.write(block)
                    left -= len(block)
            result = self.studio.library.register_clip(identifier, unquote(self.headers.get('X-Clip-Name', 'Importierter Clip')))
            return self.respond(result, 201)
        except (ValueError, TimeoutError, OSError, subprocess.SubprocessError) as exc:
            if target:
                target.unlink(missing_ok=True)
            return self.respond({'error': str(exc)}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "VideoStudioEinfach")
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--port", type=int, default=7880)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--apply-update", type=Path)
    parser.add_argument("--skip-update-once", action="store_true")
    parser.add_argument("--update-token", default="")
    parser.add_argument('--check-engine-start', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--check-settings', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.check_engine_start:
        from engine import check_engine_start
        config_path = args.data / 'config.json'
        config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
        engine = (args.engine or Path(config.get('engine', args.data / 'engine'))).resolve()
        result = check_engine_start(engine, args.check_engine_start.resolve(), args.check_settings)
        raise SystemExit(0 if result['ok'] else 1)
    if args.check_settings:
        parser.error('--check-settings benötigt --check-engine-start.')
    if args.apply_update:
        from updater import apply_plan
        apply_plan(args.apply_update)
        return
    args.data.mkdir(parents=True, exist_ok=True)
    lock_file = args.data / "application.lock"
    with lock_file.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                address_file = args.data / "adresse.json"
                if address_file.exists() and not args.no_browser:
                    address = json.loads(address_file.read_text())["url"]
                    if re.fullmatch(r"http://127\.0\.0\.1:\d+/", address):
                        webbrowser.open(address)
                return
        studio = Studio(args.data, args.engine)
        studio.update_token = args.update_token
        ports = [args.port] * 40 if args.update_token else range(args.port, args.port + 20)
        for port in ports:
            try:
                server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
                break
            except OSError:
                if args.update_token:
                    time.sleep(0.25)
                continue
        else:
            raise RuntimeError("Kein freier lokaler Anschluss gefunden.")
        server.daemon_threads = True
        server.studio = studio
        studio.server = server
        url = f"http://127.0.0.1:{server.server_port}/"
        atomic_json(studio.data / "adresse.json", {"url": url})
        if args.update_token:
            if not re.fullmatch(r"[0-9a-f]{24}", args.update_token):
                raise ValueError("Ungültige Neustartprüfung.")
            atomic_json(studio.data / "updates" / f"health-{args.update_token}.json", {"version": VERSION, "token": args.update_token, "port":server.server_port})
        if not args.no_browser:
            webbrowser.open(url)
        try:
            studio.updater.start(skip_initial=args.skip_update_once)
            server.serve_forever(poll_interval=0.3)
        finally:
            studio.updater.shutdown.set()
            server.server_close()


if __name__ == "__main__":
    main()
