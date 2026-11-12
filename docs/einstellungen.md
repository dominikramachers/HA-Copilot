# Alle Einstellungen

Diese Seite listet **jede** Option des Add-ons mit Standardwert und Bedeutung. Du findest sie in Home Assistant unter **Einstellungen → Apps → HA Copilot → Konfiguration**. Die Optionen stehen in eingeklappten Gruppen (ab 0.54.0); der Name einer Option beginnt mit der Gruppe, z. B. `domain.public_base_url`. Mit ⋮ → „In YAML bearbeiten“ siehst du alles als Text, so wie es unten bei jeder Gruppe steht. Nach jeder Änderung speichern und das Add-on **neu starten**.

Alle Optionen sind optional; fehlt eine, gilt der Standardwert. Bestehende Einstellungen werden bei Updates nie überschrieben. Beim Wechsel auf die Gruppen (0.54.0) übernimmt das Add-on die alten Werte, bis du sie in den Gruppen einträgst.

## Benutzer (`users`)

Wer die App nutzen darf. Ausführlich in [Benutzer und Rechte](benutzer.md).

In der Konfigurationsdatei: `users:` mit den Feldern darunter.

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `users.profiles` | Liste (Felder siehe unten) | ein Eintrag „Administrator“ | **Benutzer (Profile).** Wer die App nutzen darf. „Hinzufügen“ legt einen weiteren Benutzer an; meist genügt der Home-Assistant-Benutzername, alles andere ist optional. Wer noch nicht eingetragen ist, sieht in der App seinen Benutzernamen und seine ID zum Eintragen. Nach dem Speichern das Add-on neu starten. |
| `users.all_ha_users` | an/aus | aus | **Alle Home-Assistant-Benutzer zulassen.** Aus (Standard): nur die oben eingetragenen Benutzer. An: jeder Home-Assistant-Benutzer darf die App nutzen und bekommt beim ersten Zugriff automatisch ein eigenes Profil mit eigenen Chats. Eingetragene Benutzer behalten ihr Profil. Eintragen ist dann nur noch nötig für Anzeigename oder Microsoft-Anmeldung. |
| `users.ha_users_excluded` | Text | leer | **Ausgeschlossene Home-Assistant-Benutzer (optional).** Nur mit „Alle Home-Assistant-Benutzer zulassen“: Benutzernamen, Namen oder IDs, durch Komma getrennt (z. B. „kind1, gast“). Diese Benutzer kommen nicht herein. |

### Felder je Benutzer (`users.profiles`)

