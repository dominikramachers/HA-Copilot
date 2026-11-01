# API-Konto für Bilder anlegen

HA Copilot kann Fotos, Kunst und Bilder mit Schrift von **Google (Gemini)** oder **OpenAI** erzeugen lassen. Dafür brauchst du bei mindestens einem der beiden ein eigenes **API-Konto mit Guthaben** und einen Schlüssel. Ein ChatGPT-Plus- oder Google-One-Abo bezahlt diese Schnittstelle nicht, beide rechnen sie getrennt ab. Ohne Schlüssel funktionieren weiterhin SVG-Zeichnungen (Diagramme, Pläne, Logos), die Claude selbst schreibt und die nichts kosten.

Stand: November 2026. Die Anbieter ändern Menüs und Bedingungen oft. Weichen die Namen unten ab, hilft die Hilfeseite des Anbieters; am Vorgehen ändert das selten etwas.

## Welcher Anbieter?

Für den Anfang reicht **Google**: günstiger, und es ist keine Ausweisprüfung nötig. HA Copilot nimmt bei `image_provider: auto` (Standard) Google, sobald ein Google-Schlüssel eingetragen ist, und OpenAI nur für Schrift im Bild oder höchste Qualität, wenn beide eingerichtet sind. **OpenAI** lohnt sich, wenn dir Schrift im Bild wichtig ist; dort kann zusätzlich eine Verifizierung der Organisation nötig sein (siehe unten). Du kannst beide einrichten.

## Google (Gemini)

Öffne [aistudio.google.com/api-keys](https://aistudio.google.com/api-keys) und melde dich mit einem Google-Konto an, das du dauerhaft selbst kontrollierst. Klicke auf **Create API key**. Google legt ein Projekt samt Schlüssel an, der in der Tabelle erscheint.

Dieser Schlüssel allein genügt nicht für Bilder. Die Bildmodelle haben im kostenlosen Zugang (Free Tier) kein Kontingent, Anfragen scheitern dann mit „429 / limit: 0“. Aktiviere deshalb die Abrechnung: Klicke in der Tabelle in der Spalte **Billing Tier** auf **Set up billing**. Wähle dein Land, bestätige die Bedingungen und hinterlege eine Zahlungsmethode. Je nach Konto musst du im Prepay-Modell vorab mindestens 5 $ (oder den Gegenwert) einzahlen.

Auf der Billing-Seite in AI Studio kannst du bei **Available credits** ein automatisches Aufladen einrichten (**Setup auto-reload**). Ohne Aufladen scheitern Anfragen mit „402“, sobald das Guthaben leer ist. Prepay-Guthaben verfällt nach zwölf Monaten und wird nicht erstattet. Unter **Spend** lässt sich ein monatliches Ausgabenlimit für das Projekt setzen, unter **Dashboard → Usage** siehst du die Nutzung.

Trage den Schlüssel im Add-on bei `google_api_key` ein.

Stolperstein: Manche melden, dass nach dem Aktivieren der Abrechnung noch eine Weile das Free-Tier-Limit galt. Warte ein paar Stunden und versuche es erneut, bevor du etwas änderst. Hilft das nicht, erzeuge den Schlüssel im abgerechneten Projekt neu.

## OpenAI

Gehe auf [platform.openai.com](https://platform.openai.com) und melde dich an. Die Schnittstelle hängt an einer **Organisation**, nicht an deinem ChatGPT-Abo, und wird getrennt abgerechnet.

Hinterlege unter **Settings → Organization → General** bzw. im Bereich **Billing** eine Zahlungsmethode. Erlaubt sind Debit- und Kreditkarten, keine Prepaid- oder virtuellen Karten. Dabei kann eine Vorautorisierung von 5 $ erscheinen, die keine Aufladung ist. Lade danach Guthaben auf (die Schnittstelle ist pay-per-use). Fang mit einem kleinen Betrag an: Guthaben verfällt nach einem Jahr und wird nicht erstattet. Neue Konten starten mit niedrigen Limits (Tier 1); bis das Guthaben freigeschaltet ist, kann es einige Stunden dauern.

Erzeuge den Schlüssel unter [platform.openai.com/api-keys](https://platform.openai.com/api-keys) mit **Create new secret key**. Er wird nur einmal angezeigt, kopiere ihn sofort. Trage ihn im Add-on bei `openai_api_key` ein.

Stolperstein **Verifizierung der Organisation:** Für einige Bildmodelle verlangt OpenAI vorher eine Verifizierung unter **Settings → Organization → Verification**, mit amtlichem Ausweis und Selfie-Video über einen externen Dienst. Ob das für das eingestellte Modell gilt, hängt vom Modell ab; meldet die Schnittstelle einen entsprechenden Fehler, nennt die KI ihn dir wörtlich. Zahle deshalb zuerst wenig ein und prüfe, ob ein Bild entsteht, bevor du mehr auflädst.

## Im Add-on eintragen und prüfen

1. Schlüssel bei `google_api_key` und/oder `openai_api_key` eintragen, speichern, Add-on neu starten. Die Schlüssel stehen nur in der Konfiguration, nie im Chat.
2. Im Konto-Menü die **Einrichtungsprüfung** öffnen. Die Zeile „Bilder erzeugen“ zeigt, welche Anbieter bereit sind.
3. Bitte HA Copilot im Chat um ein Foto-Motiv („Male mir ein gemütliches Wohnzimmer bei Sonnenuntergang“) und danach um eine Änderung („anderer Himmel“). Die KI nennt in einem Satz, welchen Anbieter sie genommen hat; die Änderung entsteht als neue Fassung („Version 2“).
4. Meldet ein Anbieter „Modell unbekannt“, trage den aktuellen Namen aus dessen Dokumentation bei `image_model_google` bzw. `image_model_openai` ein. Die Standardnamen können veraltet sein, weil die Anbieter Modelle oft umbenennen.

## Kosten im Griff behalten

- Das Add-on führt die **Anzahl** der Bilder je Person und Monat (`image_limit_month`, Standard 30, 0 = unbegrenzt). Erst darüber fragt der Chat vor jedem weiteren Bild nach. Preise kennt das Add-on nicht.
- Setze zusätzlich beim Anbieter ein **Ausgabenlimit** (Google: *Spend*, OpenAI: Limits bzw. Billing) und lade lieber kleine Beträge auf, statt automatisches Aufladen mit hohem Betrag zu nutzen.
- Die Kosten siehst du im jeweiligen Konto. Jede neue Fassung eines Bildes ist ein weiteres bezahltes Bild.

Einzelheiten zu Limit, Rückfragen und Datenschutz: [Bilder in der Referenz](../copilot/DOCS.md#bilder-ab-0280). Zurück zur [Übersicht](README.md).
