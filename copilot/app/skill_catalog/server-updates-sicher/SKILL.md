---
name: server-updates-sicher
description: Playbook für Paketaktualisierungen auf einem Linux-Server (apt): Was ansteht, was riskant ist, wie man sicher aktualisiert und danach prüft, ob alles läuft. Nutze es bei "sind Updates offen", "spiel die Updates ein" oder "Neustart nötig".
---

# Updates sicher einspielen

## 1. Was steht an? (nur lesen)
1. `server_read` mit `updates`: Anzahl der Pakete, Sicherheitsupdates, Hinweis „Neustart erforderlich“.
2. `server_status`: Läuft der Server gesund (keine fehlgeschlagenen Dienste, genug Platz auf `/` und `/boot`)? **Nicht aktualisieren, solange der Server schon Probleme hat**, die du nicht verstehst. Erst Lage klären (Playbook „server-stoerung-eingrenzen“).
3. Für wichtige Pakete (Datenbank, Webserver, Kernel) `package_info`: installierte Version, Herkunft und Konfigurationsdateien.

## 2. Einordnen und vorschlagen
- **Sicherheitsupdates** zeitnah, in der Regel risikoarm.
- **Dienste mit Datenhaltung** (Datenbanken) und **Hauptversionssprünge**: Sicherung zuerst, Wartungsfenster, Hinweise des Herstellers beachten.
- **Kernel, libc, systemd:** wirken erst nach einem Neustart. Ein Neustart gehört zu den Änderungen, die Copilot nie selbst ausführt (Stufe 3). Sage der Person, dass sie ihn selbst zu einem passenden Zeitpunkt auslöst.
- Frage, ob es eine **Sicherung oder Momentaufnahme** gibt, wenn der Server wichtig ist.

## 3. Einspielen (nur mit Freigabe)
1. `server_package` mit `update` (Paketlisten aktualisieren).
2. Zeige vor dem Upgrade, was passieren würde (Simulation, zum Beispiel `apt-get -s upgrade` über `server_run`, falls erlaubt), und nenne Pakete, die Dienste neu starten.
3. `server_package` mit `upgrade` oder gezielt `install` für einzelne Pakete. Bei vielen Paketen lieber in überschaubaren Gruppen, wichtige Dienste einzeln.
4. Bei Rückfragen zu Konfigurationsdateien („behalten oder ersetzen?“): im Zweifel die lokale Fassung behalten und der Person sagen, dass es eine neue Vorlage gibt.

## 4. Danach prüfen
- `server_status` und `services_failed`: läuft alles, was vorher lief?
- Die wichtigsten Dienste einzeln mit `service` und im Journal nach Fehlern seit dem Update suchen (`journal`, `priority=err`, `since_minutes`).
- `updates` erneut lesen: Ist „Neustart erforderlich“ gesetzt? Dann der Person sagen, **welche** Pakete den Neustart verlangen, soweit bekannt.
- Fasse zusammen: was wurde aktualisiert (Pakete und Versionen), was läuft, was ist offen.

## Regeln
- Entferne keine Pakete, nur weil `autoremove` sie vorschlägt, ohne die Liste gezeigt zu haben.
- Aktualisiere nicht „alles“ auf Produktivsystemen ohne Rückfrage und ohne Hinweis auf Sicherung.
- Bei Fehlern mitten im Upgrade (unterbrochenes dpkg) nicht raten: Meldung zeigen, Zustand mit `package_info` und dem Journal prüfen und Optionen nennen.
