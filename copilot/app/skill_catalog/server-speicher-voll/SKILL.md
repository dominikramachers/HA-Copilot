---
name: server-speicher-voll
description: Playbook, wenn auf einem Linux-Server der Festplattenplatz knapp oder voll ist (Dateisystem, Journal, Docker, Pakete, Protokolle). Findet die Verursacher mit den Server-Werkzeugen und schlägt Aufräumschritte vor, die erst nach Freigabe laufen.
---

# Speicherplatz knapp oder voll

Ziel: herausfinden, **was** den Platz belegt und **warum es wächst**, bevor irgendetwas gelöscht wird.

## 1. Lage
1. `server_read` mit `disks`: Welches Dateisystem ist voll, wie viel Prozent? Vergleiche auch freie Inodes, wenn der Agent sie nennt: ein Dateisystem kann „voll“ sein, obwohl Platz frei ist.
2. `server_read` mit `metrics` (zum Beispiel 1440 Minuten): Wächst der belegte Platz langsam und stetig (Protokolle, Datenbank, Backups) oder sprunghaft (ein Job, ein Update, ein Absturz mit Core-Dump)?

## 2. Verursacher finden (nur lesen)
- `file_read` auf Verzeichnisse wie `/var/log`, `/var/lib`, `/var/cache`, `/home`, `/srv`, `/opt` zeigt Einträge, aber keine Summen. Wenn du Größen brauchst und `server_run` erlaubt ist, schlage `du -xh --max-depth=1 <Verzeichnis>` vor (liest nur), sonst bitte die Person, den Befehl selbst auszuführen.
- Journal: `journal` mit hoher Zeilenzahl und `priority=err` zeigt, ob ein Dienst in einer Schleife Meldungen schreibt.
- Docker: `docker` mit `ps` und `stats`; Images, Volumes und Container-Protokolle sind häufige Platzfresser.
- Pakete: `package_info` und `updates` zeigen, ob alte Kernel oder Paketreste liegen.

## 3. Aufräumen vorschlagen (nur mit Freigabe)
Reihenfolge vom mildesten zum weitreichenden, immer mit Erklärung, was verloren geht:
1. **Journal begrenzen:** `journalctl --vacuum-size=500M` (oder `--vacuum-time=14d`).
2. **Paket-Cache:** `apt-get clean`, danach `apt-get autoremove` (zeige vorher mit `-s`, was entfernt würde).
3. **Rotierte Protokolle:** nur alte, bereits gepackte Dateien (`*.gz`, `*.1`), nie die aktuelle Datei. Ist ein Dienst das Problem, löse erst die Ursache (zu gesprächiges Protokoll-Level).
4. **Docker:** `docker system df` zeigt, was frei würde; `docker image prune` und `docker builder prune` sind mild, `docker volume prune` zerstört Daten und gehört nicht zu dem, was du vorschlägst, ohne dass die Person es ausdrücklich möchte.

## Regeln
- Lösche nie Datenbanken, Mail-Verzeichnisse, Benutzerdaten oder Backups auf eigene Faust. Frage nach.
- Eine gelöschte Datei, die noch ein Prozess offen hält, gibt keinen Platz frei: Ein Neustart des Dienstes ist dann nötig. Das ist eine Änderung, also mit Freigabe.
- Nach dem Aufräumen `disks` erneut lesen und das Ergebnis nennen. Erkläre zum Schluss, was künftig das Wachstum begrenzt (Rotation, Überwachung, Platz erweitern).
