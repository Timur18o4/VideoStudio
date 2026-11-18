"""Local character references, episode recipes and reusable clips."""
from __future__ import annotations

import json
import math
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

from engine import atomic_json, build_settings
from media import FLAGS, binary, duration_frames, export_options, prepare_reference, probe, resolve_profile

HEX_ID = r'[0-9a-f]{32}'
JOB_ID = r'\d{8}-\d{6}-[0-9a-f]{8}'


def text(value, maximum, label, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(f'Bitte überprüfe {label}.')
    return value.strip()


class Library:
    def __init__(self, studio):
        self.studio, self.data = studio, studio.data
        for folder in ('images', 'characters', 'episodes', 'clips'):
            (self.data / folder).mkdir(exist_ok=True)

    def path(self, folder, identifier, suffix):
        if not isinstance(identifier, str) or not re.fullmatch(HEX_ID, identifier):
            raise ValueError('Die gespeicherte Vorlage ist ungültig.')
        path = self.data / folder / (identifier + suffix)
        if not path.is_file():
            raise ValueError('Die gespeicherte Vorlage wurde nicht gefunden.')
        return path

    def image(self, value):
        from app import normalize_image
        identifier = secrets.token_hex(16)
        path = self.data / 'images' / (identifier + '.jpg')
        normalize_image(value, path)
        return {'id': identifier, 'url': f'/library/images/{identifier}.jpg'}

    def records(self, folder):
        result = []
        for file in (self.data / folder).glob('*.json'):
            try:
                result.append(json.loads(file.read_text(encoding='utf-8')))
            except (ValueError, OSError):
                continue
        return sorted(result, key=lambda item: item.get('updated', 0), reverse=True)

    def character(self, values):
        identifier = values.get('id') or secrets.token_hex(16)
        if not re.fullmatch(HEX_ID, identifier):
            raise ValueError('Ungültige Charaktervorlage.')
        image = values.get('image')
        self.path('images', image, '.jpg')
        result = {'id': identifier, 'name': text(values.get('name'), 100, 'den Namen', True),
                  'description': text(values.get('description', ''), 1000, 'die Charakterbeschreibung'),
                  'image': image, 'updated': time.time()}
        atomic_json(self.data / 'characters' / (identifier + '.json'), result)
        return result

    def clips(self):
        result = self.records('clips')
        for statusfile in sorted((self.data / 'jobs').glob('*/status.json'), reverse=True):
            try:
                status = json.loads(statusfile.read_text(encoding='utf-8'))
                if status['state'] == 'done' and (statusfile.parent / 'video.mp4').is_file():
                    result.append({'id': statusfile.parent.name, 'name': status.get('title') or statusfile.parent.name,
                                   'url': f'/media/{statusfile.parent.name}/video.mp4', 'duration': status['seconds']})
                for index, shot in enumerate(status.get('shots', [])):
                    if shot.get('state') == 'done' and (statusfile.parent / 'shots' / f'{index+1:03}' / 'video.mp4').is_file():
                        result.append({'id': statusfile.parent.name + f'-{index+1:03}',
                                       'name': f"{status.get('title') or 'Video'} · Szene {index+1}",
                                       'url': shot['video'], 'duration': shot['seconds']})
            except (ValueError, KeyError, OSError):
                continue
        return result

    def clip_path(self, identifier):
        if not isinstance(identifier, str):
            raise ValueError('Wähle einen vorhandenen Clip.')
        if re.fullmatch(HEX_ID, identifier):
            return self.path('clips', identifier, '.mp4')
        match = re.fullmatch(f'({JOB_ID})(?:-([0-9]{{3}}))?', identifier)
        if match:
            path = self.data / 'jobs' / match[1]
            path = path / 'shots' / match[2] if match[2] else path
            path = path / 'video.mp4'
            # Only finalized outputs are reusable, never partially written files.
            if path.is_file() and any(item['id'] == identifier for item in self.clips()):
                return path
        raise ValueError('Der fertige Clip wurde nicht gefunden.')

    def register_clip(self, identifier, name):
        path = self.data / 'clips' / (identifier + '.mp4')
        info = probe(self.studio.engine, path)
        result = {'id': identifier, 'name': text(name, 200, 'den Clipnamen') or 'Importierter Clip',
                  'duration': info['duration'], 'url': f'/library/clips/{identifier}.mp4', 'updated': time.time()}
        atomic_json(path.with_suffix('.json'), result)
        return result

    def frame(self, values):
        source = self.clip_path(values.get('clip'))
        seconds = values.get('at', 0)
        info = probe(self.studio.engine, source)
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds < info['duration']:
            raise ValueError('Wähle einen Zeitpunkt innerhalb des Clips.')
        identifier = secrets.token_hex(16)
        path = self.data / 'images' / (identifier + '.jpg')
        result = subprocess.run([binary(self.studio.engine, 'ffmpeg'), '-v', 'error', '-nostdin', '-y',
                                 '-protocol_whitelist', 'file,pipe,crypto', '-ss', str(seconds), '-i', str(source),
                                 '-frames:v', '1', '-vf', 'scale=1024:1024:force_original_aspect_ratio=decrease', str(path)],
                                capture_output=True, timeout=60, creationflags=FLAGS)
        if result.returncode or not path.is_file():
            path.unlink(missing_ok=True)
            raise ValueError('An dieser Stelle konnte kein Standbild gelesen werden.')
        return {'id': identifier, 'url': f'/library/images/{identifier}.jpg'}

    def recipe(self, values):
        title = text(values.get('title', 'Neue Episode'), 120, 'den Episodentitel', True)
        options = export_options(values.get('output'))
        shots = values.get('shots')
        if not isinstance(shots, list) or not 1 <= len(shots) <= 200:
            raise ValueError('Lege zwischen 1 und 200 Szenen an.')
        clean = []
        for number, shot in enumerate(shots, 1):
            if not isinstance(shot, dict):
                raise ValueError(f'Szene {number} ist ungültig.')
            frames = duration_frames(shot.get('seconds', 6), options['fps'])
            item = {'seconds': frames / options['fps'], 'frames': frames, 'kind': shot.get('kind', 'generate')}
            if item['kind'] == 'clip':
                source = self.clip_path(shot.get('clip'))
                start = shot.get('start', 0)
                info = probe(self.studio.engine, source)
                if type(start) not in (int, float) or not math.isfinite(start) or start < 0 or start + item['seconds'] > info['duration'] + 1 / options['fps']:
                    raise ValueError(f'Szene {number}: Der gewählte Ausschnitt liegt außerhalb des Clips.')
                audio = shot.get('audio', True)
                if type(audio) is not bool:
                    raise ValueError('Die Toneinstellung ist ungültig.')
                item.update(clip=shot['clip'], start=start, audio=audio)
            elif item['kind'] == 'generate':
                scene, speech, sounds, direct = self.studio.prompt_inputs(shot)
                images = shot.get('images', [])
                if not isinstance(images, list) or len(images) > 2:
                    raise ValueError(f'Szene {number}: Wähle höchstens zwei Bilder.')
                character = shot.get('character', '')
                if character:
                    record = json.loads(self.path('characters', character, '.json').read_text(encoding='utf-8'))
                    if not images:
                        images = [record['image']]
                if not images:
                    raise ValueError(f'Szene {number}: Lade ein Startbild hoch oder wähle einen Charakter.')
                for image in images:
                    self.path('images', image, '.jpg')
                item.update(scene=scene, speech=speech, sounds=sounds, direct_prompt=direct,
                            images=images, character=character)
            else:
                raise ValueError('Unbekannter Szenentyp.')
            clean.append(item)
        return {'title': title, 'output': options, 'shots': clean}

    def save(self, values):
        result = self.recipe(values)
        identifier = values.get('id') or secrets.token_hex(16)
        if not isinstance(identifier, str) or not re.fullmatch(HEX_ID, identifier):
            raise ValueError('Ungültige Episode.')
        result.update(id=identifier, updated=time.time())
        atomic_json(self.data / 'episodes' / (identifier + '.json'), result)
        return result

    def plan(self, recipe, directory):
        from PIL import Image
        first = recipe['shots'][0]
        if first['kind'] == 'clip':
            info = probe(self.studio.engine, self.clip_path(first['clip']))
            size = info['width'], info['height']
        else:
            with Image.open(self.path('images', first['images'][0], '.jpg')) as image:
                size = image.size
        profile = resolve_profile(recipe['output'], size)
        plan = []
        for index, shot in enumerate(recipe['shots'], 1):
            folder = directory / 'shots' / f'{index:03}'
            folder.mkdir(parents=True)
            item = {**shot, 'audible': bool(shot.get('audio') or shot.get('speech', '').strip() or shot.get('sounds', '').strip())}
            if shot['kind'] == 'clip':
                item['source'] = str(self.clip_path(shot['clip']))
            else:
                paths = []
                for number, image in enumerate(shot['images'], 1):
                    target = folder / f'bild-{number}.jpg'
                    prepare_reference(self.path('images', image, '.jpg'), target, profile)
                    paths.append(target)
                description = shot['scene']
                if shot['character']:
                    record = json.loads(self.path('characters', shot['character'], '.json').read_text(encoding='utf-8'))
                    if record['description']:
                        description += '\n\nCharacter appearance: ' + record['description']
                item['settings'] = build_settings(description, shot['speech'], shot['sounds'], paths, shot['seconds'],
                                                   secrets.randbelow(2**31), shot['direct_prompt'], profile)
                if index == 1:
                    shutil.copyfile(paths[0], directory / 'bild-1.jpg')
            plan.append(item)
        return profile, plan
