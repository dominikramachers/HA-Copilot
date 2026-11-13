# API-Konto für Bilder und Sprache anlegen

HA Copilot kann Fotos, Kunst und Bilder mit Schrift von **Google (Gemini)** oder **OpenAI** erzeugen lassen. Dafür brauchst du bei mindestens einem der beiden ein eigenes **API-Konto mit Guthaben** und einen Schlüssel. Ein ChatGPT-Plus- oder Google-One-Abo bezahlt diese Schnittstelle nicht, beide rechnen sie getrennt ab. Ohne Schlüssel funktionieren weiterhin SVG-Zeichnungen (Diagramme, Pläne, Logos), die Claude selbst schreibt und die nichts kosten.

Der OpenAI-Schlüssel kann außerdem das **Sprechen mit der KI** übernehmen (Spracherkennung und Stimme); das steht im Abschnitt „OpenAI für die Sprache“ weiter unten. Und er kann **ChatGPT-Modelle im Chat** freischalten (ab 0.55.0): [ChatGPT (OpenAI) einrichten](chatgpt.md). Ein Konto, ein Schlüssel für alles ist möglich: Ist `chat.openai_api_key` leer, gilt `images.openai_api_key` auch für den Chat.

Stand: November 2026. Die Anbieter ändern Menüs und Bedingungen oft. Weichen die Namen unten ab, hilft die Hilfeseite des Anbieters; am Vorgehen ändert das selten etwas.

## Welcher Anbieter?

Für den Anfang reicht **Google**: günstiger, und es ist keine Ausweisprüfung nötig. HA Copilot nimmt bei `images.provider: auto` (Standard) Google, sobald ein Google-Schlüssel eingetragen ist, und OpenAI nur für Schrift im Bild oder höchste Qualität, wenn beide eingerichtet sind. **OpenAI** lohnt sich, wenn dir Schrift im Bild wichtig ist; dort kann zusätzlich eine Verifizierung der Organisation nötig sein (siehe unten). Du kannst beide einrichten.

## Google (Gemini)

