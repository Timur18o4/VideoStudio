"""Episode integration uses synthetic FFmpeg clips, never neural generation."""
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Studio, Handler
from engine import Runner, atomic_json, build_settings
from media import binary, duration_frames, export_options, resolve_profile, FLAGS
from preview_worker import instrument
from test_studio import picture


def wait_for(condition, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(.05)
    raise AssertionError('Test-Zeitlimit überschritten')


class Episodes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.studio = Studio(self.data)
        self.library = self.studio.library

    def tearDown(self):
        self.studio.runner.cancel()
        wait_for(lambda: not self.studio.runner.busy)
        self.tmp.cleanup()

    def make_recipe(self):
        image = self.library.image(picture())['id']
        character = self.library.character({'name': 'Mara', 'description': 'Rote Jacke', 'image': image})
        return {'title': 'Episode 1', 'output': {'fps': 25, 'aspect': '16:9'},
                'shots': [{'scene': 'Sie öffnet die Tür.', 'seconds': 6, 'character': character['id']},
                          {'scene': 'Nahaufnahme des Gesichts.', 'seconds': 6, 'images': [image]}]}

    def test_character_recipe_and_plan_roundtrip_without_model_generation(self):
        recipe = self.library.save(self.make_recipe())
        self.assertEqual(recipe, self.library.records('episodes')[0])
        fresh = Studio(self.data)
        self.assertEqual(fresh.library.records('characters')[0]['name'], 'Mara')
        directory = self.data / 'jobs' / '20261118-120000-abcd1234'
        directory.mkdir()
        profile, plan = self.library.plan(recipe, directory)
        self.assertEqual((profile['width'], profile['height']), (854, 480))
        self.assertEqual(plan[0]['settings']['force_fps'], '25')
        self.assertEqual(plan[0]['settings']['video_length'], 153)
        self.assertIn('Rote Jacke', plan[0]['settings']['prompt'])
        self.assertEqual(plan[1]['settings']['prompt'], 'Nahaufnahme des Gesichts.')
        self.assertTrue(Path(plan[0]['settings']['image_start']).is_file())

    def test_invalid_recipes_and_paths_are_rejected(self):
        valid = self.make_recipe()
        for change in ({'shots': []}, {'shots': [{'scene': 'Test', 'images': ['../../config']}]},
                       {'output': {'fps': True}}, {'output': {'aspect': '100:1'}},
                       {'shots': [{'scene': 'Test', 'seconds': float('nan')}]},
                       {'shots': [{'scene': 'Test', 'seconds': -1}]},
                       {'shots': [{'kind': 'clip', 'clip': '../../video.mp4'}]}):
            with self.assertRaises((ValueError, TypeError)):
                self.library.recipe({**valid, **change})
        self.assertFalse(list((self.data / 'jobs').iterdir()))

    def test_profile_and_frame_alignment(self):
        for fps in (16, 24, 25, 30, 48, 50, 60):
            frames = duration_frames(7, fps)
            self.assertEqual(frames, 7 * fps)
            profile = resolve_profile({'aspect': '9:16', 'resolution': 1080, 'fps': fps}, (512, 512))
            self.assertEqual((profile['width'], profile['height']), (1080, 1920))
            # Model gets enough frames on its 8n+1 grid, export trims the surplus.
            image = self.library.image(picture())['id']
            settings = build_settings('Test', '', '', [self.library.path('images', image, '.jpg')], 7, 1, True, profile)
            self.assertEqual((settings['video_length']-1)%8, 0)
            self.assertGreaterEqual(settings['video_length'], frames)
            self.assertLessEqual(settings['video_length'], frames+8)

    def technical_clip(self, path, color, audio=False, seconds=6):
        command = [binary(self.studio.engine, 'ffmpeg'), '-v', 'error', '-nostdin', '-y', '-f', 'lavfi',
                   '-i', f'color=c={color}:s=160x96:r=24:d={seconds}']
        if audio:
            command += ['-f', 'lavfi', '-i', f'sine=frequency=440:duration={seconds}', '-c:a', 'aac']
        subprocess.run(command + ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-t', str(seconds), str(path)],
                       check=True, capture_output=True, creationflags=FLAGS)

    def test_five_shots_merge_to_exact_30_seconds_at_25fps_with_mixed_audio(self):
        profile = resolve_profile({'fps': 25, 'aspect': '16:9'}, (160, 96))
        job = self.data / 'jobs' / '20261118-120000-abcd1234'
        job.mkdir()
        plan = []
        for index, color in enumerate(('red', 'green', 'blue', 'yellow', 'purple')):
            source = self.data / f'fixture-{index}.mp4'
            self.technical_clip(source, color, audio=index%2==0)
            plan.append({'kind': 'clip', 'source': str(source), 'seconds': 6, 'frames': 150,
                         'start': 0, 'audible': index%2==0})
        self.studio.runner.start_plan(job.name, profile, plan, 'Technischer Schnitt-Test')
        wait_for(lambda: not self.studio.runner.busy, 60)
        result = self.studio.runner.snapshot()
        self.assertEqual(result['state'], 'done', result)
        info = json.loads(subprocess.check_output([binary(self.studio.engine,'ffprobe'),'-v','error','-show_streams','-show_format','-of','json',str(job/'video.mp4')], creationflags=FLAGS))
        video = next(stream for stream in info['streams'] if stream['codec_type']=='video')
        self.assertEqual((video['width'],video['height'],video['r_frame_rate'],int(video['nb_frames'])),(854,480,'25/1',750))
        self.assertAlmostEqual(float(video['duration']),30,places=3)
        self.assertAlmostEqual(float(video['start_time']),0,places=3)
        self.assertAlmostEqual(float(info['format']['duration']),30,places=3)
        self.assertTrue(any(stream['codec_type']=='audio' for stream in info['streams']))
        self.assertTrue(all(shot['state']=='done' for shot in result['shots']))
        # Inspect center pixels after each cut: ordering survives normalization and concatenation.
        pixels=[]
        for second in (1,7,13,19,25):
            pixels.append(subprocess.check_output([binary(self.studio.engine,'ffmpeg'),'-v','error','-ss',str(second),'-i',str(job/'video.mp4'),'-frames:v','1','-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],creationflags=FLAGS))
        self.assertGreater(pixels[0][0], pixels[0][2]+100)
        self.assertGreater(pixels[2][2], pixels[2][0]+100)
        self.assertGreater(pixels[1][1], pixels[1][0]+60)

    def test_preview_hook_and_cancellation_stop_the_current_process_and_next_shots(self):
        # Fake engine only writes colored technical clips. It never loads an AI model.
        engine = self.data / 'engine'
        engine.mkdir()
        fixture = '''import argparse,json,subprocess,time,os
from pathlib import Path
from PIL import Image
def generate_preview(model,payload): return Image.new('RGB',(256,256),'#7864c4')
def process_tasks_cli(queue,state):
    params=queue
    cmd,data='preview',None
    if cmd == 'unused': pass
    elif cmd == 'status': pass
            elif cmd == "output":
                pass
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--process');parser.add_argument('--output-dir');args,_=parser.parse_known_args()
    settings=json.loads(Path(args.process).read_text());target=Path(args.output_dir);target.mkdir()
    (target/'started').write_text(str(os.getpid()))
    process_tasks_cli(settings,None)
    if settings.get('hold'): time.sleep(30)
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=blue:s=160x96:r=24:d=0.5','-c:v','libx264','-pix_fmt','yuv420p',str(target/'generated.mp4')],check=True)
if __name__=='__main__': main()
'''
        # Match the pinned CLI indentation, including the preview insertion anchor.
        fixture=fixture.replace("    cmd,data='preview',None\n    if cmd == 'unused': pass\n    elif cmd == 'status': pass", "    for cmd,data in [('preview',None)]:\n            if cmd == 'unused': pass\n            elif cmd == 'status': pass")
        (engine/'wgp.py').write_text(fixture,encoding='utf-8')
        changed, hooked=instrument(fixture)
        self.assertTrue(hooked);compile(changed,'fixture','exec')
        job=self.data/'jobs'/'20261118-120000-abcd1234';job.mkdir()
        profile=resolve_profile(None,(160,96))
        plan=[{'kind':'generate','settings':{'prompt':'Technischer Test','hold':index==1},'seconds':.5,'frames':12,'audible':False} for index in range(3)]
        with patch('engine.engine_python',return_value=Path(sys.executable)),patch('engine.check_engine',return_value=[]):
            self.studio.runner.start_plan(job.name,profile,plan,'Abbruchtest')
            wait_for(lambda: (job/'shots/002/render/started').exists())
            wait_for(lambda: bool(self.studio.runner.snapshot().get('live_preview')))
            self.assertTrue((job/'shots/002/live-preview.jpg').is_file())
            self.studio.runner.cancel()
            wait_for(lambda: not self.studio.runner.busy, 8)
        status=self.studio.runner.snapshot()
        self.assertEqual(status['state'],'cancelled')
        self.assertEqual(status['shots'][0]['state'],'done')
        self.assertTrue((job/'shots/001/video.mp4').is_file())
        self.assertFalse((job/'shots/003/render/started').exists())
        self.assertIsNone(self.studio.runner.proc)
        self.assertEqual(len(self.library.clips()),1)

    def test_webm_export_has_selected_dimensions_fps_and_frame_count(self):
        source=self.data/'technical.mp4';self.technical_clip(source,'cyan',seconds=1.5)
        job=self.data/'jobs'/'20261118-120000-abcd1234';job.mkdir()
        profile=resolve_profile({'aspect':'1:1','fps':30,'container':'webm'},(160,96))
        self.studio.runner.start_plan(job.name,profile,[{'kind':'clip','source':str(source),'seconds':1.5,'frames':45,'audible':False}])
        wait_for(lambda: not self.studio.runner.busy)
        result=self.studio.runner.snapshot();self.assertEqual(result['state'],'done',result)
        self.assertTrue(result['video'].endswith('.webm'))
        info=json.loads(subprocess.check_output([binary(self.studio.engine,'ffprobe'),'-v','error','-count_frames','-show_streams','-of','json',str(job/'video.webm')],creationflags=FLAGS))
        self.assertEqual(len(info['streams']),1)
        video=info['streams'][0]
        self.assertEqual((video['width'],video['height'],video['r_frame_rate'],int(video['nb_read_frames'])),(480,480,'30/1',45))

    def test_restart_keeps_finished_shots_and_marks_pending_shots_interrupted(self):
        job=self.data/'jobs'/'20261118-120000-abcd1234';job.mkdir()
        atomic_json(job/'status.json',{'id':job.name,'state':'running','shots':[{'state':'done','seconds':6},{'state':'running','seconds':6},{'state':'queued','seconds':6}]})
        runner=Runner(self.data/'engine',self.data,{'models':[]})
        result=runner.snapshot()
        self.assertEqual(result['state'],'interrupted')
        self.assertEqual([shot['state'] for shot in result['shots']],['done','interrupted','interrupted'])


class EpisodeHTTP(unittest.TestCase):
    def test_asset_auth_persistence_and_media_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            studio=Studio(Path(directory))
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.studio=studio
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def request(path, body=None, token=True, extra=None):
                headers={'Content-Type':'application/json',**({'X-Studio-Token':studio.token} if token else {}),**(extra or {})}
                return urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers),timeout=5)
            try:
                with self.assertRaises(urllib.error.HTTPError) as exc:request('/api/images',{'image':picture()},False)
                self.assertEqual(exc.exception.code,403)
                with request('/api/images',{'image':picture()}) as response:asset=json.load(response)
                with request(asset['url'],extra={'Range':'bytes=0-4'}) as response:
                    self.assertEqual(response.status,206);self.assertEqual(len(response.read()),5)
                with request('/api/library') as response:self.assertIn('episodes',json.load(response))
                for path in ('/library/images/../../config.json','/library/clips/'+asset['id']+'.json','/media/20261118-120000-abcd1234/shots/001/settings.json'):
                    with self.assertRaises(urllib.error.HTTPError) as exc:request(path)
                    self.assertEqual(exc.exception.code,404)
            finally:
                server.shutdown();server.server_close();worker.join()


if __name__=='__main__':unittest.main()
