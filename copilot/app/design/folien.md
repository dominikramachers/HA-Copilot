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
- Eine einzelne wichtige Zahl gehört in die Überschrift („Umsatz 2026: 4,2 Mio. €“) und darunter höchstens zwei Stützpunkte.

**Bilder und Diagramme**
- Eine Folie mit Bild oder Diagramm braucht höchstens 3 kurze Stichpunkte; das Bild trägt die Aussage. Ohne Text füllt ein einzelnes Bild oder Diagramm die Folie, zwei oder drei stehen nebeneinander.
- Zahlenreihen als Diagramm (`chart`, siehe allgemein), nicht als Tabelle mit 12 Zeilen. Ein Diagramm, ein Gedanke; Überschrift sagt die Aussage („Umsatz wächst seit Q2“).
- Ablauf, Aufbau, Grundriss oder Logo: als SVG zeichnen (`image_svg`) und mit `![…](name.svg)` einbetten; Fotos und Kunst mit `image_generate`. Quer- oder Breitformat, ruhiger Hintergrund, wenig Text im Bild.
- Danach `file_preview` aufrufen und prüfen, ob Text und Bild sich nicht stören.

**Für Apple Keynote:** Läuft die Präsentation auf Mac, iPad oder iPhone („für Keynote“, „mit Keynote zeigen“), setze bei `file_create` für die `.pptx` `target: keynote`. Keynote öffnet `.pptx` direkt, die Person sichert sie bei Bedarf selbst als `.key`; eine echte `.key`-Datei erzeugst du nicht. Der Keynote-Modus nimmt Mac-Schriften (Helvetica Neue, Georgia), schaltet die automatische Schrumpfung aus, die Keynote nicht kennt, und setzt etwas weniger Text je Folie. Halte die Folien darum noch knapper, nutze Säulen-, Balken-, Linien- und Kreisdiagramme (Keynote macht daraus eigene, bearbeitbare Diagramme) und verzichte auf Sonderschriften. Sag der Person kurz, dass du es für Keynote ausgelegt, aber nicht in Keynote selbst geprüft hast.

**Notizen:** Alles, was die Folie überladen würde (Hintergrund, Quellen, Redetext), kommt als Zeile `Notizen: …` unter die Folie. Es erscheint nur in der Referentenansicht.

**Gestaltung steuerst du so**
- Wähle ein Thema (`design_guide` mit `themen`) und setze es bei `file_create`. Kontrast und Schrift sind damit sicher.
- Keine Inhalte in Großbuchstaben, keine Satzzeichen-Ketten, kein Fett über ganze Zeilen. Fett nur für das Schlüsselwort eines Punktes.
- Code nur, wenn die Zielgruppe ihn braucht, und dann höchstens 12 Zeilen.

**Typische Fehler, die du vermeidest:** Textwand statt Stichpunkte · Überschrift als Rubrik · fünf verschiedene Ausdrucksformen für gleiche Dinge · zu viele Folien für die Zeit · Tabelle mit 8 Spalten · Quelle oder Annahme fehlt bei einer Zahl.
