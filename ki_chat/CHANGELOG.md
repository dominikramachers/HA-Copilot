# Änderungen

## 0.26.3
- Umbenannt: Das Add-on heißt jetzt **HA Copilot** (Name im Add-on-Store, Eintrag in der Home-Assistant-Seitenleiste, Standard von `app_name`, Anmeldeseite, Export, Dokumentation, `repository.yaml`). Der technische Name (`slug: ki_chat`), der Ordner `ki_chat`, Datenbank- und Export-Dateinamen bleiben unverändert, damit Updates und der Umzug der Daten nicht berührt werden.
- Eine eigene Eintragung bei `app_name` bleibt wie sie ist; nur wer nichts eingetragen hatte, sieht jetzt „HA Copilot“ statt „KI Chat“.

## 0.26.2
- `config.yaml`: Vier Einträge entfernt, die nur den Standardwert von Home Assistant wiederholten (`startup`, `boot`, `init`, `ingress_port`), damit die Add-on-Prüfung der CI grün ist. Das Verhalten bleibt gleich; keine neuen Optionen.

## 0.26.1
- Die Repository-Adresse ist eingetragen (Startseite des Add-ons in Home Assistant, `repository.yaml`, README, CI-Plakette). Keine Änderung am Verhalten, keine neuen Optionen.

## 0.26.0
- Neu: **Englische Oberfläche.** Neue Option `language` (`de` oder `en`), Standard und Vorgabe in den App-Einstellungen von Home Assistant ist **`de`**. Mit `en` erscheinen Oberfläche, Anmeldeseite, Meldungen des Add-ons, Einrichtungsprüfung, Export, Benachrichtigungen und Beschreibungen geplanter Aufgaben auf Englisch; die KI antwortet standardmäßig auf Englisch (wer in einer anderen Sprache schreibt, bekommt die Antwort weiterhin in dieser Sprache). Die Sprache gilt für das ganze Add-on, nicht je Person.
- Bewusst nicht übersetzt (nur die KI, das Protokoll oder die Konfiguration sehen es): Werkzeugbeschreibungen und -antworten, Anweisungen an die KI, Protokollzeilen, Fehlermeldungen der Konfiguration, die gespeicherten Themen des Smarthome-Überblicks („HA · …“), bereits gespeicherte Chat-Inhalte und Titel sowie eigene Texte aus der Personalisierung (`app_name`, `login_text`, `login_placeholder`). Die Texte der Konfigurationsseite folgen der Sprache von Home Assistant (`translations/de.yaml`, `en.yaml`).
- Technik: Die deutschen Texte im Quellcode sind die Schlüssel; Englisch kommt aus `app/locales/en.json` (Server, Seiten) und `app/locales/en-ui.json` (Browser). Fehlt eine Übersetzung, erscheint der deutsche Text. Das Wort zur Bestätigung beim Löschen aller Chats ist in der englischen Oberfläche `DELETE`; beide Wörter (`LÖSCHEN`, `DELETE`) werden in jeder Sprache angenommen. „Neuer Chat“ und „New chat“ gelten beide als noch nicht benannt (automatischer Kurztitel).
- Neue Tests (`test_i18n.py`): jeder Text im Browser-Code, im Server und auf den Seiten hat eine englische Entsprechung (und umgekehrt keine ungenutzten Einträge), Platzhalter bleiben erhalten, kein deutscher Text ohne Übersetzungsaufruf, englische Seiten und Meldungen, Standard bleibt Deutsch.
- Korrigiert: Eine Datenbankabfrage beim Start war versehentlich als Text zur Übersetzung markiert (ohne Folgen, jetzt entfernt).
- Neue Option ist optional; bestehende Konfigurationen bleiben unverändert (ohne Eintrag gilt `de`).

