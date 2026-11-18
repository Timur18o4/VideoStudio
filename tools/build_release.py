"""Build reviewable local artifacts. Never pushes, publishes, or creates releases."""
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from version import VERSION
WORK = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "build"
OUT = ROOT / "dist"
WORK.mkdir(parents=True, exist_ok=True)
OUT.mkdir(exist_ok=True)


def run(arguments):
    subprocess.run([str(x) for x in arguments], check=True, cwd=ROOT)


def bundle(name, script, additions):
    arguments = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--name", name,
                 "--distpath", OUT, "--workpath", WORK / name, "--specpath", WORK,
                 "--icon", WORK / "studio.ico"]
    for source, destination in additions:
        arguments += ["--add-data", f"{source};{destination}"]
    run(arguments + [ROOT / script])


from PIL import Image, ImageDraw
image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((5, 5, 250, 250), radius=58, fill="#211a2d")
draw.line([(94, 64), (188, 128), (94, 192), (94, 64)], fill="#bca6f7", width=12, joint="curve")
image.save(WORK / "studio.ico", sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])

licenses = ROOT / "licenses"
for package, target in [("pillow", "Pillow"), ("pyinstaller", "PyInstaller"), ("cryptography", "Cryptography"), ("cffi", "CFFI"), ("pycparser", "pycparser")]:
    package_files = importlib.metadata.files(package)
    for entry in package_files:
        if ".dist-info" in str(entry) and any(word in str(entry).lower() for word in ("license", "copying", "notice")):
            source = Path(entry.locate())
            if source.is_file():
                destination = licenses / target / Path(*Path(str(entry)).parts[1:])
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.exists():
    shutil.copyfile(python_license, licenses / "Python-LICENSE.txt")
bundle("VideoStudio", "app.py", [(ROOT / "web", "web"), (ROOT / "models.lock.json", "."), (ROOT / "requirements-engine.lock", "."), (ROOT / "update-trust.json", ".")])
payload = WORK / "payload.zip"
with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.write(OUT / "VideoStudio.exe", "VideoStudio.exe")
    for name in ("README.md", "LICENSE.md", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md"):
        archive.write(ROOT / name, name)
    for file in licenses.rglob("*"):
        if file.is_file():
            archive.write(file, str(file.relative_to(ROOT)))
update_zip = OUT / f"VideoStudio-Update-{VERSION}.zip"
shutil.copyfile(payload, update_zip)
bundle(f"VideoStudio-Setup-{VERSION}", "installer.py", [(payload, ".")])
source_zip = OUT / f"VideoStudio-{VERSION}-Quellcode.zip"
with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as archive:
    for name in ("app.py", "engine.py", "setup_engine.py", "installer.py", "updater.py", "version.py", "update-trust.json", "README.md", "LICENSE.md", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "requirements-engine.lock", "requirements-frontend.txt", "requirements-build.txt", "models.lock.json", ".gitignore", ".gitattributes"):
        archive.write(ROOT / name, "VideoStudio/" + name)
    for folder in ("web", "tests", "tools", "licenses", ".github"):
        for file in (ROOT / folder).rglob("*"):
            if file.is_file() and "__pycache__" not in file.parts:
                archive.write(file, "VideoStudio/" + file.relative_to(ROOT).as_posix())
checks = []
for file in (OUT / "VideoStudio.exe", OUT / f"VideoStudio-Setup-{VERSION}.exe", source_zip, update_zip):
    with file.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    checks.append(f"{checksum}  {file.name}")
    print(file.name, file.stat().st_size)
(OUT / "SHA256SUMS.txt").write_text("\n".join(checks) + "\n", encoding="utf-8")
