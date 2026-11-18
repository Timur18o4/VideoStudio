"""Per-user Windows installer. User media and the model cache survive uninstall."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import tempfile
import time
import zipfile
from pathlib import Path
from version import VERSION

APP_ID = "VideoStudioEinfach"
APP_NAME = "Video Studio"
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home()))
TARGET = LOCAL / "Programs" / APP_ID
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def shortcuts(target, remove=False):
    import ctypes
    buffer = ctypes.create_unicode_buffer(32768)
    # Known-folder API respects relocated and OneDrive desktops.
    ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer)
    desktop = Path(buffer.value)
    menu = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs"
    paths = [menu / "Video Studio.lnk", desktop / "Video Studio.lnk"]
    if remove:
        for path in paths:
            path.unlink(missing_ok=True)
        return
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Paths travel as JSON data, never as interpolated shell source.
        script = "$p = Get-Content -LiteralPath $env:VIDEO_STUDIO_SHORTCUT -Raw | ConvertFrom-Json; $s = (New-Object -ComObject WScript.Shell).CreateShortcut($p.link); $s.TargetPath=$p.target; $s.WorkingDirectory=$p.directory; $s.IconLocation=$p.target; $s.Description='Lokale KI-Videos aus Bildern und Text erstellen'; $s.Save()"
        info = target / "shortcut-data.json"
        info.write_text(json.dumps({"link": str(path), "target": str(target / "VideoStudio.exe"), "directory": str(target)}), encoding="utf-8")
        env = os.environ.copy()
        env["VIDEO_STUDIO_SHORTCUT"] = str(info)
        try:
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], env=env, check=True, capture_output=True, creationflags=FLAGS)
        finally:
            info.unlink(missing_ok=True)


def register(target):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}") as key:
        values = {"DisplayName": APP_NAME, "DisplayVersion": VERSION, "InstallLocation": str(target),
                  "DisplayIcon": str(target / "VideoStudio.exe"), "UninstallString": f'"{target / "Deinstallieren.exe"}" --uninstall',
                  "Publisher": "Video Studio · unabhängiges Frontend"}
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def install_to(target=TARGET, integrations=True):
    target = target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    names = []
    with zipfile.ZipFile(ROOT / "payload.zip") as payload:
        for item in payload.infolist():
            destination = (target / item.filename).resolve()
            if not destination.is_relative_to(target) or item.is_dir():
                raise ValueError("Ungültige Installationsdatei.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with payload.open(item) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
            names.append(item.filename)
    if getattr(sys, "frozen", False):
        uninstaller = target / "Deinstallieren.exe"
        if Path(sys.executable).resolve() != uninstaller:
            shutil.copyfile(sys.executable, uninstaller)
        names.append("Deinstallieren.exe")
    (target / "installation.json").write_text(json.dumps({"app": APP_ID, "files": names}), encoding="utf-8")
    if integrations:
        shortcuts(target)
        register(target)


def uninstall():
    import tkinter as tk
    from tkinter import messagebox
    import winreg
    window = tk.Tk()
    window.withdraw()
    target = Path(sys.executable).resolve().parent
    if target != TARGET.resolve():
        messagebox.showerror(APP_NAME, "Der Installationsordner konnte nicht eindeutig geprüft werden.")
        return
    marker = target / "installation.json"
    info = json.loads(marker.read_text(encoding="utf-8"))
    if info.get("app") != APP_ID:
        raise ValueError("Ungültiger Installationsordner.")
    if not messagebox.askyesno(APP_NAME, "Video Studio deinstallieren?\n\nDeine Bilder, Videos und heruntergeladenen KI-Dateien bleiben erhalten."):
        return
    for name in info["files"]:
        path = (target / name).resolve()
        if not path.is_relative_to(target):
            raise ValueError("Ungültiger Dateipfad.")
        if path.name != "Deinstallieren.exe":
            path.unlink(missing_ok=True)
    shortcuts(target, remove=True)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}")
    except FileNotFoundError:
        pass
    marker.unlink(missing_ok=True)
    # A temporary copy removes the original after this process has closed.
    helper = Path(tempfile.gettempdir()) / f"VideoStudio-Deinstallation-{os.getpid()}.exe"
    shutil.copyfile(sys.executable, helper)
    subprocess.Popen([str(helper), "--finish-uninstall"], creationflags=FLAGS)
    messagebox.showinfo(APP_NAME, "Video Studio wurde deinstalliert. Deine Inhalte bleiben erhalten.")


def finish_uninstall():
    marker = TARGET / "installation.json"
    if marker.exists():
        return
    for _ in range(60):
        try:
            (TARGET / "Deinstallieren.exe").unlink(missing_ok=True)
            for directory in sorted(TARGET.rglob("*"), key=lambda p:len(p.parts), reverse=True):
                if directory.is_dir():
                    try:
                        directory.rmdir()
                    except OSError:
                        pass
            try:
                TARGET.rmdir()
            except OSError:
                pass
            return
        except PermissionError:
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--finish-uninstall", action="store_true")
    args = parser.parse_args()
    if args.finish_uninstall:
        return finish_uninstall()
    if args.uninstall:
        return uninstall()
    if args.quiet:
        return install_to()
    import tkinter as tk
    from tkinter import ttk, messagebox
    window = tk.Tk()
    window.title("Video Studio installieren")
    window.geometry("520x470")
    window.resizable(False, False)
    window.configure(bg="#19191e")
    container = tk.Frame(window, bg="#19191e", padx=30, pady=26)
    container.pack(fill="both", expand=True)
    def label(text, size=10, color="#b9b5c4", **kw):
        tk.Label(container, text=text, bg="#19191e", fg=color, font=("Segoe UI", size), justify="left", anchor="w", wraplength=455).pack(fill="x", **kw)
    label("Video Studio", 24, "#e6dbff", pady=(0, 10))
    label("Bilder rein. Szene beschreiben. Video erstellen.", 11, "#efedf4", pady=(0, 17))
    label("Diese Vorschau installiert die einfache Oberfläche. Die KI-Dateien werden beim ersten Start automatisch eingerichtet (ca. 36 GB plus Programmbestandteile).", pady=(0, 12))
    label("Für Windows 10/11, NVIDIA ab 8 GB Grafikspeicher und mindestens 32 GB Arbeitsspeicher. Für eine neue Einrichtung etwa 65 GB freien Speicher vorsehen.", pady=(0, 12))
    label("Deine Bilder und Videos werden lokal verarbeitet.", color="#cbb7ed", pady=(0, 20))
    progress = ttk.Progressbar(container, mode="indeterminate")
    status = tk.StringVar(value="")
    tk.Label(container, textvariable=status, bg="#19191e", fg="#d0c5de", font=("Segoe UI", 9), wraplength=450).pack(fill="x", pady=(0, 5))
    done = False
    def launch():
        if done:
            subprocess.Popen([str(TARGET / "VideoStudio.exe")], cwd=TARGET, creationflags=FLAGS)
            window.destroy()
            return
        button.config(state="disabled")
        progress.pack(fill="x", pady=(0, 10))
        progress.start()
        status.set("Die Oberfläche wird installiert …")
        def work():
            try:
                install_to()
                window.after(0, finish)
            except Exception as exc:
                message = str(exc)
                window.after(0, lambda: fail(message))
        threading.Thread(target=work, daemon=True).start()
    def finish():
        nonlocal done
        done = True
        progress.stop()
        progress.pack_forget()
        status.set("Installiert. Du findest Video Studio auch auf deinem Desktop.")
        button.config(text="Video Studio öffnen", state="normal")
    def fail(message):
        progress.stop()
        progress.pack_forget()
        button.config(state="normal")
        messagebox.showerror(APP_NAME, "Die Installation ist fehlgeschlagen. Schließe ein eventuell geöffnetes Video Studio und versuche es erneut.\n\n" + message)
    button = tk.Button(container, text="Installieren", command=launch, bg="#bca6f7", fg="#20162e", activebackground="#cdb9ff", font=("Segoe UI Semibold", 11), relief="flat", padx=22, pady=8, cursor="hand2")
    button.pack(anchor="e")
    window.mainloop()


if __name__ == "__main__":
    main()