Öffne [aistudio.google.com/api-keys](https://aistudio.google.com/api-keys) und melde dich mit einem Google-Konto an, das du dauerhaft selbst kontrollierst. Klicke auf **Create API key**. Google legt ein Projekt samt Schlüssel an, der in der Tabelle erscheint.

Dieser Schlüssel allein genügt nicht für Bilder. Die Bildmodelle haben im kostenlosen Zugang (Free Tier) kein Kontingent, Anfragen scheitern dann mit „429 / limit: 0“. Aktiviere deshalb die Abrechnung: Klicke in der Tabelle in der Spalte **Billing Tier** auf **Set up billing**. Wähle dein Land, bestätige die Bedingungen und hinterlege eine Zahlungsmethode. Je nach Konto musst du im Prepay-Modell vorab mindestens 5 $ (oder den Gegenwert) einzahlen.

Auf der Billing-Seite in AI Studio kannst du bei **Available credits** ein automatisches Aufladen einrichten (**Setup auto-reload**). Ohne Aufladen scheitern Anfragen mit „402“, sobald das Guthaben leer ist. Prepay-Guthaben verfällt nach zwölf Monaten und wird nicht erstattet. Unter **Spend** lässt sich ein monatliches Ausgabenlimit für das Projekt setzen, unter **Dashboard → Usage** siehst du die Nutzung.

Trage den Schlüssel im Add-on bei `images.google_api_key` ein.

Stolperstein: Manche melden, dass nach dem Aktivieren der Abrechnung noch eine Weile das Free-Tier-Limit galt. Warte ein paar Stunden und versuche es erneut, bevor du etwas änderst. Hilft das nicht, erzeuge den Schlüssel im abgerechneten Projekt neu.

## OpenAI

Gehe auf [platform.openai.com](https://platform.openai.com) und melde dich an. Die Schnittstelle hängt an einer **Organisation**, nicht an deinem ChatGPT-Abo, und wird getrennt abgerechnet.

Hinterlege unter **Settings → Organization → General** bzw. im Bereich **Billing** eine Zahlungsmethode. Erlaubt sind Debit- und Kreditkarten, keine Prepaid- oder virtuellen Karten. Dabei kann eine Vorautorisierung von 5 $ erscheinen, die keine Aufladung ist. Lade danach Guthaben auf (die Schnittstelle ist pay-per-use). Fang mit einem kleinen Betrag an: Guthaben verfällt nach einem Jahr und wird nicht erstattet. Neue Konten starten mit niedrigen Limits (Tier 1); bis das Guthaben freigeschaltet ist, kann es einige Stunden dauern.

Erzeuge den Schlüssel unter [platform.openai.com/api-keys](https://platform.openai.com/api-keys) mit **Create new secret key**. Er wird nur einmal angezeigt, kopiere ihn sofort. Trage ihn im Add-on bei `images.openai_api_key` ein.

**Welcher Schlüsseltyp?** Im Dialog fragt OpenAI bei **Owned by**, ob der Schlüssel dir (**You**) oder einem **Service account** gehört. Beides funktioniert für das Add-on gleich. Der **Service account** gehört einem Bot-Mitglied des Projekts statt deiner Person und läuft weiter, auch wenn jemand das Projekt verlässt; das passt für ein Add-on, das dauerhaft im Hintergrund läuft. Lege am besten ein eigenes **Projekt** (zum Beispiel „HA Copilot“) an und erzeuge den Schlüssel dort; in den Projekteinstellungen kannst du ein monatliches Ausgabenlimit setzen. Bei den Berechtigungen ist **All** am einfachsten. Wer es enger will (**Restricted**), braucht für die Sprache die Audio-Funktionen (Transkription und Sprachausgabe) und für Bilder die Bildfunktion; wie die Punkte im Dialog heißen, ändert OpenAI gelegentlich.

Stolperstein **Verifizierung der Organisation:** Für einige Bildmodelle verlangt OpenAI vorher eine Verifizierung unter **Settings → Organization → Verification**, mit amtlichem Ausweis und Selfie-Video über einen externen Dienst. Ob das für das eingestellte Modell gilt, hängt vom Modell ab; meldet die Schnittstelle einen entsprechenden Fehler, nennt die KI ihn dir wörtlich. Zahle deshalb zuerst wenig ein und prüfe, ob ein Bild entsteht, bevor du mehr auflädst.

## OpenAI für die Sprache (Spracherkennung und Stimme)

Derselbe OpenAI-Zugang kann auch das **Sprechen mit der KI** übernehmen: `gpt-4o-mini-transcribe` versteht, was du sagst, und `gpt-4o-mini-tts` liest die Antwort mit einer natürlicheren Stimme vor. Das ist optional. Kostenlos geht es lokal mit Whisper und Piper in Home Assistant oder mit der Spracherkennung des Browsers (siehe [Sprechen mit der KI](../copilot/DOCS.md#sprechen-mit-der-ki-ab-0520)); OpenAI lohnt sich, wenn dir die Erkennung zu langsam oder ungenau ist oder die Stimme zu schlecht klingt.

1. Lege das API-Konto und den Schlüssel an, wie im Abschnitt „OpenAI“ oben beschrieben. Für die Sprache reicht ein kleines Guthaben. Die Preise bestimmt OpenAI und sie ändern sich; die Kosten siehst du im Konto unter Usage.
2. Trage den Schlüssel im Add-on ein. Es gibt zwei Wege:
   - **Gemeinsam mit den Bildern:** bei `images.openai_api_key` (Gruppe „Bilder“). Der Schlüssel gilt dann auch für die Sprache.
   - **Nur für die Sprache:** bei `voice.openai_api_key` (Gruppe „Sprechen mit der KI“). Er hat Vorrang vor dem gemeinsamen. Nimm diesen Weg, wenn Sprache und Bilder getrennt abgerechnet werden sollen; lege dazu bei OpenAI am besten ein eigenes Projekt mit eigenem Schlüssel an.
3. Für die **Stimme** stelle zusätzlich `voice.output` auf `service`. Welche Stimme OpenAI nimmt, wählst du bei `voice.openai_voice` (Standard `nova`, weiblich; weiblich klingen meist `nova`, `shimmer`, `coral` und `sage`, männlich `echo`, `onyx` und `ash`). Zum Anhören gibt es auf [platform.openai.com/audio/playground](https://platform.openai.com/audio/playground) einen Spielplatz; eingestellt wird die Stimme nur im Add-on, nicht bei OpenAI. Bleibt es bei `device`, liest weiter das Gerät vor (kostenlos); die Erkennung läuft trotzdem über OpenAI, sobald ein Schlüssel eingetragen ist.
4. Speichere und starte das Add-on neu. Die Zeile „Mit der KI sprechen“ in der **Einrichtungsprüfung** (Einstellungen) nennt danach die Spracherkennung „OpenAI“ und die Stimme.
5. Sprich einen Satz. In einem Protokoll-Eintrag des Add-ons steht je Runde, wie lange Erkennung, KI und Stimme gebraucht haben.

**Nachträglich eintragen:** Du kannst den Schlüssel auch später ergänzen, wenn Whisper und Piper schon laufen. Nach dem Neustart des Add-ons nimmt das Sprechen automatisch OpenAI, in Home Assistant musst du nichts umstellen. Die Stimme wechselt nur, wenn `voice.output` auf `service` steht. Möchtest du zu Whisper und Piper zurück, lösche den Schlüssel (oder nimm ihn aus der Gruppe „Sprechen mit der KI“; steht derselbe Schlüssel bei `images.openai_api_key`, gilt er auch dort für die Sprache) und starte neu.

Wichtig: Bei OpenAI gehen deine **Aufnahmen** an OpenAI (bei der Stimme auch die Antworttexte). Wer das nicht möchte, nimmt Whisper und Piper lokal. Ein ChatGPT-Plus-Abo bezahlt auch das nicht. Schneller wird vor allem die Erkennung und die Stimme; die Zeit, die die KI zum Antworten braucht, ändert sich dadurch nicht.

## Im Add-on eintragen und prüfen

1. Schlüssel bei `images.google_api_key` und/oder `images.openai_api_key` eintragen, speichern, Add-on neu starten. Die Schlüssel stehen nur in der Konfiguration, nie im Chat.
2. In den Einstellungen die **Einrichtungsprüfung** öffnen. Die Zeile „Bilder erzeugen“ zeigt, welche Anbieter bereit sind.
3. Bitte HA Copilot im Chat um ein Foto-Motiv („Male mir ein gemütliches Wohnzimmer bei Sonnenuntergang“) und danach um eine Änderung („anderer Himmel“). Die KI nennt in einem Satz, welchen Anbieter sie genommen hat; die Änderung entsteht als neue Fassung („Version 2“).
4. Meldet ein Anbieter „Modell unbekannt“, hat der Anbieter das Modell umbenannt. Die Namen sind fest im Add-on hinterlegt; ein Add-on-Update bringt die neuen. Melde es gern als Fehler.

## Kosten im Griff behalten

- Das Add-on führt die **Anzahl** der Bilder im Monat für alle Personen zusammen (`images.limit_month`, Standard 30, 0 = unbegrenzt). Erst darüber fragt der Chat vor jedem weiteren Bild nach. Preise kennt das Add-on nicht.
- Setze zusätzlich beim Anbieter ein **Ausgabenlimit** (Google: *Spend*, OpenAI: Limits bzw. Billing) und lade lieber kleine Beträge auf, statt automatisches Aufladen mit hohem Betrag zu nutzen.
- Die Kosten siehst du im jeweiligen Konto. Jede neue Fassung eines Bildes ist ein weiteres bezahltes Bild.
- ChatGPT im Chat zählt das Add-on in Token im Monat für alle Personen zusammen (`chat.openai_limit_month`, Standard 3000 = 3 Millionen, 0 = unbegrenzt); die Kosten stehen im selben OpenAI-Konto unter Usage ([Details](chatgpt.md#token-limit-für-alle)).
- Die Sprache zählt das Add-on nicht mit; sie läuft bei OpenAI über denselben Schlüssel (oder `voice.openai_api_key`) und erscheint im OpenAI-Konto unter Usage.

Einzelheiten zu Limit, Rückfragen und Datenschutz: [Bilder in der Referenz](../copilot/DOCS.md#bilder-ab-0280). Zurück zur [Übersicht](README.md).
