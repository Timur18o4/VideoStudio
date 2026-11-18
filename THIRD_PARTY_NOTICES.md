# Fremdkomponenten

Dieses unabhängige Frontend verwendet eine separat installierte, unveränderte WanGP-Engine und heruntergeladene Modelle. Es besteht keine Zugehörigkeit, Partnerschaft oder Empfehlung durch die genannten Projekte.

- WanGP / Wan2GP, DeepBeepMeep: https://github.com/deepbeepmeep/Wan2GP — WanGP Community License 2.0. Originalbedingungen in `licenses/WanGP-LICENSE.txt`; die heruntergeladene Engine enthält ihre weiteren Originalhinweise. Die Bedingungen betreffen unter anderem kostenlose Weitergabe, entgeltliche Integration und die Nennung von WanGP bei bestimmten Verkäufen erzeugter Inhalte.
- LTX-2.3, Lightricks: https://huggingface.co/Lightricks/LTX-2.3 — LTX-2 Community License; Text in `licenses/LTX-2-LICENSE.txt`. Quantisierte Dateien: https://huggingface.co/DeepBeepMeep/LTX-2.
- Gemma 3, Google: https://ai.google.dev/gemma/terms — Gemma Terms und Prohibited Use Policy gelten für den Textencoder. Originalbedingungen in `licenses/Gemma-TERMS.html` und `licenses/Gemma-PROHIBITED-USE.html`.
- uv, Astral: https://github.com/astral-sh/uv — MIT oder Apache-2.0; Originaltexte in `licenses`. uv wird bei einer frischen Einrichtung separat heruntergeladen.
- FFmpeg: https://ffmpeg.org/legal.html. Der Einrichtungsassistent lädt einen GyanD-Windows-Build von https://github.com/GyanD/codexffmpeg. Dieser unterliegt seinen eigenen GPL-Bedingungen; er ist nicht im Frontend-Installer enthalten. Das heruntergeladene Originalarchiv bleibt im Einrichtungsordner erhalten.
- CPython: https://www.python.org/psf/license/ — PSF License. Python ist im Frontend-Programm gebündelt; beim Build wird der Originaltext mit aufgenommen.
- Pillow: https://python-pillow.github.io/pillow-perf/ und https://github.com/python-pillow/Pillow — MIT-CMU und Hinweise zu mitgelieferten Bibliotheken; Originalhinweise werden beim Build in `licenses/Pillow` aufgenommen.
- PyInstaller: https://pyinstaller.org — GPL-2.0 mit Bootloader-Ausnahme; Originaltexte werden beim Build mit aufgenommen.
- Cryptography: https://cryptography.io — Apache-2.0 oder BSD-3-Clause; CFFI und pycparser mit ihren eigenen Bedingungen. Die Originaltexte dieser gebündelten Komponenten werden beim Build in `licenses` aufgenommen. Cryptography prüft die Ed25519-Signaturen der Updates.

Die Versionen der separat installierten Engine-Bibliotheken sind in `requirements-engine.lock` festgehalten. Diese Bibliotheken werden nicht im kleinen Frontend-Installer weitergegeben. Ihre jeweiligen Bedingungen gelten unverändert.
