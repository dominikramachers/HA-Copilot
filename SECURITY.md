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
- Zugangsdaten (Claude, GitHub, Entra) stehen nur in der Add-on-Konfiguration und werden aus Fehlermeldungen entfernt.
- Der Code wurde vor der Veröffentlichung umfassend geprüft (Stand 0.24.0); Ergebnis und bewusst akzeptierte Restrisiken stehen unter „Sicherheitsprüfung“ in [`copilot/DOCS.md`](copilot/DOCS.md).

**Nicht geschützt:** Ein Add-on mit Zugriff auf Home Assistant ist so sicher wie die Konfiguration, die du einstellst. Gib die Domain-Seite nur frei, wenn du die Hinweise in [`copilot/DOCS.md`](copilot/DOCS.md) gelesen hast, und vergib Schreibrechte sparsam. Inhalte aus dem Web, von GitHub oder aus Anhängen können versuchen, die KI zu beeinflussen („Prompt Injection“); deshalb fragen Änderungen nach solchen Inhalten immer im Chat nach.
