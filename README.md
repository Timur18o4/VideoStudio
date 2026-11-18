# Video Studio

Ein Windows-Frontend für lokale KI-Videos mit WanGP und LTX-2.3: einzelne Clips oder Episoden mit mehreren Szenen, gespeicherten Charakterreferenzen, eigenen Bildern und optionaler Sprache und Geräuschen. Die Berechnung läuft auf dem eigenen PC.

**Öffentliche Vorschauversion 0.2.2:** [Windows-Installer herunterladen](https://github.com/Timur18o4/VideoStudio/releases/tag/v0.2.2-preview). Unter „Assets“ die Datei `VideoStudio-Setup-0.2.2-preview.exe` auswählen. Für die Installation der Oberfläche ist kein eigenes Python nötig.

## Benutzung

**0.2.2-preview** ergänzt Episoden, Charaktervorlagen, die Szenenvorschau und einstellbare Ausgabeformate. Der Einzelclip-Modus bleibt verfügbar.

1. `VideoStudio-Setup-0.2.2-preview.exe` öffnen und installieren.
2. **Video Studio** über die Desktopverknüpfung starten. Auf einem neuen PC einmal **KI einrichten** anklicken und den Download abwarten.
3. Ein Startbild hochladen. Optional ein zweites Bild als gewünschte Schlussaufnahme ergänzen.
4. Beschreiben, was im Video passieren soll. Bei Bedarf deutschen Sprechtext und Geräusche ergänzen.
5. **Video erstellen**, danach **Video speichern**.

Ohne Sprechtext und Geräusche wird das exportierte Video stummgeschaltet. Bilder und Texte bleiben im jeweiligen lokalen Auftrag. Browser-Eingaben werden auf diesem PC gespeichert, damit sie nach dem Neuladen wieder verfügbar sind. Zum vollständigen Beenden gibt es unten **Programm beenden**. Das Schließen des Browserfensters beendet einen laufenden Auftrag nicht.

Das zweite Bild dient als Schlussbild, nicht als beliebige zusätzliche Identitätsreferenz. Die Videolänge lässt sich frei in ganzen Sekunden ab 1 eingeben, beispielsweise 7, 25 oder 90. Die Oberfläche setzt keine feste Höchstdauer. Längere Videos werden automatisch in überlappenden Abschnitten berechnet; Rechenzeit, Speicherbedarf, Übergänge und Identitätsstabilität begrenzen die praktisch sinnvolle Länge. Ein beliebig langer, durchgehend konsistenter Film ist nicht garantiert. Das Programm trainiert kein neues Personenmodell. Die Länge des Sprechtextes muss zur Videolänge passen.

## Episoden und wiederkehrende Charaktere (0.2.2)

1. **Episode & Charaktere** öffnen. Standardmäßig sind fünf Szenen vorbereitet. Unter **Charaktere & vorhandene Clips** einen Namen und ein Referenzbild speichern; Merkmale sind optional und werden dem Prompt angehängt.
2. Pro Szene den Charakter auswählen oder ein eigenes Startbild hochladen. Ein zweites Bild ist die gewünschte Schlussaufnahme. Kamera, Handlung, Dauer und bei Bedarf Sprache/Geräusche je Aufnahme eintragen.
3. Szenen hinzufügen, entfernen oder mit den Pfeilen umordnen. **Auf Szenen verteilen** verteilt die Gesamtlänge auf ganze Videobilder; fünf Szenen bei 30 Sekunden ergeben je sechs Sekunden.
4. **Episode speichern** bewahrt alle Referenzen und Anweisungen lokal. Eine gespeicherte Episode lässt sich laden und mit **Als neue Folge** kopieren, ohne die ursprüngliche Vorlage zu überschreiben.
5. **Episode erstellen** berechnet die Aufnahmen nacheinander und fügt sie in Listenreihenfolge zusammen. Fertige Szenen rechts sofort ansehen, speichern oder ihr letztes Standbild als Anfang einer neuen Szene übernehmen.

Unter **Charaktere & vorhandene Clips** lassen sich auch eigene Clips importieren (bis 1 GB). Ein Standbild an einem gewählten Zeitpunkt kann als Charakterreferenz oder Szenenbild dienen. Alternativ in einer Szene **Fertigen Clip verwenden** wählen, Beginn und Länge des Ausschnitts angeben. Ein importierter Clip wird nicht automatisch analysiert oder als Training verwendet. Die Wiedergabe importierter Originaldateien hängt vom Browser und ihrem Codec ab; die exportierten MP4-Videos verwenden H.264.

Referenzbilder sind eine visuelle Vorgabe, kein trainiertes Personenmodell. Gesicht, Kleidung und Körper können zwischen Aufnahmen abweichen. Für mehrere Personen in derselben Aufnahme ein gemeinsames Szenenbild verwenden. Das zweite Bild ist weiterhin ein Schlussbild, keine zweite Identitätsreferenz.

**Live-Zwischenbilder** zeigen die grobe RGB-Vorschau der laufenden KI-Schritte. Sie sind keine bereits fertig gerenderten Filmframes; Farben und Details können stark abweichen. Beim Laden der KI und in Rechenschritten ohne Vorschau bleibt die Anzeige leer. Falls die lokale Engine keine Vorschau liefert, wird dies angezeigt; fertige Szenen bleiben sofort abspielbar. **Abbrechen** stoppt den aktuellen Render- oder Exportprozess und startet keine weiteren Szenen. Vollständig gespeicherte Szenen bleiben erhalten, auch nach Abbruch oder Fehler.

## Bildformat, Auflösung, FPS und Datei

Die vier Auswahlfelder über dem Editor gelten für Einzelclips und die gesamte Episode. **Wie das Startbild** übernimmt das Seitenverhältnis der ersten Aufnahme. 480p/720p/1080p bezeichnen die kurze Bildkante, z. B. 1280 × 720 bei 16:9 und 720 × 1280 bei 9:16. Pixelmaße werden auf gerade Zahlen gerundet. Bilder werden eingepasst, bei Bedarf mit Rändern, damit Körperteile nicht durch automatisches Zuschneiden verschwinden.

Die ausgewählte FPS-Zahl geht an die KI und bestimmt die angeforderte Bildzahl. Das Modell erhält seine nötige Bildzahl im 8n+1-Raster; überzählige Bilder werden beim Export entfernt. Das Ergebnis hat die gewählte Auflösung, Bildrate und auf einzelne Bilder gerundete Dauer. Höhere Auflösung/FPS können deutlich länger dauern oder den Grafikspeicher überfordern. MP4 ist schneller zu exportieren; WebM benötigt eine zusätzliche Umwandlung. Zwischenclips bleiben als MP4 erhalten. Bei gemischten Szenen werden fehlende Tonspuren durch Stille ergänzt, Szenen ohne gewünschte Sprache/Geräusche bleiben stumm.

## Direkte Beschreibung und Textvorschau

**Beschreibung unverändert verwenden** ist standardmäßig aktiv. Die Anwendung übernimmt die Szenenbeschreibung einschließlich Zeilenumbrüchen und Leerzeichen unverändert. Es gibt dabei keine zusätzlichen Vorgaben für Fotorealismus, Kleidung, Körperform oder Kamerastil. Separat ausgefüllte Sprechtext- und Geräuschfelder werden als sichtbare Ergänzungen angehängt. Ohne diese beiden Felder wird das exportierte Video weiterhin stummgeschaltet.

Wer die bisherige Unterstützung für eine fotorealistische Szene mit konsistentem Aussehen möchte, kann die Option ausschalten. Unter **Text an die KI ansehen** wird vor dem Start der vollständige Text angezeigt, den die Anwendung an WanGP übergibt. Vorschau und Erstellung verwenden dieselbe Funktion. Bei neuen Aufträgen ist unter **Verwendeter Text dieses Auftrags** außerdem der tatsächlich übergebene Text einsehbar und lokal gespeichert. Bilder werden zusätzlich als visuelle Vorgabe übergeben; Modell und Textencoder verarbeiten diese Eingaben weiterhin nach ihrer Architektur.

In dieser Videooberfläche wird kein Ollama-Promptmodell aufgerufen. Eine automatische Prompt-Umschreibung durch ein Sprachmodell bleibt deaktiviert. Die Anwendung verwendet keine eigene Themen-Sperrliste und fragt keinen externen Moderationsdienst ab. Die direkte Textübergabe ist keine Garantie für beliebige Modellfähigkeiten oder wortgetreue Umsetzung und wird nicht als Entfernung eines Modell-Checkers bezeichnet.

## Automatische Updates

Ab Version 0.2 prüft das installierte Windows-Programm beim Start und etwa alle sechs Stunden auf neuere signierte GitHub-Veröffentlichungen. Ein Update wird im Hintergrund geladen und erst installiert, wenn kein Video und keine KI-Einrichtung läuft. Das Programm startet danach automatisch neu; die Browserseite verbindet sich wieder und lädt bei einer neuen Programmversion neu. Eingaben werden lokal gesichert. Ohne Internet bleibt die lokale Videoerstellung nutzbar.

Jedes Update benötigt ein mit dem eingebauten Ed25519-Prüfschlüssel verifiziertes Manifest. Paketgröße, SHA-256, Downloadadresse und enthaltene Dateipfade werden zusätzlich geprüft. Einstellungen, Projekte und Modelle sind vom Austausch ausgeschlossen. Die vorherigen Programmdateien bleiben für die Wiederherstellung erhalten. Startet die neue Version nicht zuverlässig, wird die vorherige Version wieder gestartet und die fehlgeschlagene Version nicht erneut automatisch versucht.

In **Hilfe → Nach Updates suchen** kann die Prüfung zusätzlich ausgelöst werden. Der Updater läuft nur in einer installierten Windows-Version. Eine bereits vorhandene Version 0.1 muss einmalig über den neuen Installer aktualisiert werden. Der Quellcodebetrieb wird nicht automatisch verändert.

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

WanGP ist auf Commit `38758d3c73366422efcf609abb63cab8385f3552` festgelegt. `models.lock.json` enthält feste Modellrevisionen, Größen und SHA-256-Prüfsummen. Die Paketversionen der funktionierenden lokalen Engine stehen in `requirements-engine.lock`. Geprüft wurden Installation der Oberfläche, eine separate neue Engine-Umgebung und reale Videoaufträge auf dem Entwicklungs-PC; die vorhandenen Modellgewichte wurden dabei wiederverwendet. Eine vollständige Neuinstallation auf einem separaten sauberen Windows-System steht noch aus. Die Veröffentlichung ist deshalb als Vorschau gekennzeichnet. Die Updatepakete werden separat mit Ed25519 signiert. Eine Windows-Authenticode-Signatur des Installers gibt es noch nicht.

## Fremdkomponenten

Berechnung mit **WanGP von DeepBeepMeep** und **LTX-2.3 von Lightricks**, mit Gemma-Textencoder von Google. Dies ist ein unabhängiges Frontend und kein offizielles Produkt dieser Anbieter. Die jeweiligen Lizenzbedingungen bleiben maßgeblich; siehe `THIRD_PARTY_NOTICES.md` und `licenses`.

Für den neuen Frontend-Code wurde bislang keine freie Lizenz festgelegt. Das öffentliche Repository ist daher nicht pauschal als MIT- oder Apache-lizenziert zu verstehen. Die Lizenzbedingungen der Fremdkomponenten gelten unverändert und sind separat dokumentiert. Die Bedingungen von WanGP und den Modellen sind insbesondere bei einer entgeltlichen Weitergabe oder Integration zu berücksichtigen.

## Neue Version signieren

Nur der Herausgeber führt nach dem Build `python tools/sign_release.py` aus. Dies erstellt `update.json` mit einer Ed25519-Signatur für das Update-ZIP. Der private Schlüssel liegt DPAPI-verschlüsselt außerhalb des Repositorys im lokalen Benutzerprofil und wird nicht veröffentlicht. `update-trust.json` enthält nur den öffentlichen Prüfschlüssel. Zur Ersteinrichtung eines eigenen, getrennten Herausgeberschlüssels dient `--init-key`; vorhandene Prüfschlüssel werden dabei nicht still ersetzt. Den privaten Schlüssel vor dem nächsten Rechnerwechsel separat gesichert übertragen; die DPAPI-Datei allein ist nicht auf einem anderen Benutzerkonto entschlüsselbar.
