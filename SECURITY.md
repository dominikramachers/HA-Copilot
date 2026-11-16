# Sicherheit

## Schwachstellen melden

Bitte melde Sicherheitslücken **nicht** als öffentliches Issue. Nutze stattdessen die private Meldung von GitHub:
**Security → Report a vulnerability** in diesem Repository (Private Vulnerability Reporting). Beschreibe, was du gefunden hast, wie man es nachstellt und welche Version betroffen ist. Zugangsdaten, Tokens und echte Chats gehören nicht in die Meldung.

Ich antworte so schnell wie möglich, in der Regel innerhalb weniger Tage. Das Projekt wird in der Freizeit gepflegt; eine feste Frist kann ich nicht zusagen.

## Unterstützte Versionen

Es gibt Korrekturen nur für die jeweils neueste Version. Bitte vorher aktualisieren.

## Was das Add-on schützt (und was nicht)

- Jede Person sieht nur ihre eigenen Chats, Projekte und das eigene Gedächtnis; die Trennung ist in der Datenbank erzwungen.
- Der Zugang über Home Assistant (Ingress) vertraut nur dem Home-Assistant-Proxy. Der Zugang über eine eigene Domain braucht Anmeldung (Microsoft Entra ID oder Home Assistant) mit serverseitigen Sitzungen.
- Die KI darf in Home Assistant und bei GitHub nur das, was in der Konfiguration freigegeben ist; Änderungen werden im Chat bestätigt, gefährliche Befehle sind gesperrt.
- Linux-Server (ab 0.60.4, nur wenn `servers.enabled` an ist): Der Hub im Add-on nimmt nur TLS-1.3-Verbindungen an; die Agenten verbinden sich ausgehend und werden über ein Zertifikat einer eigenen CA erkannt. Neue Server sind bis zur Bestätigung gesperrt, die KI darf sie über feste, lesende Abfragen ansehen, und jeder Aufruf steht im Protokoll. Änderungen (ab 0.60.7) laufen nur nach Einstufung durch den Agenten und ausdrücklicher Freigabe der Person im Chat (jede einzeln, mit dem genauen Befehl); zerstörerische Befehle (Stufe 3) führt weder der Agent noch der Root-Helfer je aus, und ob ein Server Änderungen erlaubt, steht allein in der lokalen Datei `/etc/copilot-agent/policy`. Port 8101 gehört nur ins Heimnetz oder VPN, nie ins Internet. Ab 0.61.0: Der Agent aktualisiert sich nach lokaler Richtlinie (`update=off|manual|auto`) selbst aus dem Add-on; er prüft Prüfsumme, Größe und einen Probelauf, und mit gesetztem `update_key` auch eine Ed25519-Signatur, und setzt bei einem Fehlstart auf die alte Fassung zurück. **Vertrauensmodell:** ohne `update_key` kann, wer das Add-on kontrolliert, über die Aktualisierung Programme mit den Rechten des Agenten und des Root-Helfers auf die Server bringen; wer das nicht will, setzt `update=off` oder einen `update_key`. Eine Signierung im Build gibt es noch nicht. Zertifikate der Server erneuern sich selbst (neue Zertifikatsanfrage, der Schlüssel verlässt den Server nicht; das alte Zertifikat gilt höchstens 7 Tage weiter). `file_read` liest jede Datei, die der Agent-Benutzer lesen darf, verweigert aber Pfade, die nach Schlüsseln, Kennwörtern oder Token aussehen, und schwärzt Geheimnisse in der Ausgabe. `server_file_write` schreibt nur in den Ordnern der lokalen Richtlinie (`write_paths`), nur nach Freigabe mit Vergleich und Sicherungskopie, nie in Kontendateien, `sudoers`, `fstab` und SSH-Schlüssel.
- Zugangsdaten (Claude, GitHub, Entra) stehen nur in der Add-on-Konfiguration und werden aus Fehlermeldungen entfernt.
- Der Code wurde vor der Veröffentlichung umfassend geprüft (Stand 0.24.0); Ergebnis und bewusst akzeptierte Restrisiken stehen unter „Sicherheitsprüfung“ in [`copilot/DOCS.md`](copilot/DOCS.md).

**Nicht geschützt:** Ein Add-on mit Zugriff auf Home Assistant ist so sicher wie die Konfiguration, die du einstellst. Gib die Domain-Seite nur frei, wenn du die Hinweise in [`copilot/DOCS.md`](copilot/DOCS.md) gelesen hast, und vergib Schreibrechte sparsam. Inhalte aus dem Web, von GitHub oder aus Anhängen können versuchen, die KI zu beeinflussen („Prompt Injection“); deshalb fragen Änderungen nach solchen Inhalten immer im Chat nach.
