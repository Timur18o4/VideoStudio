import base64
import hashlib
import json
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import Studio
from engine import atomic_json
from updater import REPOSITORY, Updater, apply_package, canonical, verify_manifest, verify_package, version_key


def payload(package,version='0.2.1-preview'):
    return {'schema':1,'repository':REPOSITORY,'version':version,'min_version':'0.2.0-preview',
            'package':{'name':f'VideoStudio-Update-{version}.zip','url':f'https://github.com/{REPOSITORY}/releases/download/v{version}/VideoStudio-Update-{version}.zip','size':package.stat().st_size,'sha256':hashlib.sha256(package.read_bytes()).hexdigest()}}


class Trust(unittest.TestCase):
    def test_signature_and_download_origin_are_required(self):
        key=Ed25519PrivateKey.generate()
        public=base64.b64encode(key.public_key().public_bytes_raw()).decode()
        with tempfile.TemporaryDirectory() as directory:
            package=Path(directory)/'update.zip';package.write_bytes(b'example')
            value=payload(package)
            def envelope():
                return {'payload':value,'signature':base64.b64encode(key.sign(canonical(value))).decode()}
            signed=envelope()
            self.assertEqual(verify_manifest(signed,public)['version'],'0.2.1-preview')
            signed['payload']['package']['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'Signatur'):
                verify_manifest(signed,public)
            value['package']['url']='https://attacker.example/update.zip'
            with self.assertRaisesRegex(ValueError,'Downloadadresse'):
                verify_manifest(envelope(),public)

    def test_version_order_including_preview_and_stable(self):
        self.assertLess(version_key('0.2.0-preview'),version_key('0.2.0'))
        self.assertLess(version_key('0.2.0'),version_key('0.2.1-preview'))
        for value in ('latest','0.2','../2.0.0',None):
            with self.assertRaises(ValueError): version_key(value)

    def test_packages_cannot_change_user_data_or_escape_program_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            package=Path(directory)/'update.zip'
            for name in ('../escape.exe','config.json','jobs/video.mp4','C:/VideoStudio.exe','licenses/../../config.json'):
                with zipfile.ZipFile(package,'w') as archive:
                    archive.writestr('VideoStudio.exe',b'MZnew')
                    archive.writestr(name,b'bad')
                with self.assertRaises(ValueError): verify_package(package,payload(package))

    def test_corrupted_and_duplicate_packages_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            package=Path(directory)/'update.zip'
            with zipfile.ZipFile(package,'w') as archive: archive.writestr('VideoStudio.exe',b'MZnew')
            value=payload(package)
            package.write_bytes(package.read_bytes()+b'corrupt')
            with self.assertRaises(ValueError):verify_package(package,value)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',UserWarning)
                with zipfile.ZipFile(package,'w') as archive:
                    archive.writestr('VideoStudio.exe',b'MZnew')
                    archive.writestr('VideoStudio.exe',b'MZother')
            with self.assertRaises(ValueError):verify_package(package,payload(package))


class Installation(unittest.TestCase):
    def test_successful_update_preserves_user_files_and_keeps_previous_program(self):
        self.exercise(True)

    def test_failed_start_restores_previous_program_and_blocks_failed_version(self):
        self.exercise(False)

    def exercise(self,success):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'program';data=root/'data';target.mkdir();(data/'updates').mkdir(parents=True)
            old=target/'VideoStudio.exe';old.write_bytes(b'MZold')
            (data/'config.json').write_text('private-config')
            (data/'model.bin').write_bytes(b'private-model')
            atomic_json(target/'installation.json',{'app':'VideoStudioEinfach','files':['VideoStudio.exe']})
            package=root/'update.zip'
            with zipfile.ZipFile(package,'w') as archive:
                archive.writestr('VideoStudio.exe',b'MZnew');archive.writestr('CHANGELOG.md','New')
            launch=Mock(return_value=Mock())
            with patch('updater.stop_process') as stop:
                result=apply_package(package,payload(package),target,data,7880,launch=launch,healthy=lambda *_:success)
            self.assertEqual(result,success)
            self.assertEqual(old.read_bytes(),b'MZnew' if success else b'MZold')
            self.assertEqual((data/'config.json').read_text(),'private-config')
            self.assertEqual((data/'model.bin').read_bytes(),b'private-model')
            self.assertEqual((target/'.update-backup-0.2.1-preview/VideoStudio.exe').read_bytes(),b'MZold')
            status=json.loads((data/'updates/status.json').read_text())
            self.assertEqual(status['state'],'installed' if success else 'rolled_back')
            self.assertEqual(launch.call_count,1 if success else 2)
            if not success:
                self.assertEqual(status['failed_version'],'0.2.1-preview');stop.assert_called_once()
                self.assertFalse((target/'CHANGELOG.md').exists())

    def test_running_video_or_setup_defers_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            studio=Studio(Path(directory));manager=Updater(studio,enabled=True)
            manager.prepared=({}, {}, Path(directory)/'update.zip')
            studio.runner.busy=True
            with patch('updater.subprocess.Popen') as launch:
                self.assertFalse(manager.install_when_idle());launch.assert_not_called()
            studio.runner.busy=False;studio.setup={'state':'running'}
            with patch('updater.subprocess.Popen') as launch:
                self.assertFalse(manager.install_when_idle());launch.assert_not_called()
            self.assertFalse(studio.updating)

    def test_offline_check_does_not_block_local_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            studio=Studio(Path(directory));manager=Updater(studio,enabled=True)
            with patch('updater.fetch_json',side_effect=OSError('offline')):manager.check()
            self.assertEqual(manager.state['state'],'unavailable')
            self.assertFalse(studio.updating);self.assertFalse(manager.checking)


if __name__=='__main__':unittest.main()
