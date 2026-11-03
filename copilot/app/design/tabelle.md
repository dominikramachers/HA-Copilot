# Tabellen (Excel)

Eine Tabelle ist eine Arbeitsfläche: Man soll Zahlen vergleichen, sortieren, filtern und nachrechnen können.

**Aufbau**
- Erste Zeile = Kopfzeile mit kurzen, eindeutigen Spaltennamen und der Einheit („Betrag (€)“, „Datum“). Sie wird farbig gesetzt, fixiert und bekommt einen Filter.
- Eine Zeile = ein Datensatz, eine Spalte = ein Merkmal. Keine leeren Zeilen oder Spalten mitten in den Daten, keine verbundenen Zellen, keine Zwischensummen mitten in der Liste.
- Gehört nicht zusammen, kommt auf ein eigenes Blatt (`sheets`), mit sprechendem Namen (höchstens 31 Zeichen). Reihenfolge: Übersicht oder Eingaben zuerst, Rechnungen danach, Rohdaten zuletzt.

**Zahlen und Formeln**
- Zahlen als Zahlen schreiben (`1234.5`, nicht „1.234,50 €“ als Text), damit man damit rechnen kann. Datum als `2026-11-03`. Einheiten gehören in die Kopfzeile.
- Rechne mit Formeln statt mit festen Ergebnissen, damit sich bei Änderungen alles mitändert: `"=SUM(B2:B20)"`, `"=B2*C2"`. Englische Funktionsnamen, Komma als Trenner.
- Eingaben und Annahmen (Steuersatz, Preis, Zielwert) stehen einmal in einer eigenen Zelle oder auf einem Blatt „Annahmen“, und die Formeln verweisen darauf. Keine Zahl in einer Formel verstecken.
- Summenzeile ans Ende der Daten, nicht in die Mitte. Prüfe, dass jede Formel auf die richtigen Zeilen zeigt.

**Lesbarkeit**
- Spaltenbreiten und Zebrastreifen übernimmt die Vorlage. Halte Texte pro Zelle kurz (höchstens etwa 60 Zeichen); lange Texte gehören in ein Textdokument.
- Sortiere sinnvoll vor (neueste oder größte zuerst, je nach Zweck).
- Keine Farbcodes als Bedeutungsträger. Wenn etwas auffallen soll, schreib eine eigene Spalte „Status“ mit Wort („offen“, „erledigt“).

**Diagramme:** Im Blatt-Objekt `"charts":[{"type":"column","title":"Umsatz je Quartal","series":["2025","2026"]}]`. Rubriken = erste Spalte, `series` = Namen von Spalten der Kopfzeile (ohne Angabe alle Spalten mit Zahlen); `type` column, bar, line oder pie. Das Diagramm erscheint rechts neben den Daten als echtes Excel-Diagramm. Höchstens 4 je Blatt.

**Nicht möglich mit `file_create`:** bedingte Formatierung, Dropdown-Listen, Pivot-Tabellen, Makros und Bilder in Zellen. Sag das ehrlich, wenn die Person es erwartet, und beschreibe, wie sie es in Excel selbst ergänzt.
