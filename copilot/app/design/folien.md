# Folien (PowerPoint)

Eine Folie ist ein Plakat, kein Dokument. Wer sie sieht, soll sie in wenigen Sekunden erfassen. Den Rest sagt die Rednerin oder steht in den Notizen.

**Aufbau des Vortrags**
1. **Titelfolie:** erste Folie mit Überschrift und höchstens zwei kurzen Zeilen darunter (Untertitel, Datum oder Name). Sie bekommt automatisch den farbigen Hintergrund.
2. **Kernaussage früh:** zweite Folie nennt Ergebnis oder Empfehlung, nicht die Gliederung. Eine Agenda (`## Agenda` mit der Zeile `[TOC]` darunter, die Folie füllt sich selbst) nur bei mehr als 10 Folien.
3. **Abschnitte:** Bei mehr als 8 Folien trenne Abschnitte mit einer Folie, die nur aus einer `##`-Überschrift besteht (kein Text darunter). Sie wird als farbige Zwischenfolie gesetzt.
4. **Schluss:** eine Folie mit Entscheidung, nächsten Schritten, Zuständigen und Terminen. Kein „Danke für Ihre Aufmerksamkeit“.
- Grobe Länge: 1 bis 2 Minuten je Folie. 10 Minuten ≈ 6 bis 8 Folien, 20 Minuten ≈ 12 bis 15.

**Eine Folie, ein Gedanke**
- Überschrift = Aussage („Rechenzentrum spart 30 % Strom“), keine Rubrik („Energie“). Höchstens 8 Wörter, eine Zeile.
- Darunter höchstens **5 Stichpunkte** mit je höchstens **12 Wörtern**, parallel formuliert, ohne Satzpunkt. Mehr gehört auf die nächste Folie oder in die Notizen.
- Drei gleichwertige Punkte lesen sich besser als sieben. Verschachtelung nur eine Ebene tief.
- Sätze am Stück nur für ein einzelnes Zitat (`> Zitat`) oder eine Schlussfolgerung.

**Tabellen und Zahlen**
- Eine Tabelle hat höchstens 5 Spalten und 6 Zeilen auf einer Folie; erste Zeile = Kopfzeile. Mehr Zeilen verteilt `file_create` selbst auf Folgefolien „(Forts.)“: besser vorher kürzen oder nach Wichtigkeit auf mehrere Folien teilen.
- Gleiche Einheit pro Spalte, Zahlen gleich gerundet, Einheit in die Kopfzeile statt in jede Zelle.
- Eine einzelne wichtige Zahl gehört in die Überschrift („Umsatz 2026: 4,2 Mio. €“) mit höchstens zwei Stützpunkten, oder als Kennzahlen-Folie (siehe unten), wenn sie die Folie tragen soll.

**Bilder und Diagramme**
- Eine Folie mit Bild oder Diagramm braucht höchstens 3 kurze Stichpunkte; das Bild trägt die Aussage. Ohne Text füllt ein einzelnes Bild oder Diagramm die Folie, zwei oder drei stehen nebeneinander.
- Zahlenreihen als Diagramm (`chart`, siehe allgemein), nicht als Tabelle mit 12 Zeilen. Ein Diagramm, ein Gedanke; Überschrift sagt die Aussage („Umsatz wächst seit Q2“).
- Ablauf, Aufbau, Grundriss oder Logo: als SVG zeichnen (`image_svg`) und mit `![…](name.svg)` einbetten; Fotos und Kunst mit `image_generate`. Quer- oder Breitformat, ruhiger Hintergrund, wenig Text im Bild.
- Danach `file_preview` aufrufen und prüfen, ob Text und Bild sich nicht stören.

