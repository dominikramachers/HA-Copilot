# Betrieb: Sicherung, Update, Umzug, Fehlerbehebung

## Wo liegt was?

| Was | Wo |
|---|---|
| Chats, Projekte, Gedächtnis, geplante Aufgaben | SQLite-Datenbank `/data/ki_chat.sqlite3` im Add-on-Speicher |
| Tägliche Schnappschüsse | `/data/snapshots/` (die letzten 7), vor einem Datenbank-Update zusätzlich `vor-update-…` (die letzten 3) |
| Von der KI erzeugte Dateien | `/data/outfiles` (nach `files_keep_days` Tagen gelöscht) |
| Sicherungen geänderter Automationen, Skripte, Szenen, Dashboards | `/data/ha-backups/` (die letzten 60) |
| Eigenes Logo, Symbol, `custom.css`, Export-Datei | Ordner `addon_config`, in Home Assistant unter `/addon_configs/<Kennung>/` (Samba-Freigabe `addon_configs` oder Datei-Editor) |

Anhänge werden **nie** gespeichert, siehe [Anhänge und Speicherplatz](../ki_chat/DOCS.md#anhänge-und-speicherplatz).

## Sicherung

HA Copilot ist mit `backup: cold` eingestellt: Home Assistant hält das Add-on bei einer Sicherung kurz an (wenige Sekunden), kopiert die Daten und startet es wieder. So ist die Kopie immer vollständig. Eine Antwort, die genau in diesem Moment läuft, wird unterbrochen; der bis dahin erhaltene Teil bleibt gespeichert.

> Die Add-on-Optionen, und damit Claude-Zugang, Entra-Geheimnis und GitHub-Token, stehen ebenfalls in der Sicherung. Schütze Sicherungen entsprechend.

Zusätzlich legt das Add-on etwa einmal am Tag einen geprüften Schnappschuss an und prüft die Datenbank bei jedem Start. Meldet sie einen Fehler, erscheint oben im Chat ein roter Hinweis, und die Datei bleibt unverändert.

## Wiederherstellen

**Aus einem Schnappschuss:** Die Namen stehen beim Start im Protokoll (`ki_chat-JJJJ-MM-TT_HHMMSS.sqlite3`).

1. In der Konfiguration `restore_snapshot` auf den Dateinamen setzen.
2. Speichern, Add-on neu starten. Der bisherige Stand wird vorher als `vor-wiederherstellung-…` gesichert.
3. Danach `restore_snapshot` **leeren**, sonst wird bei jedem Start erneut überschrieben.

**Aus einer Home-Assistant-Sicherung:** **Einstellungen → System → Sicherungen**, die Sicherung wählen und nur HA Copilot wiederherstellen (Teilwiederherstellung).

## Updates

Neue Versionen erscheinen als Release auf GitHub; Home Assistant zeigt sie im Add-on als Update. Vor dem Update empfiehlt sich eine Sicherung (im Update-Dialog ankreuzen). Konfiguration und Daten bleiben erhalten; neue Optionen sind immer optional. Was sich geändert hat, steht im Reiter **Änderungsprotokoll** und im [CHANGELOG](../ki_chat/CHANGELOG.md).

Nach „Nach Updates suchen“ kann ein Dialog „Unknown error, see supervisor logs“ erscheinen. Das ist ein Zeitlimit von Home Assistant beim Neuladen des Stores und kein Fehler des Add-ons; das Update wird trotzdem gefunden.

## Umzug in ein anderes Add-on

Für Home Assistant ist jedes Add-on mit eigener Kennung ein eigenes Add-on mit eigenen Daten (z. B. das lokale Add-on im Ordner `/addons` und das aus diesem Repository). Die Chats wandern nicht von selbst mit. So nimmst du sie mit:

1. Im **alten** Add-on `export_database: true` setzen, speichern, neu starten. Es legt `ki_chat-export.sqlite3` in seinen Config-Ordner (`/addon_configs/<alte Kennung>/`). Das geht ab Version 0.23.0; ältere Versionen vorher aktualisieren.
2. Die Datei in den Config-Ordner des **neuen** Add-ons kopieren (`/addon_configs/<neue Kennung>/`).
3. Im neuen Add-on `restore_snapshot: ki_chat-export.sqlite3` setzen und neu starten. Chats, Projekte, Gedächtnis und geplante Aufgaben sind danach da. Von der KI erzeugte Dateien und Projektdateien-Inhalte, die nicht in der Datenbank liegen, nicht.
4. `restore_snapshot` leeren, `export_database` ausschalten und die Export-Datei löschen (sie enthält alle Chats).
5. Konfiguration (Benutzer, Zugangsdaten) im neuen Add-on eintragen, bei Domain-Zugang den Tunnel auf den neuen Hostnamen richten (`http://<Hostname>:8100`, den nennt die Einrichtungsprüfung) und `public_trusted_proxies` neu setzen.
6. Das alte Add-on deinstallieren.

## Protokoll lesen

**Einstellungen → Add-ons/Apps → HA Copilot → Protokoll.** Beim Start steht dort:

- die Liste aller Home-Assistant-Benutzer mit Anmeldename und ID,
- die Zeitzone, die für geplante Aufgaben gilt („Zeitzone für geplante Aufgaben: …“),
- Hinweise zur Konfiguration (z. B. Abo-Token mit mehreren Benutzern, nicht auflösbare `ha_user`),
- die vorhandenen Schnappschüsse.

Zugangsdaten werden nie ins Protokoll geschrieben.

## Ablaufdaten nicht vergessen

Trage die Ablaufdaten ein, dann erinnert das Add-on im Chat (30 Tage vorher gelb, danach rot):

- `claude_token_expires`: ein Abo-Token gilt ein Jahr ab dem Tag von `claude setup-token`.
- `entra_secret_expires`: zu sehen in Entra unter „Zertifikate & Geheimnisse“.

## Fehlerbehebung

| Beobachtung | Ursache und Abhilfe |
|---|---|
| „Kein Zugriff“ in der App | Benutzer nicht in `profiles` (oder `all_ha_users` aus). Seite nennt Benutzername und ID, eintragen, neu starten. |
| „Testmodus“-Hinweis, Antworten nur als Echo | `backend: echo`. Zugang eintragen und `backend: claude` setzen. |
| Antworten enden mit Fehler | Zugangsdaten ungültig/abgelaufen, Nutzungslimit erreicht oder Modell vom Abo nicht zugelassen. Meldung im Chat, Einzelheiten im Protokoll. |
| „Gerade zu viele Anfragen“ | Es laufen höchstens zwei Antworten gleichzeitig (alle Benutzer, geplante Aufgaben eingerechnet). Kurz warten. |
| Die KI sieht keine Entitäten | `ha_access` des Benutzers ist `none`, oder die Entitäten sind nicht für Assist freigegeben (`ha_limit_to_exposed`). |
| Geplante Aufgabe läuft nicht | Pause, Nutzungslimit erreicht oder Add-on war länger als 2 Stunden aus („Übersprungen“ auf der Aufgabenseite). Uhrzeiten gelten in der Zeitzone von Home Assistant. |
| Keine Handy-Benachrichtigung | `notify_service` beim Benutzer prüfen (Einrichtungsprüfung zeigt, ob der Dienst existiert). |
| Rote Meldung zur Datenbank | Schnappschuss wiederherstellen (oben). |
| Seite bleibt weiß hinter dem Tunnel | Tunnel-Ziel (`http://<Hostname>:8100`) und `public_base_url` prüfen. |

Hilft das nicht: Protokoll des Add-ons und, falls es um Home Assistant geht, **Einstellungen → System → Protokolle** ansehen und ein [Issue](https://github.com/dominikramachers/HA-Copilot/issues) anlegen (ohne Zugangsdaten). Sicherheitsprobleme bitte nach [SECURITY.md](../SECURITY.md) melden.

## Deinstallation

Das Deinstallieren des Add-ons löscht seine Daten (Chats, Schnappschüsse). Vorher exportieren: in der App **Meine Daten → Alle Chats exportieren** oder die Datenbank per `export_database` sichern. Ob der Ordner `addon_config` (Logo, Export) mit entfernt wird, hängt von der Home-Assistant-Version ab; prüfe unter `/addon_configs/` nach und lösche ihn bei Bedarf von Hand.

## Entwicklung und Tests

```bash
cd ki_chat
pip install -r requirements.txt pytest pyyaml
python -m pytest -q
```

Die Tests laufen ohne Claude-Zugang. Jede Änderung muss in `ki_chat/config.yaml` die Version erhöhen und im [CHANGELOG](../ki_chat/CHANGELOG.md) stehen. Die Seite [Alle Einstellungen](einstellungen.md) wird aus `config.yaml` und `translations/de.yaml` erzeugt (`python tools/gen_options_doc.py`); ein Test schlägt fehl, wenn sie nicht mehr dazu passt.
