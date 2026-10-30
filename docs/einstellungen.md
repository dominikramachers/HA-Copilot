# Alle Einstellungen

Diese Seite listet **jede** Option des Add-ons mit Standardwert und Bedeutung. Du findest sie in Home Assistant unter **Einstellungen → Apps → HA Copilot → Konfiguration**. Mit ⋮ → „In YAML bearbeiten“ kannst du alles als Text sehen, kopieren und einfügen. Nach jeder Änderung speichern und das Add-on **neu starten**.

Pflichtfelder (immer vorhanden, mit Standardwert voreingestellt): `profiles`, `public_enabled`, `public_trusted_proxies`, `backend`, `model`, `default_effort`. Alle anderen Optionen sind optional; fehlt eine, gilt der Standardwert. Bestehende Einstellungen werden bei Updates nie überschrieben.

## Benutzer

Wer die App nutzen darf. Ausführlich in [Benutzer und Rechte](benutzer.md).

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `profiles` | Liste (Felder siehe unten) | ein Eintrag „Administrator“ | **Benutzer (Profile).** Wer die App nutzen darf. „Hinzufügen“ legt einen weiteren Benutzer an; meist genügt der Home-Assistant-Benutzername, alles andere ist optional. Wer noch nicht eingetragen ist, sieht in der App seinen Benutzernamen und seine ID zum Eintragen. Nach dem Speichern das Add-on neu starten. |
| `all_ha_users` | an/aus | aus | **Alle Home-Assistant-Benutzer zulassen.** Aus (Standard): nur die oben eingetragenen Benutzer. An: jeder Home-Assistant-Benutzer darf die App nutzen und bekommt beim ersten Zugriff automatisch ein eigenes Profil mit eigenen Chats. Eingetragene Benutzer behalten ihr Profil. Eintragen ist dann nur noch nötig für Anzeigename oder Microsoft-Anmeldung. |
| `ha_users_excluded` | Text | leer | **Ausgeschlossene Home-Assistant-Benutzer (optional).** Nur mit „Alle Home-Assistant-Benutzer zulassen“: Benutzernamen, Namen oder IDs, durch Komma getrennt (z. B. „kind1, gast“). Diese Benutzer kommen nicht herein. |

### Felder je Benutzer (`profiles`)

| Feld | Werte | Bedeutung |
|---|---|---|
| `ha_user` | Text | **Home-Assistant-Benutzername.** Anmeldename oder Person des Benutzers in Home Assistant (z. B. „doralab“). Das Add-on ermittelt daraus die ID. Alternativ die ID unten eintragen. |
| `label` | Text | **Anzeigename (optional).** Name, der in der App angezeigt wird. Leer lassen, dann gilt der Home-Assistant-Benutzername. |
| `ha_user_id` | 32 Hex-Zeichen | **Home-Assistant-Benutzer-ID (optional).** 32 Zeichen. Nur nötig, wenn der Benutzername nicht eindeutig ist. Im Add-on-Protokoll stehen beim Start alle Benutzer mit ihren IDs. |
| `entra_upn` | Text | **E-Mail / UPN für die Domain-Anmeldung (optional).** Konto, mit dem sich die Person über die öffentliche Domain per Microsoft Entra anmeldet. |
| `ha_access` | `none` \| `read` \| `execute` \| `write` | **Zugriff auf Home Assistant (optional).** Was die KI für diesen Benutzer in Home Assistant darf: none = nichts, read = lesen, execute = lesen und ausführen (Geräte schalten), write = lesen, ausführen und ändern (Automationen, Skripte, Dashboards, Helfer). Leer: es gilt der Standard unten. |
| `github_access` | `none` \| `read` \| `write` | **GitHub-Zugriff (optional).** Was die KI für diesen Benutzer bei GitHub darf: none = nichts, read = Repositories lesen, write = lesen und ändern (Dateien einchecken, Pull Requests, Issues, Repositories anlegen). Leer: es gilt der Standard unten. Das Token gehört dir als Betreiber: jeder Benutzer mit read oder write sieht damit auch deine privaten Repositories (außer die Freigabeliste schränkt es ein). |
| `web_access` | `on` \| `off` | **Websuche (optional).** on = die KI darf für diesen Benutzer im Web suchen und Seiten lesen, off = nicht. Leer: es gilt der Standard unten. |
| `notify_service` | Text | **Benachrichtigungsdienst (optional).** Home-Assistant-Dienst, über den dieser Benutzer aufs Handy benachrichtigt wird, z. B. notify.mobile_app_pixel (siehe Entwicklerwerkzeuge → Aktionen, Suche „notify“). Damit meldet sich die KI, wenn eine längere Antwort fertig ist, während niemand zusieht, und geplante Aufgaben können aufs Handy melden. Leer: keine Benachrichtigung aufs Handy. |
| `id` | a–z, 0–9, `-`, `_` (2 bis 32 Zeichen) | **Kurzname (optional).** Interne Kennung, a–z, 0–9, Bindestrich. Leer lassen: wird aus dem Anzeigenamen gebildet. Nachträglich nicht mehr ändern, die Chats hängen daran. |

