"""Test a real frozen 3.12 EXE against a 3.11 engine; no AI model or video render."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError('Run this test with the separate Python 3.11 interpreter.')
    work = args.work.resolve()
    engine = work/'engine'
    engine.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, '-m', 'venv', str(engine/'.venv')], check=True)
    child = engine/'.venv'/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    subprocess.run([str(child), '-m', 'pip', 'install', 'Pillow==11.3.0', 'tqdm==4.70.1'], check=True)
    # A startup-only stand-in prevents this regression test ever rendering media.
    (engine/'wgp.py').write_text(
        "import sys,json,unicodedata,ssl,sqlite3,ctypes,tqdm\n"
        "assert '--dry-run' in sys.argv, 'Generation is forbidden in this test'\n"
        "print('DRY-RUN startup succeeded')\n", encoding='utf-8')
    settings = work/'settings.json'
    settings.write_text('{}', encoding='utf-8')
    report = work/'startup.json'
    command = [str(args.app.resolve()), '--engine', str(engine), '--check-engine-start', str(report), '--check-settings', str(settings)]
    subprocess.run(command, check=True, timeout=120)
    result = json.loads(report.read_text(encoding='utf-8'))
    assert result['ok'] and result['frozen'] and result['dry_run'], result
    assert result['frontend_python'].startswith('3.12.'), result
    assert result['engine']['python'].startswith('3.11.'), result
    for name, path in result['engine']['modules'].items():
        assert '_MEI' not in path, (name, path)
    print('Frozen Python 3.12 frontend -> isolated Python 3.11 engine: OK (no video generated)')


if __name__ == '__main__':
    main()
