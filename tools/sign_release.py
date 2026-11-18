"""Maintainer-only release signing. Private key stays encrypted outside the checkout."""
import argparse
import base64
import ctypes
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from updater import REPOSITORY, canonical
from version import VERSION
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def dpapi(data, decrypt=False):
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    dll = ctypes.WinDLL("crypt32", use_last_error=True)
    function = dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel = ctypes.WinDLL("kernel32")
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


def load_key(initialize=False):
    if os.name != "nt":
        raise RuntimeError("Der Herausgeberschlüssel wird auf Windows mit DPAPI geschützt.")
    path = Path(os.environ.get("VIDEO_STUDIO_SIGNING_KEY", Path(os.environ["LOCALAPPDATA"]) / "VideoStudioRelease/signing-key.dpapi"))
    if not path.exists():
        if not initialize:
            raise RuntimeError("Der lokale Herausgeberschlüssel fehlt.")
        key = Ed25519PrivateKey.generate()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(dpapi(key.private_bytes_raw()))
    else:
        key = Ed25519PrivateKey.from_private_bytes(dpapi(path.read_bytes(), decrypt=True))
    public = base64.b64encode(key.public_key().public_bytes_raw()).decode("ascii")
    trust_file = ROOT / "update-trust.json"
    if trust_file.exists():
        if json.loads(trust_file.read_text(encoding="utf-8"))["public_key"] != public:
            raise RuntimeError("Der Schlüssel passt nicht zum veröffentlichten Prüfschlüssel.")
    elif initialize:
        trust_file.write_text(json.dumps({"algorithm":"Ed25519", "key_id":"videostudio-2026-01", "public_key":public}, indent=2) + "\n", encoding="utf-8")
    else:
        raise RuntimeError("Der öffentliche Prüfschlüssel fehlt.")
    return key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init-key", action="store_true")
    args = parser.parse_args()
    key = load_key(args.init_key)
    if args.init_key:
        print("Herausgeberschlüssel lokal geschützt; öffentlicher Prüfschlüssel vorbereitet.")
        return
    package = ROOT / "dist" / f"VideoStudio-Update-{VERSION}.zip"
    payload = {"schema":1, "repository":REPOSITORY, "version":VERSION, "min_version":"0.2.0-preview",
               "package":{"name":package.name, "size":package.stat().st_size,
                          "url":f"https://github.com/{REPOSITORY}/releases/download/v{VERSION}/{package.name}",
                          "sha256":hashlib.sha256(package.read_bytes()).hexdigest()}}
    envelope = {"payload":payload, "signature":base64.b64encode(key.sign(canonical(payload))).decode("ascii")}
    manifest = package.parent / "update.json"
    manifest.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sums = package.parent / "SHA256SUMS.txt"
    lines = [line for line in sums.read_text(encoding="utf-8").splitlines() if not line.endswith("  update.json")]
    lines.append(hashlib.sha256(manifest.read_bytes()).hexdigest() + "  update.json")
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Update-Manifest mit Ed25519 signiert.")


if __name__ == "__main__":
    main()
