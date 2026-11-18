"""Validated export profiles and local FFmpeg operations. No model dependencies."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

FLAGS = subprocess.CREATE_NO_WINDOW if __import__('os').name == 'nt' else 0
RATIOS = {'16:9': (16, 9), '9:16': (9, 16), '1:1': (1, 1), '4:3': (4, 3), '3:4': (3, 4), '21:9': (21, 9)}


def export_options(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError('Die Videoeinstellungen sind ungültig.')
    result = {key: value.get(key, default) for key, default in
              [('aspect', 'auto'), ('resolution', 480), ('fps', 24), ('container', 'mp4')]}
    if result['aspect'] not in ('auto', *RATIOS):
        raise ValueError('Wähle ein gültiges Bildformat.')
    if type(result['resolution']) is not int or result['resolution'] not in (480, 720, 1080):
        raise ValueError('Wähle 480p, 720p oder 1080p.')
    if type(result['fps']) is not int or result['fps'] not in (16, 24, 25, 30, 48, 50, 60):
        raise ValueError('Wähle eine der angebotenen Bildraten.')
    if result['container'] not in ('mp4', 'webm'):
        raise ValueError('Wähle MP4 oder WebM.')
    return result


def resolve_profile(options, image_size):
    options = export_options(options)
    width, height = RATIOS.get(options['aspect'], image_size)
    short = options['resolution']
    factor = short / min(width, height)
    return {**options, 'width': max(2, round(width * factor / 2) * 2),
            'height': max(2, round(height * factor / 2) * 2)}


def duration_frames(seconds, fps):
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0 or seconds * fps > 2**53 - 9:
        raise ValueError('Gib eine positive Videolänge in Sekunden ein.')
    frames = round(seconds * fps)
    if frames < 1:
        raise ValueError('Die Szene muss mindestens ein Bild lang sein.')
    return frames


def binary(engine, name):
    local = engine / 'ffmpeg_bins' / (name + ('.exe' if __import__('os').name == 'nt' else ''))
    if local.is_file():
        return str(local)
    found = shutil.which(name)
    if not found:
        raise ValueError('FFmpeg fehlt. Prüfe die KI-Einrichtung unter Hilfe.')
    return found


def probe(engine, source):
    result = subprocess.run([binary(engine, 'ffprobe'), '-v', 'error', '-protocol_whitelist', 'file,pipe,crypto',
                             '-show_streams', '-show_format', '-of', 'json', str(source)],
                            capture_output=True, timeout=30, creationflags=FLAGS)
    try:
        info = json.loads(result.stdout)
        video = next(stream for stream in info['streams'] if stream['codec_type'] == 'video')
        duration = float(video.get('duration', info['format'].get('duration', 0)))
        if result.returncode or not math.isfinite(duration) or duration <= 0:
            raise ValueError()
        return {'duration': duration, 'width': int(video['width']), 'height': int(video['height']),
                'audio': any(stream['codec_type'] == 'audio' for stream in info['streams'])}
    except (ValueError, KeyError, StopIteration, TypeError):
        raise ValueError('Der Clip konnte nicht gelesen werden. Verwende ein gültiges MP4-, MOV-, MKV- oder WebM-Video.')


def normalize_command(engine, source, target, profile, frames, audible, start=0, source_audio=True):
    width, height, fps = (profile[key] for key in ('width', 'height', 'fps'))
    duration = frames / fps
    info = probe(engine, source)
    info['audio'] = info['audio'] and source_audio
    command = [binary(engine, 'ffmpeg'), '-y', '-v', 'warning', '-nostdin', '-protocol_whitelist', 'file,pipe,crypto',
               '-ss', str(start), '-i', str(source)]
    # Every episode shot has the same stream layout. Missing sound becomes silence.
    if audible and not info['audio']:
        command += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
    vf = (f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
          f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},'
          f'tpad=stop_mode=clone:stop_duration={duration},trim=end_frame={frames},setpts=PTS-STARTPTS')
    command += ['-map', '0:v:0', '-vf', vf, '-frames:v', str(frames), '-r', str(fps), '-pix_fmt', 'yuv420p']
    if audible:
        command += ['-map', '0:a:0' if info['audio'] else '1:a:0', '-af', f'aresample=48000,apad,atrim=duration={duration},asetpts=PTS-STARTPTS',
                    '-ar', '48000', '-ac', '2', '-c:a', 'aac', '-b:a', '192k']
    else:
        command += ['-an']
    command += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-video_track_timescale', str(fps * 1024),
                '-movflags', '+faststart', '-t', str(duration), str(target)]
    return command


def final_command(engine, source, target, container):
    command = [binary(engine, 'ffmpeg'), '-y', '-v', 'warning', '-nostdin', '-i', str(source)]
    if container == 'webm':
        command += ['-c:v', 'libvpx-vp9', '-crf', '30', '-b:v', '0', '-deadline', 'good', '-cpu-used', '4', '-c:a', 'libopus']
    else:
        command += ['-c', 'copy', '-movflags', '+faststart']
    return command + [str(target)]


def prepare_reference(source, target, profile):
    from PIL import Image, ImageOps
    # Contain instead of crop: body parts in the reference stay visible.
    size = tuple(max(32, round(profile[key] / 32) * 32) for key in ('width', 'height'))
    with Image.open(source) as image:
        ImageOps.pad(image.convert('RGB'), size, color='#18151d').save(target, 'JPEG', quality=95)

