# Domain-Zugang (optional)

Im Normalfall öffnest du HA Copilot über die Seitenleiste von Home Assistant; die Anmeldung übernimmt Home Assistant. Mit dem **Domain-Zugang** erreichst du denselben Chat zusätzlich über eine eigene Adresse wie `https://chat.example.org`, zum Beispiel vom Firmenrechner oder als App auf dem Handy. Angemeldet wird mit **Microsoft Entra ID** oder, wenn du magst, mit **Home Assistant**. Beide Wege führen auf dasselbe Profil und dieselben Chats.

Der Domain-Zugang ist **standardmäßig aus**. Das Add-on öffnet von sich aus nichts zum Internet; den Tunnel richtest du selbst ein.

> **Wichtig:** Wer die Domain aktiviert, nutzt die App für mehrere Personen oder von außen. Dafür gehört ein **API-Schlüssel** (`anthropic_api_key`) in die Konfiguration, kein Abo-Token. Siehe [Installation](installation.md#4-zugang-zu-claude).

## Überblick

```
Browser ──https──▶ Cloudflare Tunnel ──http──▶ HA Copilot (Port 8100)
                                                   │
                                  Anmeldung ◀──────┤──────▶ Microsoft Entra ID
                                                   └──────▶ Home Assistant (optional)
```

## 1. Microsoft Entra: App-Registrierung

1. Im Microsoft Entra Admin Center (entra.microsoft.com) **Identität → Anwendungen → App-Registrierungen → Neue Registrierung**.
2. Name frei wählen, z. B. „HA Copilot“. Unterstützte Kontotypen: **Nur Konten in diesem Organisationsverzeichnis** (einzelner Mandant).
3. **Umleitungs-URI:** Plattform **Web**, Wert `https://chat.example.org/auth/callback` (deine Adresse, immer mit `/auth/callback`).
4. Nach dem Anlegen auf der Übersicht notieren: **Anwendungs-ID (Client)** und **Verzeichnis-ID (Mandant)**.
5. Unter **Zertifikate & Geheimnisse → Neuer geheimer Clientschlüssel** einen Schlüssel anlegen und den **Wert** sofort kopieren (er wird später nicht mehr angezeigt). Das Ablaufdatum notieren.
6. Zusätzliche API-Berechtigungen sind nicht nötig; die Anmeldung fragt nur `openid`, `profile` und `email` ab.

Wer sich anmelden darf, entscheidet nicht Entra, sondern allein die Liste `profiles` in der Konfiguration: Die UPN des Kontos muss bei einem Benutzer unter `entra_upn` stehen. Unbekannte Konten bekommen nie ein Profil.

## 2. Cloudflare Tunnel

Der Tunnel leitet `chat.example.org` auf den Port **8100** des Add-ons. Mit dem Add-on „Cloudflared“ geht das im selben Home Assistant; in dessen Konfiguration wird der Name als zusätzlicher Host eingetragen:

```yaml
additional_hosts:
  - hostname: chat.example.org
    service: http://f472b445-ki-chat:8100
```

Der Hostname im `service` ist der Name des Add-ons im internen Netz von Home Assistant. Bei HA Copilot aus diesem Repository lautet er `f472b445-ki-chat`. **Die Einrichtungsprüfung nennt dir den genauen Namen**, sobald der Domain-Zugang eingeschaltet ist. Läuft der Tunnel auf einem anderen Gerät, gib den Port unter **Netzwerk** in der Add-on-Konfiguration frei und richte den Tunnel auf die IP-Adresse von Home Assistant.

## 3. Konfiguration

```yaml
public_enabled: true
public_base_url: https://chat.example.org      # https, ohne Pfad, ohne Schrägstrich am Ende
entra_tenant_id: 00000000-0000-0000-0000-000000000000
entra_client_id: 00000000-0000-0000-0000-000000000000
entra_client_secret: "…"
session_days: 30                                # angemeldet bleiben, 1 bis 90 Tage
profiles:
  - ha_user: dominik
    label: Dominik
    entra_upn: dominik@example.org              # Konto, mit dem er sich bei Microsoft anmeldet
```

Speichern und das Add-on **neu starten**. Fehlt etwas oder ist es ungültig, startet das Add-on nicht und nennt den Grund im Protokoll. Alle Optionen: [Alle Einstellungen](einstellungen.md#zugang-über-eine-eigene-domain).

Danach `https://chat.example.org` öffnen, die E-Mail-Adresse eingeben und bei Microsoft anmelden. Beim **ersten** Login bindet das Add-on die Entra-Objekt-ID fest an das Profil; ab dann zählt nur noch diese ID, nicht mehr der Name.

## 4. Anmeldeversuche je Besucher zählen

Hinter einem Tunnel kommen alle Besucher von derselben Adresse. Ohne weitere Angabe teilen sie sich die Begrenzung der Anmeldeversuche (10 je 10 Minuten): Wenige falsche Versuche würden die Anmeldung für alle sperren. Trage deshalb die Adresse des Tunnels bei `public_trusted_proxies` ein, damit das Add-on den Header `CF-Connecting-IP` von dort auswerten darf.

1. Rufe die Anmeldeseite einmal über deine Adresse auf.
2. Öffne die **Einrichtungsprüfung**. Sie nennt unter „Anmeldeversuche werden nicht je Besucher gezählt“ die Adresse, von der die Anfragen kommen.
3. Trage sie ein, z. B. `public_trusted_proxies: ["172.30.33.5"]`, speichere und starte neu.

## Anmeldung mit Home Assistant (optional)

Mit `ha_url` (von außen erreichbare Adresse von Home Assistant, https) zeigt die Anmeldeseite zusätzlich **Mit Home Assistant anmelden**. Ohne Entra-Angaben ist das der einzige Weg.

```yaml
ha_url: https://ha.example.org
```

Der Knopf führt zur Anmeldung von Home Assistant selbst, mit allem, was dort eingerichtet ist (auch Zwei-Faktor). Das Add-on sieht dein Passwort nie: Es tauscht nur den Rückgabecode gegen ein Token, fragt ab, wer du bist, und widerruft das Token sofort. Wer hineindarf, entscheidet dieselbe Regel wie im HA-Panel: eingetragener Benutzer oder `all_ha_users` ohne Ausschluss. Home Assistant muss von der Domain-Seite aus erreichbar sein. Als Weiterleitungsadresse verwendet das Add-on `https://chat.example.org/auth/ha-callback`.

## Als App auf dem Handy

Im Handy-Browser über **Zum Home-Bildschirm** ablegen. Name (`app_name`) und Symbol (`icon.png`) kommen aus der Konfiguration, die App öffnet im Vollbild ohne Browserleiste. Auf dem iPhone hat die App einen eigenen Speicher, die Anmeldung ist dort einmal neu nötig.

## Sicherheit

- Entra: OpenID Connect mit PKCE. Geprüft werden Signatur, Aussteller, Zielgruppe, Ablauf, Nonce und Mandant; die Anmeldung ist an den startenden Browser gebunden und nur einmal einlösbar.
- Sitzungen liegen serverseitig (nur der Hash des Tokens in der Datenbank). Das Cookie ist `__Host-`-präfixiert, `Secure`, `HttpOnly`, `SameSite=Lax`.
- Schreibende Anfragen verlangen einen eigenen Header und einen passenden `Origin`.
- Anmeldeversuche sind begrenzt, die Seiten nicht in fremden Frames darstellbar und senden HSTS.
- Der Zugriff der KI auf Home Assistant über die Domain lässt sich mit `ha_access_via_domain: false` ganz abschalten.
- Das **Entra-Geheimnis läuft ab**. Trage das Ablaufdatum bei `entra_secret_expires` ein (`JJJJ-MM-TT`); 30 Tage vorher erscheint ein Hinweis im Chat.

Alle Einzelheiten: [Sicherheit in Kürze](../copilot/DOCS.md#sicherheit-in-kürze) und [SECURITY.md](../SECURITY.md).

## Probleme

| Beobachtung | Abhilfe |
|---|---|
| Das Add-on startet nach dem Einschalten nicht mehr | Im Protokoll steht, welche Angabe fehlt oder ungültig ist (`public_base_url` mit `https://`, GUIDs für Mandant und Client). |
| Microsoft meldet „Umleitungs-URI stimmt nicht überein“ | In der App-Registrierung muss genau `https://<deine Adresse>/auth/callback` stehen. |
| Nach der Anmeldung steht „Kein Zugriff“ | Die UPN des Kontos steht bei keinem Benutzer unter `entra_upn`. Die Seite zeigt die erkannte UPN. Bei Gastkonten ist es die E-Mail-Adresse des Gastes, nicht der `…#EXT#…`-Name. |
| Die Seite lädt nicht oder bricht ab | Tunnel und Hostname prüfen (`http://<Add-on-Hostname>:8100`), Tunnel-Protokoll ansehen. |
| Die Anmeldung wird nach mehreren Versuchen zeitweise abgelehnt | Begrenzung der Anmeldeversuche; kurz warten und `public_trusted_proxies` setzen (Abschnitt 4). |
