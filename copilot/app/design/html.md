# HTML-Seiten und HTML-Präsentationen (.html)

Eine HTML-Datei ist die Gestaltung, die du selbst baust: Es gibt keine Vorlage, also trägst du Schrift, Abstände und Farbe. Genau darum sieht gute HTML oft besser aus als eine .pptx. Nimm dir deshalb die Regeln einer Gestalterin, nicht die einer Textverarbeitung. Die Regeln gelten für Präsentationen, Berichte und Seiten; bei einem kleinen Schnipsel (etwa einer Karte für eine bestehende Oberfläche) nimmst du nur, was passt.

**Technik (damit die Datei überall funktioniert)**
- **Eine einzige Datei**, alles inline: `<style>` im Kopf, ein kleines `<script>` am Ende, Bilder als `data:`-Adresse oder als SVG im Text. Keine Schriften, Skripte oder Bilder aus dem Netz: die Datei muss offline und aus dem Download-Ordner öffnen.
- `<meta name="viewport" content="width=device-width, initial-scale=1">`, `lang="de"`, ein `<title>`. Schrift: Systemschrift (`system-ui, "Segoe UI", Helvetica, Arial, sans-serif`), für Überschriften wahlweise `Georgia, serif`.
- Farben als Variablen in `:root` (`--ink`, `--paper`, `--accent`, `--surface`, `--head`). Nimm die Werte eines Themes aus der Themenliste, damit Dokumente, Folien und Seiten zusammenpassen. Dunkelmodus nur, wenn er gewollt ist; dann auch beide Varianten auf Kontrast prüfen (Text gegen Grund mindestens 4,5:1).
- Maximal ein Akzent. Rand, Fläche und Weißraum gliedern; Schatten, Verläufe und Leuchteffekte nicht stapeln.

**Präsentation**
- Jede Folie ist ein `<section class="slide">` mit `min-height: 100vh` (oder festem 16:9) und eigener Hintergrundfläche; die Seite scrollt mit `scroll-snap-type: y mandatory`. Pfeiltasten, Leertaste und Bild-auf/ab springen zur nächsten Folie (5 Zeilen Script), ein Zähler „3 / 9“ unten rechts.
- Schrift skaliert mit dem Bildschirm: `font-size: clamp(1.1rem, 2.2vw, 1.75rem)` für Text, `clamp(2rem, 5vw, 4.5rem)` für Überschriften. Text nie unter 18 px. Zeilenlänge höchstens etwa 60 Zeichen.
- **Eine Folie, ein Gedanke**, wie bei Folien: Überschrift als Aussage, höchstens fünf Punkte, lieber drei. Der Rest gehört in Sprechernotizen oder auf die nächste Folie.
- **Rhythmus:** Wechsle die Art der Folie (Titel dunkel, Aussage groß, Karten, Zahl, Bild halbe Seite, Zitat dunkel, Schluss). Drei gleiche Folien hintereinander wirken wie ein Formular. Etwa jede dritte Folie trägt ein Bild, ein Diagramm oder eine große Zahl.
- **Bausteine, die gut aussehen:** Karten mit 12 bis 16 px Eckenradius auf heller Fläche (`--surface`), große Zahl mit kurzer Beschriftung, zweispaltig Text und Bild, Zwischenfolie mit großer Ziffer, Zitat groß in Serifenschrift.
- **Bewegung:** höchstens ein sanftes Einblenden je Folie (`opacity` und `transform`, 300 ms), und `@media (prefers-reduced-motion: reduce)` schaltet es ab. Keine Dauerbewegung.
- **Drucken:** `@media print` mit einer Folie je Seite (`break-after: page`, `@page { size: 1280px 720px; margin: 0 }`), damit „Als PDF sichern“ gelingt.

**Berichte und Seiten**
- Textspalte höchstens `70ch` breit, zentriert; Zeilenabstand 1,55 bis 1,7; Überschriften klar größer als Text (Verhältnis etwa 1,25 je Stufe). Tabellen mit Kopfzeile und dezenter Zebrastreifung, Zahlen rechtsbündig.
- Kennzahlen als Kartenreihe oben, dann Belege. Diagramme als einfaches Inline-SVG oder reine CSS-Balken, mit Beschriftung und Einheit; keine Bibliothek aus dem Netz.
- Bedienung: Schaltflächen als echte `<button>`, sichtbarer Fokusrahmen, Ziele mindestens 44 px hoch, sinnvoll auf dem Handy (eine Spalte unter 700 px Breite).

**Typische Fehler, die du vermeidest:** Schrift zu klein · fünf Farben · jede Folie gleich · Text auf Bild ohne Abdunkelung · Emojis als Symbole (stattdessen kleines SVG) · Inhalte aus dem Netz laden · Überschrift als Rubrik statt Aussage · Karten um alles, auch um einzelne Sätze.

**Danach:** Sag der Person kurz, dass die Datei im Browser geöffnet wird (Doppelklick), mit Pfeiltasten bedient wird und über Drucken als PDF gesichert werden kann.
