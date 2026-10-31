# HA Copilot

Privater KI-Chat für Home Assistant. Jedes Profil hat eigene Chats, die für andere Profile unsichtbar sind.

**Stand: 0.27.4.** Was in welcher Version neu ist, steht im Reiter „Änderungsprotokoll“.

**Schnellzugriff (Dokumentation im Repository, mit Bildern):**
[Installation](https://github.com/dominikramachers/HA-Copilot/blob/main/docs/installation.md) ·
[Benutzer und Rechte](https://github.com/dominikramachers/HA-Copilot/blob/main/docs/benutzer.md) ·
[Alle Einstellungen](https://github.com/dominikramachers/HA-Copilot/blob/main/docs/einstellungen.md) ·
[Funktionen](https://github.com/dominikramachers/HA-Copilot/blob/main/docs/funktionen.md) ·
[Domain-Zugang](https://github.com/dominikramachers/HA-Copilot/blob/main/docs/domain-zugang.md) ·
[Betrieb](https://github.com/dominikramachers/HA-Copilot/blob/main/docs/betrieb.md)

Diese Seite ist die ausführliche Referenz. Sie behandelt: Profile, Zugang über das HA-Sidebar-Panel (Ingress) und zusätzlich über eine eigene Domain mit Microsoft-Entra-Anmeldung, Chat-Verwaltung und Antworten der KI als Live-Stream. Name, Logo, Texte und Farben lassen sich in der Konfiguration anpassen, die Oberfläche übernimmt das Theme von Home Assistant, und Benutzer pflegt man ausschließlich in der Add-on-Konfiguration. Beide Zugangswege führen auf dasselbe Profil und damit auf dieselben Chats.

## Konfiguration

### `profiles` (Benutzer)

Hier legst du fest, wer die App nutzen darf, und nur hier. Die App selbst hat keine Verwaltungsfunktionen. Im Konfigurationsfenster legt „Hinzufügen“ einen weiteren Benutzer an; nach dem Speichern das Add-on neu starten. (Ein Auswahlmenü mit den Home-Assistant-Benutzern gibt es in Konfigurationsfenstern von Add-ons technisch nicht. Dafür löst das Add-on den Benutzernamen selbst zur ID auf, siehe unten.)

| Feld | Bedeutung |
|---|---|
| `ha_user` | Home-Assistant-Benutzername des Benutzers: Anmeldename (z. B. `doralab`) oder Name der verknüpften Person, Groß-/Kleinschreibung egal. Der frei änderbare Anzeigename des HA-Benutzers zählt bewusst nicht. Das Add-on ermittelt daraus im Hintergrund die ID. Meist ist das das einzige Feld, das du brauchst. |
| `label` | Optional. Anzeigename in der Oberfläche. Leer: es gilt `ha_user`. |
| `ha_user_id` | Alternativ die Benutzer-ID (32 Hex-Zeichen). Nur nötig, wenn der Name nicht eindeutig ist oder HA nicht antwortet; hat Vorrang vor `ha_user`. |
| `entra_upn` | Optional. UPN des Entra-Kontos, so wie ihn Entra im Token als `preferred_username` liefert (bei Gastkonten die E-Mail-Adresse des Gastes, nicht der `…#EXT#…`-Name). Beim ersten Login über die Domain wird daran die Entra-Objekt-ID (`oid`) fest an das Profil gebunden. Ab dann zählt nur noch die `oid`. |
| `id` | Optional. Interner, stabiler Schlüssel (Kleinbuchstaben, Ziffern, `-`, `_`). Leer: wird aus dem Anzeigenamen gebildet. **Die Chats gehören diesem Schlüssel.** Nach dem Anlegen nicht mehr ändern. |

Pro Benutzer sind alle Wege kombinierbar: nur Home Assistant, nur Domain oder beides, und beides führt auf dieselben Chats.

Regeln:

- Eine unbekannte Identität erhält keinen Zugriff. Automatisch angelegt werden Benutzer nur, wenn du `all_ha_users` einschaltest (siehe unten).
- Zugeordnet wird nie über Anzeigenamen der App, nur über HA-Benutzer (ID bzw. aufgelöster Name) oder UPN.
- Ändert sich eine HA-Benutzer-ID (z. B. Benutzer neu angelegt) oder eine UPN, wird nur dieser Eintrag angepasst. Die Chats bleiben beim Profil.
- Wird ein Profil aus der Liste entfernt, bleiben seine Daten in der Datenbank erhalten, der Zugriff entfällt aber.

**Wie der Benutzername aufgelöst wird:** Beim Start fragt das Add-on Home Assistant nach den Benutzern (nur lesend) und ordnet `ha_user` zu. Antwortet HA noch nicht (z. B. beim Hochfahren), versucht das Add-on es alle 20 Sekunden erneut. Passt ein Name auf keinen oder mehrere Benutzer, steht das im Protokoll des Add-ons, und der Eintrag hat solange keinen Zugang; dann den Anmeldenamen oder die ID eintragen. Zusätzlich schreibt das Add-on beim Start alle Home-Assistant-Benutzer mit Anmeldename und ID ins Protokoll (Add-on → Protokoll).

**Erste Einrichtung:** Ein Eintrag nur mit Anzeigename (so ist es voreingestellt) startet die App, passt aber auf niemanden. Öffne die App in Home Assistant: Die Seite „Kein Zugriff“ zeigt deinen Benutzernamen und deine ID. Trage den Namen bei `ha_user` ein (oder die ID bei `ha_user_id`), speichere und starte das Add-on neu. Die ID findest du alternativ unter Entwicklerwerkzeuge → Template mit
`{% for p in states.person %}{{ p.name }}: {{ p.attributes.user_id }}{% endfor %}`
(es erscheinen nur Benutzer, die mit einer Person verknüpft sind).

#### Alle Home-Assistant-Benutzer zulassen (optional)

| Option | Bedeutung |
|---|---|
| `all_ha_users` | Standard `false`: nur die eingetragenen Benutzer. `true`: jeder Home-Assistant-Benutzer darf die App nutzen und bekommt beim ersten Zugriff automatisch ein eigenes Profil (Kennung `ha-` plus Anfang seiner HA-Benutzer-ID) mit eigenen, von anderen getrennten Chats. Die Liste oben wird dann nur noch für Sonderfälle gebraucht: eigener Anzeigename oder Microsoft-Anmeldung (`entra_upn`). Wer eingetragen ist, behält sein Profil. |
| `ha_users_excluded` | Nur mit `all_ha_users`: Benutzernamen, Namen oder IDs, durch Komma getrennt (z. B. `kind1, gast`). Diese Benutzer kommen nicht herein. Die Prüfung vergleicht ID, Anmeldename und Anzeigename. Ein Ausschluss per ID wirkt sofort auch für bestehende Domain-Sitzungen, einer per Name beim nächsten Anmelden. |

Beides ändert nichts an einer bestehenden Konfiguration: Ohne `all_ha_users` gilt weiter ausschließlich die Liste. Wer die Option später wieder ausschaltet, verliert den Zugang; seine Chats bleiben in der Datenbank. Ein Benutzer, der später doch eingetragen wird, bekommt dabei ein Profil mit neuer Kennung. Soll er seine bisherigen Chats behalten, trägst du bei `id` die bisherige Kennung `ha-…` ein (steht im Protokoll bei „Anmeldung“).

### Domain-Zugang

Alle folgenden Optionen werden nur gelesen, wenn `public_enabled` auf `true` steht. Fehlt dann etwas oder ist es ungültig, startet das Add-on nicht und nennt den Grund im Log.

| Option | Bedeutung |
|---|---|
| `public_enabled` | Schaltet den Domain-Listener (Port 8100) ein. Standard `false`. |
| `public_base_url` | Öffentliche Adresse, z. B. `https://chat.example.org` (https, ohne Pfad). |
| `entra_tenant_id` | Verzeichnis-ID (Mandanten-ID) als GUID. |
| `entra_client_id` | Anwendungs-ID (Client-ID) der App-Registrierung als GUID. |
| `entra_client_secret` | Geheimer Clientschlüssel der App-Registrierung (läuft ab, Ablaufdatum notieren). |
| `ha_url` | Optional. Von außen erreichbare Adresse von Home Assistant (https, ohne Pfad), z. B. `https://ha.example.org`. Schaltet auf der Anmeldeseite zusätzlich „Mit Home Assistant anmelden“ ein. Leer: nur Entra, wie bisher. |
| `session_days` | Wie lange man angemeldet bleibt, 1 bis 90 Tage (Standard 30). Die Sitzung verlängert sich bei Nutzung, endet aber spätestens nach 90 Tagen. |
| `public_trusted_proxies` | Optional. Adressen von Proxys (z. B. des cloudflared-Add-ons), deren Header `CF-Connecting-IP` für die Ratenbegrenzung verwendet werden darf. |

Entra-Angaben sind nötig, solange `ha_url` leer ist. Mit `ha_url` darfst du sie auch ganz weglassen (nur Home-Assistant-Anmeldung); halb ausgefüllt bleiben sie ein Fehler.

Ablauf Entra: Anmeldeseite (`/login`) → E-Mail-Adresse → Weiterleitung zu Microsoft → Rückkehr auf `/auth/callback` → Sitzung → `/new`. Die eingegebene Adresse ist nur ein Hinweis für Microsoft. Wer Zugriff bekommt, entscheidet allein das von Microsoft signierte Token, das gegen die Profilliste geprüft wird.

**Anmeldung mit Home Assistant (nur mit `ha_url`):** Die Anmeldeseite zeigt dann zusätzlich „Mit Home Assistant anmelden“ (ohne Entra-Angaben nur diesen Knopf). Der Knopf führt zur Anmeldung von Home Assistant selbst (mit allem, was dort eingerichtet ist, z. B. Zwei-Faktor); dieses Add-on sieht das Passwort nie. Danach tauscht das Add-on den Rückgabecode gegen ein Token, fragt nur ab, wer die Person ist, und widerruft das Token sofort wieder. Ob die Person hinein darf, entscheidet dieselbe Regel wie im HA-Panel: eingetragen (`ha_user`/`ha_user_id`) oder `all_ha_users` ohne Ausschluss. Home Assistant muss dafür von der Domain-Seite aus erreichbar sein (das Add-on ruft `ha_url` selbst auf). Die Anmeldung ist wie bei Entra an den startenden Browser gebunden und einmalig; zusätzlich ist sie ratenbegrenzt.

### `backend`

- `echo` (Standard): Testmodus. Gibt deine Nachricht nur zurück, es wird keine KI aufgerufen und nichts abgerechnet. Oben im Chat erscheint ein Hinweis.
- `claude`: echte Antworten über das Claude-Abo.

### `anthropic_api_key`, `claude_oauth_token`

Zugang zu Claude. Du brauchst eines von beiden; die Zugangsdaten gehören dir, sie sind nicht Teil des Add-ons und werden nirgends sonst gespeichert.

- `anthropic_api_key`: API-Schlüssel aus der [Claude-Konsole](https://platform.claude.com/). Abgerechnet wird nach Verbrauch. Das ist der von Anthropic vorgesehene Weg für Programme, die Claude einbinden. Hat Vorrang, wenn beide Felder gefüllt sind.
- `claude_oauth_token`: Langzeit-Token deines Abos, erzeugt mit `claude setup-token` (Claude-Code-CLI auf einem beliebigen Rechner, mit dem Abo angemeldet). **Nur für deinen eigenen, persönlichen Gebrauch.** Anthropic erlaubt es nicht, Abo-Zugänge anderer Personen über ein Programm zu leiten oder Abos weiterzugeben; die Nutzungsgrenzen eines Abos gelten für gewöhnliche, individuelle Nutzung. Lies dazu die aktuellen Nutzungsbedingungen von Anthropic und entscheide eigenverantwortlich (das hier ist keine Rechtsberatung). Anthropic kann solche Tokens sperren.

> **Wichtig:** Sobald mehrere Personen die App nutzen (mehrere Benutzer, `all_ha_users`) oder die Domain-Seite aktiv ist (`public_enabled`), ist ein Abo-Token der falsche Weg; nimm dann einen API-Schlüssel. Das Add-on schreibt in dem Fall beim Start eine Warnung ins Protokoll.

Beides nur hier im Add-on eintragen, nie in Chats, Repos oder Screenshots. Die Felder sind als Passwort maskiert.

### `model`, `default_effort`

Modell (Standard `claude-sonnet-5-5`) und voreingestellter Aufwand (`low`, `medium`, `high`). Im Chat lässt sich der Aufwand pro Nachricht im Menü rechts unter dem Eingabefeld umschalten („Aufwand“), die Auswahl merkt sich der Browser.

### `restore_snapshot`, `export_database`, `claude_token_expires`, `entra_secret_expires`

Siehe „Daten und Sicherung“. Normalerweise leer bzw. aus.

### `title_model`

Kleines, schnelles Modell (Standard `claude-haiku-5-5`), das nach der ersten Antwort einen Kurztitel für den Chat erzeugt (2 bis 5 Wörter, wie bei Claude selbst). Das verbraucht nur einen winzigen Teil deines Abo-Kontingents. Bis der Titel da ist, steht der Anfang deiner ersten Frage als Titel. Ein von dir umbenannter Chat wird nie überschrieben, und wenn die Titelerzeugung scheitert, bleibt der Anfangstitel stehen.

## Personalisierung: Name, Logo, Texte, Farben

Alles in diesem Abschnitt ist optional; ohne Angaben sieht die App neutral aus (Name „HA Copilot“, blaues Sprechblasen-Zeichen, Farben des Home-Assistant-Themes).

### Optionen

| Option | Bedeutung |
|---|---|
| `language` | `de` (Standard) oder `en`: Sprache von Oberfläche und Meldungen, siehe „Sprache“. |
| `app_name` | Name in Anmeldeseite, Browser-Titel, Seitenleiste und als Name der App auf dem Startbildschirm (höchstens 40 Zeichen). Standard `HA Copilot`. Der Eintrag in der Home-Assistant-Seitenleiste und der Add-on-Name stehen fest in `config.yaml` (`panel_title`) und folgen dieser Option nicht. |
| `login_text` | Satz unter dem Namen auf der Anmeldeseite. |
| `login_placeholder` | Beispiel-Adresse im E-Mail-Feld der Anmeldeseite. |
| `logo_tile` | Für Logos, die auf hellem Grund schlecht lesbar sind (z. B. leuchtendes Cyan): im hellen Design auf dunkler Kachel zeigen. |
| `follow_ha_theme` | An (Standard): Farben und Hell/Dunkel kommen von Home Assistant. Aus: eingebaute Farben mit eigenem Schalter Auto/Hell/Dunkel. |
| `theme_name` | Optional, nur für die Domain: Name eines HA-Themes. Leer: das Standard-Theme von Home Assistant. |
| `accent_color`, `background_color_light/dark`, `card_color_light/dark`, `text_color_light/dark` | Optional. Hex-Farben wie `#175CD3`. Überschreiben das Theme; leer lassen heißt „aus dem Theme“. |

### Logo und Dateien (Ordner `addon_config`)

Eigene Dateien legst du in den Ordner des Add-ons. In Home Assistant ist er unter `/addon_configs/<Ordnername>/` erreichbar (z. B. per Samba-Freigabe `addon_configs` oder mit dem Datei-Editor; der Ordnername ist die Add-on-Kennung, bei lokalen Add-ons `local_ki_chat`). Änderungen wirken sofort nach dem Neuladen der Seite, ein Neustart ist nicht nötig.

| Datei | Verwendung |
|---|---|
| `logo.png` (auch `.svg`, `.webp`, `.jpg`) | Quadratisches Zeichen für Seitenleiste und Startseite; auch Quelle für das Symbol, wenn kein `icon.png` da ist. |
| `logo-full.png` | Größeres Logo für die Anmeldeseite; ohne diese Datei dient `logo`. |
| `icon.png` | Symbol für Browser-Tab und Startbildschirm. Nur PNG, am besten 512 × 512 und deckend (ohne Transparenz). |
| `custom.css` | Eigene Stile (siehe unten). |

Die Dateien wirken sofort nach dem Neuladen der Seite; Änderungen an den Optionen (Name, Texte, Farben) nach dem Speichern und einem Neustart des Add-ons.

Dateien über 2 MB (CSS über 256 KB), leere Dateien und Verknüpfungen werden ignoriert. Fehlt eine Datei, gilt das neutrale Standardbild.

### So kommen die Farben zustande

1. **In Home Assistant eingebettet (Seitenleiste von HA):** Die App liest live die Farbvariablen des aktiven Themes von Home Assistant (Profil des angemeldeten Benutzers, Hell/Dunkel wie in HA) und folgt Änderungen sofort, ohne Neuladen. Der eigene Hell/Dunkel-Schalter ist dann ausgeblendet, weil HA das vorgibt.
2. **Über die Domain (oder wenn der Zugriff auf HA nicht klappt):** Das Add-on holt das *Standard-Theme* (hell und dunkel) von Home Assistant und liefert es als Stylesheet aus; es wird kurz zwischengespeichert. Hier gilt der eigene Schalter Auto/Hell/Dunkel. Die Domain-Seiten sind nicht angemeldet und kennen den einzelnen HA-Benutzer nicht, darum das Standard-Theme.
3. **Konfigurationsfarben** (`accent_color` usw.) überschreiben beides.
4. **`custom.css`** überschreibt alles.
5. Ohne HA-Zugriff und ohne Angaben greifen die eingebauten Farben (blauer Akzent, hell/dunkel).

Aus dem Theme werden nur diese Variablen verwendet: `primary-color` (Akzent), `primary-background-color` (Hintergrund), `card-background-color` (Flächen), `sidebar-background-color`, `primary-text-color`, `secondary-text-color`, `text-primary-color` (Schrift auf Akzent), `error-color`, `warning-color`. Alle anderen Werte (Linien, Chips, Sprechblase …) werden daraus gemischt. Eigene Variablen eines Themes (z. B. `--dl-…`) bleiben unberücksichtigt; wer sie nutzen will, verknüpft sie in `custom.css`.

### Eigenes CSS (`custom.css`)

Wird als letztes geladen und gewinnt immer. Die Anmeldeseite hat seit 0.27.1 einen dezent animierten Hintergrund (treibende Punkte in der Akzentfarbe, passend zu Hell und Dunkel). Er hält an, wenn der Tab verdeckt ist, und steht still, wenn das Gerät „Bewegung reduzieren“ verlangt. Ausschalten: `canvas#particles { display: none; }` in `custom.css`. Zum Anpassen genügt meist, die Farbvariablen zu setzen:

```css
:root {
  --accent: #C026D3;              /* Akzentfarbe */
  --bg: #FAF5FF;                  /* Hintergrund */
  --panel: #FFFFFF;               /* Karten, Eingabefeld */
  --text: #2E1065;                /* Schrift */
  --r-2: 6px;                     /* Radien: --r-1 … --r-4 */
}
:root[data-theme="dark"] {
  --accent: #E879F9;
  --bg: #1A0B2E;
}
```

Verfügbare Variablen: `--bg`, `--panel`, `--sidebar`, `--sheet`, `--text`, `--text-2`, `--accent`, `--on-accent`, `--danger`, `--warn-fg`, `--plate` (Fläche hinter dem Logo auf der Anmeldeseite), `--font`, `--mono`, `--r-1` bis `--r-4`. Abgeleitet (lassen sich ebenfalls überschreiben): `--panel-2`, `--muted`, `--line`, `--line-2`, `--chip`, `--accent-soft`, `--bubble`, `--danger-soft`, `--warn-bg`, `--scrim`. Hell/Dunkel erkennt man am Attribut `:root[data-theme="light"|"dark"]`.

## Oberfläche

- **Darstellung:** Hell, Dunkel oder Auto (folgt dem Gerät). Die Auswahl steht unten in der Seitenleiste und wird pro Browser gemerkt; in Home Assistant eingebettet gibt HA Hell/Dunkel vor und der Schalter entfällt. Die Farben kommen aus dem Theme von Home Assistant, siehe „Personalisierung“.
- **Seitenleiste:** Von oben nach unten: „Neuer Chat“, **Suchen** (ab 0.22.0, siehe „Suche, Export und eigene Daten“), **Geplant** (ab 0.21.0, siehe „Geplante Aufgaben“), **Angepinnt** (angepinnte Chats), **Projekte** (auf- und zuklappbar, Plus-Symbol legt ein Projekt an; das Plus in der Projektzeile startet einen neuen Chat darin) und **Chats**. Bei den Chats stehen nur die der letzten zwei Tage (Heute, Gestern); „Alle anzeigen“ blendet die älteren ein. Über das Symbol mit den drei Punkten bei jeder Zeile (am Computer beim Darüberfahren) öffnet sich das Aktionsfenster: anpinnen, umbenennen, in ein Projekt verschieben, als Markdown exportieren, löschen. Am Laptop und Tablet öffnet das ein kleines Menü direkt am Symbol (mit Trennlinien und Tastenkürzeln: U, P, R, D; „Projekt wechseln“ klappt ein Untermenü mit Suche auf; Pfeiltasten und Esc funktionieren). Abfragen wie Projekt anlegen, Umbenennen oder Löschen bestätigen erscheinen dort als Dialog in der Bildschirmmitte mit Schließen-Kreuz; auf dem Handy hochkant bleibt alles ein Fenster von unten.
- **Warteanzeige (ab 0.17.0):** Solange die KI arbeitet, steht unter der Frage ein kleines bewegtes Zeichen mit einem Hinweis („Denkt nach“, „Tüftelt“, „Wägt ab“ …) oder der gerade laufenden Aktion („Entitäten suchen: Licht“); wartet sie auf deine Freigabe, steht das dort. Nach 20 Sekunden erscheint die Wartezeit, nach einer Minute ein Hinweis, dass die Antwort auch bei verlassenem Chat fertig wird. Sobald Text ankommt, bleibt nur das kleine Zeichen unter dem Text. Mit „Bewegung reduzieren“ im Betriebssystem steht es still.
- **Lesestatus:** Eine neue Antwort macht den Chat ungelesen: Der Name steht fett mit einem Punkt in der Akzentfarbe, ein eingeklapptes Projekt zeigt den Punkt ebenfalls, und der Tab-Titel beginnt mit „●“. Sobald der Chat angezeigt wird, gilt er als gelesen. Das passiert auch, wenn du die Antwort bei geöffnetem Fenster abwartest. Kommt die Antwort, während das Fenster im Hintergrund liegt oder du auf einem anderen Gerät bist, bleibt der Punkt, bis du den Chat öffnest. Im Menü kannst du Chats von Hand als ungelesen oder gelesen markieren (der gerade offene Chat bleibt dann ungelesen, bis du ihn erneut öffnest). Der Status gehört zum Benutzer und gilt auf allen Geräten; die Liste aktualisiert sich beim Zurückkehren ins Fenster, alle 45 Sekunden und alle 3 Sekunden, solange irgendwo eine Antwort entsteht. Projekte lassen sich ebenfalls anpinnen (stehen dann oben) und umbenennen. Wird ein Projekt gelöscht, bleiben seine Chats erhalten und stehen danach wieder bei den Chats. Weitere Einträge wie Artefakte kommen als zusätzliche `nav-item`-Zeilen in `index.html` dazu.
- **Einklappen und Handy:** Im Web am Computer lässt sich die Seitenleiste über das Symbol oben links ein- und ausblenden (wird pro Browser gemerkt). In Home Assistant gibt es das nicht, dort wäre es eine zweite Seitenleiste neben der von HA. Auf dem Handy öffnet sich die Seitenleiste im Web wie gewohnt von links (Menüsymbol), in Home Assistant als Fenster von unten (Sprechblasen-Symbol).
- **Als App auf dem Handy:** Die Domain-Version lässt sich im Handy-Browser über „Zum Home-Bildschirm“ als eigene App ablegen (Name aus `app_name`, Symbol aus `icon.png`, Vollbild ohne Browserleiste; das Manifest erzeugt das Add-on). Sie hat keine Home-Assistant-Kopfzeile. Die App hat auf dem iPhone einen eigenen Speicher, die Anmeldung per Microsoft ist dort einmal neu nötig.
- **Kopfzeile:** Der Chat-Titel steht in einer eigenen Fläche über dem Chat. In Home Assistant auf dem Handy wandert das Chats-Symbol in die Eingabe (neben die Büroklammer unter dem Eingabefeld), die Kopfzeile erscheint dort nur, wenn ein Titel da ist.
- **Startseite:** Ein neuer Chat zeigt die Begrüßung und vier Startkarten. Ein Tipp darauf füllt die Eingabe mit dem Anfang einer Frage, die du fertig schreibst. Die Karten stehen als `STARTERS` in `app.js`.
- **Anhänge:** Über die Büroklammer, per Einfügen (Strg/Cmd+V, z. B. ein Screenshot) oder per Ziehen auf die Seite lassen sich bis zu 5 Dateien pro Nachricht anhängen: Bilder (PNG, JPEG, GIF, WebP; Fotos werden im Browser auf höchstens 2000 Pixel verkleinert), PDF und Textdateien (Code, Logs, CSV, JSON, YAML, Markdown …). Zum Senden brauchst du eine Frage zu den Dateien. Word (.docx), Excel (.xlsx) und PowerPoint (.pptx) werden im Add-on in Text umgewandelt (Überschriften, Listen, Tabellen; bei Excel alle sichtbaren Blätter mit Zellwerten und Datumsangaben, Formeln als zuletzt berechneter Wert; bei PowerPoint Folientexte und Notizen). Alte Formate (.doc, .xls, .ppt), passwortgeschützte Dateien und ZIP-Archive werden mit einer Meldung abgelehnt. Was mit den Dateien passiert, steht unter „Anhänge und Speicherplatz“.
- **Projektanweisungen:** Im Menü eines Projekts (⋯) unter „Anweisungen festlegen“ lässt sich ein Text (bis 4000 Zeichen) hinterlegen, der in jedem Chat des Projekts als Anweisung an Claude mitgeht, zum Beispiel Rolle, Stil oder feste Hintergründe. Ein Punkt hinter dem Projektnamen zeigt, dass Anweisungen aktiv sind; auf der Startseite eines neuen Chats im Projekt steht ein Hinweis. Die Anweisungen liegen als Text in der Datenbank (Chats ohne Projekt bekommen keine).
- **Dateien und Vorschau aus Antworten:** Claude liefert Text. Jeder Codeblock hat „Herunterladen“ und „Kopieren“; mit `datei=name.ext` in der Eröffnungszeile (z. B. ```` ```yaml datei=automations.yaml ````) bekommt die Datei ihren Namen, sonst `datei.<Endung>` nach der Sprache. Unter jeder Antwort speichert „Als Datei“ den ganzen Text als `antwort.md`. Auf dem Handy öffnet sich dafür das Teilen-Fenster („In Dateien sichern“), am Computer der normale Download. Vollständige HTML-Seiten (Codeblock `html`) bekommen eine Schaltfläche „Vorschau“: Die Seite läuft abgeschottet unter dem Codeblock (Vollbild möglich). Siehe „Vorschau-Sicherheit“.
- **Logo:** Das Logo steht auf der Anmeldeseite (auf einem dunklen „Türschild“), als Zeichen in der Seitenleiste (auch in Home Assistant auf Laptop und Tablet; auf dem Handy in Home Assistant im Chats-Fenster und auf der Startseite) und als Symbol für Browser-Tab und Startbildschirm. Mitgeliefert ist ein neutrales Zeichen; eigene Dateien siehe „Logo und Dateien“.
- **Schrift:** Roboto (variable Schrift, Lizenz OFL, liegt im Add-on unter `app/static/fonts/`). Es werden keine Schriften von fremden Servern geladen.
- **Handy:** Die Chats öffnen als Fenster von unten (Knopf „Chats“ in der Leiste), nicht als zweites Seitenmenü neben dem von Home Assistant. In HA eingebettet fehlen Marke und Anmeldename, weil HA sie selbst zeigt.
- **Anmeldeseite:** Über das HA-Panel unter `…/login` anzusehen. Auf dem Domain-Listener ist sie unter `/login` erreichbar. Links das Logo auf dunklem Grund, rechts Titel, E-Mail-Feld und der Knopf „Mit Microsoft anmelden“; auf dem Handy liegt das Schild oberhalb. Es gibt bewusst keine Hintergrundgrafik und keinen Leuchteffekt. Ist `ha_url` gesetzt, folgt unter einer Trennlinie „oder“ der Knopf „Mit Home Assistant anmelden“. Rückmeldungen nach der Anmeldung erscheinen als Meldung unter dem Eingabefeld. Auf der Domain steht in der Seitenleiste zusätzlich ein Abmelden-Knopf.

## Abrechnung

Der Add-on nutzt den Agent SDK mit deiner Abo-Anmeldung (Pro oder Max), nicht mit einem API-Schlüssel. Nach den Hilfeseiten von Anthropic (Stand Oktober 2026) zählt diese Nutzung zu den normalen Nutzungslimits deines Abos, zusammen mit claude.ai und Claude Code. Das separate monatliche API-Guthaben gibt es nur für Max und Team, nicht für Pro, und es ist hier nicht nötig. Damit nichts extra kostet:

- In den Claude-Einstellungen die zusätzliche Nutzung („Extra usage“ bzw. Usage Credits) **ausgeschaltet** lassen. Sind die Limits erreicht, kommt dann eine Meldung im Chat statt einer Rechnung.
- Der Add-on entfernt beim Start `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` und `ANTHROPIC_BASE_URL` aus seiner Umgebung, denn ein API-Schlüssel hätte Vorrang vor dem Abo-Token.
- Das Abo ist für deine persönliche Nutzung gedacht. Konten anderer Personen darüber laufen zu lassen ist laut Anthropic nicht erlaubt.
- Anthropic hat die Regeln für Agent-SDK-Nutzung zuletzt geändert und wieder pausiert. Bei Überraschungen auf der Hilfeseite „Use the Claude Agent SDK with your Claude plan“ nachlesen.

## So arbeitet die KI

- Die KI kennt die Person, mit der sie spricht, und das Datum. Projektwissen und Gedächtnis (siehe unten) bekommt sie als Werkzeuge, nicht als Dauer-Ballast im Gespräch.
- Der Verlauf liegt in der eigenen Datenbank; bei jeder Nachricht wird er neu mitgeschickt. Bei Claude selbst wird nichts gespeichert.
- **Lange Chats:** Wird der Verlauf zu groß (ab etwa 80 000 Zeichen), fasst die KI den älteren Teil zusammen, bevor sie antwortet (das dauert einige Sekunden, dabei steht „Fasse den früheren Verlauf zusammen …“). Die letzten rund 24 000 Zeichen bleiben wörtlich erhalten. Alle Nachrichten bleiben sichtbar und gespeichert; eine Trennlinie zeigt, ab wo Claude den Verlauf nur als Zusammenfassung kennt. Das spart außerdem Kontingent, weil nicht mehr jedes Mal der ganze Chat mitgeschickt wird. Schlägt das Zusammenfassen fehl, werden wie bisher die ältesten Nachrichten weggelassen.
- Die KI hat keinen Zugriff auf Dateien, Befehle oder das Netzwerk des Servers. Das Einzige, was sie darüber hinaus kann (auch in geplanten Aufgaben, dort nur lesend), sind die Home-Assistant-Werkzeuge (siehe nächster Abschnitt) und die GitHub-Werkzeuge (Abschnitt „GitHub“), jeweils nur so weit, wie die Stufe der Person es erlaubt, die Websuche (Abschnitt „Web, Modell und Nutzungslimit“) sowie das Erzeugen und Bearbeiten von Dateien zum Herunterladen (Abschnitte „Dateien erzeugen“ und „Dateien bearbeiten“); diese landen nur im Datenordner des Add-ons und werden nie ausgeführt.
- **Antworten laufen auf dem Server weiter (ab 0.14.0):** Deine Frage wird sofort gespeichert. Du kannst während einer Antwort den Chat wechseln, einen neuen Chat anfangen, die Seite neu laden oder den Tab schließen: Die Antwort wird trotzdem fertig erzeugt und gespeichert, der Chat steht danach als ungelesen in der Liste. Solange geantwortet wird, zeigt die Zeile in der Seitenleiste einen kleinen Kreisel (auch am eingeklappten Projekt). Öffnest du den Chat währenddessen wieder, siehst du die Antwort live weiterlaufen. Nach dem Neuladen öffnet sich derselbe Chat wieder (pro Browser-Tab). Gleichzeitig laufen höchstens zwei Antworten (alle Benutzer zusammen); eine dritte wird mit „Gerade zu viele Anfragen“ abgelehnt und nicht gespeichert.
- Mit Stopp (Pfeil-Knopf wird zum Quadrat) bricht der Server die Antwort ab und behält den bisherigen Text. Bricht Claude mit einem Fehler ab, bleibt eine bereits erhaltene Teilantwort ebenfalls erhalten. Kommt gar nichts an, wird die Frage wieder zurückgenommen, und dein Text steht im Eingabefeld.
- Pro Chat läuft nur eine Antwort gleichzeitig, insgesamt höchstens zwei.
- Der Chat-Titel steht zuerst als Anfang der ersten Frage da und wird danach von einem kleinen Modell durch einen Kurztitel ersetzt (siehe `title_model`). Er lässt sich jederzeit umbenennen.

## Zugriff auf Home Assistant (ab 0.15.0)

Die KI kann Home Assistant benutzen: Zustände ansehen, Verlauf und Logbuch lesen, Geräte schalten und, mit der höchsten Stufe, Automationen, Skripte, Szenen, Dashboards und Helfer bauen oder ändern. Das passiert in einem normalen Chat („Ist im Keller Licht an?“, „Schalte das Wohnzimmer aus“, „Lege eine Szene für den Abend an“). Alles wird in der Add-on-Konfiguration eingestellt, nichts davon in der Chat-Oberfläche.

**Stufen** (`ha_access` je Benutzer, sonst `ha_access_default`, vorgegeben `read`):

| Stufe | Darf |
|---|---|
| `none` | Gar nichts in Home Assistant. Die KI chattet ganz normal. |
| `read` | Lesen: Zustände, Verlauf, Logbuch, Bereiche, verfügbare Dienste. |
| `execute` | Zusätzlich Geräte bedienen (Licht, Schalter, Klima, Rollos, Medien, Szenen und Skripte starten, Helfer setzen, Benachrichtigungen). |
| `write` | Zusätzlich Automationen, Skripte und Szenen anlegen, ändern und löschen, Dashboards speichern, Helfer und Registereinträge ändern, Vorlagen auswerten. Ohne Einschränkung auf freigegebene Entitäten. |

Jeder kann die KI unabhängig von der Stufe im Alltag wie gewohnt nutzen. Beispiel: `adm` und `dora` mit `write`, `sam` mit `execute`, alle anderen haben ohne eigenen Eintrag nur `read`.

**Weitere Optionen:**

- `ha_write_confirm`: `ask` (vorgegeben) fragt vor **jeder Änderung** an der Konfiguration in Home Assistant im Chat nach. Es erscheint eine Karte mit „Zulassen“, „Ablehnen“ und „In diesem Chat immer zulassen“ (gilt nur bis zum Neustart des Add-ons und nur für diesen Chat). `always_allow` fragt bei Änderungen nicht nach. Das Bedienen von Geräten (`execute`) fragt nie nach, außer in den Fällen unten.
- `ha_limit_to_exposed` (vorgegeben an): Die Stufen `read` und `execute` sehen und bedienen nur Entitäten, die in Home Assistant für Assist freigegeben sind (Einstellungen, Sprachassistenten, Entitäten freigeben). Das ist dieselbe Auswahl wie für Alexa/Assist. Die Stufe `write` ist davon nie eingeschränkt.
- `ha_access_via_domain` (vorgegeben an): Aus, dann hat die KI über den Zugang mit eigener Domain keinen Zugriff auf Home Assistant, nur im HA-Panel.

**Immer mit Rückfrage**, egal wie eingestellt: Schlösser (`lock`), Alarmanlagen und Sirenen, Garagen-, Tür- und Tor-Antriebe (`cover` mit entsprechender Geräteklasse) sowie jede Aktion, die in einer Nachricht mit Dateianhang ausgelöst wird. Für diese Fälle gibt es kein „immer zulassen“.

**Nie möglich**, auch nicht mit `write`: Home Assistant oder das System neu starten oder beenden, Supervisor und Add-ons verwalten, Sicherungen anlegen oder löschen, Updates installieren, Benutzer und Anmeldedaten ändern, Dienste, die Programme oder Befehle ausführen (`shell_command`, `python_script`, `command_line` und ähnliche). Die Sperrliste prüft der Server, nicht die KI.

**Schutz vor untergeschobenen Anweisungen (Prompt Injection):**

- Die Rechte entscheidet allein der Server. Eine Stufe lässt sich nicht „überreden“: Werkzeuge, die die Stufe nicht hergibt, werden der KI gar nicht angeboten, und jedes Werkzeug prüft die Stufe beim Aufruf noch einmal selbst.
- Alles, was aus Home Assistant zurückkommt (Namen, Beschreibungen, Logbucheinträge, Dashboard-Texte) und jede angehängte Datei ist für die KI Information und keine Anweisung. Die Werkzeugergebnisse sind entsprechend gekennzeichnet, und die KI ist angewiesen, nur auf Wunsch der Person im Chat zu handeln.
- Wo es um Änderungen geht, entscheidet am Ende der Mensch: die Rückfrage zeigt die genaue Aktion samt Einzelheiten.
- Die KI sieht nur, was ihre Stufe zulässt: ohne `write` nur freigegebene Entitäten, keine Vorlagen, keine Konfigurationen.
- Bei Änderungen an Automationen, Skripten, Szenen und Dashboards wird die alte Fassung vorher in `/data/ha-backups/` gesichert (die letzten 60), damit sich ein Fehler zurücknehmen lässt.

**Sichtbarkeit:** Unter einer Antwort steht einklappbar „N Aktionen in Home Assistant“ mit jedem Schritt (gelesen, geschaltet, geändert, abgelehnt, fehlgeschlagen). Wartet die KI auf eine Rückfrage, zeigt die Seitenleiste einen orangen Punkt am Chat; die Antwort läuft erst weiter, wenn du antwortest (nach 10 Minuten gilt sie als abgelehnt).

**Voraussetzung:** Das Add-on braucht `homeassistant_api: true` (steht in der Konfiguration). Mit einem Supervisor-Token hat das Add-on in Home Assistant Administratorrechte, deshalb setzt der Server die Stufen selbst durch.

## Projektwissen und Gedächtnis (ab 0.16.0)

### Projektwissen

Zu jedem Projekt lassen sich Dateien hinterlegen, auf die die KI in allen Chats dieses Projekts zugreift: Notizen, Markdown, Text, Word, Excel, PDF oder ein ZIP mit solchen Dateien (Ordnerstruktur bleibt als Dateiname erhalten). Im Projektmenü: **Wissen hinzufügen** bzw. **Wissen verwalten**.

- Die KI bekommt nur das Inhaltsverzeichnis (Dateinamen). Inhalte holt sie bei Bedarf mit `knowledge_search` und `knowledge_read`. So bleibt auch ein großes Wissen bezahlbar und der Chat schnell.
- Das Wissen gehört dem Projekt und damit der Person, der das Projekt gehört. Andere Benutzer sehen es nicht.
- Gespeichert wird nur der Text (Datenbank, damit in der HA-Sicherung enthalten). Bilder, Programme und ähnliche Dateien in einem ZIP werden übersprungen; die Übersicht nach dem Import nennt jede übersprungene Datei mit Grund.
- Grenzen: 8 MB je Hochladen, 1 000 000 Zeichen je Datei, 300 Dateien und 15 Mio. Zeichen je Projekt, im ZIP höchstens 600 Einträge (4 MB je Datei, 60 MB entpackt). Eine Datei mit gleichem Namen wird ersetzt.

### Gedächtnis

Die KI führt ein eigenes Gedächtnis aus kurzen Einträgen (Thema, höchstens 800 Zeichen Inhalt), in zwei getrennten Bereichen:

- **Haushalt:** gilt für alle Personen dieses Add-ons (Hausregeln, Geräte, Gewohnheiten). Wer ins Haushaltsgedächtnis schreiben darf, regelt `memory_household_writers`.
- **Person:** gehört nur dem jeweiligen Profil. Andere Profile können es weder lesen noch ändern, auch nicht über die KI.

Die KI weiß, mit wem sie spricht, legt nützliche und dauerhafte Dinge von selbst ab (`memory_save`), aktualisiert Einträge zum selben Thema und löscht auf Wunsch (`memory_forget`). Beides steht im Aktionsprotokoll unter der Antwort („Gemerkt“, „Vergessen“). In der Seitenleiste öffnet **Gedächtnis** die Einträge: dort lassen sich eigene Einträge ansehen, ergänzen und löschen (zweimal tippen bestätigt). Eine Grenze von 100 Einträgen je Person und 150 für den Haushalt verhindert, dass es unendlich wächst.

**Optionen** (nur in der Add-on-Konfiguration):

| Option | Wirkung |
|---|---|
| `memory_enabled` | Standard `true`. Aus: kein Gedächtnis, keine Werkzeuge, kein Eintrag im Gespräch. Gespeicherte Einträge bleiben erhalten. |
| `memory_household_writers` | `all` (Standard): jedes Profil darf den Haushalt ergänzen. `ha_write`: nur Profile mit Home-Assistant-Stufe `write`. Lesen dürfen immer alle. |
| `ha_scan_days` | Standard `7`: Smarthome-Überblick beim ersten Start und danach alle N Tage einlesen (siehe unten). `0` = nie automatisch, nur auf Knopfdruck. Höchstens 90. |

**Schutz:**

- Passwörter, Tokens, Schlüssel, IBANs und ähnliche Geheimnisse lehnt der Server als Gedächtniseintrag ab.
- Nach einem Dateianhang oder nachdem die KI eine Datei, Home-Assistant-Daten oder Projektwissen gelesen hat, fragt sie vor jeder Gedächtnisänderung im Chat nach. So kann ein untergeschobener Text (Dateiinhalt, Entitätsname) nichts unbemerkt dauerhaft festschreiben.
- Gedächtnis und Wissen werden der KI als Information übergeben, nicht als Anweisung. Das gilt auch für den Smarthome-Überblick; seine Namen stammen aus Home Assistant und sind als Daten gekennzeichnet.
- Die Einträge liegen in der Datenbank und sind in der Sicherung enthalten.

### Smarthome-Überblick (ab 0.17.0)

Damit die KI deine Home-Assistant-Umgebung von Anfang an kennt, liest das Add-on selbst einen Überblick ein und legt ihn als Haushaltseinträge ab (Thema beginnt mit „HA · “). Das passiert ohne KI-Aufruf, nur mit lesenden Abfragen an Home Assistant, und kostet daher keine Nachrichten deines Abos.

- **Wann:** etwa 30 Sekunden nach dem ersten Start, danach alle `ha_scan_days` Tage (Standard 7), außerdem auf Knopfdruck („Neu einlesen“ im Gedächtnis-Dialog). Nach einem Fehler (z. B. Home Assistant noch nicht bereit) wird nach etwa 15 bis 25 Minuten erneut versucht. Nur aktiv, wenn das Gedächtnis an ist und mindestens ein Profil Zugriff auf Home Assistant hat.
- **Was:** Name, Version, Zeitzone und Einheiten; Etagen und Bereiche; je Bereich die steuerbaren Entitäten (Licht, Schalter, Rollläden, Klima, Medien …) und Sensoren mit ihrer Art; Entitäten ohne Bereich; Entitäten je Typ; Integrationen; Automationen, Skripte und Szenen mit Namen; Helfer; Personen und Zonen (nur Namen); Dashboards. Deaktivierte, ausgeblendete und Diagnose-Entitäten werden übersprungen.
- **Was nicht:** keine Zustandswerte, keine Koordinaten, keine Zugangsdaten, keine Konfigurationsinhalte von Automationen. Details holt sich die KI bei Bedarf live mit den Home-Assistant-Werkzeugen.
- **Wer sieht es:** alle Profile mit Zugriff auf Home Assistant (mindestens `read`); Profile mit `none` sehen den Überblick nicht, und die KI bekommt ihn für sie nicht. Anders als die KI-Werkzeuge ist der Überblick nicht auf in Assist freigegebene Entitäten beschränkt; wer das nicht möchte, setzt `ha_scan_days: 0` oder schaltet das Gedächtnis aus.
- **Für die KI:** Die wichtigsten Einträge (System, Etagen und Bereiche, Entitäten je Typ, Integrationen, Personen) stehen im Kontext, höchstens etwa 3500 Zeichen; den Rest liest sie mit `overview_read` (ohne Thema: Liste der Themen). Das Gespräch bleibt dadurch schlank.
- **Ablage:** Jeder Lauf ersetzt die „HA · “-Einträge vollständig (alles oder nichts; schlägt ein Lauf fehl, bleibt der alte Stand). Sie zählen nicht gegen die 150 Einträge des Haushalts, erscheinen nicht in der Liste „Haushalt“ und sind weder von der KI noch von Hand änderbar. Eigene Einträge mit dem Thema „HA · …“ sind nicht möglich.
- **Status:** Während des Einlesens zeigt ein Hinweis oben den Fortschritt (Schritt x von 7), danach kurz das Ergebnis oder bei Fehlern „Erneut versuchen“. Im Dialog „Gedächtnis“ zeigt der Bereich „Home Assistant-Überblick“ Stand, Anzahl und die Einträge.

## GitHub (ab 0.19.0)

Die KI kann mit GitHub arbeiten: Repositories und Dateien lesen, Code durchsuchen, Issues, Pull Requests, Commits und Workflow-Läufe ansehen, und (mit Schreibrecht) Dateien einchecken, Zweige und Pull Requests anlegen, Issues schreiben, Pull Requests mergen und neue Repositories anlegen. Beispiele: „Schau in doralab/smarthome, warum der letzte Lauf fehlschlägt“, „Lege das Skript aus dem Chat als Pull Request in doralab/smarthome ab“, „Fass die offenen Issues zusammen“.

**Einrichten (einmal, nur in der Add-on-Konfiguration):**

1. Bei GitHub unter Settings → Developer settings → Personal access tokens → *Fine-grained tokens* ein Token erzeugen. Empfehlung: nur die Repositories auswählen, mit denen die KI arbeiten soll. Rechte (Repository permissions): *Contents* = Read and write, *Pull requests* = Read and write, *Issues* = Read and write, *Actions* = Read-only, *Metadata* = Read-only. Zum Lesen reichen jeweils Read-only. Neue Repositories im eigenen Konto kann GitHub nur mit einem klassischen Token (Recht „repo“) anlegen, nicht mit einem fine-grained Token; ohne klassisches Token meldet die KI beim Anlegen einen Fehler, alles andere funktioniert. Wenn die KI keine Repositories anlegen soll, nimm einfach das fine-grained Token.
2. Das Token bei `github_token` eintragen und das Add-on neu starten. Das Token liegt nur in der Konfiguration, geht ausschließlich an `api.github.com` und taucht weder im Chat noch im Verlauf noch in Fehlermeldungen auf.
3. Mit `github_access_default` oder `github_access` je Benutzer festlegen, wer GitHub nutzen darf (Standard `none`).

**Stufen** (`github_access` je Benutzer, sonst `github_access_default`):

| Stufe | Darf |
|---|---|
| `none` | Kein GitHub. |
| `read` | Lesen: Repositories, Ordner, Dateien, Code-Suche, Issues, Pull Requests (mit Änderungen), Commits, Zweige, Tags, Releases, Workflow-Läufe. |
| `write` | Zusätzlich: Dateien in einem Commit schreiben, ändern, löschen (auch mehrere Dateien auf einmal und Dateien aus dem Chat, z. B. ein erzeugtes Skript oder Dokument), Zweige anlegen, Pull Requests, Issues und Kommentare schreiben und ändern, Pull Requests mergen, Repositories anlegen (standardmäßig privat). |

**Weitere Optionen:**

- `github_repos`: Freigabeliste, durch Komma getrennt, z. B. `doralab/smarthome, doralab/*`. Leer = alles, was das Token erreicht. Mit Liste kann die KI nur diese Repositories sehen und ändern; auch der allgemeine Zugang (`github_api`) ist dann auf `/repos/besitzer/name/…` beschränkt.
- `github_write_confirm`: `ask` (vorgegeben) fragt vor **jeder Änderung** im Chat nach (Zulassen, Ablehnen, „In diesem Chat immer zulassen“). `always_allow` fragt bei gewöhnlichen Änderungen nicht nach.

**Immer mit Rückfrage**, egal wie eingestellt, und ohne „immer zulassen“: Commit auf den Hauptzweig, Commits mit Workflow-Dateien (`.github/workflows/`, sie führen bei GitHub Code aus), Pull Requests mergen, Repositories anlegen, jedes `DELETE`, sowie jede Änderung, nachdem die KI in derselben Antwort Inhalte aus Home Assistant, Projektwissen oder GitHub gelesen hat oder wenn die Nachricht einen Dateianhang hat. Die Rückfrage zeigt Repository, Zweig, Nachricht und jede Datei. Den Zweig prüft der Server vor der Rückfrage, damit du nichts bestätigst, was ohnehin scheitern würde. Empfehlung für bestehende Projekte: Änderungen auf einem neuen Zweig mit Pull Request, nicht direkt auf den Hauptzweig; die KI ist so angewiesen.

**Nie möglich**, auch nicht über den allgemeinen Zugang: Repository löschen, umbenennen, übertragen, Sichtbarkeit ändern oder archivieren, Mitarbeiter und Einladungen, Deploy- und SSH-Schlüssel, Webhooks, Geheimnisse und Variablen von Actions, Runner, Schutzregeln und Rulesets, Umgebungen, Pages, Forks, Sicherheitseinstellungen sowie das Löschen des Hauptzweigs. Das erzwingt der Server, nicht die KI. Das muss der Mensch selbst bei GitHub tun.

**Wichtig zu wissen:**

- Das Token gehört dem Betreiber des Add-ons. Wer die Stufe `read` oder `write` hat, sieht damit alle Repositories, die das Token erreicht (auch private), soweit `github_repos` nichts anderes festlegt. Vergib die Stufe also nur an Personen, denen du das zutraust, und beschränke das Token und die Liste auf das Nötige.
- Alles, was aus GitHub kommt (Dateien, Issues, Kommentare, Commit-Nachrichten), ist für die KI Information und keine Anweisung und entsprechend gekennzeichnet. Wegen des Risikos untergeschobener Anweisungen fragt jede Änderung nach, sobald in derselben Antwort GitHub-Inhalte gelesen wurden.
- Commits laufen über die Git-Schnittstelle von GitHub: mehrere Dateien landen in **einem** Commit; es wird nie erzwungen überschrieben (`force` ist aus), ein Konflikt wird gemeldet. Dateien bis 8 MB, bis 60 Dateien und 24 MB je Commit.
- **Sichtbarkeit:** Unter der Antwort steht einklappbar „N Aktionen bei GitHub, davon M Änderungen“ mit jedem Schritt; bei Commits, Pull Requests und Issues gibt es einen Link „Öffnen“ (nur Adressen auf github.com werden angezeigt).
- GitHub begrenzt Anfragen (bei Tokens 5 000 je Stunde, die Code-Suche deutlich weniger); wird das Limit erreicht, sagt die KI das.

## Web, Modell und Nutzungslimit (ab 0.20.0)

**Websuche.** Die KI kann im Web suchen und Seiten lesen, wenn es nötig ist (Preise, Versionen, Nachrichten, Regeln) oder wenn du sie darum bittest („Recherchiere …“, „Schau nach, ob …“). Unter der Antwort steht einklappbar „Recherche im Web (2 Suchen, 3 Seiten gelesen)“ mit jedem Schritt; am Ende nennt die KI ihre Quellen.

- **Einstellen:** `web_access_default` (`on` vorgegeben, `off`) und je Benutzer `web_access`. Im Chat lässt sich die Websuche im Menü rechts unter dem Eingabefeld (Knopf mit Modell und Aufwand, z. B. „Sonnet 5.5 Mittel“) je Browser ein- und ausschalten; ein kleiner Punkt am Knopf zeigt „aus“. Ausgeschaltet wird sie auch gar nicht erst angeboten.
- **Suche:** das eingebaute Werkzeug von Claude (läuft bei Anthropic, nicht in deinem Netz). Ob es mit deinem Abo bzw. API-Schlüssel nutzbar ist, entscheidet Anthropic; gibt es einen Fehler, steht er in der Aktionszeile und die KI sagt es. Die Suche verbraucht Kontingent deines Abos wie jede andere Nachricht, keine Zusatzkosten.
- **Seiten lesen** (`web_fetch`) macht das Add-on selbst, nicht Claude. Deshalb ist es gegen Zugriffe aufs Heimnetz abgesichert: Es werden nur öffentliche Adressen geladen. Gesperrt sind private und lokale Adressen (192.168.x.x, 10.x.x.x, 172.16–31.x.x, 127.x.x.x, 169.254.x.x, CGNAT, IPv6 lokal und eingebettete Varianten wie `::ffff:10.0.0.1`), interne Namen (`localhost`, `*.local`, `*.lan`, `*.internal`, Namen ohne Punkt), Zugangsdaten in der Adresse, alle Ports außer 80, 443, 8080, 8443 und Nicht-Web-Adressen (`file:`, `ftp:` …). Geprüft wird die Adresse, mit der die Verbindung tatsächlich aufgebaut wird (kein Zeitfenster für DNS-Tricks), und bei jeder Weiterleitung neu. HTML wird in lesbaren Text umgewandelt (ohne Skripte, Menüs, Fußzeilen), PDF, Text und JSON werden gelesen; Bilder und Binärdaten nicht. Grenzen: 3 MB je Seite, 20 Sekunden, 12 Seiten je Antwort.
- **Schutz vor untergeschobenen Anweisungen:** Was aus dem Web kommt, ist für die KI Information und keine Anweisung und wird so gekennzeichnet. Hat die KI in einer Antwort etwas aus dem Web gelesen, fragt danach jede Änderung (Gedächtnis, GitHub, Home Assistant: auch das Bedienen von Geräten) im Chat nach, ohne „immer zulassen“. Die KI ist angewiesen, nichts Vertrauliches in Suchanfragen und Adressen zu schreiben. Ganz auszuschließen ist das bei jedem Web-Zugriff nicht: Suchanfragen verlassen dein Haus. Wer das nicht möchte, stellt `web_access_default` auf `off`.

**Modellwahl.** `model` ist das Standard-Modell für neue Chats. Mit `models` (durch Komma getrennt, z. B. `claude-opus-5-5, claude-haiku-5-5`) legst du die weiteren Modelle fest, die man im Chat wählen kann; das Standard-Modell ist immer dabei. Die Auswahl steht neben den Denktiefe-Knöpfen (Regler-Symbol mit dem Namen des Modells); das kleine Menü zeigt die Modelle und darunter die Websuche als Schalter, gilt für diesen Chat und wird dort gemerkt; neue Chats beginnen mit dem zuletzt gewählten Modell dieses Browsers. Der Server nimmt nur Modelle aus der Liste an. Ist `models` leer, stehen `claude-opus-5-5` und `claude-haiku-5-5` zur Auswahl; mit `none` wird die Auswahl abgeschaltet. Welche Modelle dein Abo zulässt, entscheidet Anthropic: Ein nicht verfügbares Modell meldet einen Fehler mit Hinweis auf das Modell, der Chat bleibt benutzbar. Chat-Titel und Zusammenfassungen laufen unabhängig davon mit `title_model` bzw. dem Standard-Modell.

**Hinweis auf das Nutzungslimit.** Dein Claude-Abo hat Limits (Sitzungslimit über 5 Stunden, Wochenlimits). Das Programm meldet dem Add-on, wenn ein Limit fast erreicht ist oder erreicht wurde; dann erscheint oben über dem Chat ein Hinweis, z. B. „Das Sitzungslimit (5 Stunden) ist zu 83 % verbraucht. Es wird um 16:30 Uhr zurückgesetzt.“ bzw. „… ist erreicht. Es wird morgen um 08:00 Uhr zurückgesetzt.“ (Ortszeit deines Browsers). Der Hinweis verschwindet von selbst, sobald das Limit zurückgesetzt ist, und lässt sich bis zum Schließen des Tabs wegklicken. Er gilt für alle Benutzer gleich, weil das Limit dem Abo gehört; der Stand wird gespeichert und übersteht einen Neustart. Erreicht eine Antwort das Limit, steht die Rücksetzzeit auch in der Fehlermeldung. Mit API-Schlüssel statt Abo gibt es diese Meldungen nicht.

## Geplante Aufgaben (ab 0.21.0)

Unter „Neuer Chat“ steht der Menüpunkt **Geplant**. Dort legst du Aufgaben an, die die KI zu festen Zeiten erledigt, auch wenn niemand zusieht, zum Beispiel jeden Morgen um 7 Uhr eine Zusammenfassung, was im Haus offen oder auffällig ist, oder jeden Freitag eine Übersicht der neuen Issues in einem Repository. Jede Aufgabe hat:

- **Name** und **Auftrag** (bis 4000 Zeichen). Der Auftrag muss ohne Rückfrage auskommen, die KI kann während eines Laufs nichts nachfragen.
- **Zeitplan:** täglich, Montag bis Freitag, wöchentlich (an gewählten Wochentagen), monatlich (am gewählten Tag; der 31. gilt in kürzeren Monaten am letzten Tag) oder einmalig (Datum und Uhrzeit), jeweils mit Uhrzeit. Bewusst kein stündlicher Takt: Jeder Lauf verbraucht Kontingent deines Abos.
- optional ein **Modell** (wenn `models` Auswahl bietet), ob die KI **im Web recherchieren** darf, und die **Benachrichtigung** (siehe unten).

Auf der Seite lässt sich jede Aufgabe pausieren und fortsetzen (Schalter), sofort ausführen („Jetzt ausführen“; der Zeitplan bleibt davon unberührt), bearbeiten und löschen. Jede Person hat bis zu 20 Aufgaben, die anderen sehen sie nicht.

**Was bei einem Lauf passiert:** Zur Zeit legt das Add-on einen neuen Chat an (Name der Aufgabe und Datum, in der Liste mit einem kleinen Uhr-Symbol), trägt den Auftrag als erste Nachricht ein und lässt die KI antworten. Die Antwort steht danach als ungelesener Chat in der Liste. Läuft die Aufgabe gerade, kannst du den Chat öffnen und zusehen. Im Chat kannst du danach ganz normal weiterfragen, dort gelten wieder die üblichen Rechte der Person samt Rückfragen. Auf der Aufgabenseite steht der nächste Lauf, der letzte Lauf mit Ergebnis (Link zum Chat) und, wenn etwas nicht klappte, der Grund.

**Bewusst enger als ein Chat:** Weil niemand zusieht und Rückfragen nicht beantworten kann, ist alles Verändernde gar nicht erst angeboten:

- Home Assistant nur **lesen** (Zustände, Verlauf, Logbuch), auch wenn die Person Schalten oder Ändern darf. Bei Stufe `none` ganz ohne Home Assistant.
- GitHub nur **lesen**, das Gedächtnis nur **lesen**, nichts speichern oder löschen.
- Websuche und Seiten lesen (wenn für die Person und die Aufgabe erlaubt) und erzeugte Dateien (Word, Excel, PDF …) bleiben möglich. Gelesene Web-Inhalte sind wie immer Daten und keine Anweisungen; ändern kann der Lauf ohnehin nichts.
- Antworten und Dateien landen nur im Chat der Person.

**Wann ein Lauf nicht stattfindet:** War das Add-on zur Zeit nicht aktiv (Neustart, Sicherung), wird die Aufgabe bis zu 2 Stunden danach nachgeholt, später übersprungen; auf der Aufgabenseite steht dann „Übersprungen“. Ist das Nutzungslimit deines Abos erreicht (siehe „Hinweis auf das Nutzungslimit“), wird der Lauf ebenfalls übersprungen. Es laufen höchstens zwei Antworten gleichzeitig (Chats und Aufgaben zusammen); ist alles belegt, wartet die Aufgabe und startet im nächsten 30-Sekunden-Takt. Eine einmalige Aufgabe schaltet sich nach dem Lauf aus. Entfernst du eine Person aus der Konfiguration, ruhen ihre Aufgaben.

**Zeitzone:** Uhrzeiten gelten in der Zeitzone von Home Assistant. Das Add-on fragt sie kurz nach dem Start ab und übernimmt sie (steht im Protokoll: „Zeitzone für geplante Aufgaben: …“); antwortet Home Assistant dann nicht, gilt bis dahin die Zeitzone, die der Supervisor dem Add-on mitgibt. Die Anzeige im Browser („Nächster Lauf: Fr., 30.10., 08:15 Uhr“) rechnet in die Zeit deines Geräts um.

**Benachrichtigung** je Aufgabe:

- *Nur im Chat* (Standard, wenn nichts anderes möglich ist): Der Chat steht ungelesen in der Liste.
- *Zusätzlich Meldung in Home Assistant*: eine Meldung in der Glocke von Home Assistant (`persistent_notification`) mit dem Anfang der Antwort. Je Aufgabe gibt es eine Meldung, die beim nächsten Lauf ersetzt wird.
- *Zusätzlich aufs Handy*: Dienst `notify_service` der Person (nächster Absatz); Voreinstellung, sobald die Person einen hat. Ist `public_base_url` gesetzt, öffnet ein Tipp auf die Benachrichtigung die Domain-Adresse.

Es wird nur nach einem erfolgreichen Lauf benachrichtigt. Schlägt die Benachrichtigung selbst fehl, steht das bei der Aufgabe.

### `notify_service` und fertige Antworten (Benachrichtigung aufs Handy)

Im Benutzer-Eintrag der Konfiguration kannst du den Benachrichtigungsdienst der Person eintragen, z. B. `notify.mobile_app_pixel` (Entwicklerwerkzeuge, Aktionen, Suche nach „notify“). Er wird für zwei Dinge benutzt:

1. geplante Aufgaben mit „Zusätzlich aufs Handy“,
2. **fertige Antworten:** Dauert eine Antwort länger als etwa 45 Sekunden und niemand sieht mehr zu (Chat gewechselt, Tab geschlossen, Seite neu geladen), bekommt die Person eine Benachrichtigung mit dem Chat-Titel und dem Anfang der Antwort. Mit `notify_long_answers: false` ist das aus. Sieht die Person zu, kommt nichts.

Die Benachrichtigung zeigt den Anfang der Antwort, also auch auf dem Sperrbildschirm. Wer das nicht möchte, trägt keinen Dienst ein. Browser-Benachrichtigungen (Web Push) gibt es nicht; dafür bräuchte die App einen Dienst im Browser, der auch bei geschlossenem Tab läuft.

`schedules_enabled: false` schaltet den Menüpunkt ab; bestehende Aufgaben ruhen dann.

**Grenzen:** Die Läufe sind mit einer nachgebildeten KI getestet, nicht mit der echten Claude-Anbindung. Ob jeder Auftrag ohne Rückfrage ein gutes Ergebnis liefert, hängt vom Auftrag ab; schreib ihn so, dass er auch ohne dich klar ist („Wenn ein Sensor nicht antwortet, nenne ihn im Ergebnis“). Die Benachrichtigungen an Home Assistant sind gegen eine Nachbildung getestet.

## Suche, Export und eigene Daten (ab 0.22.0)

**Suche.** „Suchen“ in der Seitenleiste (am Computer auch Strg+Umschalt+F bzw. ⇧⌘F am Mac) durchsucht Titel und Nachrichten aller *deiner* Chats, auch die der geplanten Aufgaben. Es zählen nur Chats mit allen eingegebenen Wörtern (die Wörter können in verschiedenen Nachrichten stehen), ohne Beachtung von Groß- und Kleinschreibung und Umlautpunkten („kuche“ findet „Küche“). Zu jedem Treffer stehen Titel, Datum und ein Ausschnitt mit markierter Fundstelle; Enter öffnet den ersten Treffer, die Pfeiltasten wechseln zwischen den Treffern. Es werden höchstens 30 Chats gezeigt, die neuesten zuerst, und mindestens zwei Zeichen verlangt. Gesucht wird nur im Text der Nachrichten, nicht in Anhängen, Aktionsprotokollen, Projektwissen oder erzeugten Dateien.

**Chat exportieren.** Im Menü eines Chats (⋯) speichert „Als Markdown exportieren“ den Chat als `.md`-Datei mit Titel, Projekt, Datum, allen Nachrichten, den Namen der Anhänge und den Aktionen der KI (Home Assistant, GitHub, Web).

**Meine Daten** (Konto-Menü unten in der Seitenleiste):

- **Alle Chats exportieren:** Eine ZIP-Datei mit allen Chats als Markdown (je Projekt ein Ordner, geplante Aufgaben in einem eigenen Ordner), `projekte.md` (Projekte mit Anweisungen), `gedaechtnis.md` (nur dein persönliches Gedächtnis, nicht das des Haushalts) und `geplante-aufgaben.md`. Nicht enthalten sind hochgeladene Projektdateien und von der KI erzeugte Dateien (sie laufen ohnehin ab). Der Export ist auf wenige Abrufe je 10 Minuten begrenzt.
- **Alle Chats löschen:** Entfernt alle deine Chats mit Nachrichten und erzeugten Dateien unwiderruflich. Projekte, Gedächtnis und geplante Aufgaben bleiben. Zur Sicherheit gibt es zwei Schritte: erst eine Rückfrage, dann muss das Wort LÖSCHEN eingetippt werden. Läuft gerade noch eine Antwort, wird abgelehnt (erst beenden oder abwarten). Einen einzelnen Chat löschst du weiter im Chat-Menü.

Alles gilt nur für das eigene Profil; andere Personen sind nie betroffen. Die Löschfunktion ist keine Einstellung für alle, sondern bewusst nur für die eigenen Daten gedacht.

## Einrichtungsprüfung (ab 0.25.0)

Im Konto-Menü (unten links) gibt es **Einrichtungsprüfung**, wenn du den Chat über Home Assistant öffnest. Das Fenster listet auf, was eingerichtet ist und was fehlt: **Nötig** (ohne das läuft der Chat nicht richtig, z. B. der Zugang zu Claude), **Empfohlen** (z. B. Anmeldeversuche hinter dem Tunnel je Besucher zählen) und **Optional** (GitHub, Domain-Zugang, Benachrichtigungen, Erinnerung an Ablaufdaten). Jeder Punkt, der Aufmerksamkeit braucht, klappt die genauen Schritte auf. „Erneut prüfen“ liest die Konfiguration noch einmal und fragt Home Assistant und GitHub kurz ab.

- Beim ersten Start nach der Installation läuft der Chat im Testmodus (`backend: echo`). Oben erscheint dann ein Hinweis mit dem Knopf „Schritte anzeigen“, der direkt die Anleitung für den Claude-Zugang öffnet.
- Die Prüfung zeigt nie ein Geheimnis, nur ob es gesetzt ist. Bei GitHub steht zusätzlich der Kontoname, zu dem das Token gehört.
- Bei einem Umzug in ein anderes Add-on (siehe „Daten und Sicherung“) nennt die Prüfung den neuen Hostnamen, auf den der Cloudflare Tunnel zeigen muss (`http://<Hostname>:8100`), und die Adresse, die bei `public_trusted_proxies` einzutragen ist, sobald die Anmeldeseite einmal über die Domain geöffnet wurde.
- Über die Domain-Seite gibt es die Prüfung nicht: Die Konfiguration ändert man in Home Assistant.

## Sprache (ab 0.26.0)

Die Option `language` stellt die Sprache des ganzen Add-ons ein: `de` (Standard, auch bei neuen Installationen und in der Veröffentlichung) oder `en`. Nach einer Änderung das Add-on neu starten.

- **Was sich ändert:** Oberfläche (auch Anmeldeseite, „Kein Zugriff“-Seite, Dialoge, Menüs, Hinweise), Meldungen und Fehlertexte des Add-ons, Einrichtungsprüfung mit allen Schritten, Export (Dateinamen und Texte im ZIP), Benachrichtigungen, Beschreibung geplanter Aufgaben („Every day at 07:30“), Datumsformate, der Titel neuer Chats („New chat“) und die Standardsprache der KI-Antworten. Schreibt jemand in einer anderen Sprache, antwortet die KI weiterhin in dieser Sprache.
- **Was bewusst deutsch bleibt:** Alles, was nur die KI, das Protokoll oder die Konfiguration betrifft: Werkzeugbeschreibungen und -antworten, die Anweisungen an die KI, Protokollzeilen, Fehlermeldungen der Konfiguration (`ConfigError`), die gespeicherten Themen des Smarthome-Überblicks („HA · …“), die Dokumentation (`DOCS.md`, `README.md`, `CHANGELOG.md`) sowie bereits gespeicherte Chat-Inhalte, Chat-Titel, Projektnamen und Gedächtnis-Einträge. Eigene Texte aus der Personalisierung (`app_name`, `login_text`, `login_placeholder`) erscheinen so, wie du sie einträgst; nur die mitgelieferten Standardtexte werden übersetzt. Die Beschriftungen der Konfigurationsseite in Home Assistant folgen der Sprache von Home Assistant, nicht dieser Option.
- **Gilt für alle:** Die Sprache ist eine Einstellung des Add-ons, nicht je Person.
- **Aufbau (für Entwickler):** Die deutschen Texte im Quellcode sind die Schlüssel. Englisch steht in `app/locales/en.json` (Server und Seiten) und `app/locales/en-ui.json` (Browser, wird über `/branding/lang.js` geladen). Platzhalter heißen im Server `{name}`, im Browser `{0}`, `{1}`; `Einzahl||Mehrzahl` im Wörterbuch wählt nach der Zahl. Fehlt ein Eintrag, erscheint der deutsche Text (kein Absturz). `test_i18n.py` stellt sicher, dass jeder Text übersetzt ist, kein Eintrag ungenutzt bleibt und Platzhalter erhalten sind. Eine weitere Sprache bräuchte zwei neue Wörterbücher und einen Eintrag in `i18n.LANGUAGES` und im Schema.

## Dateien erzeugen (ab 0.18.0)

Bittest du die KI um eine Datei („Mach daraus ein Word-Dokument“, „Schreib mir ein PowerShell-Skript zum Sichern“, „Erstelle eine Excel-Tabelle mit …“), legt sie diese mit dem Werkzeug `file_create` an. Unter der Antwort erscheint eine Karte mit Name, Art, Größe und Download-Knopf.

- **Formate:** Word `.docx`, Excel `.xlsx`, PowerPoint `.pptx`, PDF `.pdf` sowie Textdateien (`.ps1`, `.sh`, `.bat`, `.py`, `.csv`, `.json`, `.yaml`, `.html`, `.md`, `.txt`, `.xml`, `.ini`, `.sql` und weitere). Ausführbare Dateien (`.exe`, `.dll`, Archive) erzeugt die KI nicht.
- **Word, PDF, PowerPoint:** aus Markdown. Überschriften, Absätze mit fett/kursiv/Code, Listen (auch verschachtelt), Tabellen, Codeblöcke, Zitate, Trennlinien. Bei PowerPoint beginnt jede Überschrift der Ebene 1 oder 2 (oder eine Linie `---`) eine neue Folie; die erste Folie mit Titel und Untertitel wird die Titelfolie; eine Zeile „Notizen: …“ wird zur Sprechernotiz; zu lange Folien werden automatisch geteilt („Forts.“). Format 16:9.
- **Excel:** aus JSON (mehrere Blätter möglich), CSV oder Markdown-Tabellen. Erste Zeile = Kopfzeile (fett, Farbe, fixiert, Filter). Zahlen und Datumsangaben werden echte Zellwerte (auch „1.234,5“ und „2026-03-01“; Werte mit führender Null wie „007“ bleiben Text). Zellen mit `=` werden Formeln (englische Funktionsnamen, z. B. `=SUM(B2:B10)`).
- **Windows-tauglich:** `.ps1`, `.psm1` und `.csv` werden als UTF-8 mit BOM gespeichert (sonst zeigen PowerShell 5 und Excel Umlaute falsch an), `.bat` und `.cmd` mit Windows-Zeilenenden.
- **Aufbewahrung:** `files_keep_days` (Standard 14 Tage). Danach löscht das Add-on die Datei; die Karte im Chat zeigt dann „Abgelaufen“. Löschst du einen Chat, werden seine Dateien sofort mit gelöscht. Die Dateien liegen in `/data/outfiles` (und damit in der HA-Sicherung). Grenzen: 12 Dateien je Antwort, 12 MB je Datei, 300 MB je Person.
- **Rechte und Sicherheit:** Eine Datei kann nur die Person laden, für die sie erzeugt wurde (andere erhalten „nicht gefunden“). Der Download braucht die Anmeldung, wird als Anhang mit `sandbox`-Kopfzeile ausgeliefert und nie im Browser ausgeführt. Excel-Formeln mit externen Aufrufen (`WEBSERVICE`, DDE, `|` …) werden als Text abgelegt. Die KI darf Dateien ohne Rückfrage erzeugen, weil das nichts in Home Assistant ändert; sie landen nur bei dir.
- **Abschalten:** `files_enabled: false`.
- **Bibliotheken:** python-docx, openpyxl, python-pptx und fpdf2 werden beim Bauen des Add-ons installiert, dazu die Schrift „Liberation“ für PDF (Umlaute, €, Typografie). Ohne diese Pakete bleibt das Add-on voll nutzbar, die KI kann dann nur Textdateien erzeugen und sagt das, wenn man etwas anderes möchte.

## Dateien bearbeiten (ab 0.27.0)

Die KI kann Dateien nicht nur erzeugen, sondern auch **lesen und ändern**, egal ob du sie angehängt hast oder sie selbst erzeugt hat: PDF (Formularfelder ausfüllen oder sperren, Seiten löschen, drehen, ordnen, zusammenfügen, Text ergänzen, neue Felder anlegen), Word, Excel, PowerPoint sowie Text und Code jeder Art (`.py`, `.sh`, `.json`, `.yaml`, `.html` …). Beispiel: Du hängst ein Formular an und schreibst „Die vorausgefüllten Felder sollen nicht mehr änderbar sein, der Rest soll ausfüllbar bleiben.“ Die KI liest das PDF, sperrt die ausgefüllten Felder und bietet die neue Fassung als Karte zum Herunterladen an. **Deine Datei bleibt unverändert.**

- **Werkzeuge:** `file_list` (Dateien dieses Chats), `file_read` (nummerierte Ansicht: Zeilen, Absätze, Zellen, Folien, PDF-Felder und -Seiten) und `file_edit` (Liste von Änderungen; alles oder nichts: scheitert eine, wird nichts gespeichert und die KI erfährt den Grund). Die neue Fassung ersetzt die alte unter demselben Namen oder wird mit `save_as` unter neuem Namen abgelegt.
- **Text und Code:** Ersetzen (eindeutig oder alle), Zeilen ersetzen, einfügen, löschen, anhängen, neu schreiben. Kodierung (UTF-8, Windows-1252), BOM und Zeilenenden (LF/CRLF) bleiben erhalten.
- **Word:** Text ersetzen (auch über Formatierungsgrenzen, in Tabellen, Kopf- und Fußzeilen; Format bleibt), Absätze setzen, einfügen, löschen, Tabellen anlegen und Zellen/Zeilen ändern, Formatvorlagen zuweisen.
- **Excel:** Zellen und Bereiche setzen (Zahlen, Text, Formeln mit englischen Funktionsnamen; gefährliche Formeln wie `WEBSERVICE` werden entschärft), Zeilen und Spalten einfügen oder löschen, Blätter anlegen, umbenennen, löschen. Formelwerte rechnet Excel beim Öffnen neu. **Hinweis:** Diagramme, Pivot-Tabellen, Bilder und Makros der Originaldatei können beim Speichern verloren gehen; die KI sagt es dir dann.
- **PowerPoint:** Text ersetzen, Formen und Tabellenzellen setzen, Notizen, Folien hinzufügen, löschen, verschieben.
- **PDF:** `fill_fields`, `lock_fields` (Felder schreibgeschützt machen: die ausgefüllten, die leeren, alle oder benannte), `unlock_fields`, `flatten` (Formular fest in die Seiten schreiben), `add_text`, `add_text_field`, `delete_pages`, `rotate_pages`, `reorder`, `merge`. Nicht möglich: vorhandenen Text in einer Seite ändern (PDF ist dafür nicht gebaut) und gescannte PDFs bearbeiten; die KI sagt das ehrlich. Passwortgeschützte PDFs werden abgelehnt, bei signierten PDFs warnt die KI, dass die Signatur ungültig wird.
- **Grenzen:** Dateien bis 25 MB, höchstens 200 Änderungen je Aufruf, 90 Sekunden je Aufruf; Bilder und alte Formate (`.doc`, `.xls`, `.ppt`) lassen sich nicht bearbeiten (Bilder sieht die KI direkt in der Nachricht).
- **Sicherheit:** Dateiinhalt ist Inhalt, keine Anweisung. Wie nach einem Dateianhang fragt die KI nach `file_read` vor jeder Aktion in Home Assistant, bei Gedächtnis und GitHub, die etwas ändert, immer nach. Bearbeitet wird nur im Add-on-Speicher; nichts wird ausgeführt (keine Makros, keine Skripte).
- **Abschalten:** `files_edit: false` (nur Dateien erzeugen, Anhänge nur für die eine Nachricht im Arbeitsspeicher) oder `files_enabled: false` (gar keine Dateiwerkzeuge).

## Anhänge und Speicherplatz

Dateianhänge gehen mit der Nachricht an das Add-on und werden dort im Arbeitsspeicher geprüft (Inhalt, nicht Dateiname, entscheidet über die Art) und an Claude weitergereicht. **Was danach passiert, hängt von `files_edit` ab** (Standard: an, ab 0.27.0):

- **Dateien bearbeiten an:** Von jedem Anhang außer Bildern legt das Add-on das Original als Kopie für diesen Chat im Datenordner ab (`/data/outfiles`, bis 25 MB je Datei), damit die KI in Folgenachrichten damit arbeiten kann. Die Kopien bleiben `files_keep_days` Tage (Standard 14), werden mit dem Chat gelöscht (auch bei „Alle meine Chats löschen“) und sind nur für dich zugänglich. Sie liegen damit in der HA-Sicherung. Bilder werden nicht kopiert.
- **Dateien bearbeiten aus** (`files_edit: false`): Anhänge werden **nie auf dem Home-Assistant-Server gespeichert**. Die Datei wird nach der Antwort verworfen, es gibt keinen Upload-Ordner und keine temporären Dateien.
- **In beiden Fällen** stehen in der Datenbank der Nachricht nur Name, Art und Größe, damit der Chat zeigt, was angehängt war; der Inhalt steht in keiner Nachricht. Löschst du den Chat, ist auch das weg.
- Folgefragen: Mit „Dateien bearbeiten“ sieht die KI frühere Anhänge über `file_list` und `file_read` (nur bei Bedarf, das spart Kontingent: ein Anhang wird nicht bei jeder Frage erneut an Claude geschickt). Ohne diese Option sieht Claude die Datei nur in der Nachricht, zu der sie gehört. Die Antwort von Claude bleibt im Chat. Für eine weitere Frage zur selben Datei klickst du an der Nachricht auf „Wieder anhängen“: Die Dateien kommen dann aus dem Speicher deines Browsers (nicht vom Server) zurück ins Eingabefeld. Das geht für die zuletzt gesendete Nachricht, solange du den Chat nicht wechselst oder die Seite neu lädst. Danach hängst du die Datei neu an; Claude bekommt in dem Fall den Hinweis, dass früher eine Datei dabei war.
- Als zweite Absicherung räumt das Add-on beim Start und alle 30 Minuten die Zwischenordner des Claude-Programms auf (Arbeitsordner und Zwischenspeicher in `/data/claude-work` und `/data/claude-config`, Dateien älter als 10 Minuten).
- Grenzen: 5 Dateien, zusammen 60 MB je Nachricht; Bild höchstens 5 MB, PDF, Word, Excel und PowerPoint je 50 MB, Text 1 MB. Bilder und PDFs, die Claude selbst ansieht, dürfen zusammen höchstens 22 MB haben (die Claude-API nimmt je Anfrage höchstens 32 MB). PDFs über 20 MB liest der Server deshalb nur als Text aus; Bilder, Diagramme und Layout fehlen dann, und ein reiner Scan ohne Text wird mit Hinweis abgelehnt (Scans gehen bis 20 MB). Alle Texte zusammen (auch aus Word/Excel, höchstens 250 000 Zeichen; längere Word-/Excel-Inhalte werden mit Hinweis gekürzt). Word, Excel und PowerPoint werden dafür nur im Arbeitsspeicher entpackt, mit Grenzen gegen präparierte Archive (Anzahl und Größe der Teile, keine XML-Entitäten). Größere Anfragen werden abgewiesen, bevor sie gelesen werden; alle anderen Anfragen sind auf 128 KB begrenzt.
- Dateiinhalt ist für Claude Inhalt, keine Anweisung. Zusätzlich gilt: Ist in einer Nachricht eine Datei angehängt oder hat die KI eine Datei gelesen (`file_read`), fragt sie vor jeder Aktion in Home Assistant, die etwas bedient oder ändert, immer nach (auch bei „Immer zulassen“). So kann eine präparierte Datei nichts unbemerkt auslösen.
- Schlägt die Prüfung fehl (z. B. nicht unterstütztes Format), erscheint die Meldung als Fehler im Chat; Text und Dateien bleiben im Eingabefeld.

## Vorschau-Sicherheit

Eine Vorschau ist Code, den Claude geschrieben hat, und wird deshalb wie fremder Code behandelt:

- Die Seite wird kurz im Arbeitsspeicher des Add-ons abgelegt (höchstens 12 pro Person, 150 000 Zeichen, nach einer Stunde weg, nie auf der Platte) und unter einer eigenen Adresse (`preview/<Zufalls-ID>`) ausgeliefert, nur für die Person, die sie erzeugt hat.
- Die Antwort trägt strenge Regeln: eigene, leere Herkunft (`sandbox allow-scripts`, ohne Zugriff auf Cookies, Chat oder die Seite von Home Assistant), `default-src 'none'`, also kein Netzwerk, keine Formulare, keine Navigation, keine externen Bibliotheken, Schriften oder Bilder. Nur Inline-CSS, Inline-JavaScript und `data:`-Bilder funktionieren.
- Eine Vorschau kann damit nichts nach außen schicken und nichts in Home Assistant auslösen.

## Daten und Sicherung

Alles liegt in `/data/ki_chat.sqlite3`. Das Token steht in den Add-on-Optionen und damit ebenfalls im Backup, Backups entsprechend schützen. Als Administrator mit Zugriff auf das Add-on könntest du die Datei theoretisch direkt lesen. Die Trennung gilt für die Oberfläche und die Programmierschnittstelle.

- **HA-Sicherung:** Das Add-on wird mit `backup: cold` gesichert. Home Assistant hält es dafür kurz an (wenige Sekunden), kopiert die Daten und startet es wieder. So ist die Kopie immer vollständig, auch wenn gerade jemand schreibt. Beim Beenden wird die Datenbank vorher sauber abgeschlossen. Eine Antwort, die genau in diesem Moment läuft, wird unterbrochen (die bis dahin erhaltene Teilantwort bleibt gespeichert, deine Frage ebenfalls).
- **Schnappschüsse:** Etwa einmal am Tag legt das Add-on zusätzlich einen geprüften Schnappschuss in `/data/snapshots/` an (`ki_chat-JJJJ-MM-TT_HHMMSS.sqlite3`, die letzten 7 bleiben). Er liegt im Datenordner und steckt damit in jeder HA-Sicherung. Vor dem Update auf eine neue Datenbankversion entsteht zusätzlich `vor-update-…` (die letzten 3).
- **Prüfung beim Start:** Das Add-on prüft die Datenbank bei jedem Start. Meldet sie einen Fehler, erscheint oben in der Oberfläche ein roter Hinweis mit den neuesten Schnappschüssen, und die Datei wird nicht verändert.
- **Wiederherstellen:** In den Add-on-Optionen unter `restore_snapshot` den Dateinamen eines Schnappschusses eintragen (z. B. `ki_chat-2026-10-27_033012.sqlite3`) und das Add-on neu starten. Der bisherige Stand wird vorher als `vor-wiederherstellung-…` gesichert. Danach die Option leeren; solange der Name stehen bleibt, wird nicht erneut überschrieben. Die Namen der vorhandenen Schnappschüsse stehen beim Start im Add-on-Protokoll. Aus einer ganzen HA-Sicherung stellst du den HA Copilot über Einstellungen, System, Sicherungen wieder her (Teilwiederherstellung des Add-ons).
- **Umzug in ein anderes Add-on** (z. B. vom lokalen Add-on im Ordner `/addons` zum Add-on aus einem GitHub-Repository): Für Home Assistant sind das zwei verschiedene Add-ons mit getrennten Daten, die Chats wandern nicht von selbst mit. So nimmst du sie mit: (1) Im *alten* Add-on `export_database` einschalten und neu starten; es legt `ki_chat-export.sqlite3` in seinen Config-Ordner (in Home Assistant unter `/addon_configs/<Ordner>/`, z. B. per Samba oder Datei-Editor). (2) Die Datei in den Config-Ordner des *neuen* Add-ons kopieren. (3) Im neuen Add-on `restore_snapshot` auf `ki_chat-export.sqlite3` setzen und neu starten; die Chats, Projekte, das Gedächtnis und die geplanten Aufgaben sind dann da (Dateien, die die KI erzeugt hat, und Projektdateien-Inhalte, die nicht in der Datenbank liegen, nicht). (4) Danach `restore_snapshot` leeren, `export_database` ausschalten und die Export-Datei löschen, denn sie enthält alle Chats. Die Konfiguration (Benutzer, Zugangsdaten) musst du im neuen Add-on selbst eintragen.
- **Ablauf-Hinweise:** Trage in `claude_token_expires` und `entra_secret_expires` das Ablaufdatum ein (Format `JJJJ-MM-TT`). 30 Tage vorher erscheint oben in der Oberfläche ein Hinweis und steht im Protokoll; nach Ablauf wird er rot. Das Claude-Token gilt ein Jahr ab dem Tag, an dem du `claude setup-token` ausgeführt hast. Das Ablaufdatum des Entra-Secrets zeigt Entra bei der App-Registrierung unter „Zertifikate & Geheimnisse“.

## Sicherheit in Kürze

- Die Benutzer-Header von Home Assistant (`X-Remote-User-Id`) werden nur akzeptiert, wenn die Verbindung direkt vom Ingress-Proxy (172.30.32.2) kommt. `X-Forwarded-For` wird nie ausgewertet.
- Schreibende Anfragen verlangen einen eigenen Header (Schutz gegen fremde Webseiten). Auf der Domain muss zusätzlich der `Origin` zur `public_base_url` passen.
- Anmeldung mit Home Assistant (optional): Autorisierungscode-Ablauf von Home Assistant; `state` und Browserbindung gegen Fremdanmeldung, Token wird sofort widerrufen. Home Assistant unterstützt hier meines Wissens kein PKCE, deshalb stützt sich der Schutz auf `state` und die Browserbindung. Dass die Abfrage `auth/current_user` mit einem echten Home Assistant funktioniert, ist bisher nur gegen eine Nachbildung getestet.
- Domain-Anmeldung (Entra): OpenID-Connect-Code-Flow mit PKCE. Geprüft werden Signatur (RS256, Schlüssel von Microsoft), Aussteller, Zielgruppe, Ablauf, Nonce und Mandant. Die Anmeldung ist an den Browser gebunden, der sie gestartet hat, und kann nur einmal eingelöst werden.
- Die Sitzung liegt serverseitig in der Datenbank (nur der Hash des Tokens), das Cookie ist `__Host-`-präfixiert, `Secure`, `HttpOnly`, `SameSite=Lax`. Wird ein Profil aus der Konfiguration entfernt, verliert es sofort den Zugriff.
- Unbekannte Konten werden nie angelegt. Ein anderes Konto mit derselben UPN kann ein bereits gebundenes Profil nicht übernehmen.
- Anmeldeversuche sind begrenzt (10 pro 10 Minuten und Adresse). Die Domain-Seiten sind nicht in fremden Frames darstellbar und senden HSTS. Die großen Upload-Grenzen gelten nur für angemeldete Anfragen.
- Lange Antworten bleiben über Cloudflare offen: Alle 15 Sekunden geht ein Lebenszeichen an den Browser.
- Jede Datenbankabfrage für Chats filtert auf das Profil. Zusätzlich verhindert die Datenbank selbst, dass eine Nachricht einem anderen Profil gehört als ihr Chat.
- Das Repository enthält keine echten IDs, Adressen oder Logos: `config.yaml` hat nur einen Platzhalter-Benutzer, das Logo ist neutral.
- Die App hat keine Verwaltungsfunktionen und keine Schnittstelle dafür. Mit `homeassistant_api` bekommt das Add-on Zugriff auf die Home-Assistant-API. Ohne die KI-Werkzeuge liest es damit nur die Benutzerliste und die Theme-Farben (`person/list`, `config/auth/list`, `frontend/get_themes`); alles Weitere, was die KI in Home Assistant tut, richtet sich nach den Stufen oben.
- Theme-Werte aus Home Assistant werden gefiltert (nur einfache Farb- und Längenwerte, kein `url()`), `custom.css` darf nur der Administrator ablegen, und es gilt weiter die strenge Content-Security-Policy.

## Sicherheitsprüfung (0.24.0)

Geprüft wurde der gesamte Code von Hand und mit Tests: Anmeldung über Entra und Home Assistant (state, Nonce, PKCE, Browserbindung, Einmaligkeit), Sitzungen und Cookies, das Vertrauen in den Ingress-Proxy, Größenbegrenzungen, den Web-Abruf der KI (Sperre für Heimnetz und lokale Adressen, Weiterleitungen, DNS-Tricks), ZIP- und Office-Dateien (Größe, Anzahl, XML-Entitäten), die Ablage und den Download erzeugter Dateien, die Oberfläche (kein `innerHTML`, nur `http(s)`- und `mailto:`-Links, Vorschau in einer Sandbox ohne Netzwerk), alle Datenbankabfragen (nur Platzhalter, feste Spaltenlisten), die Werkzeuge für Home Assistant und GitHub (Sperrlisten, Rückfragen, Repository-Freigabe), den Umgang mit Zugangsdaten (aus Fehlermeldungen entfernt, nicht im Protokoll, nicht im Claude-Prozess) und die Abhängigkeiten (`pip-audit`: keine bekannten Schwachstellen zum Prüfzeitpunkt).

**Gefunden und behoben:** Die großen Upload-Grenzen galten für jeden, der nur einen Cookie mit dem Namen der Sitzung oder den Header `X-Remote-User-Id` mitschickte, auch ohne Anmeldung (Belastung der Domain-Seite). Weiterhin: ungeprüfte Adresse aus `CF-Connecting-IP`, nicht abgesicherte Fehlercodes im Protokoll, der Home-Assistant-Token in der Umgebung des Claude-Prozesses, fehlende zusätzliche Header.

**Bewusst akzeptiert:**
- Beim Anmelden verrät die Antwort, ob eine E-Mail-Adresse in der Konfiguration steht (sonst gäbe es keine sofortige Meldung bei Tippfehlern). Begrenzt auf 10 Versuche je 10 Minuten und Adresse.
- Das Add-on läuft wie üblich bei Home Assistant als Benutzer root im eigenen Container. Das Claude-Programm hat darin keine Werkzeuge für Dateien oder Befehle, nur Websuche und die geprüften Werkzeuge dieses Add-ons.
- Die Abhängigkeiten sind über Versionsbereiche festgelegt, nicht auf eine genaue Version. Beim Bau des Images kommt die jeweils neueste passende Version.
- Von der KI erzeugte Excel-Dateien können Formeln enthalten (Wunsch der Nutzung); Excel warnt beim Öffnen unbekannter externer Verknüpfungen.
- Wer Zugriff auf den Konfigurationsordner oder die Add-on-Konfiguration hat, kann alles: Das ist die Administratorrolle und liegt außerhalb dessen, was das Add-on schützen kann.
- Nicht in dieser Umgebung prüfbar: das Verhalten mit echtem Claude, echtem Home Assistant (Anmeldung mit Home Assistant) und echtem Entra-Mandanten. Dafür gelten die Tests mit Nachbildungen.

## Tests

```
cd ki_chat
pip install fastapi uvicorn httpx websockets 'pyjwt[crypto]' pypdf pytest pyyaml claude-agent-sdk -r requirements-files.txt  # die Office-Bibliotheken braucht ab 0.18.0 auch der Test der Dateierzeugung
python -m pytest
```


## Gestaltung (ab 0.10.0)

- **Formen:** vier feste Radien (`--r-1` 6 px für kleine Knöpfe, `--r-2` 10 px für Eingaben, Knöpfe und Zeilen, `--r-3` 14 px für Eingabefeld und Nachrichten, `--r-4` 18 px für Fenster von unten) statt durchgehend runder Pillen. Alle Werte stehen in `app/static/theme.css`.
- **Farbe:** flache Flächen ohne Verläufe und Schatten. Der Akzent (Blau wie in den Dashboards) kennzeichnet nur Bedienbares; das Logo ist das einzig Bunte.
- **Schrift:** Roboto wie in den Dashboards; Code und Logs in Atkinson Hyperlegible Mono (0/O und l/1/I sind eindeutig unterscheidbar). Beide Dateien liegen lokal unter `app/static/fonts/`, Lizenz (OFL) daneben.
- **Startseite:** Die Vorschläge sind eine schlichte Liste statt Kacheln.
- **Logo in Home Assistant:** Laptop/Tablet in der Seitenleiste; Handy im Kopf des Chats-Fensters und über der Begrüßung (die Kopfzeile von HA selbst lässt sich nicht verändern).
