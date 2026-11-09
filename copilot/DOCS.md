# HA Copilot

Privater KI-Chat für Home Assistant. Jedes Profil hat eigene Chats, die für andere Profile unsichtbar sind.

**Stand: 0.49.0.** Was in welcher Version neu ist, steht im Reiter „Änderungsprotokoll“.

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

Der Domain-Zugang ist an, sobald `public_base_url` und eine Anmeldung eingetragen sind (Entra mit den drei Feldern darunter und/oder `ha_url`); einen eigenen Schalter gibt es seit 0.45.0 nicht mehr. Ist die Adresse eingetragen, aber keine Anmeldung, bleibt der Domain-Zugang aus und das Protokoll weist darauf hin. Ist etwas halb ausgefüllt oder ungültig, startet das Add-on nicht und nennt den Grund im Log.

| Option | Bedeutung |
|---|---|
| `public_base_url` | Öffentliche Adresse, z. B. `https://chat.example.org` (https, ohne Pfad). Schaltet zusammen mit der Anmeldung den Domain-Listener (Port 8100) ein. |
| `entra_tenant_id` | Verzeichnis-ID (Mandanten-ID) als GUID. |
| `entra_client_id` | Anwendungs-ID (Client-ID) der App-Registrierung als GUID. |
| `entra_client_secret` | Geheimer Clientschlüssel der App-Registrierung (läuft ab, Ablaufdatum notieren). |
| `ha_url` | Optional. Von außen erreichbare Adresse von Home Assistant (https, ohne Pfad), z. B. `https://ha.example.org`. Schaltet auf der Anmeldeseite zusätzlich „Mit Home Assistant anmelden“ ein. Leer: nur Entra, wie bisher. |
| `session_days` | Wie lange man angemeldet bleibt, 1 bis 90 Tage (Standard 30). Die Sitzung verlängert sich bei Nutzung, endet aber spätestens nach 90 Tagen. |
| `public_trusted_proxies` | Optional. Adressen von Proxys (z. B. des cloudflared-Add-ons), deren Header `CF-Connecting-IP` für die Ratenbegrenzung verwendet werden darf. |

Entra-Angaben sind nötig, solange `ha_url` leer ist. Mit `ha_url` darfst du sie auch ganz weglassen (nur Home-Assistant-Anmeldung); halb ausgefüllt bleiben sie ein Fehler.

Ablauf Entra: Anmeldeseite (`/login`) → E-Mail-Adresse → Weiterleitung zu Microsoft → Rückkehr auf `/auth/callback` → Sitzung → `/new`. Die eingegebene Adresse ist nur ein Hinweis für Microsoft. Wer Zugriff bekommt, entscheidet allein das von Microsoft signierte Token, das gegen die Profilliste geprüft wird.

**Anmeldung mit Home Assistant (nur mit `ha_url`):** Die Anmeldeseite zeigt dann zusätzlich „Mit Home Assistant anmelden“ (ohne Entra-Angaben nur diesen Knopf). Der Knopf führt zur Anmeldung von Home Assistant selbst (mit allem, was dort eingerichtet ist, z. B. Zwei-Faktor); dieses Add-on sieht das Passwort nie. Danach tauscht das Add-on den Rückgabecode gegen ein Token, fragt nur ab, wer die Person ist, und widerruft das Token sofort wieder. Ob die Person hinein darf, entscheidet dieselbe Regel wie im HA-Panel: eingetragen (`ha_user`/`ha_user_id`) oder `all_ha_users` ohne Ausschluss. Home Assistant muss dafür von der Domain-Seite aus erreichbar sein (das Add-on ruft `ha_url` selbst auf). Die Anmeldung ist wie bei Entra an den startenden Browser gebunden und einmalig; zusätzlich ist sie ratenbegrenzt.

### Testmodus

Solange weder `claude_oauth_token` noch `anthropic_api_key` eingetragen ist, läuft der Chat im Testmodus (bis 0.44 hieß das `backend: echo`): Er gibt deine Nachricht nur zurück, es wird keine KI aufgerufen und nichts abgerechnet, und oben im Chat erscheint ein Hinweis. Sobald einer der beiden Zugänge eingetragen ist, antwortet Claude; eine Option `backend` gibt es nicht mehr.

### `anthropic_api_key`, `claude_oauth_token`

Zugang zu Claude. Du brauchst eines von beiden; die Zugangsdaten gehören dir, sie sind nicht Teil des Add-ons und werden nirgends sonst gespeichert.

