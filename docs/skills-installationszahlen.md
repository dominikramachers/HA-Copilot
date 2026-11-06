# Installationszahlen der empfohlenen Skills aktualisieren

Die Zahlen auf den Karten unter „Anpassungen“ → „Entdecken“ stehen in `copilot/app/skill_catalog/catalog.json` (Feld `installs`, `installs_asof` nennt den Monat). In der Oberfläche werden sie auf zwei gültige Ziffern **aufgerundet** angezeigt („250 Tsd.“) und tragen keinen Hinweis. Das Add-on ruft sie nie selbst ab.

## Monatliche Aktualisierung (GitHub Action)

`.github/workflows/installs.yml` läuft am 3. jedes Monats (und auf Knopfdruck unter „Actions“ → „Installationszahlen“ → „Run workflow“). Sie fragt die API von skills.sh ab und öffnet einen Pull Request `installs-JJJJ-MM`, wenn sich Zahlen geändert haben. Die neuen Zahlen erreichen die Nutzer erst mit dem nächsten Release.

Die API von skills.sh ([Dokumentation](https://www.skills.sh/docs/api)) nimmt nur **Vercel-OIDC-Token** an, die nach etwa 12 Stunden ablaufen. Darum holt die Action bei jedem Lauf ein frisches Token über die Vercel-Befehlszeile. Einmalig nötig:

1. Bei Vercel ein (kostenloses) Konto anlegen und ein leeres Projekt erstellen; in dessen Einstellungen unter „OIDC Federation“ die Funktion einschalten.
2. Ein Zugriffs-Token erzeugen (Konto → Einstellungen → Tokens).
3. Im GitHub-Repository unter „Settings → Secrets and variables → Actions“ drei Secrets anlegen: `VERCEL_TOKEN` (das Zugriffs-Token), `VERCEL_ORG_ID` und `VERCEL_PROJECT_ID` (beide stehen in den Projekteinstellungen bei Vercel).
4. Unter „Settings → Actions → General“ bei „Workflow permissions“ den Haken „Allow GitHub Actions to create and approve pull requests“ setzen.
5. Die Action einmal von Hand starten und im Protokoll prüfen.

Ohne die Secrets endet der Lauf mit einem Hinweis, aber ohne Fehler. Hinweis: Pull Requests, die eine Action mit dem Standard-Token öffnet, lösen die normalen Prüfungen nicht von selbst aus; für eine reine Zahlen-Änderung ist das unkritisch (einmal „Update branch“ oder ein leerer Commit starten sie).

## Von Hand

`SKILLS_SH_TOKEN=<Token> python .github/scripts/update_installs.py copilot/app/skill_catalog/catalog.json` aktualisiert die Datei im selben Format; danach wie üblich committen.
