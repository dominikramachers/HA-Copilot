# ChatGPT (OpenAI) neben Claude einrichten

HA Copilot kann neben Claude auch **ChatGPT-Modelle von OpenAI** nutzen, und zwar mit denselben Fähigkeiten: Home Assistant steuern (mit denselben Rechtestufen und Rückfragen), Gedächtnis, Projektwissen und Skills, Dateien erzeugen und bearbeiten, Bilder, GitHub, Konnektoren und Plugins, Websuche und geplante Aufgaben. Die Rechte setzt der Server durch, nicht das Modell; deshalb gelten sie für ChatGPT genauso wie für Claude.

Das ist **optional und standardmäßig aus**. Ohne Einrichtung ändert sich nichts.

Stand: November 2026. OpenAI ändert Modellnamen, Preise und Bedingungen oft. Was unten über OpenAI steht, ist der Stand der Hilfeseiten beim Schreiben; prüfe es im Konto nach.

## Was du wissen solltest, bevor du es einschaltest

- **Daten gehen an OpenAI.** In einem ChatGPT-Chat gehen deine Nachrichten, Anhänge, die Ergebnisse der Werkzeuge (zum Beispiel Zustände aus Home Assistant, die die KI abfragt) und die Dateien, die sie liest, an OpenAI. In einem Claude-Chat geht nichts an OpenAI, in einem ChatGPT-Chat nichts an Claude. Das gilt auch für den Chat-Titel und die Zusammenfassung langer Chats: Sie entstehen bei dem Anbieter, bei dem der Chat läuft. Die Oberfläche weist im Modellmenü und im Chat darauf hin.
- **Das Sprechen mit der KI bleibt bei Claude Haiku**, auch wenn ChatGPT eingeschaltet ist. Ein Chat, den du per Sprache führst, geht also an Claude.
- **Ein ChatGPT-Abo reicht nicht.** Die Schnittstelle von OpenAI ist ein eigenes **API-Konto mit eigenem Guthaben**, getrennt vom ChatGPT-Abo. Abgerechnet wird nach Verbrauch.
- **Der Zähler gehört dem Add-on, die Rechnung OpenAI.** Das Add-on zählt Token, kennt aber keine Preise. Setze zusätzlich bei OpenAI ein Ausgabenlimit.

## Einrichten

