# Video Studio

Ein kleines Windows-Frontend für lokale KI-Videos mit WanGP und LTX-2.3: ein oder zwei Bilder hochladen, eine Szene beschreiben und bei Bedarf Sprache und Geräusche ergänzen. Die Berechnung läuft auf dem eigenen PC.

**Öffentliche Vorschauversion:** [Windows-Installer herunterladen](https://github.com/Timur18o4/VideoStudio/releases/tag/v0.1.0-preview). Unter „Assets“ die Datei `VideoStudio-Setup-0.1.0-preview.exe` auswählen. Für die Installation der Oberfläche ist kein eigenes Python nötig.

## Benutzung

1. `VideoStudio-Setup-0.1.0-preview.exe` öffnen und installieren.
2. **Video Studio** über die Desktopverknüpfung starten. Auf einem neuen PC einmal **KI einrichten** anklicken und den Download abwarten.
3. Ein Startbild hochladen. Optional ein zweites Bild als gewünschte Schlussaufnahme ergänzen.
4. Beschreiben, was im Video passieren soll. Bei Bedarf deutschen Sprechtext und Geräusche ergänzen.
5. **Video erstellen**, danach **Video speichern**.

Ohne Sprechtext und Geräusche wird das exportierte Video stummgeschaltet. Bilder und Texte bleiben im jeweiligen lokalen Auftrag. Browser-Eingaben werden auf diesem PC gespeichert, damit sie nach dem Neuladen wieder verfügbar sind. Zum vollständigen Beenden gibt es unten **Programm beenden**. Das Schließen des Browserfensters beendet einen laufenden Auftrag nicht.

Das zweite Bild dient als Schlussbild, nicht als beliebige zusätzliche Identitätsreferenz. Die Version erstellt kurze Videos von 4, 8 oder 12 Sekunden. Sie trainiert kein neues Personenmodell. Identität, Bewegungen, genaue Worte und Lippenbewegungen sind modellabhängig und nicht garantiert. Die Länge des Sprechtextes muss zur Videolänge passen.

## Voraussetzungen

- Windows 10/11, 64 Bit.
- NVIDIA-Grafikkarte mit mindestens 8 GB Grafikspeicher; aktueller, mit CUDA 13 kompatibler NVIDIA-Treiber.
- Mindestens 32 GB Arbeitsspeicher vorgesehen; die bisherige reale Videoerzeugung wurde auf einer RTX 3060 Ti mit **64 GB** Arbeitsspeicher geprüft. 32 GB und andere Grafikkarten sind noch nicht verifiziert.
- Für eine neue Einrichtung etwa 65 GB freier Speicher. Die gepinnten KI-Dateien umfassen rund 36,3 GB; Python, CUDA-Bibliotheken, Download-Cache und Exporte brauchen zusätzlichen Platz.
- Internet für die erste Einrichtung. Die Videoerzeugung startet anschließend ausdrücklich im Offline-Modus.

Das Programm bindet ausschließlich an `127.0.0.1`. Es bietet keinen öffentlichen Server, keine Cloud-Inferenz und keine CDN-Schriftarten. Bei der Einrichtung werden Dateien von GitHub, Hugging Face, PyPI, dem PyTorch-Paketserver und dem im Lockfile genannten ONNX-Paketserver geladen. Die Oberfläche besitzt keine Hochladefunktion zu diesen Diensten. Die Modellsoftware ist ein eigenständiges Fremdprojekt.

## Dateien auf dem eigenen PC

Programm: `%LOCALAPPDATA%\Programs\VideoStudioEinfach`.

Einstellungen, KI und Videos: `%LOCALAPPDATA%\VideoStudioEinfach`. Die Deinstallation der Oberfläche entfernt diese Inhalte nicht. Auf dem Entwicklungs-PC wird die bereits eingerichtete lokale WanGP-Installation über die lokale `config.json` verwendet; diese Konfiguration wird nicht verteilt.

## Quellcode und Build

Für den Start aus dem Quellcode Python 3.12 verwenden, `python -m pip install -r requirements-frontend.txt` ausführen und danach `python app.py` starten. Eine vorhandene kompatible WanGP-Installation lässt sich beim ersten Start mit `--engine "Pfad zu Wan2GP"` verbinden. Für Benutzer des Installers übernimmt die Einrichtung diesen Schritt automatisch.

`python -m pip install -r requirements-build.txt` installiert die festgelegten Build-Werkzeuge. `python tools/build_release.py` erstellt eine eigenständige Programmdatei, einen Installer, ein Quellcodearchiv und `SHA256SUMS.txt`. `python -m unittest discover -s tests -v` prüft unter anderem Dateiannahme, Zugriffsschutz, Videobereitstellung und Wiederaufnahme von Downloads. GitHub Actions führt die Tests unter Windows und Linux aus. Der Quellcode enthält keine persönlichen Bilder, fertigen Benutzervideos oder lokalen Einstellungen.

WanGP ist auf Commit `38758d3c73366422efcf609abb63cab8385f3552` festgelegt. `models.lock.json` enthält feste Modellrevisionen, Größen und SHA-256-Prüfsummen. Die Paketversionen der funktionierenden lokalen Engine stehen in `requirements-engine.lock`. Geprüft wurden Installation der Oberfläche, eine separate neue Engine-Umgebung und reale Videoaufträge auf dem Entwicklungs-PC; die vorhandenen Modellgewichte wurden dabei wiederverwendet. Eine vollständige Neuinstallation auf einem separaten sauberen Windows-System steht noch aus. Die Veröffentlichung ist deshalb als Vorschau gekennzeichnet. Es gibt noch keine Windows-Codesignatur und keine automatische Aktualisierung.

## Fremdkomponenten

Berechnung mit **WanGP von DeepBeepMeep** und **LTX-2.3 von Lightricks**, mit Gemma-Textencoder von Google. Dies ist ein unabhängiges Frontend und kein offizielles Produkt dieser Anbieter. Die jeweiligen Lizenzbedingungen bleiben maßgeblich; siehe `THIRD_PARTY_NOTICES.md` und `licenses`.

Für den neuen Frontend-Code wurde bislang keine freie Lizenz festgelegt. Das öffentliche Repository ist daher nicht pauschal als MIT- oder Apache-lizenziert zu verstehen. Die Lizenzbedingungen der Fremdkomponenten gelten unverändert und sind separat dokumentiert. Die Bedingungen von WanGP und den Modellen sind insbesondere bei einer entgeltlichen Weitergabe oder Integration zu berücksichtigen.