## 0.25.0
- Neu: **Einrichtungsprüfung** (Konto-Menü unten links → „Einrichtungsprüfung“, nur über Home Assistant). Sie zeigt, was eingerichtet ist und was fehlt, gegliedert in „Nötig“, „Empfohlen“ und „Optional“. Zu jedem offenen Punkt stehen die genauen Schritte, mit den Namen der Optionen und dem Weg dorthin (Einstellungen → Apps → KI Chat → Konfiguration). „Erneut prüfen“ liest alles noch einmal.
- Geprüft werden: Zugang zu Claude (Testmodus oder echt, Abo-Token oder API-Schlüssel, Hinweis bei einem Abo-Token für mehrere Personen), Datenbank, Verbindung zu Home Assistant (mit Antwort von Home Assistant), nicht gefundene Home-Assistant-Benutzer, Zugriff der KI auf Home Assistant, GitHub (Token vorhanden, Stufe, Antwort von GitHub zum Token), Zugang über eine eigene Adresse (mit Hostname für den Tunnel und der Adresse für `public_trusted_proxies`), Benachrichtigungen aufs Handy (Dienst existiert in Home Assistant) und Erinnerungen an Ablaufdaten.
- Solange der Chat im Testmodus läuft (noch kein Claude-Zugang), erscheint oben ein Hinweis mit dem Knopf „Schritte anzeigen“.
- Es werden nie Geheimnisse angezeigt, nur ob sie gesetzt sind. Über die Domain-Seite gibt es die Prüfung nicht (geändert wird in Home Assistant).
- Keine neuen Optionen; bestehende Konfigurationen bleiben unverändert.

## 0.24.0
- Sicherheitsprüfung des gesamten Codes (Anmeldung, Sitzungen, Ingress-Vertrauen, Web-Abruf, Dateien und Archive, Oberfläche, Datenbankabfragen, Werkzeuge für Home Assistant und GitHub, Umgang mit Zugangsdaten, Abhängigkeiten). Ergebnis und bewusst akzeptierte Restrisiken stehen in der Dokumentation unter „Sicherheitsprüfung“.
- Korrigiert: Die großen Upload-Grenzen (Senden mit Dateien, Vorschau, Projektwissen) galten schon, wenn nur ein Cookie mit dem Namen der Sitzung oder ein `X-Remote-User-Id`-Header mitgeschickt wurde. Jetzt gelten sie nur noch für Anfragen mit gültiger Sitzung (Domain) bzw. vom Home-Assistant-Proxy mit bekannter Person (Ingress). Vorher konnte jemand ohne Anmeldung die Domain-Seite mit sehr großen Anfragen belasten.
- Korrigiert: Hinter Cloudflare wird `CF-Connecting-IP` nur noch übernommen, wenn es eine echte Adresse ist. Sonst gilt die Adresse der Gegenstelle (kein Müll in Protokoll und Ratenbegrenzung).
- Protokoll: Fehlercodes von Microsoft/Home Assistant stehen in Anführungszeichen im Protokoll (kein Einschleusen von Zeilen).
- Zusätzlich abgesichert: Der Claude-Prozess bekommt den Zugangstoken von Home Assistant (`SUPERVISOR_TOKEN`) nicht mehr in seine Umgebung. Neue Antwort-Header: `Permissions-Policy` (überall) sowie `Cross-Origin-Opener-Policy` und `Cross-Origin-Resource-Policy` auf der Domain-Seite.
- Neue Tests (`test_security.py`). Keine neuen Optionen; bestehende Konfigurationen bleiben unverändert.

## 0.23.0
- Vorbereitung der Veröffentlichung: persönliche Namen aus Doku, Übersetzungen, Lizenz und Tests entfernt (Beispiele jetzt neutral), `SECURITY.md`, GitHub-Actions-Datei (Tests, Add-on-Prüfung, Image-Bau), Platzhalter für die Repository-Adresse in `repository.yaml` und `config.yaml`.
- Hinweis zum Abo-Token: Ein Claude-Abo-Token (`claude_oauth_token`) ist nur für den persönlichen Gebrauch gedacht. README, Dokumentation und Konfigurationstext sagen das deutlich; das Add-on schreibt beim Start eine Warnung ins Protokoll, wenn ein Abo-Token zusammen mit mehreren Benutzern, `all_ha_users` oder der Domain-Seite genutzt wird. Für mehrere Personen gilt der API-Schlüssel.
- Umzug in ein anderes Add-on (z. B. vom lokalen Add-on zum GitHub-Add-on): neue Option `export_database` legt die Datenbank beim Start als `ki_chat-export.sqlite3` in den Config-Ordner; `restore_snapshot` findet die Datei auch dort. Schritte siehe „Daten und Sicherung“.
- Bestehende Konfigurationen bleiben unverändert (neue Option ist optional und aus).

## 0.22.3
- Modellmenü kompakter, wie bei Claude: schmaleres Menü mit der Überschrift „Modell“, die Modelle ohne Symbol (Haken beim gewählten), darunter „Websuche“ als Schalter. Auf dem Handy bleibt es ein Fenster von unten, ebenfalls ohne Symbole bei den Modellen.