| Feld | Werte | Bedeutung |
|---|---|---|
| `ha_user` | Text | **Home-Assistant-Benutzername.** Anmeldename oder Person des Benutzers in Home Assistant (z. B. „doralab“). Das Add-on ermittelt daraus die ID. Alternativ die ID unten eintragen. |
| `label` | Text | **Anzeigename (optional).** Name, der in der App angezeigt wird. Leer lassen, dann gilt der Home-Assistant-Benutzername. |
| `ha_user_id` | 32 Hex-Zeichen | **Home-Assistant-Benutzer-ID (optional).** 32 Zeichen. Nur nötig, wenn der Benutzername nicht eindeutig ist. Im Add-on-Protokoll stehen beim Start alle Benutzer mit ihren IDs. |
| `entra_upn` | Text | **E-Mail / UPN für die Domain-Anmeldung (optional).** Konto, mit dem sich die Person über die öffentliche Domain per Microsoft Entra anmeldet. |
| `ha_access` | `none` \| `read` \| `execute` \| `write` | **Zugriff auf Home Assistant (optional).** Was die KI für diesen Benutzer in Home Assistant darf: none = nichts, read = lesen, execute = lesen und ausführen (Geräte schalten), write = lesen, ausführen und ändern (Automationen, Skripte, Dashboards, Helfer). Leer: es gilt der Standard dieser Option in der Gruppe „Chat (Claude & OpenAI)“ bzw. „Sprechen mit der KI“. |
| `github_access` | `none` \| `read` \| `write` | **GitHub-Zugriff (optional).** Was die KI für diesen Benutzer bei GitHub darf: none = nichts, read = Repositories lesen, write = lesen und ändern (Dateien einchecken, Pull Requests, Issues, Repositories anlegen). Leer: es gilt der Standard dieser Option in der Gruppe „Chat (Claude & OpenAI)“ bzw. „Sprechen mit der KI“. Das Token gehört dir als Betreiber: jeder Benutzer mit read oder write sieht damit auch deine privaten Repositories (außer die Freigabeliste schränkt es ein). |
| `connector_access` | `none` \| `use` \| `own` \| `global` | **Konnektoren (optional).** Was die KI für diesen Benutzer bei Konnektoren (MCP-Server wie Microsoft 365, Google Workspace oder Zabbix) darf: none = keine, use = freigegebene (globale) Konnektoren nutzen, own = zusätzlich eigene anlegen, global = zusätzlich globale Konnektoren für alle anlegen und ändern (auch Adressen im Heimnetz). Leer: es gilt der Standard dieser Option in der Gruppe „Chat (Claude & OpenAI)“ bzw. „Sprechen mit der KI“. |
| `web_access` | `on` \| `off` | **Websuche (optional).** on = die KI darf für diesen Benutzer im Web suchen und Seiten lesen, off = nicht. Leer: es gilt der Standard dieser Option in der Gruppe „Chat (Claude & OpenAI)“ bzw. „Sprechen mit der KI“. |
| `voice_access` | `on` \| `off` | **Sprechen mit der KI (optional).** on = diese Person darf per Sprache mit der KI sprechen (Mikrofon-Knopf im Chat), off = nicht. Leer: es gilt der Standard dieser Option in der Gruppe „Chat (Claude & OpenAI)“ bzw. „Sprechen mit der KI“. |
| `notify_service` | Text | **Benachrichtigungsdienst (optional).** Home-Assistant-Dienst, über den dieser Benutzer aufs Handy benachrichtigt wird, z. B. notify.mobile_app_pixel (siehe Entwicklerwerkzeuge → Aktionen, Suche „notify“). Vorgabe für die Geräte dieser Person (jede Person wählt ihre Geräte selbst unter Einstellungen → Benachrichtigungen; ohne Auswahl gelten die Geräte ihrer Person in Home Assistant). Leer: keine Vorgabe. |
| `id` | a–z, 0–9, `-`, `_` (2 bis 32 Zeichen) | **Kurzname (optional).** Interne Kennung, a–z, 0–9, Bindestrich. Leer lassen: wird aus dem Anzeigenamen gebildet. Nachträglich nicht mehr ändern, die Chats hängen daran. |

## Chat (Claude & OpenAI) (`chat`)

