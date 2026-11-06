# ik-herby – amtliche Gemeindewappen (Polen)

Verzeichnis der **amtlichen Wappen polnischer Gemeinden und Kreise**, gewonnen aus den Ratsbeschlüssen
(„uchwała w sprawie ustanowienia herbu“) in den Amtsblättern der Woiwodschaften. Das Übersichtsplan-Tool
für Infrakit liest dieses Verzeichnis und wählt amtliche Wappen automatisch aus.

Pilot: **Woiwodschaft Małopolska**.

## So funktioniert es
1. `scripts/build_index.py` fragt die offizielle **ELI-Schnittstelle des Sejm** (`api.sejm.gov.pl/eli`) nach Beschlüssen mit „herb“ im Titel.
2. Der Titel ergibt das beschließende Organ (z. B. „Rady Gminy Chełmiec“) und das Datum. Über **Wikidata** (TERC-Kennung) wird die Gemeinde zugeordnet.
3. Gilt der Beschluss noch (nicht aufgehoben), wird das PDF geladen und die Anlage „Herb“ als Bild ausgeschnitten.
4. Ergebnis: `data/index.json` (Wikidata-ID → Beschluss, Datum, Link, Bild) und `data/img/<QID>.png`. Bericht: `data/report.md`.

Amtlich eingeführte Wappen sind in Polen nicht urheberrechtlich geschützt. Das Programm beachtet robots.txt, fragt langsam (1 Anfrage pro Sekunde) und identifiziert sich mit einem eigenen User-Agent.

## Einrichten (einmalig)
1. Dieses Repository unter `Infra0104/ik-herby` anlegen und die Dateien hochladen.
2. Unter **Settings → Actions → General** „Read and write permissions“ für Workflows erlauben.
3. Optional unter **Settings → Variables** eine Variable `CONTACT` mit einer Kontakt-Adresse anlegen (wird im User-Agent mitgeschickt).
4. **Actions → „Wappenverzeichnis aktualisieren“ → Run workflow** mit `discover = true` starten. Der Bericht zeigt, ob das Amtsblatt Małopolska in der Schnittstelle enthalten ist.
5. Danach ohne `discover` starten. Ab dann läuft es monatlich automatisch.

## Für das Tool
Das Übersichtsplan-Tool lädt `https://cdn.jsdelivr.net/gh/Infra0104/ik-herby@main/data/index.json`.
Fehlt die Datei, arbeitet das Tool wie bisher mit Wikidata und Wikipedia.

## Grenzen
- Wappen aus Beschlüssen, die vor der Digitalisierung der Amtsblätter gefasst wurden, fehlen. Dafür gilt weiter die Ampel im Tool.
- Nicht eindeutig zugeordnete Beschlüsse stehen in `data/report.md` unter „Nicht zugeordnet“ und brauchen einen Blick von Hand.
- Automatisch ausgeschnittene Bilder bitte anfangs stichprobenartig prüfen.
