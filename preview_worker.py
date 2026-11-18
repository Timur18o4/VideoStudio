"""Expose WanGP's existing RGB denoising previews in CLI mode, without editing WanGP.

The hook is intentionally limited to the pinned CLI command consumer. Missing or
changed hooks disable the optional preview, never the generation itself.
"""
import os
import sys
import types
from pathlib import Path


def instrument(source):
    start = source.find('def process_tasks_cli(')
    end = source.find('\ndef ', start + 1)
    if start < 0:
        return source, False
    if end < 0:
        end = len(source)
    section = source[start:end]
    anchor = '            elif cmd == "output":'
    if section.count(anchor) != 1:
        return source, False
    hook = ('            elif cmd == "preview":\n'
            '                _studio_preview(generate_preview, params.get("model_type", ""), data)\n')
    return source[:start] + section.replace(anchor, hook + anchor) + source[end:], True


def main():
    engine, destination = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    sys.argv = [str(engine / 'wgp.py'), *sys.argv[3:]]
    sys.path.insert(0, str(engine))
    os.chdir(engine)
    enabled = True

    def save_preview(generate, model, payload):
        nonlocal enabled
        if not enabled:
            return
        try:
            image = generate(model, payload)
            if hasattr(image, 'image'):
                image = image.image
            if image is not None:
                image = image.convert('RGB')
                image.thumbnail((1280, 720))
                temporary = destination.with_suffix('.tmp')
                image.save(temporary, 'JPEG', quality=80)
                temporary.replace(destination)
                print('\n[STUDIO_PREVIEW]', flush=True)
        except Exception as exc:
            enabled = False
            print(f'\n[STUDIO_PREVIEW_UNAVAILABLE] {type(exc).__name__}', flush=True)

    path = engine / 'wgp.py'
    source, hooked = instrument(path.read_text(encoding='utf-8'))
    if not hooked:
        print('[STUDIO_PREVIEW_UNAVAILABLE] CLI hook changed', flush=True)
    module = types.ModuleType('__main__')
    module.__dict__.update(__file__=str(path), __package__=None, _studio_preview=save_preview)
    sys.modules['__main__'] = module
    exec(compile(source, str(path), 'exec'), module.__dict__)


if __name__ == '__main__':
    main()
