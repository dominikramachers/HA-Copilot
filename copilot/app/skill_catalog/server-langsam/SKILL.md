---
name: server-langsam
description: Playbook für einen langsamen Linux-Server oder hohe Auslastung (Last, CPU, Arbeitsspeicher, Auslagerung, Datenträger-Wartezeit, Docker). Unterscheidet mit den Server-Werkzeugen, ob ein Prozess, zu wenig Speicher oder der Datenträger bremst.
---

# Server ist langsam oder überlastet

## 1. Lage und Verlauf
1. `server_status`: Load im Verhältnis zur CPU-Anzahl (Load 8 bei 8 Kernen ist ausgelastet, bei 2 Kernen überlastet), Speicher, Datenträger.
2. `server_read` mit `metrics` (zum Beispiel 360 Minuten): Seit wann? Dauerhaft, in Spitzen zu bestimmten Zeiten (Backup, Cron) oder seit einem Ereignis (Update, neuer Dienst)?

## 2. Welcher Engpass?
- **CPU:** `processes` zeigt die ressourcenhungrigsten Prozesse. Ein Prozess mit dauerhaft hoher CPU ist ein Kandidat; mehrere kleine sind eher Last durch Anfragen.
- **Arbeitsspeicher:** `memory`: Ist „verfügbar“ klein und die Auslagerung (Swap) wird genutzt oder wächst, fehlt Speicher. Im Journal nach „oom“ oder „Out of memory“ suchen (`journal`, `priority=err`): Dort steht, welcher Prozess beendet wurde.
- **Datenträger:** Hohe Last bei niedriger CPU-Auslastung deutet auf Warten auf Ein-/Ausgabe hin. Prüfe `disks` (voll?) und frage nach Backups, Datenbank-Wartung oder Virenscans zu dieser Zeit.
- **Dienste in Schleife:** `services_failed` und das Journal: Ein Dienst, der ständig neu startet, kostet Last.
- **Container:** `docker` mit `stats` zeigt CPU und Speicher je Container; ein Container ohne Limit kann den Host leer ziehen.

## 3. Einordnen, bevor du handelst
Beschreibe, was du siehst, mit Zahlen und Zeitraum, und was die wahrscheinlichste Ursache ist. Beispiel: „Seit 02:10 Uhr ist der Load bei 9, der Prozess X belegt 780 % CPU; das passt zum nächtlichen Job Y.“

## 4. Maßnahmen (nur mit Freigabe)
- Prozess oder Dienst neu starten (`server_service`), wenn er sich aufgehängt hat; sage vorher, welche Verbindungen dabei unterbrochen werden.
- Konfiguration anpassen (Speichergrenzen, Worker-Anzahl, Zeitpunkt des Jobs) mit `server_file_write`.
- Dauerhafte Lösungen nennst du als Empfehlung, ohne sie selbst durchzuführen: mehr RAM, Limits für Container, Jobs zeitlich entzerren, Überwachung einrichten.
- Prozesse hart beenden (`kill`) ist eine Änderung mit Risiko: nur auf ausdrücklichen Wunsch, mit Name und Nummer des Prozesses, und nie bei Systemdiensten wie `sshd`, `systemd` oder dem Copilot-Agenten.

## Regeln
- Ein einzelner Messwert ist keine Diagnose: vergleiche mit dem Verlauf aus `metrics`.
- Nach einer Maßnahme warte kurz, lies `server_status` erneut und berichte, ob sich der Wert verändert hat.
