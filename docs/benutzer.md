# Benutzer und Rechte

HA Copilot hat **keine eigene Benutzerverwaltung** in der Oberfläche. Wer die App nutzen darf und was die KI für ihn tun darf, legst du ausschließlich in der Add-on-Konfiguration fest (**Einstellungen → Add-ons/Apps → HA Copilot → Konfiguration**). Jeder Benutzer hat ein **Profil** mit eigenen Chats, eigenen Projekten, eigenem Gedächtnis und eigenen geplanten Aufgaben. Andere Benutzer sehen davon nichts, auch nicht über die KI.

![Der Chat im Home-Assistant-Rahmen](screenshots/ha-copilot-im-panel.png)

## Schritt für Schritt: den ersten Benutzer anlegen

1. **Add-on starten** (siehe [Installation](installation.md)). Ein Eintrag nur mit Anzeigename (so ist es voreingestellt) startet die App, passt aber auf niemanden.
2. **HA Copilot in der Seitenleiste öffnen.** Es erscheint die Seite **Kein Zugriff**. Sie zeigt deinen **Benutzernamen** und deine **ID**. Das ist die Information, die du brauchst.
3. **Konfiguration öffnen** und den Eintrag unter **Benutzer (Profile)** anpassen:

   ```yaml
   profiles:
     - ha_user: dominik        # Anmeldename aus der Seite „Kein Zugriff“
       label: Dominik          # Anzeigename in der App (optional)
       ha_access: write        # Rechte der KI in Home Assistant (optional)
   ```

4. **Speichern** und das Add-on **neu starten**.
5. Die Seite in Home Assistant neu laden. Der Chat ist da.

> Findet das Add-on den Namen nicht oder mehrere Benutzer dazu, steht der Grund im Protokoll, und der Eintrag hat solange keinen Zugang. Trage dann die ID bei `ha_user_id` ein; sie hat Vorrang vor `ha_user`.

## Weitere Benutzer hinzufügen

In der Konfiguration bei **Benutzer (Profile)** auf **Hinzufügen** tippen und einen weiteren Eintrag ausfüllen. In der YAML-Ansicht (⋮ → In YAML bearbeiten) sieht das so aus:

```yaml
profiles:
  - ha_user: dominik
    label: Dominik
    ha_access: write          # darf in Home Assistant alles bauen und ändern
    github_access: write      # darf bei GitHub schreiben
    notify_service: notify.mobile_app_pixel
  - ha_user: anna
    label: Anna
    ha_access: execute        # darf Geräte bedienen, aber nichts umbauen
  - ha_user: kind1
    label: Lisa
    ha_access: none           # chattet nur, die KI sieht Home Assistant nicht
    web_access: off           # keine Websuche
```

Nach dem Speichern das Add-on neu starten. Jeder Benutzer meldet sich dabei wie gewohnt in Home Assistant an; das Add-on erkennt ihn über Home Assistant und ordnet ihn seinem Profil zu. Ein Passwort für die App gibt es nicht.

### Alle Felder eines Benutzers

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `ha_user` | meist ja | Anmeldename (oder Name der verknüpften Person) in Home Assistant, Groß-/Kleinschreibung egal. Der frei änderbare Anzeigename eines HA-Benutzers zählt bewusst nicht. |
| `label` | nein | Anzeigename in der App. Leer: `ha_user`. |
| `ha_user_id` | nein | Benutzer-ID (32 Hex-Zeichen) statt des Namens. Nur nötig bei mehrdeutigem Namen. Hat Vorrang. |
| `entra_upn` | nein | Konto für die Anmeldung über die [eigene Domain](domain-zugang.md) mit Microsoft. |
| `ha_access` | nein | Rechte der KI in Home Assistant: `none`, `read`, `execute`, `write` (siehe unten). Leer: `ha_access_default`. |
| `github_access` | nein | Rechte der KI bei GitHub: `none`, `read`, `write`. Leer: `github_access_default`. |
| `web_access` | nein | `on` oder `off`: Websuche. Leer: `web_access_default`. |
| `notify_service` | nein | Benachrichtigungsdienst fürs Handy, z. B. `notify.mobile_app_pixel`. |
| `id` | nein | Interner, stabiler Schlüssel. **Die Chats gehören diesem Schlüssel**, nach dem Anlegen nicht mehr ändern. |