Zugang zu Claude ([Installation](installation.md#4-zugang-zu-claude)), Modell, Gedächtnis, geplante Aufgaben, Dateien, Zugriff auf Home Assistant und die Standards für GitHub und Konnektoren. GitHub und Konnektoren sind ausführlich in der [Dokumentation](../copilot/DOCS.md#konnektoren-ab-0410) beschrieben.

In der Konfigurationsdatei: `chat:` mit den Feldern darunter.

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `chat.anthropic_api_key` | Text (geheim) | leer | **Anthropic-API-Schlüssel.** Alternative zum Abo-Token (Abrechnung nach Verbrauch über die Claude-Konsole). Hat Vorrang, wenn beides eingetragen ist. |
| `chat.claude_oauth_token` | Text (geheim) | leer | **Claude-Zugangstoken (Abo).** Langzeit-Token aus „claude setup-token“ (Claude-Abo). NUR für den eigenen, persönlichen Gebrauch. Mehrere Benutzer oder die Domain-Seite brauchen einen API-Schlüssel (Anthropic-Nutzungsbedingungen beachten). Ohne Token und ohne API-Schlüssel läuft nur der Testmodus. |
| `chat.claude_token_expires` | Text | leer | **Claude-Token läuft ab am.** Datum (JJJJ-MM-TT) für die Erinnerung in der App. |
| `chat.model` | Text | `claude-sonnet-5-5` | **Standard-Modell.** Modell für neue Chats, z. B. claude-sonnet-5-5. In der Oberfläche kann man es je Chat wechseln (Opus und Haiku stehen zusätzlich zur Wahl). |
| `chat.memory_enabled` | an/aus | an | **Gedächtnis der KI.** An (Standard): Die KI merkt sich Fakten selbstständig, für den ganzen Haushalt und getrennt für jede Person. Jeder kann die Einträge im Chat unter „Gedächtnis“ ansehen, ändern und löschen. Aus: kein Gedächtnis. |
| `chat.schedules_enabled` | an/aus | an | **Geplante Aufgaben erlauben.** An (Standard): Menüpunkt „Geplant“, in dem die KI zu festen Zeiten Aufgaben erledigt (nur lesend, ohne Rückfragen). Aus: keine geplanten Aufgaben, bestehende ruhen. Geplante Läufe verbrauchen Kontingent deines Abos. |
| `chat.incognito_enabled` | an/aus | an | **Inkognito-Chat erlauben.** An (Standard): Neben „Neuer Chat“ gibt es das Gespenster-Symbol für einen Inkognito-Chat. Er steht in keiner Liste und Suche, nutzt und ändert kein Gedächtnis, wird nicht exportiert und beim Schließen gelöscht. Aus: kein Inkognito-Chat. |
| `chat.files_enabled` | an/aus | an | **Dateien erzeugen.** An (Standard): Die KI kann auf Wunsch Dateien erstellen (Word, Excel, PowerPoint, PDF sowie Skripte und andere Textdateien) und im Chat zum Herunterladen anbieten. Aus: nur Text und Codeblöcke. |
| `chat.ha_access_default` | `none` \| `read` \| `execute` \| `write` | `execute` | **Standard-Zugriff auf Home Assistant.** Gilt für alle Benutzer ohne eigene Angabe: none, read, execute (Standard) oder write. Bei read und execute sieht und steuert die KI nur Entitäten, die in Home Assistant für Assist freigegeben sind (siehe nächste Option). |
| `chat.ha_limit_to_exposed` | an/aus | an | **Nur für Assist freigegebene Entitäten (lesen/ausführen).** An (Standard): Benutzer mit read oder execute sehen und steuern nur Entitäten, die in Home Assistant unter Einstellungen → Sprachassistenten → Freigeben für Assist freigegeben sind. Benutzer mit write sind davon nicht betroffen. |
| `chat.github_access_default` | `none` \| `read` \| `write` | `none` | **Standard-Zugriff auf GitHub.** Gilt für alle Benutzer ohne eigene Angabe: none (Standard), read oder write. Wirkt, sobald eine Person ihr GitHub in den Einstellungen verbunden hat. Je Benutzer überschreibbar mit github_access. |
| `chat.connector_access_default` | `none` \| `use` \| `own` \| `global` | `use` | **Standard-Recht für Konnektoren.** Gilt für alle Benutzer ohne eigene Angabe: none, use (Standard: globale Konnektoren nutzen), own (zusätzlich eigene anlegen) oder global (zusätzlich globale verwalten). Konnektoren verbinden die KI mit Diensten außerhalb von Home Assistant; was sie darüber liest, behandelt sie wie fremde Inhalte. |
| `chat.openai_enabled` | an/aus | aus | **ChatGPT (OpenAI) im Chat erlauben.** Aus (Standard): nur Claude. An (und Schlüssel eingetragen): ChatGPT-Modelle stehen im Chat zur Wahl, mit Home-Assistant-Steuerung, Gedächtnis, Dateien, Bildern, GitHub, Konnektoren, Websuche und geplanten Aufgaben. Was in einem ChatGPT-Chat geschrieben wird, geht an OpenAI (nie an Claude), in einem Claude-Chat nie an OpenAI. Sprechen mit der KI bleibt immer bei Claude Haiku. |
| `chat.openai_api_key` | Text (geheim) | leer | **OpenAI-API-Schlüssel (Chat).** Schlüssel von platform.openai.com (API keys) für die ChatGPT-Modelle; ein ChatGPT-Abo reicht dafür nicht, das API-Konto braucht eigenes Guthaben. Leer: der Schlüssel aus „Bilder“ wird mitbenutzt. |
| `chat.openai_key_expires` | Text | leer | **OpenAI-Schlüssel (Chat) läuft ab am.** Datum (JJJJ-MM-TT) für die Erinnerung in der App; 30 Tage vorher erscheint ein Hinweis im Chat. |
| `chat.openai_models` | Text | `gpt-5.6-terra, gpt-5.6-luna, gpt-5.6-sol` | **ChatGPT-Modelle.** Modelle, die im Chat zur Wahl stehen (höchstens 6), durch Komma getrennt. Standard: gpt-5.6-terra, gpt-5.6-luna, gpt-5.6-sol. Der erste Eintrag ist die erste Wahl der Liste. Leer: Standardliste. |
| `chat.openai_limit_month` | Zahl 0 bis 100000 | `3000` | **ChatGPT-Token je Person und Monat (in Tausend).** Wie viele Token (Eingabe plus Ausgabe) jede Person im Monat mit ChatGPT-Modellen verbrauchen darf, in Tausend (Standard 3000 = 3 Millionen, 0 = kein Limit). Darüber fragt der Chat vor jeder weiteren Antwort nach (Zulassen oder Ablehnen). |

## Bilder (`images`)

Die KI erzeugt Bilder von selbst: SVG kostenlos, Fotos und Kunst über OpenAI oder Google. Ausführlich in der [Dokumentation](../copilot/DOCS.md#bilder-ab-0280).

In der Konfigurationsdatei: `images:` mit den Feldern darunter.

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `images.openai_api_key` | Text (geheim) | leer | **OpenAI-API-Schlüssel (Bilder).** Schlüssel von platform.openai.com (API keys). Nötig für Bilder von OpenAI (und, wenn bei „Sprechen mit der KI“ kein eigener Schlüssel steht, auch für die Spracherkennung); ein ChatGPT-Abo reicht dafür nicht, das API-Konto braucht eigenes Guthaben. Bildwunsch und Referenzbilder werden an OpenAI übertragen. Leer: keine Bilder von OpenAI. |
| `images.google_api_key` | Text (geheim) | leer | **Google-API-Schlüssel (Bilder).** Schlüssel für die Gemini-API von aistudio.google.com (Get API key) mit aktivierter Abrechnung; ein Google-Abo reicht dafür nicht. Bildwunsch und Referenzbilder werden an Google übertragen. Leer: keine Bilder von Google. |
| `images.openai_key_expires` | Text | leer | **OpenAI-Schlüssel läuft ab am.** Datum (JJJJ-MM-TT) für die Erinnerung in der App. Bei platform.openai.com unter „API keys“ steht, ob und wann der Schlüssel abläuft; 30 Tage vorher erscheint ein Hinweis im Chat. |
| `images.google_key_expires` | Text | leer | **Google-Schlüssel läuft ab am.** Datum (JJJJ-MM-TT) für die Erinnerung in der App. Bei aistudio.google.com unter „API keys“ bzw. in der Google Cloud Console steht, ob und wann der Schlüssel abläuft; 30 Tage vorher erscheint ein Hinweis im Chat. |
| `images.provider` | `auto` \| `openai` \| `google` | `auto` | **Bildanbieter.** auto (Standard): Die KI wählt je Bild, Google für Entwürfe und Änderungen (günstiger), OpenAI für Bilder mit Schrift oder höchster Qualität. openai oder google: immer dieser Anbieter. Ist nur ein Schlüssel eingetragen, wird dieser genommen. |
| `images.limit_month` | Zahl 0 bis 10000 | `30` | **Bilder je Person und Monat.** Wie viele Bilder von OpenAI oder Google jede Person im Monat erzeugen darf (Standard 30, 0 = kein Limit). Darüber fragt der Chat vor jedem weiteren Bild nach (Zulassen oder Ablehnen). SVG-Zeichnungen der KI zählen nicht, sie kosten nichts. |

## Sprechen mit der KI (`voice`)

Optional: mit der KI sprechen (Mikrofon-Knopf im Chat). Ausführlich in der [Dokumentation](../copilot/DOCS.md#sprechen-mit-der-ki-ab-0520).

In der Konfigurationsdatei: `voice:` mit den Feldern darunter.

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `voice.access_default` | `on` \| `off` | `off` | **Standard – wer darf sprechen.** Gilt für alle Benutzer ohne eigene Angabe: off (Standard) = niemand, on = alle. |
| `voice.browser_stt` | an/aus | an | **Spracherkennung des Browsers nutzen.** An (Standard): Ohne OpenAI-Schlüssel und ohne Spracherkennung in Home Assistant nutzt die App die kostenlose Spracherkennung des Browsers (Chrome, Edge, Safari; fehlt in Firefox). Der Ton geht dabei an Google bzw. Apple, nicht an dieses Add-on. Aus: dann geht Sprechen nur mit OpenAI-Schlüssel oder Home Assistant. |
| `voice.output` | `device` \| `service` | `device` | **Stimme.** device (Standard) = die Antwort liest das Gerät vor, kostenlos. service = derselbe Dienst wie die Spracherkennung liest vor (OpenAI oder Home Assistant), klingt besser, kostet bei OpenAI wenige Cent. |
| `voice.openai_voice` | `alloy` \| `ash` \| `ballad` \| `coral` \| `echo` \| `fable` \| `nova` \| `onyx` \| `sage` \| `shimmer` \| `verse` | `nova` | **Stimme bei OpenAI.** Gilt nur, wenn die Stimme von OpenAI kommt (Stimme: service und OpenAI-Schlüssel). Standard nova (weiblich). Weiblich klingen meist nova, shimmer, coral und sage; männlich echo, onyx und ash; alloy, fable, ballad und verse liegen dazwischen oder wirken je nach Satz anders. Zum Ausprobieren auf platform.openai.com/audio/playground. |
| `voice.instructions` | Text | leer | **Eigene Wünsche an die gesprochenen Antworten (optional).** Ein bis drei Sätze, die die KI bei jeder gesprochenen Antwort zusätzlich beachtet, zum Beispiel „Nenne Räume immer beim Namen“ oder „Antworte in einem Satz“. Höchstens 600 Zeichen. Leer: nur die Grundregeln (kurz, wie man spricht, keine Gerätenamen). |
| `voice.chat_days` | Zahl 0 bis 365 | `30` | **Sprachgespräche aufbewahren (Tage).** Sprachgespräche, die nicht in einem Chat begonnen wurden, stehen nicht in der Chatliste und werden nach so vielen Tagen gelöscht (Standard 30, 0 = behalten). Angeheftete bleiben. |
| `voice.openai_api_key` | Text (geheim) | leer | **OpenAI-Schlüssel nur für die Sprache (optional).** Schlüssel von platform.openai.com (API keys) für die Spracherkennung (und die Stimme bei output: service); wenige Cent pro Stunde Sprache, das API-Konto braucht eigenes Guthaben. Leer: es gilt der OpenAI-Schlüssel der Gruppe „Bilder“, und ist auch der leer, die Spracherkennung des Browsers. Aufnahmen gehen an OpenAI. |
| `voice.openai_key_expires` | Text | leer | **OpenAI-Schlüssel (Sprache) läuft ab am.** Datum (JJJJ-MM-TT) für die Erinnerung in der App, nur für den eigenen Schlüssel dieser Gruppe. 30 Tage vorher erscheint ein Hinweis im Chat. Ohne eigenen Schlüssel gilt das Datum bei „Bilder“ (images.openai_key_expires). |

## Domain-Zugang (Entra) (`domain`)

Optional; der Zugang ist an, sobald `domain.public_base_url` und eine Anmeldung eingetragen sind. Ausführlich in [Domain-Zugang](domain-zugang.md).

In der Konfigurationsdatei: `domain:` mit den Feldern darunter.

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `domain.public_base_url` | Text | leer | **Öffentliche Adresse.** z. B. https://chat.example.org. Muss zur Redirect-URI der Entra-App passen. Der Domain-Zugang ist an, sobald diese Adresse und eine Anmeldung (Entra oder ha_url) eingetragen sind. |
| `domain.ha_url` | Text | leer | **Adresse von Home Assistant für die Anmeldung über die Domain (optional).** Nur wenn sich Benutzer über die Domain mit ihrem Home-Assistant-Konto anmelden sollen: von außen erreichbare Adresse, z. B. https://ha.example.org. Dann erscheint auf der Anmeldeseite „Mit Home Assistant anmelden“. Leer lassen: nur Microsoft Entra. |
| `domain.entra_tenant_id` | Text | leer | **Entra: Verzeichnis-ID (Tenant).** GUID aus der Entra-App-Registrierung (Übersicht, „Verzeichnis-ID (Mandant)“). |
| `domain.entra_client_id` | Text | leer | **Entra: Anwendungs-ID (Client).** GUID aus der Entra-App-Registrierung (Übersicht, „Anwendungs-ID (Client)“). |
| `domain.entra_client_secret` | Text (geheim) | leer | **Entra: geheimer Clientschlüssel.** Wert des Clientschlüssels (Zertifikate & Geheimnisse). Läuft ab: Datum bei `domain.entra_secret_expires` eintragen. |
| `domain.entra_secret_expires` | Text | leer | **Entra-Schlüssel läuft ab am.** Datum (JJJJ-MM-TT) für die Erinnerung in der App. |
| `domain.session_days` | Zahl 1 bis 90 | `30` | **Anmeldedauer (Tage).** Wie lange eine Anmeldung über die Domain gültig bleibt (1–90). |
| `domain.public_trusted_proxies` | Liste | leer | **Vertrauenswürdige Proxys.** Adressen von Reverse-Proxys (z. B. Cloudflare-Tunnel-Container), deren Weiterleitungs-Header gelten dürfen. |

## Personalisierung (`look`)

Alles optional. Ausführlich in der [Dokumentation](../copilot/DOCS.md#personalisierung-name-logo-texte-farben).

In der Konfigurationsdatei: `look:` mit den Feldern darunter.

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `look.app_name` | Text | `HA Copilot` | **App-Name.** Name in Anmeldeseite, Titel und Seitenleiste. Standard: HA Copilot. Der Name des Eintrags in der Home-Assistant-Seitenleiste ist fest und lässt sich hier nicht ändern. |
| `look.language` | `de` \| `en` | `de` | **Sprache.** de (Standard) für Deutsch oder en für Englisch. Gilt für die Oberfläche, die Meldungen des Add-ons und die Standardsprache der KI-Antworten (wer in einer anderen Sprache schreibt, bekommt die Antwort weiterhin in dieser Sprache). Bereits gespeicherte Chats bleiben unverändert. |
| `look.login_text` | Text | leer | **Text auf der Anmeldeseite.** Kurzer Satz unter dem Namen, z. B. „Anmelden mit deinem Firmenkonto.“ |
| `look.login_placeholder` | Text | leer | **Beispiel-Adresse im Anmeldefeld.** Platzhalter im E-Mail-Feld der Anmeldeseite, z. B. name@firma.de. |
| `look.logo_tile` | an/aus | aus | **Logo auf dunkler Kachel.** Für Logos, die nur auf dunklem Grund gut aussehen (z. B. helle oder neonfarbene Logos): zeigt sie im hellen Design auf einer dunklen Kachel. |
| `look.follow_ha_theme` | an/aus | an | **Home-Assistant-Theme übernehmen.** An: Farben und Hell/Dunkel folgen live dem aktiven Theme von Home Assistant (in der Seitenleiste von HA) bzw. dem Standard-Theme (über die Domain). Aus: eingebaute Farben mit eigenem Hell/Dunkel-Schalter. |
| `look.theme_name` | Text | leer | **Theme für die Domain (optional).** Name eines Home-Assistant-Themes, das über die Domain gelten soll. Leer: Standard-Theme von Home Assistant. |

## Globale Einstellungen (`global`)

Normalerweise leer oder aus. Siehe [Betrieb](betrieb.md).

In der Konfigurationsdatei: `global:` mit den Feldern darunter.

| Option | Werte | Standard | Bedeutung |
|---|---|---|---|
| `global.restore_snapshot` | Text | leer | **Datenbank wiederherstellen.** Nur im Notfall: Name eines Snapshots, der beim nächsten Start eingespielt wird. Danach leeren. |
| `global.export_database` | an/aus | aus | **Datenbank exportieren (Umzug).** Nur für den Umzug in ein anderes Add-on (z. B. vom lokalen Add-on zum GitHub-Add-on): Beim Start wird eine Kopie aller Chats als copilot-export.sqlite3 in den Config-Ordner des Add-ons gelegt. Danach ausschalten und die Datei löschen. |

