# PDF

Ein PDF ist fertig und unveränderlich: gedacht zum Lesen, Drucken und Versenden. Es wird wie ein Dokument aus Markdown gesetzt (Schrift ohne Serifen, A4, Seitenzahl unten).

**Wann PDF?** Für Abgabe, Archiv, Versand, Druck. Muss die Person es noch bearbeiten, nimm Word (`.docx`).

**Aufbau**
- Titel mit `#`, Abschnitte mit `##`, Unterabschnitte mit `###`. Anfang mit dem Wichtigsten (Zusammenfassung oder Anlass).
- Kurze Absätze (höchstens 5 Zeilen), Listen für Aufzählungen, Tabellen mit Kopfzeile und höchstens 6 Spalten (A4 hoch). Breite Tabellen werden eng; kürze Spalten oder teile die Tabelle.
- Lange Dokumente gliedere in Abschnitte von je etwa einer halben Seite. Mehr als etwa 10 Seiten: prüfe, ob es kürzer geht.

**Lesbarkeit beim Druck**
- Schwarz-weiß tauglich: Bedeutung nie nur über Farbe. Überschriften tragen den Aufbau, nicht Farbflächen.
- Hinweise als Zitat (`> Hinweis: …`), feine Trennlinien mit `---`, Code in Codeblöcken (kurz halten, lange Zeilen brechen um).

**Deckblatt, Umbruch, Kopf- und Fußzeile:** wie in Word: `[DECKBLATT]` (Text davor wird Titelseite ohne Fußzeile), `[SEITENUMBRUCH]`, `[KOPFZEILE: Text]` (oben rechts) und `[FUSSZEILE: Text]` (unten links, Seitenzahl rechts). Links `[Text](Webadresse)` sind anklickbar.

**Formulare:** Neue ausfüllbare Formulare entstehen mit `file_edit` an einem vorhandenen PDF (Felder anlegen, ausfüllen, sperren), nicht mit `file_create`.

**Bilder, Diagramme, Verzeichnis:** `![Beschreibung](name.png)`, `chart`-Block und `[TOC]` (mit Seitenzahlen, Links und Lesezeichen im PDF) wie in allgemein beschrieben. Bilder stehen mittig, werden nicht auf mehrere Seiten geteilt und rücken im Zweifel auf die nächste.

**Grenzen:** Sonderzeichen außerhalb der Schrift (Emojis) fallen weg, keine Spalten. Sag das offen.