## 0.22.2
- GitHub: Ist GitHub nicht eingerichtet (kein `github_token`) oder für die Person nicht freigegeben (`github_access` auf `none`), weiß die KI jetzt genau das und sagt, was in der Konfiguration fehlt, statt zu vermuten.

## 0.22.1
- Modellauswahl: Ist `models` leer, bietet der Chat jetzt Opus 5.5 und Haiku 5.5 neben dem Standard-Modell zur Auswahl an (bisher gab es dann gar keine Auswahl). `models: none` schaltet die Auswahl ab. Eingetragene Listen bleiben unverändert.
- Seitenleiste kompakter, wie bei Claude: „Neuer Chat“, „Suchen“ und „Geplant“ ohne Rahmen als schlanke Zeilen mit dezenten Symbolen; weniger Abstand um das Logo.

## 0.22.0
- Suche: Neuer Menüpunkt **Suchen** (am Computer auch Strg/Cmd+K). Durchsucht Titel und Nachrichten der eigenen Chats, alle Wörter müssen vorkommen, ohne Beachtung von Groß-/Kleinschreibung und Umlautpunkten. Treffer mit Ausschnitt und markierter Fundstelle, bedienbar mit Tastatur.
- Export: Im Chat-Menü „Als Markdown exportieren“. Unter **Meine Daten** (Konto-Menü) gibt es einen ZIP-Export aller Chats (Markdown, je Projekt ein Ordner) samt Projekten mit Anweisungen, persönlichem Gedächtnis und geplanten Aufgaben.
- Löschen: Unter **Meine Daten** lassen sich alle eigenen Chats unwiderruflich löschen (Rückfrage und Eintippen von LÖSCHEN; abgelehnt, solange eine Antwort läuft). Projekte, Gedächtnis und geplante Aufgaben bleiben.
- Alles betrifft nur das eigene Profil. Keine neuen Optionen, keine Änderung an der Datenbank; bestehende Konfigurationen bleiben unverändert.

## 0.21.0
- Geplante Aufgaben: Neuer Menüpunkt **Geplant** in der Seitenleiste. Aufgaben mit Name, Auftrag und Zeitplan (täglich, Montag bis Freitag, wöchentlich an gewählten Tagen, monatlich, einmalig), optional Modell, Websuche und Benachrichtigung. Pausieren, „Jetzt ausführen“, bearbeiten, löschen; bis zu 20 je Person. Jeder Lauf legt einen neuen Chat an (ungelesen, mit Uhr-Symbol in der Liste); darin geht es normal weiter.
- Läufe ohne Rückfragen und nur lesend: Home Assistant und GitHub nur lesen, Gedächtnis nur lesen, kein Ändern. Websuche und erzeugte Dateien bleiben möglich. Versäumte Läufe werden bis 2 Stunden danach nachgeholt, sonst übersprungen; ist das Nutzungslimit erreicht, wird übersprungen. Auf der Aufgabenseite stehen nächster Lauf, letzter Lauf und Grund bei Problemen.
- Benachrichtigungen: je Aufgabe nur im Chat, Meldung in Home Assistant oder aufs Handy. Neu im Benutzer-Eintrag: `notify_service` (z. B. `notify.mobile_app_pixel`). Damit meldet sich die KI auch, wenn eine längere Antwort (ab etwa 45 Sekunden) fertig ist, während niemand zusieht; abschaltbar mit `notify_long_answers`.
- Neue Optionen `schedules_enabled` (Menüpunkt an/aus) und `notify_long_answers`; neu je Benutzer `notify_service`. Die Uhrzeiten gelten in der Zeitzone von Home Assistant (wird beim Start übernommen). Datenbank-Schema 12 (Tabelle `schedules`, Kennzeichen am Chat).
- Das Fenster von unten bekommt für Formulare die Knöpfe „Abbrechen“ und „Speichern“.
- Bestehende Konfigurationen bleiben unverändert (alles Neue ist optional).

