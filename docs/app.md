# App-Zugang (mobile App „HA Copilot“)

Seit 0.59.0 kann das Add-on die Anmeldung für die mobile App **HA Copilot** bereitstellen (iPhone/iPad). Die App liegt in einem eigenen Repository (`HA-Copilot-Mobile`) und zeigt dieselbe Oberfläche wie die Handy-Ansicht im Browser; sie fügt Dinge hinzu, die ein Browser nicht kann (Schlüsselspeicher, App-Sperre, später Push). Dieses Add-on liefert nur die Anmeldung und die Geräteverwaltung.

Die Funktion ist **standardmäßig aus** und nur über den [Domain-Zugang](domain-zugang.md) (https) möglich.

## Einschalten

```yaml
domain:
  app_access: true
  device_days: 90      # optional, 1 bis 180
```

Danach nichts weiter: Entra-App-Registrierung, Rückkehradressen und Cloudflare Tunnel bleiben, wie sie sind. In der App gibst du die Adresse deiner Domain ein (z. B. `https://chat.example.org`); die App fragt `…/app/v1/discovery` ab und zeigt dann die Anmeldewege an, die dein Server anbietet (Microsoft und/oder Home Assistant).

## Ablauf der Anmeldung

1. Die App erzeugt ein Geheimnis (`verifier`) und schickt nur dessen Hash (`challenge`, SHA-256) im Systembrowser an `/app/v1/login`. Der Systembrowser (bei iOS `ASWebAuthenticationSession`) ist kein eingebettetes Fenster: die App sieht weder Passwort noch Eingaben.
2. Du meldest dich wie im Browser an: Microsoft (mit allem, was dort eingerichtet ist, z. B. Zwei-Faktor) und/oder Home Assistant.
3. Der Server leitet auf `ha-copilot://auth?code=…&state=…` zurück. Der Code gilt 60 Sekunden und einmal.
4. Die App tauscht Code und `verifier` gegen ein **Gerätetoken** (`POST /app/v1/token`) und legt es im Schlüsselspeicher des Geräts ab (iOS: Keychain, nur auf diesem Gerät, nur nach Entsperren).
5. Für das App-Fenster holt die App ein **Einmal-Ticket** (30 Sekunden) und öffnet damit `/app/v1/enter`. Der Server setzt daraufhin das Sitzungs-Cookie im App-Fenster. Das Gerätetoken steht nie in einer Adresse und nie im Protokoll.

## Was wo gespeichert ist

| Ort | Was | Wie |
|---|---|---|
| Gerät (Schlüsselspeicher) | Gerätetoken, Adresse, `server_id` | Keychain, nicht in Sicherungen |
| Server (Datenbank) | Gerät (Name, System, App-Version, Zeiten) und **nur der Hash** des Tokens | Tabelle `devices` |
| Server (Arbeitsspeicher) | offene Anmeldevorgänge, Codes, Tickets (nur als Hash, kurzlebig) | verschwinden beim Neustart |
| App-Fenster | Sitzungs-Cookie, höchstens 7 Tage ohne Nutzung | `__Host-`, `Secure`, `HttpOnly` |

## Sicherheit

- **Kein Entra- oder HA-Token in der App.** Die App bekommt nur ein eigenes Gerätetoken, das ausschließlich bei diesem Add-on gilt und jederzeit entzogen werden kann.
- **PKCE (S256):** Ein abgefangener Einmal-Code (etwa durch eine andere App, die dasselbe Adressschema `ha-copilot://` beansprucht) ist ohne `verifier` wertlos und verfällt nach dem ersten Versuch, auch dem falschen.
- **Anmeldung nur im Systembrowser**, damit sich keine App (auch nicht diese) als Anmeldeseite ausgeben kann und Passwort-Manager, Passkeys und Zwei-Faktor wie gewohnt funktionieren.
- **Frische Anmeldung für die App:** Ein bereits angemeldeter Browser überspringt die Anmeldeseite nicht, wenn sie für die App aufgerufen wird. Die Seite zeigt den Hinweis, die Adresse im Browser zu prüfen.
- **Token erneuern und Diebstahl erkennen:** Die App erneuert ihr Token regelmäßig. Das alte gilt danach noch fünf Minuten (falls die Antwort verloren ging). Wird es später noch einmal gezeigt, hat jemand es kopiert: das Gerät wird gesperrt, seine Sitzungen enden.
- **Harte Grenzen:** `device_days` ohne Nutzung, in jedem Fall 180 Tage ab der Anmeldung; Sitzung im App-Fenster höchstens 7 Tage.
- **Sofort entziehbar:** Einstellungen → **Geräte (App)**. Wird ein Profil aus der Konfiguration entfernt oder ausgeschlossen, hört auch sein Gerät sofort auf zu funktionieren.
- **Begrenzung:** Anmeldestarts, Tokenabrufe und Fehlversuche sind je Gegenstelle begrenzt. Entdeckung und alle Antworten der Schnittstelle sind `no-store`.
- **Nur https**, nur die eine eingetragene Domain; das App-Fenster darf nur diese Adresse laden, alles andere öffnet sich im Systembrowser.

### Bekannte Restrisiken

- **Anmeldeseite vortäuschen:** Wer eine Person dazu bringt, in einem Browser eine gefälschte Anmeldeseite zu öffnen, bekommt wie überall ihr Passwort. Für die App gilt dasselbe wie für den Browser; der Hinweis auf der Seite und der Systembrowser (Adresszeile sichtbar) sind die Gegenmaßnahme.
- **Verlorenes, entsperrtes Gerät:** Wer das Gerät entsperrt in der Hand hat, ist angemeldet. Die App kann eine zusätzliche Sperre (Face ID / Code) verlangen; entfernen kannst du das Gerät jederzeit in den Einstellungen.
- **Adressschema auf Android:** Dort kann eine zweite App dasselbe Schema beanspruchen; PKCE schützt davor (siehe oben).

## Schnittstellen (Referenz)

Alle unter `/app/v1`, nur auf dem Domain-Server, nur mit `domain.app_access`.

| Aufruf | Zweck |
|---|---|
| `GET /discovery` | Version, `server_id`, Anmeldewege (`entra`, `ha`) |
| `GET /login?challenge&state&platform&device&app_version` | Beginn im Systembrowser, leitet auf `/login` |
| `POST /token` `{code, verifier}` | Gerätetoken ausstellen |
| `POST /refresh` (Bearer) | Token erneuern |
| `POST /ticket` (Bearer) | Einmal-Ticket für das App-Fenster |
| `GET /enter?ticket=` | Sitzung im App-Fenster setzen, weiter nach `/new` |
| `POST /logout` (Bearer) | Gerät entfernen |

Dazu in der Oberfläche: `GET /api/devices`, `DELETE /api/devices/{id}`, `DELETE /api/devices`.

## Stand und Grenzen

- Die Server-Seite ist mit simuliertem Entra und simuliertem Home Assistant vollständig getestet (`tests/test_app_access.py`).
- **Noch nicht auf einem echten iPhone geprüft:** `ASWebAuthenticationSession`, Cookie-Verhalten im App-Fenster, Datei-Downloads, Mikrofon, lokale Netzwerke.
- **Push-Benachrichtigungen, Android:** nicht Teil dieser Version.

Zurück zum [Domain-Zugang](domain-zugang.md).