## Claude (Antworten)

Zugang zu Claude und Modelle. Ausführlich in [Installation](installation.md#4-zugang-zu-claude).

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `backend` | `echo` \| `claude` | `echo` | **Antwortquelle.** echo: Testbetrieb ohne KI. claude: echte Antworten über das Claude-Abo. |
| `claude_oauth_token` | Text (geheim) | leer | **Claude-Zugangstoken (Abo).** Langzeit-Token aus „claude setup-token“ (Claude-Abo). NUR für den eigenen, persönlichen Gebrauch. Mehrere Benutzer oder die Domain-Seite brauchen einen API-Schlüssel (Anthropic-Nutzungsbedingungen beachten). |
| `anthropic_api_key` | Text (geheim) | leer | **Anthropic-API-Schlüssel.** Alternative zum Abo-Token (Abrechnung nach Verbrauch über die Claude-Konsole). Hat Vorrang, wenn beides eingetragen ist. |
| `model` | Text | `claude-sonnet-5-5` | **Standard-Modell.** Modell für neue Chats, z. B. claude-sonnet-5-5. In der Oberfläche kann man es je Chat wechseln, wenn unten weitere Modelle eingetragen sind. |
| `title_model` | Text | `claude-haiku-5-5` | **Modell für Chat-Titel.** Kleineres Modell für automatische Titel. |
| `models` | Text | leer | **Weitere wählbare Modelle (optional).** Durch Komma getrennt, z. B. „claude-opus-5-5, claude-haiku-5-5“. Das Standard-Modell oben ist immer dabei. Leer: Opus 5.5 und Haiku 5.5 stehen zur Auswahl. „none“: keine Modellauswahl im Chat. Welche Modelle dein Abo zulässt, entscheidet Anthropic; ein nicht verfügbares Modell meldet einen Fehler. |
| `default_effort` | `low` \| `medium` \| `high` | `medium` | **Standard-Denktiefe.** low, medium oder high. |
| `web_access_default` | `on` \| `off` | `on` | **Standard: Websuche.** on (Standard) oder off. Die KI kann im Web suchen und Seiten lesen, wenn es nötig ist oder wenn man sie darum bittet. Je Benutzer überschreibbar; im Chat lässt sie sich je Nachricht abschalten. Die Suchanfragen verlassen dabei das Haus. |

## Zugriff auf Home Assistant

Was die KI in Home Assistant sehen und tun darf.

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `ha_access_default` | `none` \| `read` \| `execute` \| `write` | `read` | **Standard-Zugriff auf Home Assistant.** Gilt für alle Benutzer ohne eigene Angabe: none, read (Standard), execute oder write. Bei read und execute sieht und steuert die KI nur Entitäten, die in Home Assistant für Assist freigegeben sind (siehe unten). |
| `ha_write_confirm` | `ask` \| `always_allow` | `ask` | **Bestätigung bei Änderungen.** ask (Standard): Jede Änderung an Automationen, Skripten, Dashboards, Helfern und Einstellungen muss im Chat bestätigt werden (einmal, oder „in diesem Chat immer zulassen“). always_allow: ohne Rückfrage. Sensible Aktionen (Schlösser, Alarmanlage, Garagentor) und Nachrichten mit Dateianhang fragen immer nach. |
| `ha_limit_to_exposed` | an/aus | an | **Nur für Assist freigegebene Entitäten (lesen/ausführen).** An (Standard): Benutzer mit read oder execute sehen und steuern nur Entitäten, die in Home Assistant unter Einstellungen → Sprachassistenten → Freigeben für Assist freigegeben sind. Benutzer mit write sind davon nicht betroffen. |
| `ha_access_via_domain` | an/aus | an | **HA-Zugriff auch über die Domain.** An (Standard): Die Rechtestufen gelten auch bei Anmeldung über die öffentliche Domain. Aus: dort hat die KI keinen Zugriff auf Home Assistant, nur im HA-Panel. |
| `ha_scan_days` | Zahl 0 bis 90 | `7` | **Smarthome-Überblick einlesen (alle … Tage).** Der HA Copilot liest beim ersten Start und danach alle N Tage (Standard 7) einen Überblick über Home Assistant ein (Bereiche, Geräte, Automationen, Integrationen) und legt ihn im Haushaltsgedächtnis ab, damit die KI deine Umgebung von Anfang an kennt. 0 = nie automatisch, nur auf Knopfdruck im Gedächtnis-Dialog. Es werden nur Namen und Zuordnungen gelesen, keine Zustandswerte, Koordinaten oder Zugangsdaten. Gilt nur, wenn das Gedächtnis aktiv ist. |

## GitHub

Optional: die KI arbeitet mit deinen Repositories.

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `github_token` | Text (geheim) | leer | **GitHub-Token.** Persönliches Zugriffstoken von GitHub (Einstellungen → Entwicklereinstellungen → Fine-grained tokens). Gib ihm nur die Repositories und Rechte, die die KI haben soll: Contents, Pull requests und Issues (je lesen und schreiben), Metadata (lesen); zum Anlegen neuer Repositories ein klassisches Token mit dem Recht „repo“. Leer: GitHub ist aus. |
| `github_access_default` | `none` \| `read` \| `write` | `none` | **Standard-Zugriff auf GitHub.** Gilt für alle Benutzer ohne eigene Angabe: none (Standard), read oder write. Ohne Token in der Konfiguration hat das keine Wirkung. |
| `github_write_confirm` | `ask` \| `always_allow` | `ask` | **Bestätigung bei GitHub-Änderungen.** ask (Standard): Jede Änderung (Commit, Pull Request, Issue, Kommentar …) muss im Chat bestätigt werden (einmal, oder „in diesem Chat immer zulassen“). always_allow: ohne Rückfrage. Immer nachgefragt wird bei Commits auf den Hauptzweig, Merge, neuen Repositories, Löschen, Workflow-Dateien und nach dem Lesen fremder Inhalte oder mit Dateianhang. |
| `github_repos` | Text | leer | **Erlaubte Repositories (optional).** Freigabeliste, durch Komma getrennt: „doralab/smarthome, doralab/*“. besitzer/* erlaubt alle Repositories eines Besitzers. Leer: alles, was das Token erreicht. Die KI kann auf andere Repositories dann gar nicht zugreifen. |

## Funktionen

Gedächtnis, geplante Aufgaben, Dateien und Sprache.

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `language` | `de` \| `en` | `de` | **Sprache.** de (Standard) für Deutsch oder en für Englisch. Gilt für die Oberfläche, die Meldungen des Add-ons und die Standardsprache der KI-Antworten (wer in einer anderen Sprache schreibt, bekommt die Antwort weiterhin in dieser Sprache). Bereits gespeicherte Chats bleiben unverändert. |
| `memory_enabled` | an/aus | an | **Gedächtnis der KI.** An (Standard): Die KI merkt sich Fakten selbstständig, für den ganzen Haushalt und getrennt für jede Person. Jeder kann die Einträge im Chat unter „Gedächtnis“ ansehen, ändern und löschen. Aus: kein Gedächtnis. |
| `memory_household_writers` | `all` \| `ha_write` | `all` | **Wer das Haushaltsgedächtnis ändern darf.** all (Standard): jeder Benutzer; ha_write: nur Benutzer mit Zugriffsstufe write (die anderen können es lesen, die KI trägt für sie nichts ein). Das persönliche Gedächtnis gehört immer der jeweiligen Person. |
| `schedules_enabled` | an/aus | an | **Geplante Aufgaben erlauben.** An (Standard): Menüpunkt „Geplant“, in dem die KI zu festen Zeiten Aufgaben erledigt (nur lesend, ohne Rückfragen). Aus: keine geplanten Aufgaben, bestehende ruhen. Geplante Läufe verbrauchen Kontingent deines Abos. |
| `notify_long_answers` | an/aus | an | **Benachrichtigung bei fertigen Antworten.** An (Standard): Dauert eine Antwort länger als etwa 45 Sekunden und niemand sieht zu (Chat gewechselt, Tab zu), bekommt die Person eine Benachrichtigung aufs Handy. Wirkt nur für Benutzer mit eingetragenem Benachrichtigungsdienst. |
| `files_enabled` | an/aus | an | **Dateien erzeugen.** An (Standard): Die KI kann auf Wunsch Dateien erstellen (Word, Excel, PowerPoint, PDF sowie Skripte und andere Textdateien) und im Chat zum Herunterladen anbieten. Aus: nur Text und Codeblöcke. |
| `files_edit` | an/aus | an | **Dateien bearbeiten.** An (Standard): Angehängte Dateien (PDF, Word, Excel, PowerPoint, Text und Code) werden für diesen Chat aufbewahrt, und die KI kann sie lesen und bearbeiten, z. B. PDF-Felder ausfüllen oder sperren, Word-Texte ändern, Excel-Zellen setzen, Code anpassen. Die bearbeitete Fassung erscheint zum Herunterladen, das Original bleibt unverändert. Aus: Anhänge liegen nur für die eine Nachricht im Arbeitsspeicher und nichts davon wird gespeichert. Braucht „Dateien erzeugen“. |
| `files_keep_days` | Zahl 1 bis 365 | `14` | **Dateien aufbewahren (Tage).** Wie lange erzeugte, bearbeitete und angehängte Dateien im Chat verfügbar bleiben (1 bis 365, Standard 14). Danach werden sie gelöscht; der Chat bleibt. Dateien eines gelöschten Chats werden sofort entfernt. |

## Zugang über eine eigene Domain

Optional, nur mit `public_enabled`. Ausführlich in [Domain-Zugang](domain-zugang.md).

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `public_enabled` | an/aus | aus | **Domain-Zugang aktivieren.** Schaltet den Zugang über die öffentliche Domain (Port 8100) ein, mit Microsoft Entra und/oder (mit Adresse von Home Assistant) der Anmeldung über Home Assistant. |
| `public_base_url` | Text | leer | **Öffentliche Adresse.** z. B. https://chat.example.org. Muss zur Redirect-URI der Entra-App passen. |
| `entra_tenant_id` | Text | leer | **Entra: Verzeichnis-ID (Tenant).** GUID aus der Entra-App-Registrierung (Übersicht, „Verzeichnis-ID (Mandant)“). |
| `entra_client_id` | Text | leer | **Entra: Anwendungs-ID (Client).** GUID aus der Entra-App-Registrierung (Übersicht, „Anwendungs-ID (Client)“). |
| `entra_client_secret` | Text (geheim) | leer | **Entra: geheimer Clientschlüssel.** Wert des Clientschlüssels (Zertifikate & Geheimnisse). Läuft ab: Datum bei `entra_secret_expires` eintragen. |
| `ha_url` | Text | leer | **Adresse von Home Assistant für die Anmeldung über die Domain (optional).** Nur wenn sich Benutzer über die Domain mit ihrem Home-Assistant-Konto anmelden sollen: von außen erreichbare Adresse, z. B. https://ha.example.org. Dann erscheint auf der Anmeldeseite „Mit Home Assistant anmelden“. Leer lassen: nur Microsoft Entra. |
| `session_days` | Zahl 1 bis 90 | `30` | **Anmeldedauer (Tage).** Wie lange eine Anmeldung über die Domain gültig bleibt (1–90). |
| `public_trusted_proxies` | Liste | leer | **Vertrauenswürdige Proxys.** Adressen von Reverse-Proxys (z. B. Cloudflare-Tunnel-Container), deren Weiterleitungs-Header gelten dürfen. |

## Aussehen und Name

Alles optional. Ausführlich in der [Dokumentation](../ki_chat/DOCS.md#personalisierung-name-logo-texte-farben).

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `app_name` | Text | `HA Copilot` | **App-Name.** Name in Anmeldeseite, Titel und Seitenleiste. Standard: HA Copilot. Der Name des Eintrags in der Home-Assistant-Seitenleiste ist fest und lässt sich hier nicht ändern. |
| `login_text` | Text | leer | **Text auf der Anmeldeseite.** Kurzer Satz unter dem Namen, z. B. „Anmelden mit deinem Firmenkonto.“ |
| `login_placeholder` | Text | leer | **Beispiel-Adresse im Anmeldefeld.** Platzhalter im E-Mail-Feld der Anmeldeseite, z. B. name@firma.de. |
| `logo_tile` | an/aus | aus | **Logo auf dunkler Kachel.** Für Logos, die nur auf dunklem Grund gut aussehen (z. B. helle oder neonfarbene Logos): zeigt sie im hellen Design auf einer dunklen Kachel. |
| `follow_ha_theme` | an/aus | an | **Home-Assistant-Theme übernehmen.** An: Farben und Hell/Dunkel folgen live dem aktiven Theme von Home Assistant (in der Seitenleiste von HA) bzw. dem Standard-Theme (über die Domain). Aus: eingebaute Farben mit eigenem Hell/Dunkel-Schalter. |
| `theme_name` | Text | leer | **Theme für die Domain (optional).** Name eines Home-Assistant-Themes, das über die Domain gelten soll. Leer: Standard-Theme von Home Assistant. |
| `accent_color` | Hex-Farbe, z. B. `#175CD3` | leer | **Akzentfarbe.** Hex-Wert wie #175CD3. Überschreibt die Akzentfarbe aus dem Theme. Leer: aus dem Theme. |
| `background_color_light` | Hex-Farbe, z. B. `#175CD3` | leer | **Hintergrund hell.** Hex-Wert wie #F3F4F6. Leer: aus dem Theme. |
| `background_color_dark` | Hex-Farbe, z. B. `#175CD3` | leer | **Hintergrund dunkel.** Hex-Wert wie #0D192D. Leer: aus dem Theme. |
| `card_color_light` | Hex-Farbe, z. B. `#175CD3` | leer | **Flächen hell.** Farbe von Karten und Eingabefeldern im hellen Design. Leer: aus dem Theme. |
| `card_color_dark` | Hex-Farbe, z. B. `#175CD3` | leer | **Flächen dunkel.** Farbe von Karten und Eingabefeldern im dunklen Design. Leer: aus dem Theme. |
| `text_color_light` | Hex-Farbe, z. B. `#175CD3` | leer | **Schrift hell.** Textfarbe im hellen Design. Leer: aus dem Theme. |
| `text_color_dark` | Hex-Farbe, z. B. `#175CD3` | leer | **Schrift dunkel.** Textfarbe im dunklen Design. Leer: aus dem Theme. |

## Daten, Sicherung und Erinnerungen

Normalerweise leer oder aus. Siehe [Betrieb](betrieb.md).

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `restore_snapshot` | Text | leer | **Datenbank wiederherstellen.** Nur im Notfall: Name eines Snapshots, der beim nächsten Start eingespielt wird. Danach leeren. |
| `export_database` | an/aus | aus | **Datenbank exportieren (Umzug).** Nur für den Umzug in ein anderes Add-on (z. B. vom lokalen Add-on zum GitHub-Add-on): Beim Start wird eine Kopie aller Chats als ki_chat-export.sqlite3 in den Config-Ordner des Add-ons gelegt. Danach ausschalten und die Datei löschen. |
| `claude_token_expires` | Text | leer | **Claude-Token läuft ab am.** Datum (JJJJ-MM-TT) für die Erinnerung in der App. |
| `entra_secret_expires` | Text | leer | **Entra-Schlüssel läuft ab am.** Datum (JJJJ-MM-TT) für die Erinnerung in der App. |