**Für Apple Keynote:** Läuft die Präsentation auf Mac, iPad oder iPhone („für Keynote“, „mit Keynote zeigen“), setze bei `file_create` für die `.pptx` `target: keynote`. Keynote öffnet `.pptx` direkt, die Person sichert sie bei Bedarf selbst als `.key`; eine echte `.key`-Datei erzeugst du nicht. Der Keynote-Modus nimmt Mac-Schriften (Helvetica Neue, Georgia), schaltet die automatische Schrumpfung aus, die Keynote nicht kennt, und setzt etwas weniger Text je Folie. Halte die Folien knapper, nutze Säulen-, Balken-, Linien- und Kreisdiagramme (bearbeitbar in Keynote) und keine Sonderschriften. Sag kurz, dass du es für Keynote ausgelegt, aber dort nicht geprüft hast.

**So setzt `file_create` die Folien (daraus planst du den Inhalt)**
- **Karten:** Eine Folie, die nur aus 2 bis 6 Punkten besteht, die alle mit einem fetten Stichwort beginnen (`- **Wallbox:** Laden über Nacht`) und keine Unterpunkte haben, wird als Reihe von Karten gesetzt: Stichwort als Titel, Erklärung darunter. Gut für Schritte, Vorteile, Zeitabschnitte. Ohne fettes Stichwort bleibt es eine normale Liste.
- **Text mit einem Bild:** Ein einzelnes Bild plus Text: das Bild füllt die rechte Folienhälfte bis zum Rand, der Text steht links. Diagramme stehen auf einer Fläche, beim Text daneben rechts.
- **Rhythmus:** Wechsle die Folienart (Karten, Zahl, Bild, Diagramm, Zitat, Zwischenfolie). Mehr als drei reine Listenfolien hintereinander wirken wie ein Dokument; etwa jede dritte Folie sollte etwas Sichtbares tragen.
- **Zwischenfolien** (nur `##`-Überschrift) erhalten automatisch eine große Ziffer: so führen sie durch den Vortrag.

**Besondere Folien (je eigene Zeilen im Markdown)**
- **Zwei Spalten:** eine Zeile `+++` teilt den Inhalt einer Folie in links und rechts (Liste, Tabelle, Text, Bild oder Diagramm je Seite), z. B. Vorher/Nachher oder Vor- und Nachteile. Beginne jede Seite mit einer Zeile `### Überschrift der Spalte`: sie steht als Titel auf der Fläche. Eine Teilung je Folie, jede Seite knapp.
- **Zitat:** besteht die Folie nur aus einem `> Zitat` und optional einer Zeile `— Quelle`, wird sie als große Zitatfolie gesetzt. Die Überschrift ist dann eine kleine Marke („Kundenstimme“).
- **Kennzahlen:** ein bis vier Zahlen groß nebeneinander: je eine fette Kurzzahl mit Ziffer, gefolgt von einer Erklärung, z. B. `**4,2 Mio. €**` und darunter (Leerzeile oder gleich dahinter) `Umsatz im 3. Quartal`. Die Folie darf sonst nichts enthalten. Alle Zahlen stehen auf Karten und sind gleich groß; halte sie kurz („19,1 %“, „49,5 Mio.“).
- **Vollbild-Bild:** `![Beschreibung](name.png){vollbild}` füllt die ganze Folie (zugeschnitten). Die Überschrift steht auf einem Balken unten, ein Absatz danach als kleine Bildzeile. Für Eindruck und Stimmung, nicht für Diagramme.

**Notizen:** Alles, was die Folie überladen würde (Hintergrund, Quellen, Redetext), kommt als Zeile `Notizen: …` unter die Folie. Es erscheint nur in der Referentenansicht.

**Gestaltung steuerst du so**
- Wähle ein Thema (`design_guide` mit `themen`) und setze es bei `file_create`. Kontrast und Schrift sind damit sicher.
- Keine Inhalte in Großbuchstaben, keine Satzzeichen-Ketten, kein Fett über ganze Zeilen. Fett nur für das Schlüsselwort eines Punktes.
- Code nur, wenn die Zielgruppe ihn braucht, und dann höchstens 12 Zeilen.

**Typische Fehler, die du vermeidest:** Textwand statt Stichpunkte · Überschrift als Rubrik · fünf verschiedene Ausdrucksformen für gleiche Dinge · zu viele Folien für die Zeit · Tabelle mit 8 Spalten · Quelle oder Annahme fehlt bei einer Zahl.