Die vollständige Liste mit allen Werten steht in [Alle Einstellungen](einstellungen.md#benutzer).

## Rechte der KI

Die Stufen gelten **je Benutzer** und werden vom Server durchgesetzt, nicht von der KI. Eine Stufe lässt sich im Chat nicht „überreden“.

| Stufe | Home Assistant | GitHub |
|---|---|---|
| `none` | gar nichts, die KI chattet nur | kein Zugriff |
| `read` | Zustände, Verlauf, Logbuch, Bereiche lesen | Repositories, Dateien, Issues, Pull Requests lesen |
| `execute` | zusätzlich Geräte bedienen (Licht, Klima, Rollos, Szenen …) | (nicht vorhanden) |
| `write` | zusätzlich Automationen, Skripte, Szenen, Dashboards, Helfer anlegen und ändern | zusätzlich Dateien einchecken, Zweige, Pull Requests, Issues |

Voreinstellung ohne eigenen Eintrag: Home Assistant `read` (`ha_access_default`), GitHub `none` (`github_access_default`). Änderungen an der Konfiguration von Home Assistant und GitHub fragen standardmäßig im Chat nach (`ha_write_confirm`, `github_write_confirm`), Schlösser, Alarmanlagen und Garagentore **immer**. Neustart, Updates, Sicherungen und Benutzerverwaltung von Home Assistant sind nie möglich. Alle Einzelheiten: [Zugriff auf Home Assistant](../copilot/DOCS.md#zugriff-auf-home-assistant-ab-0150) und [GitHub](../copilot/DOCS.md#github-ab-0190).

## Alle Home-Assistant-Benutzer zulassen

Statt jeden Benutzer einzutragen, kannst du jeden Home-Assistant-Benutzer automatisch zulassen:

```yaml
all_ha_users: true
ha_users_excluded: "gast, kind1"
```

- Jeder Home-Assistant-Benutzer bekommt beim ersten Zugriff automatisch ein **eigenes Profil** (Kennung `ha-` plus Anfang seiner ID) mit eigenen, von den anderen getrennten Chats.
- `ha_users_excluded` nimmt Benutzernamen, Namen oder IDs, durch Komma getrennt. Diese Benutzer kommen nicht herein.
- Die Liste `profiles` brauchst du dann nur noch für Sonderfälle: eigener Anzeigename, abweichende Rechte, Microsoft-Anmeldung. Wer eingetragen ist, behält sein Profil und seine Rechte; alle anderen haben die Standardrechte (`ha_access_default`, `github_access_default`).
- Ein Abo-Token ist mit mehreren Benutzern nicht erlaubt, siehe [Installation](installation.md#4-zugang-zu-claude).

## Benutzer entfernen, umbenennen, wechseln

- **Entfernen:** Eintrag aus der Liste löschen, Add-on neu starten. Der Zugriff entfällt sofort, die Chats bleiben in der Datenbank. Wer die Daten loswerden will, löscht vorher in der App unter **Meine Daten → Alle Chats löschen**.
- **Anzeigename ändern:** nur `label` ändern.
- **HA-Benutzer wurde neu angelegt (neue ID):** `ha_user` bzw. `ha_user_id` im Eintrag anpassen. Die Chats bleiben beim Profil, solange `id` gleich bleibt.
- **Von „alle zulassen“ auf eine feste Liste wechseln:** Wer später eingetragen wird, bekommt ein Profil mit neuer Kennung. Damit er seine bisherigen Chats behält, trage bei `id` seine bisherige Kennung `ha-…` ein (sie steht im Protokoll bei „Anmeldung“).

## Zugang über die eigene Domain

Wer nicht in Home Assistant, sondern über eine eigene Adresse arbeitet, meldet sich mit Microsoft Entra ID oder mit Home Assistant an. Beides führt auf **dasselbe Profil** und dieselben Chats. Der Eintrag bekommt dafür `entra_upn`; die Einrichtung steht unter [Domain-Zugang](domain-zugang.md).

## Datenschutz zwischen Benutzern

- Jede Abfrage nach Chats filtert auf das Profil; zusätzlich verhindert die Datenbank selbst, dass eine Nachricht einem anderen Profil gehört als ihr Chat.
- Das **Haushalts-Gedächtnis** ist die einzige gemeinsame Ablage. Wer hineinschreiben darf, regelt `memory_household_writers`. Das **persönliche Gedächtnis**, Projekte, Projektwissen, geplante Aufgaben und erzeugte Dateien sind privat.
- Jeder Benutzer kann in der App unter **Meine Daten** alle eigenen Chats als ZIP exportieren oder löschen.
- Wer Zugriff auf die Add-on-Konfiguration oder den Konfigurationsordner hat, ist Administrator und kann technisch alles lesen. Die Trennung gilt für die Oberfläche und die Programmierschnittstelle.
