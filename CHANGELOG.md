# Änderungen

## 0.2.0-preview

- Frei eingebbare Videolänge in ganzen Sekunden ab 1 statt fester Auswahl.
- Automatische Fortsetzung längerer Videos in überlappenden Abschnitten mit begrenzter Fenstergröße.
- Mehr Platz für längere Sprechtexte.
- Automatische Updateprüfung beim Start und alle sechs Stunden sowie manuelle Prüfung unter Hilfe.
- Signierte Update-Manifeste (Ed25519), SHA-256-Prüfung, feste Downloadadressen und erlaubte Programmdateien.
- Installation erst ohne laufenden Auftrag, automatischer Neustart mit Startprüfung und Wiederherstellung bei Fehlern.
- Erhalt der lokalen Einstellungen, Bilder, Videos und KI-Dateien bei Updates.

## 0.1.0-preview

- Einfaches lokales Frontend mit einem Startbild und optionalem Schlussbild.
- Szenenbeschreibung, optional deutscher Sprechtext und Geräusche.
- Videos mit 4, 8 oder 12 Sekunden; automatische Bildausrichtung und feste Modellvorgaben.
- Fortschrittsanzeige, Abbrechen, Vorschau, Download und lokale Videohistorie.
- Wiederherstellung von Eingaben nach dem Neuladen.
- Windows-Installer mit Desktop- und Startmenüverknüpfung.
- Automatische lokale Einrichtung mit festen Modellrevisionen, Prüfsummen und fortsetzbaren Downloads.
- Offline-Berechnung mit WanGP / LTX-2.3; Dateien bleiben auf dem eigenen PC.

Dies ist eine Vorschau. Geprüft auf RTX 3060 Ti mit 8 GB Grafikspeicher und 64 GB Arbeitsspeicher. Identität, genaue Worte, Lippenbewegungen und Prompttreue sind nicht garantiert. Eine vollständige Ersteinrichtung auf einem separaten sauberen Windows-PC steht noch aus.