## 0.20.0
- Websuche: Die KI kann im Web suchen (eingebautes Suchwerkzeug von Claude) und Seiten lesen (neues Werkzeug `web_fetch`), wenn es nötig ist oder wenn man sie im Gespräch darum bittet („Recherchiere …“). Unter der Antwort steht „Recherche im Web (n Suchen, m Seiten gelesen)“ mit jedem Schritt, die KI nennt ihre Quellen. Neue Optionen `web_access_default` (on/off) und je Benutzer `web_access`; im Chat lässt sich die Websuche über die neue Schaltfläche im Eingabefeld ein- und ausschalten.
- Seiten lesen ist gegen Zugriffe aufs Heimnetz abgesichert (nur öffentliche Adressen, geprüft in dem Moment, in dem die Verbindung aufgebaut wird, auch bei Weiterleitungen; keine internen Namen, Zugangsdaten in Adressen, ungewöhnlichen Ports). Nach dem Lesen von Web-Inhalten fragt jede Änderung (Gedächtnis, GitHub, Home Assistant) in derselben Antwort im Chat nach.
- Modellwahl: Neue Option `models` (weitere wählbare Modelle, durch Komma getrennt); `model` bleibt das Standard-Modell. Im Chat wählt man das Modell über die Schaltfläche neben der Denktiefe; die Wahl wird je Chat gemerkt. Der Server nimmt nur Modelle aus der Liste an. Ein nicht verfügbares Modell meldet einen Fehler mit Hinweis. Datenbank-Schema 11 (Modell je Chat).
- Nutzungslimit: Über dem Chat erscheint ein Hinweis, wenn das Limit des Abos fast erreicht oder erreicht ist, mit Auslastung und Zeitpunkt der Rücksetzung (Sitzungs- und Wochenlimits). Er verschwindet nach der Rücksetzung von selbst. Erreicht eine Antwort das Limit, nennt die Fehlermeldung die Rücksetzzeit.
- Rückfrage-Karten und Kurzfassungen unterscheiden jetzt Home Assistant, GitHub und Gedächtnis.
- Bestehende Konfigurationen bleiben unverändert: ohne `models` gibt es keine Modellauswahl, die Websuche ist standardmäßig an (abschaltbar mit `web_access_default: off`).

## 0.19.0
- GitHub-Anbindung: Die KI kann Repositories, Ordner und Dateien lesen, im Code suchen und Issues, Pull Requests (mit den Änderungen), Commits, Zweige, Tags, Releases und Workflow-Läufe ansehen (inklusive der fehlgeschlagenen Schritte eines Laufs).
- Mit Schreibrecht: mehrere Dateien in **einem** Commit schreiben, ändern oder löschen (auch Dateien aus dem Chat, etwa ein mit `file_create` erzeugtes Skript), neuen Zweig anlegen, Pull Requests, Issues und Kommentare erstellen oder ändern, Pull Requests mergen, Repositories anlegen (standardmäßig privat). Dazu der allgemeine Zugang `github_api` für alles Übrige (Labels, Releases, Workflow-Läufe starten …).
- Sicherheit: Jede Änderung wird im Chat bestätigt (mit allen Einzelheiten, auf Wunsch „in diesem Chat immer zulassen“). Immer mit Rückfrage und ohne „immer zulassen“: Commit auf den Hauptzweig, Workflow-Dateien, Merge, Repository anlegen, Löschen, sowie Änderungen nach dem Lesen fremder Inhalte in derselben Antwort oder bei Dateianhang. Nie möglich: Repository löschen oder umbenennen, Sichtbarkeit, Zugriffsrechte, Schlüssel, Geheimnisse, Webhooks, Schutzregeln, Hauptzweig löschen. Der Zweig wird vor der Rückfrage geprüft.
- Neue Optionen: `github_token` (Passwort, nur in der Konfiguration, nie im Chat), `github_access_default` und je Benutzer `github_access` (`none`, `read`, `write`), `github_repos` (Freigabeliste `besitzer/name` oder `besitzer/*`), `github_write_confirm` (`ask` oder `always_allow`).
- Oberfläche: unter der Antwort „N Aktionen bei GitHub, davon M Änderungen“ mit Link „Öffnen“ zu Commit, Pull Request oder Issue (nur Adressen auf github.com). Die Rückfragekarte nennt jetzt, worum es geht (Home Assistant, GitHub oder Gedächtnis).
- Bestehende Konfigurationen bleiben unverändert; ohne Token ist GitHub aus.

