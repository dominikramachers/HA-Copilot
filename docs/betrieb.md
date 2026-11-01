# Betrieb: Sicherung, Update, Umzug, Fehlerbehebung

## Wo liegt was?

| Was | Wo |
|---|---|
| Chats, Projekte, Gedächtnis, geplante Aufgaben | SQLite-Datenbank `/data/copilot.sqlite3` im Add-on-Speicher |
| Tägliche Schnappschüsse | `/data/snapshots/` (die letzten 7), vor einem Datenbank-Update zusätzlich `vor-update-…` (die letzten 3) |
| Von der KI erzeugte Dateien | `/data/outfiles` (nach `files_keep_days` Tagen gelöscht) |
| Sicherungen geänderter Automationen, Skripte, Szenen, Dashboards | `/data/ha-backups/` (die letzten 60) |
| Eigenes Logo, Symbol, `custom.css`, Export-Datei | Ordner `addon_config`, in Home Assistant unter `/addon_configs/<Kennung>/` (Samba-Freigabe `addon_configs` oder Datei-Editor) |

Anhänge: Mit der Option `files_edit` (Standard) liegt eine Kopie für `files_keep_days` Tage in `/data/outfiles` (und damit in der Sicherung); mit `files_edit: false` werden Anhänge **nie** gespeichert, siehe [Anhänge und Speicherplatz](../copilot/DOCS.md#anhänge-und-speicherplatz).

## Sicherung

HA Copilot ist mit `backup: cold` eingestellt: Home Assistant hält das Add-on bei einer Sicherung kurz an (wenige Sekunden), kopiert die Daten und startet es wieder. So ist die Kopie immer vollständig. Eine Antwort, die genau in diesem Moment läuft, wird unterbrochen; der bis dahin erhaltene Teil bleibt gespeichert.

> Die Add-on-Optionen, und damit Claude-Zugang, Entra-Geheimnis und GitHub-Token, stehen ebenfalls in der Sicherung. Schütze Sicherungen entsprechend.

Zusätzlich legt das Add-on etwa einmal am Tag einen geprüften Schnappschuss an und prüft die Datenbank bei jedem Start. Meldet sie einen Fehler, erscheint oben im Chat ein roter Hinweis, und die Datei bleibt unverändert.

## Wiederherstellen

**Aus einem Schnappschuss:** Die Namen stehen beim Start im Protokoll (`copilot-JJJJ-MM-TT_HHMMSS.sqlite3`).

1. In der Konfiguration `restore_snapshot` auf den Dateinamen setzen.
2. Speichern, Add-on neu starten. Der bisherige Stand wird vorher als `vor-wiederherstellung-…` gesichert.
3. Danach `restore_snapshot` **leeren**, sonst wird bei jedem Start erneut überschrieben.

**Aus einer Home-Assistant-Sicherung:** **Einstellungen → System → Sicherungen**, die Sicherung wählen und nur HA Copilot wiederherstellen (Teilwiederherstellung).

## Updates

Neue Versionen erscheinen als Release auf GitHub; Home Assistant zeigt sie im Add-on als Update. Vor dem Update empfiehlt sich eine Sicherung (im Update-Dialog ankreuzen). Konfiguration und Daten bleiben erhalten; neue Optionen sind immer optional. Was sich geändert hat, steht im Reiter **Änderungsprotokoll** und im [CHANGELOG](../copilot/CHANGELOG.md).

Nach „Nach Updates suchen“ kann ein Dialog „Unknown error, see supervisor logs“ erscheinen. Das ist ein Zeitlimit von Home Assistant beim Neuladen des Stores und kein Fehler des Add-ons; das Update wird trotzdem gefunden.

## Umzug in ein anderes Add-on

Für Home Assistant ist jedes Add-on mit eigener Kennung ein eigenes Add-on mit eigenen Daten (z. B. das lokale Add-on im Ordner `/addons` und das aus diesem Repository). Die Chats wandern nicht von selbst mit. So nimmst du sie mit:

1. Im **alten** Add-on `export_database: true` setzen, speichern, neu starten. Es legt `copilot-export.sqlite3` (Versionen bis 0.28: `ki_chat-export.sqlite3`) in seinen Config-Ordner (`/addon_configs/<alte Kennung>/`). Das geht ab Version 0.23.0; ältere Versionen vorher aktualisieren.
2. Die Datei in den Config-Ordner des **neuen** Add-ons kopieren (`/addon_configs/<neue Kennung>/`).
3. Im neuen Add-on `restore_snapshot` auf diesen Dateinamen setzen und neu starten. Chats, Projekte, Gedächtnis und geplante Aufgaben sind danach da. Von der KI erzeugte Dateien und Projektdateien-Inhalte, die nicht in der Datenbank liegen, nicht.
4. `restore_snapshot` leeren, `export_database` ausschalten und die Export-Datei löschen (sie enthält alle Chats).
5. Konfiguration (Benutzer, Zugangsdaten) im neuen Add-on eintragen, bei Domain-Zugang den Tunnel auf den neuen Hostnamen richten (`http://<Hostname>:8100`, den nennt die Einrichtungsprüfung) und `public_trusted_proxies` neu setzen.
6. Das alte Add-on deinstallieren.

## Umzug von der Kennung ki_chat auf copilot (Version 0.28 auf 0.29)

Bis Version 0.28 hieß die Kennung des Add-ons `ki_chat` (in Home Assistant `<Repository-Kennung>_ki_chat`, Hostname `<Repository-Kennung>-ki-chat`). Ab 0.29.0 heißt sie `copilot`. Für Home Assistant ist das ein **neues Add-on**: Es hat eigene Optionen und einen leeren Datenspeicher. Das alte Add-on bleibt installiert und läuft weiter, bekommt aber keine Updates mehr. Solange du es nicht deinstalliert hast, ist es dein Rückweg. Wer erst jetzt mit dem Add-on beginnt, braucht diesen Abschnitt nicht.

Nimm dir etwa eine halbe Stunde. Die Oberfläche ist dazwischen kurz nicht erreichbar.

1. **Auf 0.28.0 sein.** Das alte Add-on muss mindestens 0.23.0 haben (dann kennt es `export_database`).
2. **Notieren, was nicht in der Datenbank steht:** die Optionen des alten Add-ons (Konfiguration, Menü ⋮, **In YAML bearbeiten**, den Text kopieren; er enthält auch Token und Schlüssel) und die eigenen Dateien im Config-Ordner (`logo.png`, `logo-full.png`, `icon.png`, `custom.css`).
3. **Exportieren:** Im alten Add-on `export_database: true` setzen, speichern und neu starten. Es legt `ki_chat-export.sqlite3` im Ordner `/addon_configs/<Repository-Kennung>_ki_chat/` ab (per Samba-Freigabe `addon_configs` oder Datei-Editor erreichbar).
4. **Altes Add-on stoppen.** Sonst laufen geplante Aufgaben doppelt.
5. **Neues Add-on installieren.** Nach der Aktualisierung des Repositories (Add-on-Store, ⋮, **Nach Updates suchen**) steht HA Copilot mit der neuen Kennung `copilot` im Store. Installieren, aber noch nicht starten.
6. **Dateien übertragen:** `ki_chat-export.sqlite3` und, falls vorhanden, Logo-Dateien und `custom.css` in den Ordner `/addon_configs/<Repository-Kennung>_copilot/` kopieren. Fehlt der Ordner noch, starte das neue Add-on einmal kurz (es meldet dann womöglich, dass noch keine Benutzer eingetragen sind) und stoppe es wieder.
7. **Optionen übernehmen:** In der Konfiguration des neuen Add-ons **In YAML bearbeiten** wählen und den kopierten Text einfügen. Dazu `restore_snapshot: ki_chat-export.sqlite3` setzen, `export_database` aus lassen, speichern.
8. **Starten.** Im Protokoll steht „Datenbank aus Schnappschuss ki_chat-export.sqlite3 wiederhergestellt“. Chats, Projekte, Gedächtnis und geplante Aufgaben sind da. Von der KI erzeugte Dateien und angehängte Originale nicht.
9. **Aufräumen im neuen Add-on:** `restore_snapshot` leeren und die Export-Datei löschen (sie enthält alle Chats).
10. **Umgebung anpassen:**
    - Bei Domain-Zugang den Tunnel auf den neuen Hostnamen richten (`http://<Repository-Kennung>-copilot:8100`; die Einrichtungsprüfung nennt ihn). Die Rückkehradresse in Entra (`https://<deine Domain>/auth/callback`) bleibt unverändert, weil sie an der Domain hängt.
    - `public_trusted_proxies` prüfen (die Adresse kann sich ändern; die Einrichtungsprüfung zeigt sie).
    - Der Eintrag in der Seitenleiste von Home Assistant ist jetzt der des neuen Add-ons. Lesezeichen, Dashboard-Links und Verknüpfungen in der Companion-App, die auf den alten Pfad (`/<Repository-Kennung>_ki_chat`) zeigen, anpassen.
11. **Prüfen:** Einrichtungsprüfung öffnen (Konto-Menü), einen Chat öffnen, eine Frage senden, bei Bedarf die Anmeldung über die Domain testen.
12. **Altes Add-on deinstallieren,** wenn alles stimmt. Seine Daten und der alte Config-Ordner verschwinden damit; die Export-Datei darin hast du vorher gelöscht.

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
cd copilot
pip install -r requirements.txt pytest pyyaml
python -m pytest -q
```

Die Tests laufen ohne Claude-Zugang. Jede Änderung muss in `copilot/config.yaml` die Version erhöhen und im [CHANGELOG](../copilot/CHANGELOG.md) stehen. Die Seite [Alle Einstellungen](einstellungen.md) wird aus `config.yaml` und `translations/de.yaml` erzeugt (`python tools/gen_options_doc.py`); ein Test schlägt fehl, wenn sie nicht mehr dazu passt.
