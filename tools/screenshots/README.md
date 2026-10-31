# Screenshots erzeugen

Die Bilder in `docs/screenshots/` zeigen **echte Oberflächen mit Demo-Daten**, keine Mock-ups und keine privaten Daten:

- **Home Assistant:** eine frische Test-Instanz von Home Assistant Core (`pip install homeassistant`, Version 2026.2.3) mit der eingebauten `demo`-Integration, einem Demo-Benutzer und einem Platzhalter-Dashboard „Zuhause“ (`ha_dashboard.py`).
- **HA Copilot:** die echte App aus diesem Repository (`ki_chat/`), gestartet mit Beispiel-Chats, -Gedächtnis und -Aufgaben (`demo_addon.py`) und einer **nachgebildeten KI** (keine Verbindung zu Claude, keine Zugangsdaten).
- **Einbettung:** Die Test-Instanz hat keinen Supervisor. Das Panel „HA Copilot“ ist deshalb ein kleines eigenes Panel (`ha_config/www/copilot-panel.js`), das die App wie der Ingress des Supervisors in einem Frame gleicher Herkunft einbettet; die Aufnahme leitet die Ingress-Adresse auf die Demo-App um. Die Oberfläche der App (Seitenleiste, Dialoge, Farben aus dem Home-Assistant-Theme) ist dieselbe wie in einer echten Installation. Nicht abgebildet sind Dinge, die nur der Supervisor liefert (Add-on-Store, Konfigurationsseite des Add-ons).

## Ablauf

```bash
python -m venv venv && venv/bin/pip install homeassistant==2026.2.3 numpy pymicro-vad pyspeex-noise
pip install -r ki_chat/requirements.txt playwright && playwright install chromium

mkdir work && cp -r tools/screenshots/ha_config work/hademo
venv/bin/hass -c work/hademo &                      # Test-Instanz auf Port 8123
SHOT_WORK=work python tools/screenshots/ha_onboard.py work/ha_token.json
python tools/screenshots/ha_dashboard.py work/ha_token.json

TZ=Europe/Berlin python tools/screenshots/demo_addon.py &                          # Demo-App auf Port 8099
KI_LANG=en KI_PORT=8098 TZ=Europe/Berlin python tools/screenshots/demo_addon.py &  # englische Variante

export SHOT_WORK=work
python tools/screenshots/capture_ha.py docs/screenshots        # Seitenleiste, Dashboard, Chat in Home Assistant
python tools/screenshots/capture_features.py docs/screenshots  # Einrichtungsprüfung, Suche, Geplant, Gedächtnis, Menü
python tools/screenshots/capture_app.py docs/screenshots       # Chat allein, Handy, Englisch, Nachricht bearbeiten
python tools/screenshots/capture_theme.py docs/screenshots     # dasselbe mit dem eigenen Theme DORALAB, hell und dunkel
```

Das Theme „DORALAB“ liegt als `ha_config/themes/doralab.yaml` (nur Farben, kein Logo). `capture_theme.py` schaltet es für die Aufnahme mit dem Dienst `frontend.set_theme` ein und danach wieder aus. `capture_features.py` erzeugt zusätzlich Handy-Bilder von Home Assistant (`ha-handy-*.png`), die nicht in der Dokumentation verwendet werden.

Die Bilder werden danach auf 256 Farben verkleinert (Pillow, `optimize=True`), das hält das Repository klein.

Die Skripte sind Hilfsmittel für die Dokumentation und gehören nicht zum Add-on; sie werden nicht ins Image gebaut und nicht in CI ausgeführt.