## 0.18.0
- Die KI kann jetzt Dateien erstellen und zum Herunterladen anbieten: Word (.docx), Excel (.xlsx), PowerPoint (.pptx), PDF sowie alle Arten von Textdateien (PowerShell, Shell, Batch, Python, CSV, JSON, YAML, HTML, Markdown …). Unter der Antwort erscheint pro Datei eine Karte mit Name, Art, Größe und Download-Knopf; auf dem Handy öffnet der Knopf das Teilen-Fenster („In Dateien sichern“).
- Neues Werkzeug `file_create`. Word, PDF und PowerPoint entstehen aus Markdown (Überschriften, Listen, Tabellen, Codeblöcke; bei PowerPoint beginnt jede Überschrift eine Folie, „Notizen: …“ wird Sprechernotiz, lange Folien werden geteilt). Excel entsteht aus JSON, CSV oder Markdown-Tabellen (Kopfzeile formatiert, Spaltenbreiten, Filter, Formeln, Zahlen und Datumsangaben als echte Zellwerte).
- Skripte bekommen das, was Windows braucht: `.ps1` und `.csv` als UTF-8 mit BOM (Umlaute stimmen), `.bat` mit Windows-Zeilenenden.
- Schutz: Formeln mit externen Aufrufen (z. B. WEBSERVICE, DDE) werden in Excel als Text abgelegt. Dateien gehören der Person, die sie erzeugt hat; andere bekommen 404. Eine Datei lässt sich nur mit Anmeldung laden und wird mit strenger Sicherheitskopfzeile ausgeliefert.
- Aufbewahrung: Neue Option `files_keep_days` (Standard 14, 1 bis 365). Danach wird die Datei gelöscht, der Chat bleibt (Karte zeigt „Abgelaufen“). Löschst du einen Chat, gehen seine Dateien sofort mit. Je Antwort höchstens 12 Dateien, je Person insgesamt höchstens 300 MB, je Datei 12 MB.
- Neue Option `files_enabled` (Standard an), um das Erzeugen abzuschalten.
- Die Office-Bibliotheken (python-docx, openpyxl, python-pptx, fpdf2) und die Schrift für PDF werden beim Bauen des Add-ons optional installiert. Schlägt das fehl, startet das Add-on trotzdem und die KI erzeugt nur Textdateien.
- Datenbank-Schema 10 (Tabelle `outfiles`, Dateien liegen in `/data/outfiles`).

## 0.17.0
- Smarthome-Überblick: Beim ersten Start und danach alle 7 Tage liest das Add-on selbst einen Überblick über Home Assistant ein (Etagen und Bereiche mit ihren Geräten, Automationen, Skripte, Szenen, Helfer, Integrationen, Personen, Zonen, Dashboards) und legt ihn im Haushaltsgedächtnis ab. Die KI kennt die Umgebung damit von Anfang an, auch ohne dass vorher jemand MCP oder KI mit Home Assistant benutzt hat. Es werden nur lesende Abfragen gemacht und nur Namen und Zuordnungen gespeichert (keine Zustandswerte, Koordinaten oder Zugangsdaten); das kostet keine Abo-Nachrichten.
- Sichtbar für alle Profile mit Zugriff auf Home Assistant (mindestens Lesen). Die wichtigsten Teile stehen im Kontext der KI, den Rest holt sie bei Bedarf mit dem neuen Werkzeug `overview_read`. Die Einträge heißen „HA · …“, werden bei jedem Lauf ersetzt, zählen nicht gegen die Obergrenze des Haushaltsgedächtnisses und lassen sich weder von der KI noch von Hand überschreiben.
- Status: Hinweis oben mit Fortschritt („Home Assistant wird eingelesen (3 von 7) …“), danach mit Zahlen oder (bei Fehler) mit „Erneut versuchen“. Im Gedächtnis-Dialog zeigt der Bereich „Home Assistant-Überblick“ Stand, Einträge und „Neu einlesen“.
- Neue Option `ha_scan_days` (Standard 7, 0 = nur auf Knopfdruck, höchstens 90). Datenbank-Schema 9 (kleine Zustandstabelle).
- Neue Warteanzeige: statt des pulsierenden Punkts ein kleines bewegtes Zeichen mit Hinweis („Denkt nach“, „Tüftelt“ …) oder der laufenden Aktion („Entitäten suchen: Licht“). Nach 20 Sekunden kommt die Wartezeit dazu, nach einer Minute ein Hinweis. Beim Schreiben bleibt nur das kleine Zeichen unter dem Text; bei „Bewegung reduzieren“ steht es still.

## 0.16.2
- Seitenleiste aufgeräumt: „Gedächtnis“ steht nicht mehr oben neben „Neuer Chat“. Unten gibt es jetzt einen Konto-Eintrag (Avatar, Name, Auf/Ab-Pfeil); er öffnet ein Menü mit Gedächtnis, Darstellung (Auto, Hell, Dunkel) und Abmelden. Auf dem Handy erscheint dasselbe als Fenster von unten.
- In Home Assistant bleibt der Eintrag sichtbar, solange das Menü etwas enthält (Gedächtnis); Darstellung und Abmelden erscheinen dort nicht, weil HA Theme und Anmeldung vorgibt.

