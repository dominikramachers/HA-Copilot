# Mitgelieferte Skills

Jeder Ordner hier ist ein Skill im Standardformat (`SKILL.md` plus optional `references/` und `assets/`). Die Einträge stehen in `catalog.json`.
Die Lizenztexte liegen in `licenses/`; beim Hinzufügen kommt der passende Text als `LICENSE.txt` in das Skill.

## Herkunft

| Quelle | Skills | Lizenz |
| --- | --- | --- |
| https://github.com/anthropics/skills (Commit ca45fc4) | `frontend-design`, `internal-comms` (unverändert, mit eigener `LICENSE.txt`), `theme-factory` (ohne die PDF-Vorschau) | Apache-2.0, Copyright Anthropic, PBC |
| https://github.com/anthropics/knowledge-work-plugins (Commit d900840) | Skills aus Marketing, Design, Technik, Daten, Produkt, Kundenservice, Personal und Betrieb | Apache-2.0, Copyright Anthropic, PBC |
| https://github.com/coreyhaines31/marketingskills (Commit 88c79f6) | Skills zu Texten, Social Media, SEO, Preisen, PR und Community | MIT, Copyright Corey Haines |
| dieses Repository | `geschaeftsbrief-din-5008`, `protokoll-besprechung`, `e-mail-professionell`, `praesentation-storyline`, `zusammenfassung-kernaussagen`, `dokument-gemeinsam-schreiben` | MIT, Copyright DORALAB |

## Änderungen gegenüber den Quellen (Apache-2.0 verlangt diesen Hinweis)

- Der Kopf der `SKILL.md` ist auf `name` und `description` verkürzt; andere Felder (zum Beispiel `argument-hint`, `metadata`) entfallen. In der `description` von `social` fehlen die Stichwörter zum Social Listening (die Dateien dazu sind nicht enthalten, siehe unten).
- Entfernt sind Ordner `evals/` und `scripts/`, Lizenzdateien (siehe oben), Binärdateien sowie der Verweis auf `CONNECTORS.md` in den Skills von knowledge-work-plugins.
- Entfernt sind außerdem Dateien mit Abruf-Anleitungen für fremde Dienste (`social/references/listening*.md`, `public-relations/references/newsjacking.md`) und der Leitfaden zu Headless-CMS in `content-strategy` samt den Verweisen darauf.
- Sonst sind die Texte unverändert. Platzhalter wie `~~Quelle` aus den Skills von Anthropic bleiben stehen; die KI fragt dann nach, was gemeint ist.

## Ausgewählt und ausgelassen

Aufgenommen ist, was ohne eigene Zugänge, Konten oder Programme auf dem Rechner funktioniert und nicht für ein bestimmtes Produkt wirbt. Nicht aufgenommen sind Skills, die Werbung für Dienste enthalten, an Dienste von Dritten gebunden sind (Verkauf, Werbekonten, Analysewerkzeuge), Dateien in Office-Formaten über eigene Programme erzeugen (diese stehen unter einer nicht freien Lizenz) oder keine Lizenz haben (`doc-coauthoring`; im Repository von Anthropic liegt dafür weiterhin keine Lizenzdatei, deshalb gibt es stattdessen das eigene, neu geschriebene `dokument-gemeinsam-schreiben`).

Die Zahlen zu Installationen sind öffentlichen Verzeichnissen entnommen (Stand November 2026) und werden nicht zur Laufzeit abgerufen, sondern monatlich per GitHub Action (`.github/workflows/installs.yml`) oder bei der Pflege des Katalogs nachgezogen (`installs_asof` in `catalog.json`); in der Oberfläche erscheinen sie aufgerundet. Ohne Zahl gab es keine verlässliche Angabe.

Neue Einträge kommen in `catalog.json`; `tests/test_skills.py` prüft, dass jeder Eintrag einen Ordner, eine Lizenz, eine Quelle und beide Sprachen hat.
