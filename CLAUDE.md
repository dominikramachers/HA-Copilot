# HA Copilot: Hinweise für die Arbeit am Repository

Das Add-on liegt in `copilot/` (FastAPI, Vanilla-JS, SQLite). Tests: `cd copilot && python -m pytest -q`. Arbeit über Feature-Branch und Pull Request; gemergt und veröffentlicht wird vom Besitzer.

## Jede Änderung ist ein Release
Für jede Änderung, die Nutzer bemerken, gehören zusammen und werden im selben Pull Request angepasst:
1. `copilot/config.yaml` (`version`) hochzählen.
2. `copilot/CHANGELOG.md`: neuer Abschnitt `## <Version>` (ausführlich, darf technisch sein).
3. `copilot/DOCS.md`: `**Stand: <Version>.**`; passende Abschnitte und `docs/funktionen.md` nachziehen.
4. **`copilot/app/news.json`: Eintrag für dieselbe Version** (neueste zuerst), `de` und `en`, in einfacher Sprache aus Sicht der KI („Ich kann jetzt …“), ohne Technik, Titel höchstens 40 und Text höchstens 220 Zeichen. Daraus entsteht das Fenster „Das ist neu“, das jede Person nach einem Update einmal sieht. `tests/test_welcome.py` schlägt fehl, wenn der Eintrag fehlt oder Fachwörter enthält.
5. Neue Texte in `copilot/app/static/*.js` und im Server immer über `tr()` und mit englischer Übersetzung (`app/locales/en-ui.json` bzw. `en.json`); `tests/test_i18n.py` prüft das.