- `anthropic_api_key`: API-Schlüssel aus der [Claude-Konsole](https://platform.claude.com/). Abgerechnet wird nach Verbrauch. Das ist der von Anthropic vorgesehene Weg für Programme, die Claude einbinden. Hat Vorrang, wenn beide Felder gefüllt sind.
- `claude_oauth_token`: Langzeit-Token deines Abos, erzeugt mit `claude setup-token` (Claude-Code-CLI auf einem beliebigen Rechner, mit dem Abo angemeldet). **Nur für deinen eigenen, persönlichen Gebrauch.** Anthropic erlaubt es nicht, Abo-Zugänge anderer Personen über ein Programm zu leiten oder Abos weiterzugeben; die Nutzungsgrenzen eines Abos gelten für gewöhnliche, individuelle Nutzung. Lies dazu die aktuellen Nutzungsbedingungen von Anthropic und entscheide eigenverantwortlich (das hier ist keine Rechtsberatung). Anthropic kann solche Tokens sperren.

> **Wichtig:** Sobald mehrere Personen die App nutzen (mehrere Benutzer, `all_ha_users`) oder die Domain-Seite aktiv ist, ist ein Abo-Token der falsche Weg; nimm dann einen API-Schlüssel. Das Add-on schreibt in dem Fall beim Start eine Warnung ins Protokoll.

Beides nur hier im Add-on eintragen, nie in Chats, Repos oder Screenshots. Die Felder sind als Passwort maskiert.

### `model`

Standard-Modell für neue Chats (Standard `claude-sonnet-5-5`). Im Chat lässt sich der Aufwand (`low`, `medium`, `high`; voreingestellt `medium`) pro Nachricht im Menü rechts unter dem Eingabefeld umschalten („Aufwand“), die Auswahl merkt sich der Browser. Weitere Modelle (Opus, Haiku) stehen fest zur Auswahl; Chat-Titel erzeugt ein kleines Haiku-Modell.

### `restore_snapshot`, `export_database`, `claude_token_expires`, `entra_secret_expires`

Siehe „Daten und Sicherung“. Normalerweise leer bzw. aus.

## Personalisierung: Name, Logo, Texte, Farben

Alles in diesem Abschnitt ist optional; ohne Angaben sieht die App neutral aus (Name „HA Copilot“, blaues Sprechblasen-Zeichen, Farben des Home-Assistant-Themes).

### Optionen

| Option | Bedeutung |
|---|---|
| `language` | `de` (Standard) oder `en`: Sprache von Oberfläche und Meldungen, siehe „Sprache“. |
| `app_name` | Name in Anmeldeseite, Browser-Titel, Seitenleiste und als Name der App auf dem Startbildschirm (höchstens 40 Zeichen). Standard `HA Copilot`. Der Eintrag in der Home-Assistant-Seitenleiste und der Add-on-Name stehen fest in `config.yaml` (`panel_title`) und folgen dieser Option nicht. |
| `login_text` | Satz unter der Überschrift „Willkommen bei <app_name>!“ auf der Anmeldeseite (Standard: „Melde dich an, um mit der KI zu chatten.“). |
| `login_placeholder` | Beispiel-Adresse im E-Mail-Feld der Anmeldeseite. |
| `logo_tile` | Für Logos, die auf hellem Grund schlecht lesbar sind (z. B. leuchtendes Cyan): im hellen Design auf dunkler Kachel zeigen. |
| `follow_ha_theme` | An (Standard): Farben und Hell/Dunkel kommen von Home Assistant. Aus: eingebaute Farben mit eigenem Schalter Auto/Hell/Dunkel. |
| `theme_name` | Optional, nur für die Domain: Name eines HA-Themes. Leer: das Standard-Theme von Home Assistant. |

### Logo und Dateien (Ordner `addon_config`)

Eigene Dateien legst du in den Ordner des Add-ons. In Home Assistant ist er unter `/addon_configs/<Ordnername>/` erreichbar (z. B. per Samba-Freigabe `addon_configs` oder mit dem Datei-Editor; der Ordnername ist die Add-on-Kennung, bei lokalen Add-ons `local_copilot`). Änderungen wirken sofort nach dem Neuladen der Seite, ein Neustart ist nicht nötig.

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
3. **Eigene Farben** gehören in `custom.css` (siehe oben); seit 0.45.0 gibt es dafür keine Optionen mehr.
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

- **Darstellung:** Hell, Dunkel oder Auto (folgt dem Gerät). Die Auswahl steht unter **Einstellungen → Allgemein** und wird pro Browser gemerkt; in Home Assistant eingebettet gibt HA Hell/Dunkel vor und der Schalter entfällt. Die Farben kommen aus dem Theme von Home Assistant, siehe „Personalisierung“.
- **Seitenleiste:** Von oben nach unten: „Neuer Chat“, **Suchen** (ab 0.22.0, siehe „Suche, Export und eigene Daten“), **Geplant** (ab 0.21.0, siehe „Geplante Aufgaben“), **Angepinnt** (angepinnte Chats), **Projekte** (auf- und zuklappbar, Plus-Symbol legt ein Projekt an; das Plus in der Projektzeile startet einen neuen Chat darin) und **Chats**. Bei den Chats stehen nur die der letzten zwei Tage (Heute, Gestern); „Alle anzeigen“ blendet die älteren ein. Über das Symbol mit den drei Punkten bei jeder Zeile (am Computer beim Darüberfahren) öffnet sich das Aktionsfenster: anpinnen, umbenennen, in ein Projekt verschieben, als Markdown exportieren, löschen. Am Laptop und Tablet öffnet das ein kleines Menü direkt am Symbol (mit Trennlinien und Tastenkürzeln: U, P, R, D; „Projekt wechseln“ klappt ein Untermenü mit Suche auf; Pfeiltasten und Esc funktionieren). Abfragen wie Projekt anlegen, Umbenennen oder Löschen bestätigen erscheinen dort als Dialog in der Bildschirmmitte mit Schließen-Kreuz; auf dem Handy hochkant bleibt alles ein Fenster von unten.
- **Eigene Nachrichten (ab 0.27.5):** Unter jeder eigenen Nachricht steht beim Darüberfahren (am Touchscreen nach dem Antippen) dezent, wann sie gesendet wurde: bis zu einer Stunde „vor 33 Minuten“, danach auf Stunden gerundet („vor 1 Stunde“, „vor 2 Stunden“, bis sechs Stunden), dann „Heute Nacht/Morgen/Mittag/Nachmittag/Abend“, „Gestern“, „Vorgestern“, „vor 3 Tagen“ (bis sechs Tage) und ab einer Woche das Datum. Der genaue Zeitpunkt steht im Hinweis des Zeitstempels. Daneben ein Stift (**Bearbeiten**) und ein Symbol zum **Kopieren** des Textes. Zum Bearbeiten siehe „So arbeitet die KI“. **Unter den Antworten der KI** stehen „Kopieren“ und „Als Datei“ (speichert den ganzen Text als `antwort.md`) als dezente Symbole: bei der letzten Antwort dauerhaft, bei älteren erst beim Darüberfahren; ebenfalls nur dann steht dort, wann die Antwort fertig wurde (gleiche Zeitangabe wie oben).
- **Warteanzeige (ab 0.17.0):** Solange die KI arbeitet, steht unter der Frage ein kleines bewegtes Zeichen mit einem Hinweis („Denkt nach“, „Tüftelt“, „Wägt ab“ …) oder der gerade laufenden Aktion („Entitäten suchen: Licht“); wartet sie auf deine Freigabe, steht das dort. Nach 20 Sekunden erscheint die Wartezeit, nach einer Minute ein Hinweis, dass die Antwort auch bei verlassenem Chat fertig wird. Sobald Text ankommt, bleibt nur das kleine Zeichen unter dem Text. Mit „Bewegung reduzieren“ im Betriebssystem steht es still.
- **Lesestatus:** Eine neue Antwort macht den Chat ungelesen: Der Name steht fett mit einem Punkt in der Akzentfarbe, ein eingeklapptes Projekt zeigt den Punkt ebenfalls, und der Tab-Titel beginnt mit „●“. Sobald der Chat angezeigt wird, gilt er als gelesen. Das passiert auch, wenn du die Antwort bei geöffnetem Fenster abwartest. Kommt die Antwort, während das Fenster im Hintergrund liegt oder du auf einem anderen Gerät bist, bleibt der Punkt, bis du den Chat öffnest. Im Menü kannst du Chats von Hand als ungelesen oder gelesen markieren (der gerade offene Chat bleibt dann ungelesen, bis du ihn erneut öffnest). Der Status gehört zum Benutzer und gilt auf allen Geräten; die Liste aktualisiert sich beim Zurückkehren ins Fenster, alle 45 Sekunden und alle 3 Sekunden, solange irgendwo eine Antwort entsteht. Projekte lassen sich ebenfalls anpinnen (stehen dann oben) und umbenennen. Wird ein Projekt gelöscht, bleiben seine Chats erhalten und stehen danach wieder bei den Chats. Weitere Einträge wie Artefakte kommen als zusätzliche `nav-item`-Zeilen in `index.html` dazu.
- **Einklappen und Handy:** Im Web am Computer lässt sich die Seitenleiste über das Symbol oben links ein- und ausblenden (wird pro Browser gemerkt). In Home Assistant gibt es das nicht, dort wäre es eine zweite Seitenleiste neben der von HA. Auf dem Handy öffnet sich die Seitenleiste im Web wie gewohnt von links (Menüsymbol), in Home Assistant als Fenster von unten (Sprechblasen-Symbol).
- **Als App auf dem Handy:** Die Domain-Version lässt sich im Handy-Browser über „Zum Home-Bildschirm“ als eigene App ablegen (Name aus `app_name`, Symbol aus `icon.png`, Vollbild ohne Browserleiste; das Manifest erzeugt das Add-on). Sie hat keine Home-Assistant-Kopfzeile. Die App hat auf dem iPhone einen eigenen Speicher, die Anmeldung per Microsoft ist dort einmal neu nötig.
- **Chatliste:** Hinter dem Namen eines Chats dreht sich ein kleiner Kreisel, solange die KI dort antwortet (auch wenn du den Chat verlassen hast). Die drei Punkte (Aktionen) erscheinen am Computer erst beim Darüberfahren. Zu lange Namen blenden aus; nach etwa einer Sekunde zeigt ein Hinweis den vollen Namen und die letzte Aktivität.
- **Kopfzeile:** Der Chat-Titel steht in einer eigenen Fläche über dem Chat. Im Web auf dem Handy gibt es keinen Balken mehr: nur runde Knöpfe für die Chat-Liste (links) und „Neuer Chat“ (rechts). In Home Assistant auf dem Handy wandert das Chats-Symbol in die Eingabe (neben die Büroklammer im Eingabefeld), die Kopfzeile erscheint dort nur, wenn ein Titel da ist.
- **Startseite:** Ein neuer Chat zeigt die Begrüßung und vier Startkarten. Ein Tipp darauf füllt die Eingabe mit dem Anfang einer Frage, die du fertig schreibst. Die Karten stehen als `STARTERS` in `app.js`.
- **Anhänge:** Über die Büroklammer, per Einfügen (Strg/Cmd+V, z. B. ein Screenshot) oder per Ziehen auf die Seite lassen sich bis zu 5 Dateien pro Nachricht anhängen: Bilder (PNG, JPEG, GIF, WebP; Fotos werden im Browser auf höchstens 2000 Pixel verkleinert), PDF und Textdateien (Code, Logs, CSV, JSON, YAML, Markdown …). Zum Senden brauchst du eine Frage zu den Dateien. Word (.docx), Excel (.xlsx) und PowerPoint (.pptx) werden im Add-on in Text umgewandelt (Überschriften, Listen, Tabellen; bei Excel alle sichtbaren Blätter mit Zellwerten und Datumsangaben, Formeln als zuletzt berechneter Wert; bei PowerPoint Folientexte und Notizen). Alte Formate (.doc, .xls, .ppt), passwortgeschützte Dateien und ZIP-Archive werden mit einer Meldung abgelehnt. Was mit den Dateien passiert, steht unter „Anhänge und Speicherplatz“.
- **Projektanweisungen:** Im Menü eines Projekts (⋯) unter „Anweisungen festlegen“ lässt sich ein Text (bis 4000 Zeichen) hinterlegen, der in jedem Chat des Projekts als Anweisung an Claude mitgeht, zum Beispiel Rolle, Stil oder feste Hintergründe. Ein Punkt hinter dem Projektnamen zeigt, dass Anweisungen aktiv sind; auf der Startseite eines neuen Chats im Projekt steht ein Hinweis. Die Anweisungen liegen als Text in der Datenbank (Chats ohne Projekt bekommen keine).
- **Dateien und Vorschau aus Antworten:** Claude liefert Text. Jeder Codeblock ist ein kompakter Kasten mit kleinen Symbolknöpfen oben rechts (Herunterladen, Kopieren, bei HTML zusätzlich Vorschau; der Name erscheint beim Darüberfahren, nach dem Klick kurz ein Haken); lange Zeilen brechen um; mit `datei=name.ext` in der Eröffnungszeile (z. B. ```` ```yaml datei=automations.yaml ````) bekommt die Datei ihren Namen, sonst `datei.<Endung>` nach der Sprache. Unter jeder Antwort speichert das Symbol „Als Datei speichern“ den ganzen Text als `antwort.md`. Auf dem Handy öffnet sich dafür das Teilen-Fenster („In Dateien sichern“), am Computer der normale Download. Vollständige HTML-Seiten (Codeblock `html`) bekommen eine Schaltfläche „Vorschau“: Die Seite läuft abgeschottet unter dem Codeblock (Vollbild möglich). Siehe „Vorschau-Sicherheit“.
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
- **Auf einen Ausschnitt antworten (ab 0.32.0):** Text in einer Antwort der KI markieren, dann auf **Antworten** tippen oder klicken. Der Ausschnitt steht als Zitat in einer Leiste über dem Eingabefeld; **x** entfernt es wieder. Beim Senden steht das Zitat über deiner Nachricht und geht der KI als Zitatblock (`> …`) mit; gespeichert wird es als Teil der Nachricht (Feld `quote` bei `POST /api/chats/{id}/send`, höchstens 2000 Zeichen; der Chat-Titel kommt aus deiner eigenen Frage, beim Bearbeiten der Nachricht bleibt das Zitat erhalten). Es gibt ein Zitat je Nachricht; ein neuer Ausschnitt ersetzt das alte, ein Chatwechsel verwirft es. Zitate lassen sich nur aus fertigen Antworten der KI auswählen.
- **Nachricht bearbeiten (ab 0.27.5):** Mit dem Stift unter einer eigenen Nachricht wird sie zum Eingabefeld (Strg/Cmd+Enter sendet, Esc bricht ab). „Senden“ ersetzt diese Frage und **alles danach** durch die neue Frage und eine neue Antwort; bei Claude und in der Datenbank bleibt die alte Fassung nicht erhalten. Der Verlauf davor bleibt Teil des Gesprächs. Hängen an der alten Frage Dateien, werden sie nicht übernommen (die Oberfläche weist darauf hin; mit „Dateien bearbeiten“ abgelegte Kopien und von der KI erzeugte Dateien bleiben im Chat erhalten). Der Titel des Chats ändert sich nicht. Geht die neue Antwort ganz schief (kein Text, z. B. bei einem Fehler oder Stopp), nimmt der Server die neue Frage zurück und stellt den alten Verlauf wieder her; Bearbeiten geht nur für eigene Fragen im eigenen Chat (`edit_message_id` an `POST /api/chats/{id}/send`; Antworten, fremde und unbekannte Nummern ergeben 404). Reicht die Zusammenfassung eines langen Chats (siehe „Lange Chats“) bis in den ersetzten Teil, wird sie verworfen und bei Bedarf neu erstellt. Während eine Antwort läuft, lässt sich nichts bearbeiten.
- Der Chat-Titel steht zuerst als Anfang der ersten Frage da und wird danach von einem kleinen Modell durch einen Kurztitel ersetzt (2 bis 5 Wörter, wie bei Claude selbst; das verbraucht nur einen winzigen Teil deines Abo-Kontingents). Ein von dir umbenannter Chat wird nie überschrieben, und scheitert die Titelerzeugung, bleibt der Anfangstitel stehen. Er lässt sich jederzeit umbenennen.

## Zugriff auf Home Assistant (ab 0.15.0)

Die KI kann Home Assistant benutzen: Zustände ansehen, Verlauf und Logbuch lesen, Geräte schalten und, mit der höchsten Stufe, Automationen, Skripte, Szenen, Dashboards und Helfer bauen oder ändern. Das passiert in einem normalen Chat („Ist im Keller Licht an?“, „Schalte das Wohnzimmer aus“, „Lege eine Szene für den Abend an“). Alles wird in der Add-on-Konfiguration eingestellt, nichts davon in der Chat-Oberfläche.

**Stufen** (`ha_access` je Benutzer, sonst `ha_access_default`, vorgegeben `execute`):

| Stufe | Darf |
|---|---|
| `none` | Gar nichts in Home Assistant. Die KI chattet ganz normal. |
| `read` | Lesen: Zustände, Verlauf, Logbuch, Bereiche, verfügbare Dienste. |
| `execute` | Zusätzlich Geräte bedienen (Licht, Schalter, Klima, Rollos, Medien, Szenen und Skripte starten, Helfer setzen, Benachrichtigungen). |
| `write` | Zusätzlich Automationen, Skripte und Szenen anlegen, ändern und löschen, Dashboards speichern, Helfer und Registereinträge ändern, Vorlagen auswerten. Ohne Einschränkung auf freigegebene Entitäten. |

Jeder kann die KI unabhängig von der Stufe im Alltag wie gewohnt nutzen. Beispiel: `adm` und `dora` mit `write`, `sam` mit `read` (nur ansehen), alle anderen haben ohne eigenen Eintrag `execute`.

**Weitere Optionen:**

- Jede **Änderung** an der Konfiguration in Home Assistant fragt im Chat nach (fest seit 0.45.0, die Option `ha_write_confirm` gibt es nicht mehr). Es erscheint eine Karte mit „Zulassen“, „Ablehnen“ und „In diesem Chat immer zulassen“ (gilt nur bis zum Neustart des Add-ons und nur für diesen Chat). Das Bedienen von Geräten (`execute`) fragt nie nach, außer in den Fällen unten.
- `ha_limit_to_exposed` (vorgegeben an): Die Stufen `read` und `execute` sehen und bedienen nur Entitäten, die in Home Assistant für Assist freigegeben sind (Einstellungen, Sprachassistenten, Entitäten freigeben). Das ist dieselbe Auswahl wie für Alexa/Assist. Die Stufe `write` ist davon nie eingeschränkt.

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
- **Die KI kann Notizen ins Projektwissen schreiben (ab 0.44.0).** In einem Projekt-Chat gibt es das Werkzeug `knowledge_save`: Die KI legt eine Markdown-Notiz an, ergänzt sie (`mode=append`) oder ersetzt sie (`mode=replace`). Sie tut das nur, wenn du es möchtest („speichere das im Projektwissen“), und nur mit dem, was im Chat gesagt oder erarbeitet wurde. Geschrieben wird immer in den Ordner `KI/` (zum Beispiel `KI/zabbix-mcp.md`); eine hochgeladene Datei kann die KI nie ändern, auch nicht mit gleichem Namen, und Namen mit `..` lehnt der Server ab. Die Notizen erscheinen unter **Wissen verwalten** und lassen sich dort wie andere Dateien löschen. Es gelten dieselben Grenzen (300 Dateien, 15 Mio. Zeichen je Projekt, 1 000 000 Zeichen je Datei, 20 000 Zeichen je Aufruf), Zugangsdaten und Kontonummern lehnt der Server ab. Nach einem Dateianhang oder nach gelesenem Fremdinhalt (Home Assistant, Web, GitHub, Konnektoren, Dateien, Wissen) fragt die KI vor dem Schreiben im Chat nach. In geplanten Aufgaben und in Chats ohne Projekt gibt es das Werkzeug nicht. Das Gedächtnis (kurze Merkzettel, unten) bleibt davon getrennt.

### Gedächtnis

Die KI führt ein eigenes Gedächtnis aus kurzen Einträgen (Thema, höchstens 800 Zeichen Inhalt), in zwei getrennten Bereichen:

- **Haushalt:** gilt für alle Personen dieses Add-ons (Hausregeln, Geräte, Gewohnheiten). Jede Person darf ihn ergänzen; was für alle wichtig ist (etwa zum Smarthome), landet so von selbst dort.
- **Person:** gehört nur dem jeweiligen Profil. Andere Profile können es weder lesen noch ändern, auch nicht über die KI.

Die KI weiß, mit wem sie spricht, legt nützliche und dauerhafte Dinge von selbst ab (`memory_save`), aktualisiert Einträge zum selben Thema und löscht auf Wunsch (`memory_forget`). Beides steht im Aktionsprotokoll unter der Antwort („Gemerkt“, „Vergessen“). In der Seitenleiste öffnet **Gedächtnis** die Einträge: dort lassen sich eigene Einträge ansehen, ergänzen und löschen (zweimal tippen bestätigt). Eine Grenze von 100 Einträgen je Person und 150 für den Haushalt verhindert, dass es unendlich wächst.

**Meine Anweisungen und Import aus Claude (ab 0.42.0).** Unter **Einstellungen → Gedächtnis** steht oben **Meine Anweisungen**: ein Text bis 4000 Zeichen, der in allen Chats dieser Person als Anweisung mitgeht (Tonfall, Sprache, feste Vorlieben), zusätzlich zu den Anweisungen eines Projekts; bei einem Widerspruch gelten die des Projekts. Das ist das Gegenstück zu den „Vorlieben“ bei Claude. Gespeichert wird er je Person in `profiles.instructions` (Datenbankschema 18), er gilt auch für geplante Aufgaben und steht in „Meine Daten“ (`anweisungen.md`). Zugangsdaten und Kontonummern lehnt der Server ab.

Darunter liest **Aus Claude übernehmen** einen Gedächtnis-Export von Claude (Einstellungen, Bereich Gedächtnis, Export als ZIP mit Markdown) oder eine einzelne Markdown-/Textdatei ein. Der Ablauf hat zwei Schritte:

1. **Vorschau** (`POST /api/memory/import/preview`, speichert nichts): Das ZIP wird sicher gelesen (höchstens 400 Dateien, 2 MB je Datei, 20 MB entpackt, nur `.md`, `.markdown`, `.txt`; Systemdateien und Pfade mit `..` werden übergangen). Aus `profile.md` wird ein Eintrag „Profil“, aus `areas/`, `topics/` und `people/` je ein Eintrag (Thema aus dem Dateinamen, bei Personen „Person: …“), aus `preferences.md` auf oberster Ebene der Text für **Meine Anweisungen**. Weitere Vorlieben-Dateien (zum Beispiel aus Projekten) werden normale Einträge. Kopfdaten (`---`), Markierungen wie `[stated]` und Zusätze wie `(for=code)` werden entfernt. Texte über 800 Zeichen werden an Zeilengrenzen auf mehrere Einträge verteilt, Themen über 60 Zeichen gekürzt, ein Thema mit dem reservierten Anfang „HA · “ wird umbenannt. Funde mit Zugangsdaten, Schlüsseln oder Kontonummern werden aussortiert und unter „übersprungen“ genannt. Eine lose Liste ohne Überschriften (zum Beispiel aus einem anderen KI-Dienst) wird je Punkt ein Eintrag. Das Format des Exports ist nicht festgeschrieben; der Leser ist deshalb bewusst allgemein und versteht auch den eigenen Export dieses Add-ons (`gedaechtnis.md`).
2. **Übernehmen** (`POST /api/memory/import`): Die Person sieht jeden Eintrag mit Haken, entscheidet, ob er in „Mein Gedächtnis“ oder (mit Schreibrecht) im Haushalt landet, und kann die Anweisungen vor dem Speichern ändern und an die bisherigen anhängen oder sie ersetzen. Themen, die es schon gibt, sind abgewählt und mit Hinweis versehen; ein Haken ersetzt den bisherigen Eintrag. Der Server prüft alles noch einmal (Längen, Zugangsdaten, reservierte Themen, Obergrenze 100/150, Schreibrecht) und meldet übersprungene Einträge mit Grund. Anfragen sind je Person auf 30 in 10 Minuten begrenzt.

Importierte Einträge sind wie alle Gedächtnisinhalte Information für die KI. **Importierte Anweisungen dagegen wirken als Anweisung**: Deshalb gibt es sie nur nach der Vorschau, sichtbar und änderbar. Wer ein ZIP von Dritten bekommt, prüft den Text, bevor er ihn übernimmt.

**Optionen** (nur in der Add-on-Konfiguration):

| Option | Wirkung |
|---|---|
| `memory_enabled` | Standard `true`. Aus: kein Gedächtnis, keine Werkzeuge, kein Eintrag im Gespräch. Gespeicherte Einträge bleiben erhalten. |

**Schutz:**

- Passwörter, Tokens, Schlüssel, IBANs und ähnliche Geheimnisse lehnt der Server als Gedächtniseintrag ab.
- Nach einem Dateianhang oder nachdem die KI eine Datei, Home-Assistant-Daten oder Projektwissen gelesen hat, fragt sie vor jeder Gedächtnisänderung im Chat nach. So kann ein untergeschobener Text (Dateiinhalt, Entitätsname) nichts unbemerkt dauerhaft festschreiben.
- Gedächtnis und Wissen werden der KI als Information übergeben, nicht als Anweisung. Das gilt auch für den Smarthome-Überblick; seine Namen stammen aus Home Assistant und sind als Daten gekennzeichnet.
- Die Einträge liegen in der Datenbank und sind in der Sicherung enthalten.

### Smarthome-Überblick (ab 0.17.0)

Damit die KI deine Home-Assistant-Umgebung von Anfang an kennt, liest das Add-on selbst einen Überblick ein und legt ihn als Haushaltseinträge ab (Thema beginnt mit „HA · “). Das passiert ohne KI-Aufruf, nur mit lesenden Abfragen an Home Assistant, und kostet daher keine Nachrichten deines Abos.

- **Wann:** etwa 30 Sekunden nach dem ersten Start, danach alle 7 Tage, außerdem auf Knopfdruck („Neu einlesen“ im Gedächtnis-Dialog). Nach einem Fehler (z. B. Home Assistant noch nicht bereit) wird nach etwa 15 bis 25 Minuten erneut versucht. Nur aktiv, wenn das Gedächtnis an ist und mindestens ein Profil Zugriff auf Home Assistant hat.
- **Was:** Name, Version, Zeitzone und Einheiten; Etagen und Bereiche; je Bereich die steuerbaren Entitäten (Licht, Schalter, Rollläden, Klima, Medien …) und Sensoren mit ihrer Art; Entitäten ohne Bereich; Entitäten je Typ; Integrationen; Automationen, Skripte und Szenen mit Namen; Helfer; Personen und Zonen (nur Namen); Dashboards. Deaktivierte, ausgeblendete und Diagnose-Entitäten werden übersprungen.
- **Was nicht:** keine Zustandswerte, keine Koordinaten, keine Zugangsdaten, keine Konfigurationsinhalte von Automationen. Details holt sich die KI bei Bedarf live mit den Home-Assistant-Werkzeugen.
- **Wer sieht es:** alle Profile mit Zugriff auf Home Assistant (mindestens `read`); Profile mit `none` sehen den Überblick nicht, und die KI bekommt ihn für sie nicht. Anders als die KI-Werkzeuge ist der Überblick nicht auf in Assist freigegebene Entitäten beschränkt; wer das nicht möchte, schaltet das Gedächtnis aus.
- **Für die KI:** Die wichtigsten Einträge (System, Etagen und Bereiche, Entitäten je Typ, Integrationen, Personen) stehen im Kontext, höchstens etwa 3500 Zeichen; den Rest liest sie mit `overview_read` (ohne Thema: Liste der Themen). Das Gespräch bleibt dadurch schlank.
- **Ablage:** Jeder Lauf ersetzt die „HA · “-Einträge vollständig (alles oder nichts; schlägt ein Lauf fehl, bleibt der alte Stand). Sie zählen nicht gegen die 150 Einträge des Haushalts, erscheinen nicht in der Liste „Haushalt“ und sind weder von der KI noch von Hand änderbar. Eigene Einträge mit dem Thema „HA · …“ sind nicht möglich.
- **Status:** Während des Einlesens zeigt ein Hinweis oben den Fortschritt (Schritt x von 7), danach kurz das Ergebnis oder bei Fehlern „Erneut versuchen“. Im Dialog „Gedächtnis“ zeigt der Bereich „Home Assistant-Überblick“ Stand, Anzahl und die Einträge.

## Skills (ab 0.36.0)

Ein **Skill** ist eine Anleitung für die KI zu einer bestimmten Art von Aufgabe, zum Beispiel „Zabbix-Templates erstellen“ oder „Angebote schreiben“. Das Format ist das von Anthropic: ein Ordner mit `SKILL.md` (Kopf mit `name` und `description`, danach die Anleitung) und optional `references/`, `assets/` und `scripts/`.

- **Wo (ab 0.37.0):** Die Seite heißt **Anpassungen** (Seitenleiste, unter „Geplant“) und hat oben die Reiter **Skills**, **Konnektoren** (ab 0.41.0, siehe unten) und **Plugins** (ab 0.43.0, siehe unten). Unter „Skills“ schaltet ein Umschalter zwischen **Meine** (deine Skills, darunter die **Standard**-Skills; ab 0.40.0 mit **Suche** über Name und Beschreibung) und **Entdecken**; jede Karte trägt ein kleines Symbol (bei empfohlenen Skills je Kategorie, sonst das Skill-Symbol, bei Standard-Skills Schichten); rechts steht **Hinzufügen** mit **Skill importieren**, **Von GitHub-Link** und **Selbst schreiben**. Skills gelten **global je Person**, also in allen Chats und auch in Projekten; es gibt keine Skills nur für ein Projekt. Die KI wählt anhand der Beschreibung selbst, welches Skill zur Aufgabe passt; was du nicht in jedem Chat haben willst, schaltest du auf der Karte aus. Jede Person hat ihre eigenen; niemand sieht die Skills anderer.
- **Entdecken (Empfohlen):** Zeigt 70 geprüfte Skills, die mit dem Add-on kommen, in acht Kategorien: Marketing & Social Media (Texte, SEO, Social Media, Preise, PR, Community), Design (Gestaltung, Kritik, Barrierefreiheit, Nutzerforschung), Büro & Dokumente (Geschäftsbrief nach DIN 5008, Protokoll, E-Mail, Präsentation, Zusammenfassung, Dokumente gemeinsam schreiben, Statusbericht, Prozesse), Technik & IT, Daten & Analyse, Produkt & Projekte, Kunden & Support und Personal. Oben stehen **Suche** (Name, Beschreibung, Kategorie; Umlaute und Groß-/Kleinschreibung sind egal), **Sortierung** (Beliebteste, A bis Z) und die **Kategorien** mit der Zahl der Treffer. Die Karten nennen den Autor. „Beliebteste“ ordnet nach der Verbreitung der Skills (Zahlen öffentlicher Verzeichnisse, Stand November 2026, in `catalog.json`; sie werden nicht angezeigt und nicht automatisch aktualisiert). Die Skills stammen aus [anthropics/skills](https://github.com/anthropics/skills) und [anthropics/knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins) (Apache-2.0), [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) (MIT) und sechs eigene deutsche Skills (MIT). Aufgenommen ist, was ohne eigene Zugänge funktioniert und nicht für ein Produkt wirbt; was geändert oder weggelassen wurde, steht in `app/skill_catalog/NOTICE.md`. Quelle und Lizenz zeigt die Detailansicht, der Lizenztext liegt als `LICENSE.txt` im Skill. **Hinzufügen** kopiert das Skill in „Meine“, dort lässt es sich ausschalten, ansehen und entfernen. Empfohlene Skills gelten als vertrauenswürdig (kein Fremdinhalt). Ist der Name schon vergeben, etwa durch ein eigenes Skill, bleibt das eigene unangetastet.
- **Hinzufügen:** **Skill importieren** nimmt eine einzelne `SKILL.md`, ein `.skill` oder ein ZIP (mit dem Ordner darin oder flach). Vor dem Speichern zeigt eine Vorschauseite Name, Beschreibung, Dateien, Warnungen und Übersprungenes; dasselbe Skill erneut importiert ersetzt das vorhandene. **Selbst schreiben** öffnet eine Seite mit Name, Beschreibung („wann nutzen?“) und großem Feld für die Anleitung. Ein Klick auf eine Karte öffnet das Skill: Anleitung und alle weiteren Dateien lesen, ein- und ausschalten, als `.skill` sichern, löschen. Die Skills sind auch in „Meine Daten“ (ZIP) enthalten, unter `skills/`.
- **Von GitHub-Link (ab 0.38.0):** Du gibst den Link zu einem Skill-Ordner in einem **öffentlichen** GitHub-Repository an, zum Beispiel `https://github.com/besitzer/repo/tree/main/skills/name` (auch der Link zu einer Datei darin, zum Repo oder die Kurzform `besitzer/repo`; liegt dort genau ein Skill, wird er gefunden, sonst nennt die Meldung die Namen). Danach erscheint dieselbe Vorschau wie beim Hochladen, zusätzlich mit der Quelle (`besitzer/repo@abcdef1 ordner`, der Commit ist festgehalten); gespeichert wird erst nach „Hinzufügen“, und das Skill gilt als **importiert** (Fremdinhalt, siehe unten). Das Add-on ruft dafür nur `api.github.com` und `raw.githubusercontent.com` auf, **anonym und ohne das GitHub-Token** aus der Konfiguration; private Repositories lassen sich deshalb nicht holen (dort die Dateien herunterladen und als ZIP importieren). Ohne Anmeldung erlaubt GitHub 60 Anfragen je Stunde und IP-Adresse; bei Überschreitung bittet eine Meldung um etwas Geduld. Grenzen: 120 Dateien, 3 MB zusammen, Dateien über 2 MB und versteckte Dateien sowie `node_modules/` und `evals/` werden übersprungen. Das macht das Add-on auf deinen Klick, nicht die KI; sie hat weiterhin keinen Zugriff auf das Netzwerk.
- **So nutzt die KI sie:** In der Systemanweisung stehen nur Name, Herkunft und Beschreibung der eingeschalteten Skills (Beschreibungen auf 300 Zeichen gekürzt, zusammen höchstens 9000 Zeichen; was darüber hinausgeht, steht nur mit dem Namen da, `skill_load` liefert trotzdem alles). Passt eine Aufgabe, lädt die KI das Skill mit `skill_load` (Anleitung plus Liste der weiteren Dateien) und liest Dateien daraus bei Bedarf mit `skill_file`. Im Chat steht dann „Skill genutzt: <Name>“, die Warteanzeige zeigt die Lupe. Auch **geplante Aufgaben** können die Skills der Person nutzen (nur lesend).
- **Standard-Skills:** Die mitgelieferten Gestaltungs-Leitfäden (Grundregeln, Word, PowerPoint, Excel, PDF, HTML) stehen unter „Meine“ im Abschnitt **Standard** (nur ansehen). Sie sind immer an und lassen sich nicht ausschalten. **Eigene, importierte und empfohlene Skills gehen ihnen vor**, wenn sie zur Aufgabe passen (zum Beispiel ein Design-Skill); die Standardregeln gelten für das, was das Skill offen lässt. Bei neuen Dateien weist die automatisch gelieferte Regelantwort auf passende Skills hin.
- **Skripte werden nie ausgeführt.** `scripts/` wird wie jede andere Datei als Text gespeichert und kann von der KI gelesen und als Vorlage genutzt werden; der Import weist darauf hin. Das Add-on hat keine Umgebung, in der fremder Code sicher liefe (es hält Zugangsdaten und Datenbank).
- **Importierte Skills sind Fremdinhalt.** Wie Dateianhänge oder Webseiten gelten sie als möglicherweise eingeschleuste Anweisungen: Hat die KI in einer Antwort ein importiertes Skill geladen, fragt sie danach vor jeder Änderung in Home Assistant, bei GitHub, im Gedächtnis und vor Bildern erst nach (Aktionsart `skill-ext`). Selbst geschriebene und empfohlene Skills (`skill`) lösen das nicht aus. Im normalen Gebrauch fällt das nur bei Änderungen auf, die nach dem Laden eines importierten Skills folgen.
- **Grenzen:** `SKILL.md` höchstens 40 000 Zeichen, `description` 1024, je Skill 40 Dateien und 500 000 Zeichen Text, 4 MB je Hochladen, 120 Skills je Person (bis 0.36.x 60). Namen: Kleinbuchstaben, Ziffern, Bindestriche (höchstens 64). Binärdateien (Bilder, Programme) werden übersprungen.
- **Technik:** Tabellen `skills` (Name je Person eindeutig, Spalte `origin`: `own`, `imported`, `recommended`) und `skill_files` (Datenbankschema 15, in der HA-Sicherung enthalten). Die empfohlenen Skills liegen unter `app/skill_catalog/` (`catalog.json` mit Kategorien und Skills, je Skill ein Ordner, die Lizenztexte in `licenses/`, dazu `NOTICE.md`; die Lizenz kommt beim Hinzufügen als `LICENSE.txt` ins Skill). Schnittstellen: `GET/POST /api/skills` (die Antwort enthält auch `categories`), `POST /api/skills/preview`, `POST /api/skills/github` (holt den Ordner von GitHub, liefert Vorschau und ZIP), `POST /api/skills/new`, `GET/PATCH/DELETE /api/skills/{id}`, `GET /api/skills/{id}/file?path=`, `GET /api/skills/{id}/export`, `GET /api/skills/standard/{name}`, `GET /api/skills/recommended/{id}` (und `/file?path=`), `POST /api/skills/recommended/{id}`. Keine neuen Optionen.

## Konnektoren (ab 0.41.0)

Ein **Konnektor** verbindet die KI mit einem Dienst außerhalb von Home Assistant über das **Model Context Protocol (MCP)**, zum Beispiel mit deinem Zabbix-Server, später mit Microsoft 365 oder Google Workspace. Ein Skill ist eine *Anleitung* (Text), ein Konnektor gibt der KI *Werkzeuge* (nachschlagen, anlegen, senden). Beides lässt sich kombinieren: Das Skill sagt, wie man vorgeht, der Konnektor liefert die Daten und Aktionen.

- **Wo:** Seite **Anpassungen** → Reiter **Konnektoren**: Karten mit Symbol (Anfangsbuchstaben), Suche, Status (*Verbunden*, *Nicht verbunden*, *Neu anmelden*, *Fehler*) und Schalter. Ein Klick öffnet die Detailansicht mit **Verbinden/Anmelden**, **Neu einlesen**, **Trennen**, **Bearbeiten** und der Liste der Werkzeuge. Ab 0.42.0 hat der Reiter denselben Aufbau wie „Skills“: **Meine | Entdecken | Community** und **Hinzufügen** in einer Zeile. Bei „Meine“ stehen deine **eigenen** Konnektoren oben, danach die für alle freigegebenen. Siehe „Entdecken, Community und Logos“.
- **Entdecken, Community und Logos (ab 0.42.0):**
  - **Entdecken** zeigt einen Katalog von 31 Diensten in sechs Kategorien (Suche und Kategorien wie bei den Skills): Google (Gmail, Kalender, Drive, Docs, Tabellen, Präsentationen, Chat, Kontakte), Microsoft Learn, GitHub, Sentry, Vercel, Supabase, Hugging Face, Cloudflare Docs, Context7, DeepWiki, Exa, Notion, Linear, Atlassian, monday.com, Airtable, Todoist, Canva, Fireflies, Slack, Stripe, PayPal und HubSpot. „Hinzufügen“ öffnet eine Einrichtungsseite; Adresse, Anmeldeart und Berechtigungen kommen aus dem Katalog. Bei jedem Eintrag steht, woher die Adresse stammt: aus der Dokumentation des Anbieters, aus der Konnektoren-Liste von Anthropic oder nur aus allgemeiner Kenntnis (dann nicht selbst geprüft).
  - **Google Workspace:** Du brauchst eine **eigene App** in der Google Cloud Console (Web-Client mit dem Haken „Use this client for an AI-powered agent“; die Einrichtungsseite führt durch die Schritte und zeigt die Weiterleitungs-URI zum Kopieren). Client-ID und Secret trägst du bei „Hinzufügen“ ein, danach klickst du auf „Anmelden“. Die Berechtigungen sind für Gmail, Kalender und Drive vorgegeben; bei Docs, Tabellen, Präsentationen, Chat und Kontakte trägst du sie nach Googles Seite selbst ein. Googles Server sind eine **Developer Preview** und können sich ändern.
  - **Microsoft 365** gibt es **nur als Anleitung**: Anthropics Microsoft-Server verlangt eine Freischaltung durch Anthropic, Microsofts eigene Server sind Vorschau. Beschrieben wird der Community-Server „ms-365-mcp-server“ (Softeria), den du selbst betreibst, mit Entra-App-Registrierung. Das ist nicht ausprobiert und kein Microsoft-Produkt.
  - **Community** (nur mit Stufe `own`/`global`) durchsucht das offene **MCP-Register** nach Servern im Internet. Die Einträge sind **nicht geprüft** (jede Person kann dort etwas eintragen); „Hinzufügen“ öffnet das Formular mit den Angaben, die Anmeldeart kann falsch sein. Der Aufbau der Register-Antwort ist nach der Dokumentation nachgebaut, nicht gegen das echte Register geprüft.
  - **Logos:** Dienste aus dem Katalog tragen ihr Marken-Logo (22 mitgeliefert, simple-icons, CC0; für Slack, Canva, Exa, Fireflies, DeepWiki, Context7, monday.com und Microsoft gibt es keins, dort stehen die Anfangsbuchstaben). Bei jedem Konnektor kannst du im Formular ein **eigenes Logo** wählen: per **Link** (das Add-on holt das Bild einmal, nur `https` und öffentliche Adressen) oder per **Upload**. Erlaubt sind PNG, JPEG, GIF und WebP bis 128 kB; SVG nicht, weil es Skripte tragen kann. „Logo entfernen“ stellt das Marken-Logo bzw. die Anfangsbuchstaben wieder her. Ein Logo sehen alle, die den Konnektor sehen (privat: nur du).
- **Rechte** (`connector_access` je Benutzer, sonst `connector_access_default`, vorgegeben `use`): `none` keine Konnektoren; `use` freigegebene (globale) nutzen; `own` zusätzlich **eigene** (private, nur für die Person) anlegen; `global` zusätzlich **globale für alle** anlegen und ändern und Adressen im Heimnetz erlauben. Private Konnektoren sieht nur ihr Besitzer, auch die Administration nicht. Ein globaler Konnektor kann *pro Person angemeldet* sein (jede Person meldet sich selbst an, z. B. Mail) oder **einen gemeinsamen Zugang** haben (einmal hinterlegt, alle nutzen ihn, ohne ihn zu sehen; nur ohne OAuth).
- **Anmeldearten:** *Keine*, *Token (Bearer)*, *Schlüssel in einem Header* (Name des Headers frei, z. B. `X-API-Key`) und *OAuth* (Autorisierungscode mit PKCE). Bei OAuth findet das Add-on die Anmeldeadressen selbst (Standard der MCP-Spezifikation: geschützte Ressource, Metadaten des Autorisierungsservers) und registriert sich, wenn der Dienst das anbietet. Dienste ohne automatische Registrierung (z. B. Google) brauchen eine **eigene App** beim Dienst: Client-ID, Secret, Berechtigungen und gegebenenfalls Anmelde-/Token-Adresse und Zusatzangaben (`access_type=offline`) trägst du unter „Erweitert“ ein.
- **Rückkehr nach der Anmeldung:** Mit **Domain-Zugang** (`public_base_url`) kehrt der Browser automatisch auf `https://<Domain>/connectors/callback` zurück; diese Adresse muss beim Dienst als Weiterleitungs-Adresse erlaubt sein. Ohne Domain-Zugang gilt `http://localhost/connectors/callback`: Der Browser zeigt nach der Anmeldung eine Fehlerseite, du kopierst die Adresse aus der Adresszeile und fügst sie im Add-on ein.
- **Werkzeuge:** Beim Verbinden liest das Add-on die Werkzeugliste des Servers (höchstens 40 je Konnektor). Werkzeuge, die der Server als rein lesend kennzeichnet (`readOnlyHint`), sind **an**; alle anderen (auch ohne Angabe) sind **aus**, bis du sie einschaltest. Die KI sieht sie als `conn<Nummer>_<Name>`; je Antwort höchstens 80. Ein Neu-Einlesen behält deine Auswahl.
- **Sicherheit:** Das Add-on ist der MCP-Client und reicht die Werkzeuge als eigene weiter (Server `ki`). Dadurch gelten die üblichen Regeln: Lesen ohne Rückfrage; **jede Änderung fragt im Chat nach** (einmal, oder „in diesem Chat immer zulassen“ je Konnektor); nach **Fremdinhalt** (alles, was in derselben Antwort aus Home Assistant, Web, GitHub, Dateien, importierten Skills oder einem Konnektor kam) oder mit Dateianhang **immer**. Alles, was ein Konnektor liefert, ist Fremdinhalt (Aktionsarten `mcp-read`, `mcp-write`): Es kennzeichnet sich in der Antwort als Daten und löst bei anderen Werkzeugen (Home Assistant, GitHub, Gedächtnis, Bilder) die Rückfrage aus. **Geplante Aufgaben nutzen nur lesende Werkzeuge.** Zugangsdaten (Token, Client-Secret) liegen **verschlüsselt** (Fernet) in der Datenbank; der Schlüssel ist die Datei `connector.key` im Datenordner (Rechte 600), **nicht** im Config-Ordner und nicht in den Schnappschüssen; Token gehen nie an den Claude-Prozess, nie in Protokoll, Fehlermeldung oder „Meine Daten“. Eine Sicherung von Home Assistant enthält Datenbank *und* Schlüssel; wer die Sicherung hat, kann die Zugangsdaten lesen.
- **Adress-Schutz (SSRF):** Wer Konnektoren anlegen darf (Stufe `own` oder `global`), darf auch Adressen im Heimnetz und mit `http` eintragen, zum Beispiel einen Zabbix-MCP-Server wie `http://mon.example.lan:8080/mcp`. Bis 0.43.2 brauchte das die Option `connector_allow_private` bzw. den Haken „Heimnetz“; seit 0.45.0 ist es einfach erlaubt. **Nie** erlaubt: Link-Local (u. a. Cloud-Metadaten 169.254.169.254), Multicast, nicht routbare Adressen und die Namen `supervisor` und `hassio`. Ausnahme ab 0.43.2: Heimnetz-DNS setzt für einen Namen oft die IPv6-Antwort auf `100::` (Discard-Präfix, Pakete dorthin werden verworfen), damit er nur über IPv4 erreichbar ist; solche Adressen werden übergangen, solange der Name noch eine brauchbare Adresse hat. Steht nur `100::` da, bleibt es abgelehnt. Weiterleitungen werden nicht befolgt; Antworten sind auf 4 MiB begrenzt, ein Aufruf hat 30 Sekunden Zeit. Der Name wird vor jedem Aufruf aufgelöst und geprüft; ein Angreifer mit eigenem DNS-Server könnte zwischen Prüfung und Verbindung die Antwort wechseln (DNS-Rebinding). Das schützt der Adress-Schutz nur teilweise; deshalb dürfen nur Personen mit Stufe `own`/`global` überhaupt Adressen eintragen.
- **Grenzen:** Nur **Streamable HTTP** (Adressen enden oft auf `/mcp`); der alte SSE-Transport (`/sse`) wird nicht unterstützt. Antworten des Servers als JSON oder als Ereignisstrom; Anfragen des Servers an das Add-on (Sampling, Roots) werden nicht beantwortet. Bilder aus Werkzeugergebnissen werden an die KI weitergegeben (PNG, JPEG, GIF, WebP bis 4 MiB, höchstens 4). Die Konnektoren von claude.ai (OAuth-Apps von Anthropic) lassen sich nicht übernehmen; sie gehören zu deinem Claude-Konto und nicht zum Add-on.
- **Bekannt und ungetestet:** Alles ist bisher nur gegen nachgebaute MCP-, OAuth- und Register-Server getestet, nicht gegen echte Dienste (Zabbix, Google, Microsoft, das MCP-Register). Mehrere Katalogadressen stammen aus Listen oder allgemeiner Kenntnis (`source`). Beim ersten Einsatz bitte mit einem Konnektor ohne Schreibrechte anfangen. Die zentrale Gefahr bleibt eingeschleuste Anweisung in gelesenen Inhalten (Mails, Tickets, Webseiten); deshalb die Rückfragen und die abgeschalteten Schreibwerkzeuge.
- **Technik:** Tabellen `connectors`, `connector_accounts` und `connector_icons` (Datenbankschema 17). Module `connectors.py` (Dienst, Werkzeugkasten), `mcp_client.py`, `connector_oauth.py`, `netguard.py`, `vault.py`, `connector_catalog/` (Katalog `catalog.json`, Anleitungen), `connector_icons.py` (Bildprüfung, Abruf), `connector_registry.py` (Register-Suche). Schnittstellen: `GET/POST /api/connectors`, `GET /api/connectors/catalog`, `GET /api/connectors/registry`, `GET /api/connectors/{id}/icon`, `PATCH/DELETE /api/connectors/{id}`, `POST …/connect`, `…/refresh`, `…/disconnect`, `…/oauth/start`, `PATCH …/account`, `POST /api/connectors/oauth/finish`, `GET /connectors/callback` (ohne Sitzung: der einmalige, kurz gültige `state` bindet an Person und Konnektor). Verbinden und Anmelden sind begrenzt (40 je 10 Minuten und Person); je Person höchstens 10 private, insgesamt 30 globale Konnektoren. Optionen: `connector_access`, `connector_access_default`, `connector_write_confirm`, `connector_allow_private`.

## Plugins (ab 0.43.0)

Ein **Plugin** ist ein Paket aus Skills und Konnektoren zu einem Thema, zum Beispiel „Entwicklung“ (Skills für Code-Prüfung und Fehlersuche, dazu Sentry und Dokumentation zu Bibliotheken). Du findest sie auf der Seite **Anpassungen** im Reiter **Plugins**: Umschalter **Meine | Entdecken**, Suche und rechts **Von GitHub-Link**.

- **Entdecken:** 10 Pakete (Posteingang & Termine, Büro & Dokumente, Entwicklung, Recherche, IT-Betrieb, Projekt & Team, Marketing & Inhalte, Daten & Auswertung, Kundenservice, Design & Gestaltung). Die Karte zeigt, wie viele Skills und Konnektoren dazugehören; die Detailansicht nennt jeden Teil. **Hinzufügen** legt die Skills an (wie bei „Skills → Entdecken“) und die Konnektoren als *nicht verbunden*; verbunden wird danach bei den Konnektoren. Google-Dienste und Slack brauchen eine eigene App, Microsoft 365 ist nur eine Anleitung: Sie werden nicht angelegt, die Ergebnisseite verweist auf „Konnektoren → Entdecken“. Wer keine eigenen Konnektoren anlegen darf (Stufe unter `own`), bekommt nur die Skills. Noch einmal „Hinzufügen“ ergänzt nur, was fehlt.
- **Von GitHub-Link:** Du gibst den Link zu einem Claude-Plugin auf GitHub an (Repository, Ordner oder Datei; öffentlich, anonym abgerufen, fester Commit). Das Plugin ist ein Ordner mit `.claude-plugin/plugin.json`, `skills/<name>/SKILL.md` und `.mcp.json`. Übernommen werden **nur Skills und Server-Adressen**. Befehle (`commands/`), Unteragenten (`agents/`), Hooks und Skripte werden nie geladen; die Vorschau nennt sie nur. In der **Vorschau** (nichts ist gespeichert) kreuzt du an, was du willst, und wählst bei jeder Server-Adresse die Anmeldeart (sie ist geraten). Server müssen `https` und Streamable HTTP nutzen; Programme auf dem eigenen Rechner, der alte SSE-Transport und Adressen mit Platzhaltern werden mit Grund abgelehnt. Importierte Skills gelten als **Fremdinhalt**; ein gleichnamiges eigenes Skill wird nie überschrieben. Ein neuerer Stand desselben Plugins ersetzt den alten.
- **Meine:** Karten mit Herkunft („aus dem Katalog“, „von GitHub“) und dem Hinweis, wenn Teile fehlen (zum Beispiel ein Skill, den du inzwischen gelöscht hast). Die Detailansicht zeigt Skills und Konnektoren mit Zustand und führt zum Konnektor. **Entfernen** löscht **nur, was das Plugin selbst angelegt hat**; Skills und Konnektoren, die du vorher schon hattest oder selbst geändert hast, bleiben.
- **Grenzen:** höchstens 40 Plugins je Person (zusätzlich gelten die Grenzen für Skills, 120, und Konnektoren, 10 private je Person); GitHub-Abruf höchstens 400 Dateien und 6 MB; 30 Hinzufügen- oder Abrufvorgänge je 10 Minuten. Jede Person hat ihre eigenen Plugins.
- **Technik:** Tabelle `plugins` (Datenbankschema 19); Module `package_catalog/` (Katalog `catalog.json`), `plugins.py` (`PluginService`: Katalog, Installieren, Vorschau, Übernehmen, Entfernen), `plugins_github.py` (Abruf). Schnittstellen: `GET /api/plugins`, `POST /api/plugins/catalog/{id}`, `POST /api/plugins/github`, `POST /api/plugins/import`, `DELETE /api/plugins/{id}`. Keine neuen Optionen.

## GitHub (ab 0.19.0)

Die KI kann mit GitHub arbeiten (ab 0.46.0 mit dem eigenen Konto jeder Person): Repositories und Dateien lesen, Code durchsuchen, Issues, Pull Requests, Commits und Workflow-Läufe ansehen, und (mit Schreibrecht) Dateien einchecken, Zweige und Pull Requests anlegen, Issues schreiben, Pull Requests mergen und neue Repositories anlegen. Beispiele: „Schau in doralab/smarthome, warum der letzte Lauf fehlschlägt“, „Lege das Skript aus dem Chat als Pull Request in doralab/smarthome ab“, „Fass die offenen Issues zusammen“.

**Einrichten: jede Person verbindet ihr eigenes GitHub (ab 0.46.0).** In den **Einstellungen** (Konto-Menü unten links → Einstellungen) gibt es die Seite **GitHub**, sobald die Person Rechte dafür hat (`github_access` ist `read` oder `write`). Dort:

1. **Mit GitHub verbinden** wählen. Es erscheint ein Code und der Knopf „GitHub öffnen“.
2. Bei GitHub den Code eingeben und den Zugriff bestätigen. Die Seite wartet und meldet sich von selbst mit „Verbunden als …“; der Code gilt 15 Minuten.
3. Alternativ **Token einfügen**: ein selbst erzeugtes Token (Fine-grained oder klassisch). Das Add-on prüft es bei GitHub, bevor es gespeichert wird.
4. **Trennen** löscht das Token im Add-on. Der Zugang bei GitHub bleibt bestehen, bis die Person ihn dort unter Einstellungen → Anwendungen widerruft.

Das Token liegt **verschlüsselt** in der Datenbank (Fernet, Schlüssel `connector.key` im Datenordner wie bei den Konnektoren), geht nur an `api.github.com` und nie an den Browser, ins Protokoll, in Fehlermeldungen oder in „Meine Daten“. Wer kein GitHub braucht oder haben soll, verbindet einfach nichts. Wer verbunden ist, arbeitet mit **seinem eigenen Konto** und sieht nur, was dieses Konto sieht. Die Anmeldung läuft über die OAuth-App „HA Copilot“ (Device Flow, nur die öffentliche Client-ID steckt im Add-on, kein Geheimnis) mit dem Recht `repo` (Repositories lesen und schreiben, auch private). Dateien im Ordner `.github/workflows/` kann die KI auf diesem Weg nicht ändern (dafür bräuchte die App das Recht `workflow`); bei Organisationen muss ein Besitzer die App eventuell erst freigeben.

**Welche Rechte jemand hat, bleibt Sache der Konfiguration:** `github_access` im Benutzer-Eintrag, sonst `github_access_default` (Standard `none`). Ein verbundenes Konto ändert daran nichts: Bei `read` kann die KI auch mit dem eigenen Konto nur lesen.

**Kein gemeinsames Token mehr (ab 0.47.0).** Die Optionen `github_token` und `github_repos` gibt es nicht mehr. Wer kein eigenes Konto verbunden hat, hat kein GitHub, auch nicht in geplanten Aufgaben. Ein altes `github_token` in der Konfiguration wird ignoriert und kann gelöscht werden. Wer ein Token selbst erzeugen will, fügt es im Seite „GitHub“ unter **Token einfügen** ein: bei GitHub unter Settings → Developer settings → Personal access tokens, Empfehlung *Fine-grained tokens* mit nur den nötigen Repositories und den Rechten *Contents*, *Pull requests*, *Issues* (je Read and write, zum Lesen Read-only) sowie *Actions* und *Metadata* (Read-only). Neue Repositories im eigenen Konto kann GitHub nur mit einem klassischen Token (Recht „repo“) anlegen.

**Stufen** (`github_access` je Benutzer, sonst `github_access_default`):

| Stufe | Darf |
|---|---|
| `none` | Kein GitHub. |
| `read` | Lesen: Repositories, Ordner, Dateien, Code-Suche, Issues, Pull Requests (mit Änderungen), Commits, Zweige, Tags, Releases, Workflow-Läufe. |
| `write` | Zusätzlich: Dateien in einem Commit schreiben, ändern, löschen (auch mehrere Dateien auf einmal und Dateien aus dem Chat, z. B. ein erzeugtes Skript oder Dokument), Zweige anlegen, Pull Requests, Issues und Kommentare schreiben und ändern, Pull Requests mergen, Repositories anlegen (standardmäßig privat). |

**Weitere Optionen:**

- Eine Freigabeliste für Repositories gibt es nicht mehr (`github_repos` entfiel mit dem gemeinsamen Token in 0.47.0): Ein verbundenes Konto reicht ohnehin nur so weit, wie die Person bei GitHub selbst darf. Wer die KI auf bestimmte Repositories beschränken will, fügt ein Fine-grained Token ein, das nur diese Repositories enthält.
- Jede GitHub-**Änderung** fragt im Chat nach (Zulassen, Ablehnen, „In diesem Chat immer zulassen“); das ist seit 0.45.0 fest, die Option `github_write_confirm` gibt es nicht mehr.

**Immer mit Rückfrage**, egal wie eingestellt, und ohne „immer zulassen“: Commit auf den Hauptzweig, Commits mit Workflow-Dateien (`.github/workflows/`, sie führen bei GitHub Code aus), Pull Requests mergen, Repositories anlegen, jedes `DELETE`, sowie jede Änderung, nachdem die KI in derselben Antwort Inhalte aus Home Assistant, Projektwissen oder GitHub gelesen hat oder wenn die Nachricht einen Dateianhang hat. Die Rückfrage zeigt Repository, Zweig, Nachricht und jede Datei. Den Zweig prüft der Server vor der Rückfrage, damit du nichts bestätigst, was ohnehin scheitern würde. Empfehlung für bestehende Projekte: Änderungen auf einem neuen Zweig mit Pull Request, nicht direkt auf den Hauptzweig; die KI ist so angewiesen.

**Nie möglich**, auch nicht über den allgemeinen Zugang: Repository löschen, umbenennen, übertragen, Sichtbarkeit ändern oder archivieren, Mitarbeiter und Einladungen, Deploy- und SSH-Schlüssel, Webhooks, Geheimnisse und Variablen von Actions, Runner, Schutzregeln und Rulesets, Umgebungen, Pages, Forks, Sicherheitseinstellungen sowie das Löschen des Hauptzweigs. Das erzwingt der Server, nicht die KI. Das muss der Mensch selbst bei GitHub tun.

**Wichtig zu wissen:**

- Das Konto einer Person gilt in Chats ebenso wie in geplanten Aufgaben (dort nur lesend). Die KI sieht damit **alles, was dieses Konto sieht** (auch private Repositories); vergib die Stufe `write` also nur an Personen, denen du das zutraust. Ein Konto, das die Person bei GitHub widerruft, meldet sich beim nächsten Zugriff mit der Bitte, neu zu verbinden; die Einrichtungsprüfung zeigt es ebenfalls.
- Alles, was aus GitHub kommt (Dateien, Issues, Kommentare, Commit-Nachrichten), ist für die KI Information und keine Anweisung und entsprechend gekennzeichnet. Wegen des Risikos untergeschobener Anweisungen fragt jede Änderung nach, sobald in derselben Antwort GitHub-Inhalte gelesen wurden.
- Commits laufen über die Git-Schnittstelle von GitHub: mehrere Dateien landen in **einem** Commit; es wird nie erzwungen überschrieben (`force` ist aus), ein Konflikt wird gemeldet. Dateien bis 8 MB, bis 60 Dateien und 24 MB je Commit.
- **Sichtbarkeit:** Unter der Antwort steht einklappbar „N Aktionen bei GitHub, davon M Änderungen“ mit jedem Schritt; bei Commits, Pull Requests und Issues gibt es einen Link „Öffnen“ (nur Adressen auf github.com werden angezeigt).
- GitHub begrenzt Anfragen (bei Tokens 5 000 je Stunde, die Code-Suche deutlich weniger); wird das Limit erreicht, sagt die KI das.

## Web, Modell und Nutzungslimit (ab 0.20.0)

**Websuche.** Die KI kann im Web suchen und Seiten lesen, wenn es nötig ist (Preise, Versionen, Nachrichten, Regeln) oder wenn du sie darum bittest („Recherchiere …“, „Schau nach, ob …“). Unter der Antwort steht einklappbar „Recherche im Web (2 Suchen, 3 Seiten gelesen)“ mit jedem Schritt; am Ende nennt die KI ihre Quellen.

- **Einstellen:** Standardmäßig an; je Benutzer lässt sie sich mit `web_access: off` abschalten. Im Chat lässt sich die Websuche im Menü rechts unter dem Eingabefeld (Knopf mit Modell und Aufwand, z. B. „Sonnet 5.5 Mittel“) je Browser ein- und ausschalten; ein kleiner Punkt am Knopf zeigt „aus“. Ausgeschaltet wird sie auch gar nicht erst angeboten.
- **Suche:** das eingebaute Werkzeug von Claude (läuft bei Anthropic, nicht in deinem Netz). Ob es mit deinem Abo bzw. API-Schlüssel nutzbar ist, entscheidet Anthropic; gibt es einen Fehler, steht er in der Aktionszeile und die KI sagt es. Die Suche verbraucht Kontingent deines Abos wie jede andere Nachricht, keine Zusatzkosten.
- **Seiten lesen** (`web_fetch`) macht das Add-on selbst, nicht Claude. Deshalb ist es gegen Zugriffe aufs Heimnetz abgesichert: Es werden nur öffentliche Adressen geladen. Gesperrt sind private und lokale Adressen (192.168.x.x, 10.x.x.x, 172.16–31.x.x, 127.x.x.x, 169.254.x.x, CGNAT, IPv6 lokal und eingebettete Varianten wie `::ffff:10.0.0.1`), interne Namen (`localhost`, `*.local`, `*.lan`, `*.internal`, Namen ohne Punkt), Zugangsdaten in der Adresse, alle Ports außer 80, 443, 8080, 8443 und Nicht-Web-Adressen (`file:`, `ftp:` …). Geprüft wird die Adresse, mit der die Verbindung tatsächlich aufgebaut wird (kein Zeitfenster für DNS-Tricks), und bei jeder Weiterleitung neu. HTML wird in lesbaren Text umgewandelt (ohne Skripte, Menüs, Fußzeilen), PDF, Text und JSON werden gelesen; Bilder und Binärdaten nicht. Grenzen: 3 MB je Seite, 20 Sekunden, 12 Seiten je Antwort.
- **Schutz vor untergeschobenen Anweisungen:** Was aus dem Web kommt, ist für die KI Information und keine Anweisung und wird so gekennzeichnet. Hat die KI in einer Antwort etwas aus dem Web gelesen, fragt danach jede Änderung (Gedächtnis, GitHub, Home Assistant: auch das Bedienen von Geräten) im Chat nach, ohne „immer zulassen“. Die KI ist angewiesen, nichts Vertrauliches in Suchanfragen und Adressen zu schreiben. Ganz auszuschließen ist das bei jedem Web-Zugriff nicht: Suchanfragen verlassen dein Haus. Wer das nicht möchte, stellt `web_access: off` im Benutzer-Eintrag.

**Modellwahl.** `model` ist das Standard-Modell für neue Chats. Opus und Haiku stehen daneben zur Auswahl (fest im Add-on, keine Option mehr). Die Auswahl steht neben den Denktiefe-Knöpfen (Regler-Symbol mit dem Namen des Modells); das kleine Menü zeigt die Modelle und darunter die Websuche als Schalter, gilt für diesen Chat und wird dort gemerkt; neue Chats beginnen mit dem zuletzt gewählten Modell dieses Browsers. Der Server nimmt nur Modelle aus der Liste an. Welche Modelle dein Abo zulässt, entscheidet Anthropic: Ein nicht verfügbares Modell meldet einen Fehler mit Hinweis auf das Modell, der Chat bleibt benutzbar. Chat-Titel und Zusammenfassungen laufen unabhängig davon mit einem kleinen Haiku-Modell bzw. dem Standard-Modell.

**Hinweis auf das Nutzungslimit.** Dein Claude-Abo hat Limits (Sitzungslimit über 5 Stunden, Wochenlimits). Das Programm meldet dem Add-on, wenn ein Limit fast erreicht ist oder erreicht wurde; dann erscheint oben über dem Chat ein Hinweis, z. B. „Das Sitzungslimit (5 Stunden) ist zu 83 % verbraucht. Es wird um 16:30 Uhr zurückgesetzt.“ bzw. „… ist erreicht. Es wird morgen um 08:00 Uhr zurückgesetzt.“ (Ortszeit deines Browsers). Der Hinweis verschwindet von selbst, sobald das Limit zurückgesetzt ist, und lässt sich bis zum Schließen des Tabs wegklicken. Er gilt für alle Benutzer gleich, weil das Limit dem Abo gehört; der Stand wird gespeichert und übersteht einen Neustart. Erreicht eine Antwort das Limit, steht die Rücksetzzeit auch in der Fehlermeldung. Mit API-Schlüssel statt Abo gibt es diese Meldungen nicht.

## Geplante Aufgaben (ab 0.21.0)

Unter „Neuer Chat“ steht der Menüpunkt **Geplant**. Dort legst du Aufgaben an, die die KI zu festen Zeiten erledigt, auch wenn niemand zusieht, zum Beispiel jeden Morgen um 7 Uhr eine Zusammenfassung, was im Haus offen oder auffällig ist, oder jeden Freitag eine Übersicht der neuen Issues in einem Repository. Jede Aufgabe hat:

- **Name** und **Auftrag** (bis 4000 Zeichen). Der Auftrag muss ohne Rückfrage auskommen, die KI kann während eines Laufs nichts nachfragen.
- **Zeitplan:** täglich, Montag bis Freitag, wöchentlich (an gewählten Wochentagen), monatlich (am gewählten Tag; der 31. gilt in kürzeren Monaten am letzten Tag) oder einmalig (Datum und Uhrzeit), jeweils mit Uhrzeit. Bewusst kein stündlicher Takt: Jeder Lauf verbraucht Kontingent deines Abos.
- optional ein **Modell** (Opus oder Haiku statt des Standards), ob die KI **im Web recherchieren** darf, und die **Benachrichtigung** (siehe unten).

Auf der Seite lässt sich jede Aufgabe pausieren und fortsetzen (Schalter), sofort ausführen („Jetzt ausführen“; der Zeitplan bleibt davon unberührt), bearbeiten und löschen. Jede Person hat bis zu 20 Aufgaben, die anderen sehen sie nicht.

**Was bei einem Lauf passiert:** Zur Zeit legt das Add-on einen neuen Chat an (Name der Aufgabe und Datum, in der Liste mit einem kleinen Uhr-Symbol), trägt den Auftrag als erste Nachricht ein und lässt die KI antworten. Die Antwort steht danach als ungelesener Chat in der Liste. Läuft die Aufgabe gerade, kannst du den Chat öffnen und zusehen. Im Chat kannst du danach ganz normal weiterfragen, dort gelten wieder die üblichen Rechte der Person samt Rückfragen. Auf der Aufgabenseite steht der nächste Lauf, der letzte Lauf mit Ergebnis (Link zum Chat) und, wenn etwas nicht klappte, der Grund.

**Bewusst enger als ein Chat:** Weil niemand zusieht und Rückfragen nicht beantworten kann, ist alles Verändernde gar nicht erst angeboten:

- Home Assistant nur **lesen** (Zustände, Verlauf, Logbuch), auch wenn die Person Schalten oder Ändern darf. Bei Stufe `none` ganz ohne Home Assistant.
- GitHub nur **lesen**, das Gedächtnis nur **lesen**, nichts speichern oder löschen; auch ins Projektwissen schreibt die KI in einem Lauf nicht.
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
2. **fertige Antworten:** Dauert eine Antwort länger als etwa 45 Sekunden und niemand sieht mehr zu (Chat gewechselt, Tab geschlossen, Seite neu geladen), bekommt die Person eine Benachrichtigung mit dem Chat-Titel und dem Anfang der Antwort. Das gilt für alle, die einen `notify_service` eingetragen haben. Sieht die Person zu, kommt nichts.

Die Benachrichtigung zeigt den Anfang der Antwort, also auch auf dem Sperrbildschirm. Wer das nicht möchte, trägt keinen Dienst ein. Browser-Benachrichtigungen (Web Push) gibt es nicht; dafür bräuchte die App einen Dienst im Browser, der auch bei geschlossenem Tab läuft.

`schedules_enabled: false` schaltet den Menüpunkt ab; bestehende Aufgaben ruhen dann.

**Grenzen:** Die Läufe sind mit einer nachgebildeten KI getestet, nicht mit der echten Claude-Anbindung. Ob jeder Auftrag ohne Rückfrage ein gutes Ergebnis liefert, hängt vom Auftrag ab; schreib ihn so, dass er auch ohne dich klar ist („Wenn ein Sensor nicht antwortet, nenne ihn im Ergebnis“). Die Benachrichtigungen an Home Assistant sind gegen eine Nachbildung getestet.

## Suche, Export und eigene Daten (ab 0.22.0)

**Suche.** „Suchen“ in der Seitenleiste (am Computer auch Strg+Umschalt+F bzw. ⇧⌘F am Mac) durchsucht Titel und Nachrichten aller *deiner* Chats, auch die der geplanten Aufgaben. Es zählen nur Chats mit allen eingegebenen Wörtern (die Wörter können in verschiedenen Nachrichten stehen), ohne Beachtung von Groß- und Kleinschreibung und Umlautpunkten („kuche“ findet „Küche“). Zu jedem Treffer stehen Titel, Datum und ein Ausschnitt mit markierter Fundstelle. Es werden höchstens 30 Chats gezeigt, die neuesten zuerst, und mindestens zwei Zeichen verlangt. **Seit 0.41.0** zeigt das Fenster schon ohne Suchwort Vorschläge: **Aktiv** (Chats, in denen gerade eine Antwort entsteht oder eine Bestätigung wartet), **Letzte Elemente** (die sechs zuletzt benutzten Chats mit Datum, ungelesene mit Punkt) und **Aktionen** (Neuer Chat, Neues Projekt, Anpassungen). Reiter oben begrenzen die Suche auf **Alle**, **Chats** (zeitlich gruppiert), **Projekte** (ein Klick zeigt das Projekt in der Seitenleiste) und **Geplant** (nur wenn geplante Aufgaben eingeschaltet sind). Mit Suchwort erscheinen Chats (mit Ausschnitt), passende Projekte, geplante Aufgaben und Aktionen (z. B. „neu“ findet „Neuer Chat“). Bedienung per Tastatur: Pfeil hoch/runter wählt aus, Enter öffnet die Auswahl, bei leerem Feld wechseln Pfeil links/rechts den Reiter, Esc schließt; die Tastenhinweise unten stehen nur am Computer. Gesucht wird nur im Text der Nachrichten, nicht in Anhängen, Aktionsprotokollen, Projektwissen oder erzeugten Dateien.

**Chat exportieren.** Im Menü eines Chats (⋯) speichert „Als Markdown exportieren“ den Chat als `.md`-Datei mit Titel, Projekt, Datum, allen Nachrichten, den Namen der Anhänge und den Aktionen der KI (Home Assistant, GitHub, Web).

**Meine Daten** (Einstellungen → Meine Daten):

- **Alle Chats exportieren:** Eine ZIP-Datei mit allen Chats als Markdown (je Projekt ein Ordner, geplante Aufgaben in einem eigenen Ordner), `projekte.md` (Projekte mit Anweisungen), `gedaechtnis.md` (nur dein persönliches Gedächtnis, nicht das des Haushalts), `anweisungen.md` (deine persönlichen Anweisungen, falls vorhanden) und `geplante-aufgaben.md`. Nicht enthalten sind hochgeladene Projektdateien und von der KI erzeugte Dateien (sie laufen ohnehin ab). Der Export ist auf wenige Abrufe je 10 Minuten begrenzt.
- **Alle Chats löschen:** Entfernt alle deine Chats mit Nachrichten und erzeugten Dateien unwiderruflich. Projekte, Gedächtnis und geplante Aufgaben bleiben. Zur Sicherheit gibt es zwei Schritte: erst eine Rückfrage, dann muss das Wort LÖSCHEN eingetippt werden. Läuft gerade noch eine Antwort, wird abgelehnt (erst beenden oder abwarten). Einen einzelnen Chat löschst du weiter im Chat-Menü.

Alles gilt nur für das eigene Profil; andere Personen sind nie betroffen. Die Löschfunktion ist keine Einstellung für alle, sondern bewusst nur für die eigenen Daten gedacht.

## Einstellungen und Konto-Menü (ab 0.48.1)

Unten links in der Seitenleiste öffnet das Konto-Menü, wie bei Claude, nur noch das Wichtigste: **Einstellungen**, **Nutzung**, **Einrichtungsprüfung** (wenn der Chat über Home Assistant läuft) und, nur über die eigene Domain, **Abmelden**. Gedächtnis, Kurzanleitung und „Das ist neu“ erreichst du nur über die Einstellungen. **Auf dem Handy** gibt es dieses Menü nicht: Ein Tipp auf deinen Namen unten in der Seitenleiste öffnet gleich die Einstellungen, als kompakte Liste mit Karten je Gruppe (wie in der Claude-App); „Abmelden“ steht dort ganz unten. Alles Weitere liegt in den **Einstellungen**, einem **großen Fenster** über dem Chat (Laptop und Tablet, wie bei Claude) mit Liste links und Inhalt rechts; es schließt mit dem Kreuz, mit Esc oder mit einem Klick daneben. Auf dem Handy ist es eine eigene Seite: erst die Liste, dann der Inhalt mit „Zurück“:

- **Präferenzen:** *Allgemein* (Design hell/dunkel/Auto, in Home Assistant eingebettet gibt HA das Design vor; Sprache und Name nur zur Ansicht, die Sprache stellt der Administrator mit `language` ein), *Nutzung*, *Gedächtnis*, *GitHub* (wenn dir `github_access` ≠ `none` gegeben wurde), *Meine Daten*.
- **Hilfe:** *Kurzanleitung*, *Das ist neu* (die Neuerungen der letzten Versionen), *Einrichtungsprüfung*.

**Nutzung** zeigt zwei Dinge. **Claude-Abo:** je Zeitfenster ein Balken mit Prozent verwendet, Rest und Zeitpunkt der Rücksetzung: *Aktuelle Sitzung* (Fenster von 5 Stunden) und *Diese Woche* (Wochenlimit; je nach Abo auch Opus oder Sonnet getrennt). Die Werte meldet Claude mit den Antworten der KI; die Seite zeigt den letzten gemeldeten Stand („Stand: heute, 14:03 Uhr“). Ist die Rücksetzzeit vorbei, steht dort „zurückgesetzt“, der neue Wert erscheint mit der nächsten Antwort. Solange noch nichts gemeldet wurde (zum Beispiel nach der Installation), steht „Noch keine Angabe zum Limit“. Orange Balken heißen „fast erreicht“, rote „erreicht“. Das Limit gehört dem Abo und gilt für alle Personen im Add-on zusammen. **Bilder:** Fotos und Kunstbilder von OpenAI oder Google im laufenden Monat (`image_limit_month`); SVG-Grafiken zählen nicht.

**Seite merken.** Wer neu lädt (zum Beispiel weil Home Assistant das Fenster neu aufbaut), bleibt auf der Seite: Geplant, Anpassungen mit Skills, Konnektoren oder Plugins (auf dem Handy auch die Einstellungen mit der gewählten Unterseite; das Einstellungsfenster am Laptop schließt beim Neuladen) mit Skills, Konnektoren oder Plugins. Das Add-on merkt sich das im Browser (`sessionStorage`), nicht in der Adresse, weil Home Assistant die Adresse im eingebetteten Fenster nicht behält. Ein geöffneter Chat wurde schon vorher gemerkt.

**Technik:** Schnittstelle `GET /api/usage` (`windows`: alle bekannten Zeitfenster des Abos, `limits`: nur Warnungen, `images`: Bilder der Person im Monat). Keine neuen Optionen. Die Sprache bleibt eine Einstellung des Administrators; eine Sprachwahl je Person ist nicht enthalten.

## Einrichtungsprüfung (ab 0.25.0)

Unter **Einstellungen → Einrichtungsprüfung** (Konto-Menü unten links) findest du die Prüfung, wenn du den Chat über Home Assistant öffnest. Die Seite listet auf, was eingerichtet ist und was fehlt: **Nötig** (ohne das läuft der Chat nicht richtig, z. B. der Zugang zu Claude), **Empfohlen** (z. B. Anmeldeversuche hinter dem Tunnel je Besucher zählen) und **Optional** (GitHub, Domain-Zugang, Benachrichtigungen, Erinnerung an Ablaufdaten). Jeder Punkt, der Aufmerksamkeit braucht, klappt die genauen Schritte auf. „Erneut prüfen“ liest die Konfiguration noch einmal und fragt Home Assistant und GitHub kurz ab.

- Beim ersten Start nach der Installation läuft der Chat im Testmodus (solange kein Claude-Zugang eingetragen ist). Oben erscheint dann ein Hinweis mit dem Knopf „Schritte anzeigen“, der direkt die Anleitung für den Claude-Zugang öffnet.
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
- **Excel:** aus JSON (mehrere Blätter möglich), CSV oder Markdown-Tabellen. Erste Zeile = Kopfzeile (fett, Themenfarbe, fixiert, Filter, getönte Wechselzeilen). Zahlen und Datumsangaben werden echte Zellwerte (auch „1.234,5“ und „2026-03-01“; Werte mit führender Null wie „007“ bleiben Text). Zellen mit `=` werden Formeln (englische Funktionsnamen, z. B. `=SUM(B2:B10)`).
- **Windows-tauglich:** `.ps1`, `.psm1` und `.csv` werden als UTF-8 mit BOM gespeichert (sonst zeigen PowerShell 5 und Excel Umlaute falsch an), `.bat` und `.cmd` mit Windows-Zeilenenden.
- **Aufbewahrung:** 14 Tage (fest). Danach löscht das Add-on die Datei; die Karte im Chat zeigt dann „Abgelaufen“. Löschst du einen Chat, werden seine Dateien sofort mit gelöscht. Die Dateien liegen in `/data/outfiles` (und damit in der HA-Sicherung). Grenzen: 12 Dateien je Antwort, 12 MB je Datei, 300 MB je Person.
- **Rechte und Sicherheit:** Eine Datei kann nur die Person laden, für die sie erzeugt wurde (andere erhalten „nicht gefunden“). Der Download braucht die Anmeldung, wird als Anhang mit `sandbox`-Kopfzeile ausgeliefert und nie im Browser ausgeführt. Excel-Formeln mit externen Aufrufen (`WEBSERVICE`, DDE, `|` …) werden als Text abgelegt. Die KI darf Dateien ohne Rückfrage erzeugen, weil das nichts in Home Assistant ändert; sie landen nur bei dir.
- **Abschalten:** `files_enabled: false`.
- **Bibliotheken:** python-docx, openpyxl, python-pptx, fpdf2, cairosvg (SVG zeichnen) und pypdfium2 (Vorschau) werden beim Bauen des Add-ons installiert, dazu die Schrift „Liberation“ für PDF (Umlaute, €, Typografie), libcairo2 und LibreOffice (nur für die Vorschau). Ohne diese Pakete bleibt das Add-on voll nutzbar, die KI kann dann nur Textdateien erzeugen und sagt das, wenn man etwas anderes möchte.

### Gestaltung der Dateien (ab 0.30.0)

**Neu in 0.31.0:** Der Folien-Renderer setzt Präsentationen mit großer Schrift, Karten (Liste mit fetten Stichworten), Bild über die halbe Folie, Zwischenfolien mit Ziffer, dunklem Zitat und Kennzahlenkarten. Für HTML-Seiten und -Präsentationen gibt es den Leitfaden `html`, der beim ersten `.html` automatisch geladen wird.

Neue Word-, PowerPoint-, Excel- und PDF-Dateien gestaltet die KI nach festen Regeln statt nach Gefühl.

- **Leitfäden:** Das Werkzeug `design_guide` liefert kurze Texte zu `allgemein`, `folien`, `dokument`, `tabelle`, `pdf`, `html` und `themen`. Die KI ruft es vor dem Erstellen einer neuen Datei auf (nicht beim Bearbeiten vorhandener Dateien, nicht bei Code). Die Texte liegen unter `app/design/*.md` und sind eigene, kurze Regeln: eine Aussage je Folie, höchstens sechs kurze Punkte, Überschriften als Aussagen, genug Weißraum, ein Farbthema je Datei, Zahlen einheitlich, Kopfzeile bei Tabellen.
- **Themen:** `klar` (Standard, sachlich), `ozean` (ruhig, technisch), `wald` (natürlich), `terrakotta` (warm), `schiefer` (kräftig, nüchtern), `beere` (kreativ), `sand` (zurückhaltend, mit Serifenschrift). Sag einfach, wofür die Datei ist („für die Geschäftsführung“, „Einladung zum Sommerfest“); die KI wählt. Mit einer Markenfarbe („in unserem Orange #C2410C“) nutzt sie `accent`; zu helle Farben werden für Text und Linien automatisch abgedunkelt.
- **Was sich ändert:** PowerPoint hat farbige Titel- und Zwischenfolien (eine Folie nur mit `##`-Überschrift), Foliennummer und Titel in der Fußzeile. Word hat eine Fußzeile mit Seitenzahl, helle Tabellenlinien, farbigen Tabellenkopf und Zebrazeilen. Excel hat farbige Kopfzeile und getönte Wechselzeilen. PDF hat Themenfarben und Zebrazeilen in Tabellen.
- **Selbstkontrolle:** `file_create` meldet der KI Auffälligkeiten (z. B. mehr als sechs Punkte auf einer Folie, Tabelle mit mehr als fünf Spalten, übersprungene Überschriftenebenen); sie darf einmal nachbessern.
- **Bilder und Diagramme:** Die KI bettet Bilder dieses Chats ein (erzeugte Bilder, SVG-Zeichnungen, angehängte Fotos) und setzt Diagramme (Balken, Linie, Kreis). In PowerPoint und Excel sind es echte, bearbeitbare Diagramme, in Word und PDF Bilder. Sag z. B.: „Zeichne den Ablauf als Grafik und setz sie auf Folie 3“ oder „Stell die Umsätze als Balkendiagramm dar“.
- **Inhaltsverzeichnis:** In PDF mit Seitenzahlen und Links, in Word als echtes Verzeichnis (Seitenzahlen nach Rechtsklick „Feld aktualisieren“), in PowerPoint als Agenda-Folie.
- **Keynote:** Für Präsentationen auf Mac, iPad und iPhone sagst du einfach „für Keynote“. Die KI erzeugt dann eine `.pptx` im Keynote-Modus (Mac-Schriften, keine automatische Schrumpfung, knappere Folien), die Keynote direkt öffnet; als `.key` sicherst du sie in Keynote selbst. Eine echte `.key`-Datei kann das Add-on nicht erzeugen. Die Anpassungen folgen Apples Hinweisen zum Import von PowerPoint-Dateien. Jede `.pptx` wird nach dem Erzeugen so bereinigt, dass Keynote sie nicht als „ungültig“ ablehnt (Notizmaster-Eintrag, Foliengröße, Diagramm-Kennungen, Vorlagenreste); ein Test in Keynote selbst steht aus. Lässt sich eine Datei trotzdem nicht importieren, sag der KI die Fehlermeldung und ob die Datei Notizen, Diagramme oder Bilder enthält.
- **Selbstkontrolle mit Bild:** Mit dem Werkzeug `file_preview` sieht die KI ihr Ergebnis (Folien, Seiten, Zeichnungen) und bessert klare Layoutfehler einmal nach. Word und PowerPoint wandelt dafür LibreOffice um (im Add-on enthalten, rund 400 MB; wer den Platz sparen will, entfernt den Block im Dockerfile, dann meldet `file_preview` ehrlich, dass LibreOffice fehlt). Excel-Dateien gibt es nicht als Bild.
- **Automatisch:** Die Leitfäden muss die KI nicht selbst abrufen: Beim ersten neuen Word-, PowerPoint-, Excel-, PDF- oder HTML-Dokument einer Antwort liefert `file_create` zuerst die passenden Regeln und die Themenliste, die KI plant danach und erzeugt die Datei im zweiten Anlauf (du siehst davon nichts außer einem Werkzeugaufruf mehr).
- **Links:** `[Text](Adresse)`, nackte Webadressen und `mailto:` sind in Word, PDF und PowerPoint anklickbar.
- **Folientypen:** Zwei Spalten (`+++`), Zitatfolie (nur ein Zitat), Kennzahlen (ein bis vier fette Zahlen mit Erklärung) und Vollbild-Bild (`{vollbild}`). Die PowerPoint-Vorlage trägt außerdem Farben und Schriften des Themas, damit von dir hinzugefügte Folien und Diagramme passen.
- **Word und PDF:** Deckblatt (`[DECKBLATT]`), `[SEITENUMBRUCH]`, `[KOPFZEILE: …]`, `[FUSSZEILE: …]`; Word-Listen sind echte Listen (nummerierte beginnen je Liste bei 1).
- **Excel:** Zahlenformate je Spalte, Summenzeile, bedingte Formatierung (Schwellen, Datenbalken, Farbverlauf) und Druckeinstellungen (A4, auf Seitenbreite, Kopfzeile auf jeder Seite). Text wie „12,50 €“ oder „18 %“ wird eine echte Zahl mit passendem Format.
- **Pages und Numbers:** Sag „für Pages“ bzw. „für Numbers“, dann setzt die KI `target: pages` (.docx) bzw. `target: numbers` (.xlsx) mit Mac-Schriften. Beides folgt Apples Hinweisen zum Import von Microsoft-Dateien und ist nicht auf einem Apple-Gerät getestet.
- **Grenzen:** Keine Fußnoten, keine Animationen und Übergänge, keine Spalten im Fließtext von Word und PDF, keine Dropdown-Listen oder Pivot-Tabellen in Excel. Wer ein bestimmtes Aussehen braucht, bearbeitet die Datei danach in Word, PowerPoint oder Excel.
- **Herkunft:** Anregungen aus den frei lizenzierten Skills `theme-factory` (Apache-2.0) und `frontend-slides` (MIT); es sind keine Texte oder Code übernommen. Die Office-Skills von Anthropic sind nicht frei lizenziert und deshalb nicht enthalten.

## Dateien bearbeiten (ab 0.27.0)

Die KI kann Dateien nicht nur erzeugen, sondern auch **lesen und ändern**, egal ob du sie angehängt hast oder sie selbst erzeugt hat: PDF (Formularfelder ausfüllen oder sperren, Seiten löschen, drehen, ordnen, zusammenfügen, Text ergänzen, neue Felder anlegen), Word, Excel, PowerPoint sowie Text und Code jeder Art (`.py`, `.sh`, `.json`, `.yaml`, `.html` …). Beispiel: Du hängst ein Formular an und schreibst „Die vorausgefüllten Felder sollen nicht mehr änderbar sein, der Rest soll ausfüllbar bleiben.“ Die KI liest das PDF, sperrt die ausgefüllten Felder und bietet die neue Fassung als Karte zum Herunterladen an. **Deine Datei bleibt unverändert.**

- **Werkzeuge:** `file_list` (Dateien dieses Chats), `file_read` (nummerierte Ansicht: Zeilen, Absätze, Zellen, Folien, PDF-Felder und -Seiten) und `file_edit` (Liste von Änderungen; alles oder nichts: scheitert eine, wird nichts gespeichert und die KI erfährt den Grund). Die neue Fassung ersetzt die alte unter demselben Namen oder wird mit `save_as` unter neuem Namen abgelegt.
- **Text und Code:** Ersetzen (eindeutig oder alle), Zeilen ersetzen, einfügen, löschen, anhängen, neu schreiben. Kodierung (UTF-8, Windows-1252), BOM und Zeilenenden (LF/CRLF) bleiben erhalten.
- **Word:** Text ersetzen (auch über Formatierungsgrenzen, in Tabellen, Kopf- und Fußzeilen; Format bleibt), Absätze setzen, einfügen, löschen, Tabellen anlegen und Zellen/Zeilen ändern, Formatvorlagen zuweisen.
- **Excel:** Zellen und Bereiche setzen (Zahlen, Text, Formeln mit englischen Funktionsnamen; gefährliche Formeln wie `WEBSERVICE` werden entschärft), Zeilen und Spalten einfügen oder löschen, Blätter anlegen, umbenennen, löschen. Formelwerte rechnet Excel beim Öffnen neu. **Diagramme, Bilder und Formen bleiben erhalten (ab 0.39.0):** Ihre Teile werden unverändert aus der Originaldatei in die neue übernommen; Diagrammbezüge folgen umbenannten Blättern und aktualisieren sich mit den Zellwerten. Beim Einfügen oder Löschen von Zeilen und Spalten werden die Bereiche der Diagramme **nicht** angepasst (die KI weist darauf hin), Diagramme auf gelöschten Blättern entfallen mit dem Blatt. **Hinweis:** Pivot-Tabellen, Makros und eigene Diagrammblätter können beim Speichern verloren gehen; die KI sagt es dir dann.
- **PowerPoint:** Text ersetzen, Formen und Tabellenzellen setzen, Notizen, Folien hinzufügen, löschen, verschieben.
- **PDF:** `fill_fields`, `lock_fields` (Felder schreibgeschützt machen: die ausgefüllten, die leeren, alle oder benannte), `unlock_fields`, `flatten` (Formular fest in die Seiten schreiben), `add_text`, **`replace_text`** (ab 0.39.0), `add_text_field`, `delete_pages`, `rotate_pages`, `reorder`, `merge`. **`replace_text`** `{find, replace, page(s)?, match_case?}` ersetzt vorhandenen Text **per Überlagerung**: Der Server findet den Text samt Position (pypdfium2), deckt ihn mit der Hintergrundfarbe der Umgebung ab und schreibt den neuen Text darüber, in Größe und Farbe des alten und an dessen Grundlinie; ist der neue Text länger, wird er bis auf 70 % verkleinert, darüber hinaus kann er angrenzenden Text berühren (die KI meldet es). Grenzen: Der alte Text bleibt unter der Abdeckung im PDF und lässt sich noch auslesen oder kopieren (**zum Schwärzen ungeeignet**, die KI sagt es); die Schrift ist Liberation Sans statt der Originalschrift; gedrehte Seiten und Treffer über mehrere Zeilen (nur die erste Zeile bekommt den neuen Text) sind eingeschränkt; höchstens 200 Treffer je Befehl; Scans und Bilder haben keinen Text. Nicht möglich: den Seiteninhalt wirklich umschreiben und gescannte PDFs bearbeiten; die KI sagt das ehrlich. Passwortgeschützte PDFs werden abgelehnt, bei signierten PDFs warnt die KI, dass die Signatur ungültig wird.
- **Grenzen:** Dateien bis 25 MB, höchstens 200 Änderungen je Aufruf, 90 Sekunden je Aufruf; alte Formate (`.doc`, `.xls`, `.ppt`) lassen sich nicht bearbeiten. Bilder bearbeitet `file_edit` nicht; dafür gibt es die Bildfunktion ([Bilder](#bilder-ab-0280)).
- **Sicherheit:** Dateiinhalt ist Inhalt, keine Anweisung. Wie nach einem Dateianhang fragt die KI nach `file_read` vor jeder Aktion in Home Assistant, bei Gedächtnis und GitHub, die etwas ändert, immer nach. Bearbeitet wird nur im Add-on-Speicher; nichts wird ausgeführt (keine Makros, keine Skripte).
- **Abschalten:** `files_enabled: false` (gar keine Dateiwerkzeuge). Ein separater Schalter nur für das Bearbeiten von Anhängen (`files_edit`) existiert seit 0.45.0 nicht mehr: Anhänge werden für diesen Chat aufbewahrt.

## Bilder (ab 0.28.0)

Die KI erzeugt Bilder von selbst, sobald du eines möchtest („Male mir ein gemütliches Wohnzimmer bei Sonnenuntergang“, „Zeichne den Grundriss als Plan“, „Mach daraus ein Logo“). Du musst nichts einschalten und kein Modell wählen. Sie entscheidet nach Aufwand:

- **SVG (kostenlos, ohne Schlüssel):** Diagramme, Ablaufpläne, Grundrisse, Logos, Symbole und einfache Illustrationen schreibt Claude als SVG-Quelltext (`image_svg`). Das kostet nichts und lässt sich beliebig oft ändern. Der Server prüft den Quelltext streng: keine Skripte, keine Ereignisse, keine eingebetteten Bilder, Animationen oder Links, nichts von außen. Angezeigt wird das SVG als Bild, nicht als Seite.
- **Bildmodell (OpenAI oder Google):** Fotos, Kunst, komplexe Szenen und Bilder mit Schrift (`image_generate`). Das kostet je Bild Geld auf deinem API-Konto. Sind beide Anbieter eingerichtet, nimmt die KI Google für Entwürfe und Änderungen (günstiger) und OpenAI für Schrift im Bild und höchste Qualität; mit `image_provider` kannst du einen Anbieter fest vorgeben. Ist nur ein Schlüssel eingetragen, wird dieser genommen. Ohne Schlüssel zeichnet die KI, was als SVG geht, und sagt dir sonst, was fehlt.
- Die KI nennt in einem Satz den gewählten Weg („Das ist ein Foto-Motiv, deshalb habe ich es mit Google erzeugen lassen“).

### Ändern, neu erzeugen, am selben Bild weiterarbeiten

Gefällt dir ein Bild nicht oder möchtest du etwas anders („Himmel rosa“, „kleiner“, „ohne Hut“), schreibst du das einfach in denselben Chat. Die KI ändert das **vorhandene** Bild statt ein neues zu erfinden: Sie gibt es dem Bildmodell als Vorlage mit und beschreibt nur die Änderung. Es entsteht eine **neue Fassung** („Version 2“, `name-v2.png`) neben der alten, die erhalten bleibt. Dasselbe geht mit einem **angehängten Foto** („Mach daraus ein Aquarell“). Jede neue Fassung von OpenAI/Google zählt aufs Monatslimit; SVG-Änderungen nicht (die KI liest den Quelltext und schreibt ihn neu).

### Anzeige im Chat

- **Platzhalter beim Erzeugen:** Sobald die KI ein Bild beauftragt, zeigt der Chat eine Karte „Bild wird erzeugt …“ (bei OpenAI/Google meist 20 bis 90 Sekunden; SVG ist sofort da). Wartet die KI auf deine Freigabe, steht dort „Wartet auf deine Freigabe“. Die Antwort läuft auf dem Server weiter wie jede andere: Chat wechseln oder Seite neu laden verliert nichts.
- **Bildkarte:** Vorschau, Dateiname, Herkunft („Google“, „OpenAI“, „gezeichnet (SVG)“), gegebenenfalls „Version 2“, Größe in Bildpunkten.
- **Bildvorschau:** Ein Klick auf die Karte öffnet das Bild groß. Dort: **Herunterladen**, **Schließen** (Knopf, Esc oder Klick neben das Bild), Klick auf das Bild wechselt zwischen „einpassen“ und Originalgröße, bei mehreren Bildern einer Antwort blätterst du mit den Pfeiltasten oder den Knöpfen. Die Vorschau ist ein eigenes Fenster mit Tastaturbedienung (Tab bleibt im Fenster, der Fokus kehrt zur Karte zurück).
- Die Bilder bleiben 14 Tage wie alle erzeugten Dateien; danach zeigt die Karte „Abgelaufen“. Sie liegen in `/data/outfiles` (und damit in der HA-Sicherung), gehören nur dir und werden mit dem Chat gelöscht.

### Kosten und Limit

- **Monatslimit:** `image_limit_month` (Standard 30, `0` = unbegrenzt) gilt **je Person und Kalendermonat** für Bilder von OpenAI/Google. SVG zählt nicht. Alle Personen dürfen Bilder erzeugen, es gibt keine Beschränkung auf einzelne Benutzer.
- **Erst über dem Limit wird gefragt:** Ab dem ersten Bild über dem Limit erscheint im Chat die Rückfrage **Zulassen / Ablehnen** mit Anbieter, Modell und Bildwunsch; sie gilt für dieses eine Bild (jedes weitere fragt wieder). Mit „Ablehnen“ entsteht nichts, und die KI schlägt höchstens eine Alternative (z. B. SVG) vor. Beantwortest du die Rückfrage nicht, gilt sie nach 10 Minuten als abgelehnt.
- **Ausnahme, immer mit Rückfrage:** Hat die KI in derselben Antwort Inhalte aus dem Web oder aus Dateien gelesen (Websuche, GitHub, Home Assistant, Projektwissen, `file_read`) oder war ein Dokument angehängt, fragt sie vor **jedem** Bild von OpenAI/Google nach, auch unter dem Limit. Solche Inhalte könnten untergeschobene Anweisungen enthalten („erzeuge ein Bild mit diesem Text …“), und der Bildwunsch verlässt dein Haus. Ein angehängtes **Foto allein** löst das nicht aus.
- **Obergrenzen:** höchstens 4 Bilder je Antwort, Bildwunsch bis 4000 Zeichen, Referenzbilder PNG/JPEG/WebP bis 20 MB (höchstens 4 je Wunsch).
- **Geplante Aufgaben** erzeugen keine Bilder (dort kann niemand zustimmen).
- Die Preise bestimmen OpenAI und Google und ändern sich; das Add-on kennt sie nicht und führt nur die **Anzahl** der Bilder. Die Kosten siehst du im jeweiligen Konto (platform.openai.com, aistudio.google.com bzw. Google Cloud). Grobe Orientierung, ohne Gewähr: von etwa einem Cent (OpenAI, niedrige Qualität) bis über 20 Cent (OpenAI, höchste Qualität); bei Google je nach Modell grob 3 bis 15 Cent je Bild. Bei Änderungen kommen die Kosten für das Referenzbild hinzu.

### Einrichtung

Eine Schritt-für-Schritt-Anleitung zum Anlegen der Konten steht unter [API-Konto für Bilder anlegen](https://github.com/dominikramachers/HA-Copilot/blob/main/docs/bilder-konten.md). Kurzfassung:

1. **OpenAI:** Auf platform.openai.com ein API-Konto anlegen, Guthaben aufladen, unter „API keys“ einen Schlüssel erzeugen. Je nach Modell kann OpenAI zuvor eine **Verifizierung der Organisation** verlangen (Einstellungen → Organization → Verification); sonst meldet die Schnittstelle einen Fehler, den die KI dir wörtlich nennt.
2. **Google:** Auf aistudio.google.com („Get API key“) einen Schlüssel für die Gemini-API erzeugen und im zugehörigen Cloud-Projekt die **Abrechnung** aktivieren (die Bildmodelle der Gemini-API sind kostenpflichtig).
3. Schlüssel bei `openai_api_key` bzw. `google_api_key` eintragen, speichern, Add-on neu starten. Die Einrichtungsprüfung (Einstellungen) zeigt „Bilder erzeugen“ mit dem Stand.
4. Ein **ChatGPT-Plus-** oder **Google-One-Abo** bezahlt die Schnittstelle nicht; beide Anbieter rechnen die API getrennt ab.

**Modellnamen:** `gpt-image-2.5-sunburst` (OpenAI) und `gemini-3.1-flash-image-preview` (Google, auch „Nano Banana 2“) sind seit 0.45.0 fest im Add-on hinterlegt, die Optionen `image_model_openai` und `image_model_google` entfallen; bei Namensänderungen der Anbieter bringt ein Add-on-Update die neuen Namen. Fehler der Anbieter (unbekanntes Modell, ungültiger Schlüssel, leeres Guthaben, Sicherheitsfilter, zu viele Anfragen) erklärt die KI verständlich; der Schlüssel taucht dabei nie auf.

### Datenschutz und Sicherheit

- **Was an OpenAI/Google geht:** nur der Bildwunsch (Text, den die KI formuliert) und, bei Änderungen, das Referenzbild. Dein restlicher Chat, Home-Assistant-Daten und das Gedächtnis gehen nicht mit. Die Anbieter verarbeiten das nach ihren eigenen Bedingungen; bei OpenAI und Google gelten für die kostenpflichtige Schnittstelle andere Regeln als für die Apps, die genaue Aufbewahrung regeln deren Bedingungen. Schicke keine Fotos fremder Personen oder vertrauliche Bilder, die nicht an einen US-Anbieter gehen sollen. Mit leeren Schlüsseln bleibt alles beim SVG, und es geht nichts an diese Anbieter.
- Die Schlüssel stehen nur in der Add-on-Konfiguration, gehen ausschließlich als Anmelde-Kopfzeile an `api.openai.com` bzw. `generativelanguage.googleapis.com`, nie in einer Adresse, einem Protokoll oder einer Meldung.
- **Anzeige:** Das Bild wird mit Anmeldung geladen (`/api/files/…`, nur für den Besitzer) und als `<img>` angezeigt; auch ein SVG läuft so ohne Skripte und ohne Netzzugriff. Heruntergeladen wird es mit der strengen `sandbox`-Kopfzeile wie jede erzeugte Datei.
- Ob Claude das Bild „sieht“: nein. Die KI beauftragt das Bild und beschreibt es nicht im Einzelnen; ob es dir gefällt, beurteilst du.
- **Abschalten:** Bilder folgen `files_enabled`. Nur OpenAI/Google zu nutzen verhindern geht, indem die Schlüssel leer bleiben (dann bleibt SVG).

## Anhänge und Speicherplatz

Dateianhänge gehen mit der Nachricht an das Add-on und werden dort im Arbeitsspeicher geprüft (Inhalt, nicht Dateiname, entscheidet über die Art) und an Claude weitergereicht. **Was danach passiert** (ab 0.27.0, seit 0.45.0 fest):

- **Aufbewahrung der Anhänge (fest):** Von jedem Anhang (Bilder: siehe unten) legt das Add-on das Original als Kopie für diesen Chat im Datenordner ab (`/data/outfiles`, bis 25 MB je Datei), damit die KI in Folgenachrichten damit arbeiten kann. Die Kopien bleiben 14 Tage, werden mit dem Chat gelöscht (auch bei „Alle meine Chats löschen“) und sind nur für dich zugänglich. Sie liegen damit in der HA-Sicherung. Bilder werden nur kopiert, solange die Bildfunktion an ist (folgt `files_enabled`): als Vorlage für ein neues Bild, siehe [Bilder](#bilder-ab-0280).
- **Immer** stehen in der Datenbank der Nachricht nur Name, Art und Größe, damit der Chat zeigt, was angehängt war; der Inhalt steht in keiner Nachricht. Löschst du den Chat, ist auch das weg.
- Folgefragen: Die KI sieht frühere Anhänge über `file_list` und `file_read` (nur bei Bedarf, das spart Kontingent: ein Anhang wird nicht bei jeder Frage erneut an Claude geschickt). Die Antwort von Claude bleibt im Chat. Für eine weitere Frage zur selben Datei klickst du an der Nachricht auf „Wieder anhängen“: Die Dateien kommen dann aus dem Speicher deines Browsers (nicht vom Server) zurück ins Eingabefeld. Das geht für die zuletzt gesendete Nachricht, solange du den Chat nicht wechselst oder die Seite neu lädst. Danach hängst du die Datei neu an; Claude bekommt in dem Fall den Hinweis, dass früher eine Datei dabei war.
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

Alles liegt in `/data/copilot.sqlite3`. Das Token steht in den Add-on-Optionen und damit ebenfalls im Backup, Backups entsprechend schützen. Als Administrator mit Zugriff auf das Add-on könntest du die Datei theoretisch direkt lesen. Die Trennung gilt für die Oberfläche und die Programmierschnittstelle.

- **HA-Sicherung:** Das Add-on wird mit `backup: cold` gesichert. Home Assistant hält es dafür kurz an (wenige Sekunden), kopiert die Daten und startet es wieder. So ist die Kopie immer vollständig, auch wenn gerade jemand schreibt. Beim Beenden wird die Datenbank vorher sauber abgeschlossen. Eine Antwort, die genau in diesem Moment läuft, wird unterbrochen (die bis dahin erhaltene Teilantwort bleibt gespeichert, deine Frage ebenfalls).
- **Schnappschüsse:** Etwa einmal am Tag legt das Add-on zusätzlich einen geprüften Schnappschuss in `/data/snapshots/` an (`copilot-JJJJ-MM-TT_HHMMSS.sqlite3`, die letzten 7 bleiben). Er liegt im Datenordner und steckt damit in jeder HA-Sicherung. Vor dem Update auf eine neue Datenbankversion entsteht zusätzlich `vor-update-…` (die letzten 3).
- **Prüfung beim Start:** Das Add-on prüft die Datenbank bei jedem Start. Meldet sie einen Fehler, erscheint oben in der Oberfläche ein roter Hinweis mit den neuesten Schnappschüssen, und die Datei wird nicht verändert.
- **Wiederherstellen:** In den Add-on-Optionen unter `restore_snapshot` den Dateinamen eines Schnappschusses eintragen (z. B. `copilot-2026-10-27_033012.sqlite3`) und das Add-on neu starten. Der bisherige Stand wird vorher als `vor-wiederherstellung-…` gesichert. Danach die Option leeren; solange der Name stehen bleibt, wird nicht erneut überschrieben. Die Namen der vorhandenen Schnappschüsse stehen beim Start im Add-on-Protokoll. Aus einer ganzen HA-Sicherung stellst du den HA Copilot über Einstellungen, System, Sicherungen wieder her (Teilwiederherstellung des Add-ons).
- **Umzug in ein anderes Add-on** (z. B. vom lokalen Add-on im Ordner `/addons` zum Add-on aus einem GitHub-Repository): Für Home Assistant sind das zwei verschiedene Add-ons mit getrennten Daten, die Chats wandern nicht von selbst mit. So nimmst du sie mit: (1) Im *alten* Add-on `export_database` einschalten und neu starten; es legt `copilot-export.sqlite3` (Versionen bis 0.28: `ki_chat-export.sqlite3`) in seinen Config-Ordner (in Home Assistant unter `/addon_configs/<Ordner>/`, z. B. per Samba oder Datei-Editor). (2) Die Datei in den Config-Ordner des *neuen* Add-ons kopieren. (3) Im neuen Add-on `restore_snapshot` auf diesen Dateinamen setzen und neu starten; die Chats, Projekte, das Gedächtnis und die geplanten Aufgaben sind dann da (Dateien, die die KI erzeugt hat, und Projektdateien-Inhalte, die nicht in der Datenbank liegen, nicht). (4) Danach `restore_snapshot` leeren, `export_database` ausschalten und die Export-Datei löschen, denn sie enthält alle Chats. Die Konfiguration (Benutzer, Zugangsdaten) musst du im neuen Add-on selbst eintragen. **Von Version 0.28 auf 0.29** (die Kennung des Add-ons wechselt von `ki_chat` auf `copilot`) beschreibt [Betrieb: Umzug von der Kennung ki_chat](https://github.com/dominikramachers/HA-Copilot/blob/main/docs/betrieb.md#umzug-von-der-kennung-ki_chat-auf-copilot-version-028-auf-029) jeden Schritt.
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
cd copilot
pip install fastapi uvicorn httpx websockets 'pyjwt[crypto]' pypdf pytest pyyaml claude-agent-sdk -r requirements-files.txt  # die Office-Bibliotheken braucht ab 0.18.0 auch der Test der Dateierzeugung
python -m pytest
```


## Gestaltung (ab 0.10.0)

- **Formen:** vier feste Radien (`--r-1` 6 px für kleine Knöpfe, `--r-2` 10 px für Eingaben, Knöpfe und Zeilen, `--r-3` 14 px für Eingabefeld und Nachrichten, `--r-4` 18 px für Fenster von unten) statt durchgehend runder Pillen. Alle Werte stehen in `app/static/theme.css`.
- **Farbe:** flache Flächen ohne Verläufe und Schatten. Der Akzent (Blau wie in den Dashboards) kennzeichnet nur Bedienbares; das Logo ist das einzig Bunte.
- **Schrift:** Roboto wie in den Dashboards; Code und Logs in Atkinson Hyperlegible Mono (0/O und l/1/I sind eindeutig unterscheidbar). Beide Dateien liegen lokal unter `app/static/fonts/`, Lizenz (OFL) daneben.
- **Startseite:** Die Vorschläge sind eine schlichte Liste statt Kacheln.
- **Logo in Home Assistant:** Laptop/Tablet in der Seitenleiste; Handy im Kopf des Chats-Fensters und über der Begrüßung (die Kopfzeile von HA selbst lässt sich nicht verändern).