1. Lege bei [platform.openai.com](https://platform.openai.com) ein Konto an und hinterlege unter **Billing** eine Zahlungsmethode und etwas Guthaben. Die einzelnen Schritte, Stolpersteine und die Verifizierung der Organisation stehen im Abschnitt „OpenAI“ von [API-Konto für Bilder und Sprache](bilder-konten.md#openai).
2. Erzeuge unter [platform.openai.com/api-keys](https://platform.openai.com/api-keys) einen Schlüssel (**Create new secret key**, wird nur einmal angezeigt).
3. Öffne die Konfiguration des Add-ons, Gruppe **Chat (Claude & OpenAI)**, und trage ein:

```yaml
chat:
  openai_enabled: true
  openai_api_key: sk-...             # Schlüssel von platform.openai.com
  openai_key_expires: "2026-12-31"   # optional: Erinnerung vor dem Ablauf
```

4. Speichern und das Add-on **neu starten**. Den Schlüssel gibst du nur dort ein, nie im Chat, in Repositories oder Screenshots.
5. Öffne in den Einstellungen die **Einrichtungsprüfung**. Die Zeile „ChatGPT (OpenAI)“ zeigt, ob der Schalter an ist, ein Schlüssel vorhanden ist und welche Modelle im Menü stehen. Ein Schlüssel wird nie angezeigt, nur ob er gesetzt ist.
6. Im Chat steht jetzt im Modellmenü (Regler-Symbol rechts unter dem Eingabefeld) neben den Claude-Modellen die Gruppe **ChatGPT**. Wähle ein Modell und schreibe etwas. Ein kleiner Hinweis erinnert daran, dass dieser Chat zu OpenAI geht.

Ist `chat.openai_api_key` leer, nutzt das Add-on den Schlüssel aus der Gruppe **Bilder** (`images.openai_api_key`), wenn dort einer steht. Dann braucht ihr nur ein OpenAI-Konto für Bilder, Sprache und Chat.

## Modelle

Standardmäßig stehen drei Modelle zur Wahl: `gpt-5.6-terra`, `gpt-5.6-luna` und `gpt-5.6-sol`. Welche das sind und wie sie heißen, lässt sich einstellen, weil OpenAI Namen ändert:

```yaml
chat:
  openai_models: "gpt-5.6-terra, gpt-5.6-luna, gpt-5.6-sol"   # höchstens 6, durch Komma getrennt
```

Die Namen müssen wie bei OpenAI heißen (`gpt-…`, `chatgpt-…` oder `o1`, `o3` …). Anderes (zum Beispiel ein Claude-Name) wird abgelehnt; die Fehlermeldung nennt dann den Eintrag und die Option. Der erste Eintrag steht in der Liste oben. Eine Anfrage an ein Modell, das dein Konto nicht kennt, scheitert mit der Meldung von OpenAI; die KI nennt sie dir im Chat, und du wechselst das Modell oder trägst in `openai_models` ein passendes ein.

## Modell wählen: Auto, Standardmodell und Chat

Es gibt drei Stellen, und die jeweils engste gewinnt:

1. **Im Chat** (Modellmenü): gilt für diesen Chat.
2. **Standardmodell in deinen Einstellungen** (Einstellungen → Allgemein): gilt für jeden neuen Chat, den du anfängst. Zur Wahl stehen **Auto**, die Claude-Modelle (Sonnet, Opus, Haiku) und, wenn eingeschaltet, die ChatGPT-Modelle. Das ist eine persönliche Einstellung; jede Person stellt ihr eigenes ein.
3. **Auto** heißt: das Modell, das der Administrator im Add-on eingestellt hat (`chat.model`, Standard `claude-sonnet-5-5`). Im Menü steht **Auto** immer ganz oben.

**Mitten im Chat wechseln (ab 0.55.1):** Das geht jederzeit, auch zwischen Claude und ChatGPT. Das neue Modell bekommt den bisherigen Verlauf (Texte, bei langen Chats die Zusammenfassung) und erfährt, dass der Chat vorher mit einem anderen Modell lief. Gedächtnis, Projektwissen, Skills, Konnektoren, Dateien des Chats und die Rückfrage-Freigaben gelten weiter. Nicht übernommen werden Ergebnisse früherer Werkzeugaufrufe, die Denkschritte und früher hochgeladene Anhänge; das Modell liest bei Bedarf noch einmal nach. **Datenschutz beim Wechsel:** Wechselst du von Claude zu ChatGPT, geht der bisherige Verlauf des Chats ab dann auch an OpenAI (die Oberfläche sagt es dir); beim Wechsel zurück geht er an Claude, bei OpenAI bleibt, was schon gesendet wurde.

Eine Einstellung je Projekt gibt es bewusst nicht. Ein Chat, in dem du selbst ein Modell gewählt hast, behält es. Ein Chat ohne eigene Wahl folgt deinem Standardmodell. Wird ein Modell später aus `openai_models` entfernt oder ChatGPT ausgeschaltet, gilt das Standardmodell der Person wieder als **Auto**.

## Token-Limit für alle

`chat.openai_limit_month` begrenzt, wie viele Token (Eingabe plus Ausgabe) alle Personen zusammen im Kalendermonat mit ChatGPT-Modellen verbrauchen dürfen (bis 0.57 galt es je Person). Es gibt ein API-Konto bei OpenAI, deshalb auch ein gemeinsames Limit und für alle dieselbe Anzeige. Angegeben wird es **in Tausend**: Der Standard `3000` sind 3 Millionen, `0` heißt kein Limit.

- Wird das Limit erreicht, **fragt der Chat vor jeder weiteren Antwort nach** (Zulassen oder Ablehnen), genau wie bei den Bildern. Es sperrt nichts von allein.
- In **geplanten Aufgaben** kann niemand antworten; dort wird die Aufgabe mit einer Meldung abgelehnt, sobald das Limit erreicht ist.
- Gezählt wird, was OpenAI als Verbrauch zurückmeldet. Titel und Zusammenfassungen zählen nicht mit. Der Zähler beginnt jeden Monat neu und steht unter **Einstellungen → Nutzung** („ChatGPT in diesem Monat“); die Seite aktualisiert sich selbst, jede Person sieht dieselbe Zahl.
- Das Limit zählt Token, keine Euro. Wie teuer ein Token ist, hängt vom Modell ab; die Rechnung steht in deinem OpenAI-Konto unter **Usage**.

## Kosten klein halten

- Setze bei OpenAI ein monatliches Ausgabenlimit und lade nur kleine Beträge auf.
- Lange Chats werden bei jeder Nachricht neu gesendet; das Add-on fasst sie ab etwa 80 000 Zeichen zusammen (bei dem Anbieter des Chats). Ein neuer Chat für ein neues Thema spart Token.
- Nutze für Routine (Licht, Fragen zu Geräten) das kleinste Modell der Liste, für längere Arbeit ein größeres.
- OpenAI bietet für einige Konten ein Programm an, bei dem man Daten teilt und dafür kostenlose Token bekommt. Ob dein Konto dabei ist, ob es für diese Modelle gilt und ob Werkzeugaufrufe ausgenommen sind, ändert sich und ist hier **nicht geprüft**; schau in den Einstellungen deiner OpenAI-Organisation unter **Data controls** nach. Beachte: Wer daran teilnimmt, gibt die Inhalte seiner Chats an OpenAI zur Verbesserung der Modelle frei. Für ein Haus, in dem mehrere Personen schreiben, ist das meist nicht gewollt.

## Was anders ist als bei Claude

- Die **Websuche** macht bei ChatGPT das Werkzeug von OpenAI (läuft bei OpenAI), bei Claude das von Anthropic. Die Schalter (`web_access`, Menü im Chat) gelten für beide, und auch hier fragt jede Änderung nach, sobald die KI etwas aus dem Web gelesen hat.
- Das Add-on speichert bei OpenAI nichts: Anfragen gehen mit `store: false`, der Verlauf liegt wie bei Claude in der eigenen Datenbank und wird bei jeder Nachricht neu mitgeschickt. Ob OpenAI Anfragen kurz aus Gründen des Missbrauchsschutzes aufbewahrt, regeln die Bedingungen von OpenAI.
- Die **Nutzungsbalken des Claude-Abos** (Sitzung, Woche) gelten nur für Claude. Für ChatGPT zeigt die Seite den Monatsverbrauch an Token.
- Bei einem Fehler von OpenAI (Schlüssel falsch, kein Guthaben, zu viele Anfragen, Modell unbekannt) zeigt der Chat eine verständliche Meldung und bleibt benutzbar.

## Probelauf

Prüfe nach dem Einrichten der Reihe nach:

1. Neuer Chat mit einem ChatGPT-Modell: „Sag Hallo und nenne das Datum.“ Die Antwort kommt als Strom.
2. „Welche Lichter sind gerade an?“ (Stufe mindestens **lesen**). Die Werkzeugzeile zeigt die Abfrage.
3. „Merke dir, dass ich … mag.“ Gedächtnis und Rückfrage im Chat.
4. Ein Bild anhängen und danach fragen; eine Datei erzeugen lassen.
5. „Recherchiere kurz, wie das Wetter morgen wird.“ Die Websuche zeigt Schritte und Quellen.
6. In den Einstellungen das **Standardmodell** auf ein ChatGPT-Modell stellen, neuen Chat öffnen: Das Modell ist vorgewählt. Zurück auf **Auto**.
7. Unter **Nutzung** steigt der ChatGPT-Zähler.

## Nicht geprüft

Entwickelt und getestet wurde gegen eine Nachbildung der OpenAI-Schnittstelle (die Entwicklungsumgebung erreicht `api.openai.com` nicht). **Nicht an der echten Schnittstelle geprüft** sind: die Modellnamen und ob dein Konto sie nutzen darf, der Verlauf mit Werkzeugaufrufen über mehrere Runden bei `store: false`, die Ereignisse der Websuche, das Verhalten bei Verifizierung der Organisation sowie die Datenfreigabe-Programme von OpenAI. Zeigt sich im Chat etwas Merkwürdiges, steht die genaue Antwort von OpenAI im Protokoll des Add-ons.

Zurück zur [Übersicht](README.md).
