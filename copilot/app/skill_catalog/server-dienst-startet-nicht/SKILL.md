---
name: server-dienst-startet-nicht
description: Playbook für einen systemd-Dienst auf einem Linux-Server, der nicht startet, abstürzt oder dauernd neu startet (failed, activating, Restart-Schleife). Liest Zustand, Journal und Konfiguration und führt gezielt zur Ursache.
---

# Dienst startet nicht oder fällt immer wieder aus

## 1. Zustand und Meldungen
1. `server_read` mit `service` und `unit` (zum Beispiel `nginx.service`): Zustand, Hauptprozess, Exit-Code, wie lange er läuft, wie oft er neu gestartet wurde.
2. `server_read` mit `journal`, `unit` und `lines` um 100: Die **erste** Fehlermeldung nach dem Start ist meist wichtiger als die letzte. Lies von oben, nicht nur das Ende.
3. Gibt es noch mehr ausgefallene Dienste? `services_failed`. Häufen sich Fehler, liegt die Ursache oft woanders (Platz, Speicher, Netz, Abhängigkeit).

## 2. Typische Ursachen und wie du sie erkennst
- **Konfigurationsfehler** („syntax error“, „invalid“, Zeilennummer): `file_read` auf die genannte Datei, gezielt um die Zeile. Bei Webservern und ähnlichen gibt es einen Testbefehl (zum Beispiel `nginx -t`); schlage ihn vor, er ändert nichts.
- **Port belegt** („address already in use“): `server_read` mit `network`: Welcher Prozess lauscht schon?
- **Berechtigung** („permission denied“): Eigentümer und Modus der Datei oder des Verzeichnisses; bei SELinux/AppArmor zeigt das Journal „denied“-Meldungen.
- **Platz oder Speicher** („No space left“, „Out of memory“, „Killed“): `disks`, `memory`, im Journal nach „oom“ suchen. Weiter mit „server-speicher-voll“ oder „server-langsam“.
- **Abhängigkeit fehlt** („dependency failed“, Datenbank nicht erreichbar): den Dienst prüfen, von dem er abhängt, zuerst.
- **Nach einem Update:** `package_info` für das Paket und das Datum der Änderung mit dem ersten Fehler im Journal vergleichen; geänderte Konfigurationsdateien nach Paketupdate sind ein häufiger Grund.
- **Container:** `docker` mit `ps` und `logs` für den Container, wenn der Dienst dort läuft.

## 3. Beheben (nur mit Freigabe)
- Zuerst die Ursache beheben (Konfiguration korrigieren mit `server_file_write`, das Vergleich und Sicherungskopie zeigt), **dann** `server_service` mit `restart`. Ein Neustart ohne Ursachenbehebung verdeckt das Problem nur.
- Bei Konfigurationsänderungen: erst den Testbefehl des Dienstes vorschlagen, dann neu laden (`reload`), wo der Dienst das kann, statt hart neu zu starten.
- `enable` und `disable` ändern das Verhalten beim Booten: erkläre das vorher.
- Nach der Änderung `service` und das Journal erneut lesen und sagen, ob der Dienst läuft und stabil bleibt (nicht nur „gestartet“).

## Regeln
- Zeige der Person die Meldung, auf die du dich stützt, und trenne Beobachtung von Vermutung.
- Keine Pakete installieren oder entfernen, nur weil es „sicher helfen könnte“. Erst belegen, dass das Paket die Ursache ist.
- Bleibt die Ursache unklar, sage das und nenne die nächsten Prüfschritte, die die Person oder du (mit Freigabe) machen kannst.
