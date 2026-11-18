import base64
import hashlib
import io
import json
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Handler, Studio, normalize_image
from engine import Runner, atomic_json, build_settings
from setup_engine import download, extract_zip, hardware_check
from PIL import Image


def picture(width=512, height=896):
    output = io.BytesIO()
    image = Image.new("RGB", (width, height), "#788597")
    exif = Image.Exif()
    exif[0x010E] = "Private metadata must not be exported"
    image.save(output, "JPEG", exif=exif)
    return base64.b64encode(output.getvalue()).decode("ascii")


class Images(unittest.TestCase):
    def test_invalid_and_too_small_images_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "image.jpg"
            for raw in ("garbage", base64.b64encode(b"not an image").decode(), picture(50, 60)):
                with self.assertRaises(ValueError):
                    normalize_image(raw, target)

    def test_uploaded_images_are_resized_and_private_metadata_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "image.jpg"
            normalize_image(picture(3000, 4000), target)
            with Image.open(target) as image:
                self.assertEqual(image.size, (1536, 2048))
                self.assertFalse(image.getexif())

    def test_second_image_is_end_frame_and_speech_is_included(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f"image-{i}.jpg" for i in range(2)]
            for path in paths:
                normalize_image(picture(), path)
            settings = build_settings("Sie winkt.", "Hallo Welt.", "Meeresrauschen", paths, 8, 123)
            self.assertEqual(settings["image_prompt_type"], "SE")
            self.assertEqual(settings["image_end"], str(paths[1].resolve()))
            self.assertEqual(settings["video_length"], 193)
            self.assertEqual(settings["resolution"], "512x896")
            self.assertEqual(settings["audio_prompt_type"], "")
            self.assertIn('"Hallo Welt."', settings["prompt"])


class HTTP(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data = Path(self.temporary.name)
        self.studio = Studio(self.data)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.studio = self.studio
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join()
        self.temporary.cleanup()

    def request(self, path, body=None, headers=None):
        return urllib.request.urlopen(urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                headers={"Content-Type":"application/json", **(headers or {})}), timeout=5)

    def test_page_uses_only_local_assets_and_exposes_no_user_paths(self):
        with self.request("/") as result:
            text = result.read().decode()
            self.assertNotIn("https://", text)
            self.assertNotIn(str(self.data), text)
            self.assertIn("default-src 'self'", result.headers["Content-Security-Policy"])

    def test_mutating_requests_require_token_and_matching_origin(self):
        for headers in ({}, {"X-Studio-Token":self.studio.token,"Origin":"https://attacker.example"}, {"X-Studio-Token":self.studio.token,"Host":"attacker.example"}):
            with self.assertRaises(urllib.error.HTTPError) as exc:
                self.request("/api/generate", {}, headers)
            self.assertEqual(exc.exception.code, 403)

    def test_session_and_validation(self):
        with self.request("/api/session") as result:
            self.assertEqual(json.load(result)["token"], self.studio.token)
        with self.assertRaises(urllib.error.HTTPError) as exc:
            self.request("/api/generate", {"scene":"","images":[]}, {"X-Studio-Token":self.studio.token})
        self.assertEqual(exc.exception.code, 400)
        self.assertFalse(list((self.data / "jobs").iterdir()))

    def test_media_range_and_download_headers(self):
        folder = self.data / "jobs/20261117-123456-1234abcd"
        folder.mkdir()
        (folder / "video.mp4").write_bytes(b"0123456789")
        with self.request("/media/20261117-123456-1234abcd/video.mp4?download=1", headers={"Range":"bytes=2-5"}) as result:
            self.assertEqual(result.status, 206)
            self.assertEqual(result.read(), b"2345")
            self.assertEqual(result.headers["Content-Range"], "bytes 2-5/10")
            self.assertIn("attachment", result.headers["Content-Disposition"])
        with self.assertRaises(urllib.error.HTTPError) as exc:
            self.request("/media/20261117-123456-1234abcd/video.mp4", headers={"Range":"bytes=20-30"})
        self.assertEqual(exc.exception.code, 416)

    def test_file_traversal_and_arbitrary_file_reads_are_blocked(self):
        for path in ("/media/../../config.json", "/config.json", "/%2e%2e/app.py", "/media/20261117-123456-1234abcd/diagnose.log"):
            with self.assertRaises(urllib.error.HTTPError) as exc:
                self.request(path)
            self.assertEqual(exc.exception.code, 404)


class Recovery(unittest.TestCase):
    def test_interrupted_jobs_are_recovered_without_restarting_them(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            job = data / "jobs/20261117-123456-1234abcd"
            job.mkdir(parents=True)
            atomic_json(job / "status.json", {"id":job.name,"state":"running","message":"old"})
            runner = Runner(data / "engine", data, {"models":[]})
            self.assertEqual(runner.snapshot()["state"], "interrupted")
            self.assertIsNone(runner.proc)
            self.assertEqual(json.loads((job / "status.json").read_text(encoding="utf-8"))["state"], "interrupted")

    def test_zip_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "source.zip"
            with zipfile.ZipFile(archive,"w") as source:
                source.writestr("../escape.txt", "bad")
            with self.assertRaises(ValueError):
                extract_zip(archive, Path(directory) / "engine")
            self.assertFalse((Path(directory) / "escape.txt").exists())

    def test_download_resumes_and_checks_complete_hash(self):
        payload = b"A local model fixture\x00" * 100
        offsets = []
        class Source(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def do_GET(self):
                value=self.headers.get("Range")
                if value:
                    start,end=value.removeprefix("bytes=").split("-")
                    start,end=int(start),int(end) if end else len(payload)-1
                    offsets.append(start)
                    self.send_response(206)
                    self.send_header("Content-Range",f"bytes {start}-{end}/{len(payload)}")
                    body=payload[start:end+1]
                else:
                    self.send_response(200); body=payload
                self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(("127.0.0.1",0),Source)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            with tempfile.TemporaryDirectory() as directory, patch("setup_engine.BLOCK",128), patch("setup_engine.STREAM_THRESHOLD",64):
                dest=Path(directory)/"model.bin"
                dest.with_name("model.bin.download").write_bytes(payload[:256])
                item={"url":f"http://127.0.0.1:{server.server_port}/model","size":len(payload),"sha256":hashlib.sha256(payload).hexdigest()}
                download(item,dest,lambda *_:None)
                self.assertEqual(dest.read_bytes(),payload)
                self.assertIn(256,offsets)
                dest.write_bytes(b"x"*len(payload))
                download(item,dest,lambda *_:None)
                self.assertEqual(dest.read_bytes(),payload)
                self.assertEqual(len(list(Path(directory).glob("*.beschaedigt-*"))),1)
        finally:
            server.shutdown();server.server_close();worker.join()

    def test_archive_download_recovers_when_server_ignores_range(self):
        payload=b"source archive"*1000
        class Source(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def do_GET(self):
                self.send_response(200);self.send_header("Content-Length",str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(("127.0.0.1",0),Source)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                dest=Path(directory)/"archive.zip"
                dest.with_name("archive.zip.download").write_bytes(payload[:256])
                item={"url":f"http://127.0.0.1:{server.server_port}/archive","size":len(payload),"sha256":hashlib.sha256(payload).hexdigest()}
                download(item,dest,lambda *_:None)
                self.assertEqual(dest.read_bytes(),payload)
        finally:
            server.shutdown();server.server_close();worker.join()


if __name__ == "__main__":
    unittest.main()
