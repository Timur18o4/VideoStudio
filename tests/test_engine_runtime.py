"""Regression for a packaged 3.12 frontend launching a separate Python engine."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import engine_command, engine_environment, popen_engine


class EngineRuntime(unittest.TestCase):
    def test_environment_removes_bundle_paths_but_keeps_external_programs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / '_MEI123'
            external = root / 'ffmpeg'
            similar = root / '_MEI123-other'
            original = {'PATH': os.pathsep.join(map(str, [bundle, bundle/'PIL', external, similar])),
                        'PYTHONHOME': 'wrong-python', 'PYTHONPATH': 'wrong-modules', '_PYI_APPLICATION_HOME_DIR': str(bundle),
                        '_MEIPASS2': str(bundle), 'LD_LIBRARY_PATH': str(bundle), 'LD_LIBRARY_PATH_ORIG': 'system-libraries'}
            result = engine_environment(original, bundle)
            self.assertEqual(result['PATH'], os.pathsep.join(map(str, [external, similar])))
            self.assertEqual(result['LD_LIBRARY_PATH'], 'system-libraries')
            self.assertEqual(result['HF_HUB_OFFLINE'], '1')
            for key in ('PYTHONHOME', 'PYTHONPATH', '_PYI_APPLICATION_HOME_DIR', '_MEIPASS2'):
                self.assertNotIn(key, result)
                self.assertIn(key, original)

    def test_worker_cannot_import_an_incompatible_module_beside_the_bundled_script(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, engine = root/'_MEI123', root/'engine'
            bundle.mkdir(); engine.mkdir()
            shutil.copyfile(Path(__file__).resolve().parents[1]/'preview_worker.py', bundle/'preview_worker.py')
            # This would shadow the engine's standard library without Python -I.
            (bundle/'unicodedata.py').write_text("raise RuntimeError('incompatible bundled Python module')\n", encoding='utf-8')
            (engine/'wgp.py').write_text(
                "import sys,json,unicodedata,ssl,sqlite3,ctypes\n"
                "assert '--dry-run' in sys.argv\n"
                "print(json.dumps({'module':unicodedata.__file__,'isolated':sys.flags.isolated,'encoding':sys.stdout.encoding,'text':'ä €'},ensure_ascii=False))\n", encoding='utf-8')
            with patch.object(sys, '_MEIPASS', str(bundle), create=True), patch('engine.engine_python', return_value=Path(sys.executable)):
                command = engine_command(engine, root/'preview.jpg', ['--dry-run'])
                process = popen_engine(command, engine)
                output = process.communicate(timeout=20)[0].decode('utf-8')
            self.assertEqual(process.returncode, 0, output)
            result = json.loads(output.splitlines()[-1])
            self.assertNotIn(str(bundle), result['module'])
            self.assertEqual(result['isolated'], 1)
            self.assertEqual(result['encoding'], 'utf-8')
            self.assertEqual(result['text'], 'ä €')

    @unittest.skipUnless(os.name == 'nt', 'Windows DLL search path')
    def test_dll_search_directory_is_restored_when_launch_fails(self):
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.SetDllDirectoryW.argtypes = (ctypes.c_wchar_p,)
        kernel.GetDllDirectoryW.argtypes = (ctypes.c_uint32, ctypes.c_wchar_p)
        def current():
            value = ctypes.create_unicode_buffer(32768)
            kernel.GetDllDirectoryW(len(value), value)
            return value.value or None
        original = current()
        with tempfile.TemporaryDirectory() as directory:
            try:
                kernel.SetDllDirectoryW(directory)
                with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', directory, create=True):
                    with self.assertRaises(FileNotFoundError):
                        popen_engine([str(Path(directory)/'missing-python.exe')], Path(directory))
                self.assertEqual(current(), directory)
            finally:
                kernel.SetDllDirectoryW(original)


if __name__ == '__main__':
    unittest.main()
