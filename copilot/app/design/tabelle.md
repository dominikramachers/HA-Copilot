# Tabellen (Excel)

Eine Tabelle ist eine Arbeitsfläche: Man soll Zahlen vergleichen, sortieren, filtern und nachrechnen können.

**Aufbau**
- Erste Zeile = Kopfzeile mit kurzen, eindeutigen Spaltennamen und der Einheit („Betrag (€)“, „Datum“). Sie wird farbig gesetzt, fixiert und bekommt einen Filter.
- Eine Zeile = ein Datensatz, eine Spalte = ein Merkmal. Keine leeren Zeilen oder Spalten mitten in den Daten, keine verbundenen Zellen, keine Zwischensummen mitten in der Liste.
- Gehört nicht zusammen, kommt auf ein eigenes Blatt (`sheets`), mit sprechendem Namen (höchstens 31 Zeichen). Reihenfolge: Übersicht oder Eingaben zuerst, Rechnungen danach, Rohdaten zuletzt.

**Zahlen und Formeln**
- Zahlen als Zahlen schreiben (`1234.5`), damit man damit rechnen kann; „12,50 €“ und „18 %“ als Text erkennt die Vorlage selbst und macht daraus Zahlen mit Euro- bzw. Prozentformat. Datum als `2026-11-03` (wird `03.11.2026`). Einheiten gehören in die Kopfzeile.
- Rechne mit Formeln statt mit festen Ergebnissen, damit sich bei Änderungen alles mitändert: `"=SUM(B2:B20)"`, `"=B2*C2"`. Englische Funktionsnamen, Komma als Trenner.
- Eingaben und Annahmen (Steuersatz, Preis, Zielwert) stehen einmal in einer eigenen Zelle oder auf einem Blatt „Annahmen“, und die Formeln verweisen darauf. Keine Zahl in einer Formel verstecken.
- Summenzeile ans Ende der Daten, nicht in die Mitte: Im Blatt `"totals": true` (alle Zahlenspalten) oder `"totals": ["Menge","Betrag"]`; sie entsteht mit SUM-Formeln, fett und mit Linie (Beschriftung „Summe“, änderbar mit `"totals_label"`). Schreibe sie nicht selbst als Zeile.

**Lesbarkeit**
- Spaltenbreiten und Zebrastreifen übernimmt die Vorlage. Halte Texte pro Zelle kurz (höchstens etwa 60 Zeichen); lange Texte gehören in ein Textdokument.
- Sortiere sinnvoll vor (neueste oder größte zuerst, je nach Zweck).
- Keine Farbcodes als Bedeutungsträger. Wenn etwas auffallen soll, schreib eine eigene Spalte „Status“ mit Wort („offen“, „erledigt“).

**Formate, Hervorhebung, Druck (im Blatt-Objekt)**
- `"formats": {"Betrag": "euro", "Anteil": "prozent", "Datum": "datum"}`: Spalte (Kopfname oder Buchstabe) → `euro`, `prozent` (Wert 0,18 = 18 %), `zahl`, `ganzzahl`, `datum` oder ein Excel-Format wie `0.0 "kg"`.
- `"rules": [{"column":"Betrag","type":"gt","value":1000,"style":"bad"}, {"column":"Anteil","type":"databar"}]`: bedingte Formatierung. `type`: `gt`, `lt`, `gte`, `lte`, `eq`, `ne`, `between` (mit `value2`), `databar` (Balken in der Zelle), `colorscale` (Farbverlauf). `style`: `good` (grün), `bad` (rot), `warn` (gelb). Farbe nie allein als Bedeutung: daneben bleibt die Statusspalte.
- Druck ist eingestellt: A4, auf Seitenbreite, Kopfzeile auf jeder Seite, Querformat ab 7 Spalten, Seitenzahl unten.

**Für Apple Numbers:** `target: numbers` setzt die Mac-Schrift. Numbers öffnet `.xlsx`, kennt aber keine Datenüberprüfung, Pivot-Slicer und Makros; Formeln, Formate, bedingte Formatierung und Säulen-, Balken-, Linien- und Kreisdiagramme kommen an. Nicht in Numbers selbst geprüft; sag das.

**Diagramme:** Im Blatt-Objekt `"charts":[{"type":"column","title":"Umsatz je Quartal","series":["2025","2026"]}]`. Rubriken = erste Spalte, `series` = Namen von Spalten der Kopfzeile (ohne Angabe alle Spalten mit Zahlen); `type` column, bar, line oder pie. Das Diagramm erscheint rechts neben den Daten als echtes Excel-Diagramm. Höchstens 4 je Blatt.

**Nicht möglich mit `file_create`:** Dropdown-Listen, Pivot-Tabellen, Makros und Bilder in Zellen. Sag das ehrlich, wenn die Person es erwartet, und beschreibe, wie sie es in Excel selbst ergänzt.