## 0.16.1
- Sauberes Herunterfahren: Beim Stoppen oder Aktualisieren beendet sich das Add-on mit Exit-Code 0 (vorher Warnung „did not handle SIGTERM“ im Supervisor-Log). Offene Streams werden nach höchstens 5 Sekunden getrennt.
- Ordner-Zuordnung auf `app_config` umgestellt (neuer Name des Supervisors, derselbe Ordner `/addon_configs/<Name>/`, Logo und eigene Dateien bleiben erhalten).

## 0.16.0
- Projektwissen: Text-, Markdown-, Word-, Excel-, PDF-Dateien oder ein ZIP daraus zu einem Projekt hochladen. Die KI sieht das Inhaltsverzeichnis und sucht oder liest bei Bedarf selbst nach.
- Gedächtnis je Haushalt und je Person, strikt getrennt. Die KI weiß, mit wem sie spricht, merkt sich Dauerhaftes selbst, aktualisiert und vergisst auf Wunsch. Ansicht und Löschen in der Seitenleiste.
- Neue Optionen `memory_enabled` und `memory_household_writers` (`all` oder `ha_write`).
- Schutz: Geheimnisse werden nicht gespeichert; nach Dateianhängen und nach gelesenen Fremdinhalten fragt die KI vor jeder Gedächtnisänderung nach.
- Datenbank-Schema 8 (neue Tabellen, bestehende Daten bleiben).

## 0.15.0
- Die KI kann Home Assistant benutzen: lesen, Geräte bedienen und (höchste Stufe) Automationen, Skripte, Szenen, Dashboards und Helfer ändern. Rechte je Benutzer in der Konfiguration (`ha_access`: none, read, execute, write; Vorgabe `ha_access_default: read`).
- Bestätigung im Chat vor Änderungen (`ha_write_confirm`: ask oder always_allow), immer bei Schlössern, Alarm, Garagentoren und bei Dateianhängen. Lesen und Bedienen nur für in Assist freigegebene Entitäten (`ha_limit_to_exposed`), Zugriff über die Domain abschaltbar (`ha_access_via_domain`).
- Protokoll der Aktionen unter jeder Antwort, Markierung in der Seitenleiste bei wartender Rückfrage, Sicherung der alten Fassung vor Änderungen.
- Die KI weiß, mit wem sie spricht und welches Datum heute ist.

## 0.14.1
- Dateien bis 50 MB (PDF, Word, Excel), zusammen bis 60 MB je Nachricht. PDFs über 20 MB werden als Text ausgelesen (die Claude-API nimmt je Anfrage höchstens 32 MB).
- Neue Option `anthropic_api_key` (API-Schlüssel als Alternative zum Abo-Token).

## 0.14.0
- Die Frage wird beim Senden sofort gespeichert; Antworten laufen auf dem Server weiter, auch wenn der Chat gewechselt, die Seite neu geladen oder der Tab geschlossen wird.
- Kreisel in der Seitenleiste, solange in einem Chat geantwortet wird; Stopp-Knopf bricht serverseitig ab und behält den bisherigen Text.

## 0.13.0
- Menüs am Auslöser und mittige Dialoge nach dem Vorbild von claude.ai, Lesestatus der Chats.

## 0.12.0
- Optional alle Home-Assistant-Benutzer zulassen; optional „Mit Home Assistant anmelden“ auf der Domain-Anmeldeseite. Dialoge auf großen Bildschirmen mittig.

## 0.11.0
- Name, Logo, Texte, Farben und Benutzer in der Add-on-Konfiguration; Theme von Home Assistant wird übernommen.

## 0.10.0
- Überarbeitetes Design (hell/dunkel), neue Anmeldeseite.

## 0.9.0
- Projektanweisungen, Word- und Excel-Dateien, Download von Antwortdateien, HTML-Vorschau.

## 0.8.0
- Dateianhänge (nur im Arbeitsspeicher).

## 0.7.0
- Tägliche Datenbank-Schnappschüsse, Wiederherstellung, Zusammenfassen langer Chats, Hinweise zu ablaufenden Zugangsdaten.

## 0.6.x
- Seitenleiste, Projekte, Anpinnen, automatische Kurztitel.
