"""Modus „Auto“: Modell je nach Anspruch der Nachricht (0.67.0)."""

from app import autoroute as ar
from app.autoroute import LIGHT, NORMAL, STRONG

TIERS = ar.Tiers.from_choices("claude-sonnet-5-5", ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "gpt-5.6-sol"])


def test_tiers_from_choices_and_fallback():
    assert TIERS == ar.Tiers("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5")
    only = ar.Tiers.from_choices("claude-sonnet-5-5", ["claude-sonnet-5-5", "gpt-5.6-terra"])
    assert only.model(LIGHT) == only.model(STRONG) == "claude-sonnet-5-5"  # fehlt ein Modell, gilt das normale; nie OpenAI


def test_light_requests():
    for text in ("Hallo", "Danke!", "Schalte das Licht im Wohnzimmer an", "Wie warm ist es im Bad?", "Mach die Vitrine aus", "Wie spät ist es?"):
        assert ar.level_for(text) == LIGHT, text


def test_normal_requests():
    assert ar.level_for("Erstelle eine Automation, die abends um 22 Uhr alle Lichter im Erdgeschoss ausschaltet") == NORMAL
    assert ar.level_for("Was ist der Unterschied zwischen Zigbee und Thread, und was passt besser zu meinem Haushalt?") == NORMAL
    assert ar.level_for("Hallo", attachments=[{"name": "foto.jpg", "mime": "image/jpeg"}]) == NORMAL  # Anhang: nie leicht
    assert ar.level_for("Schreibe ein kurzes Python-Skript") == NORMAL


def test_strong_requests():
    assert ar.level_for("x", research=True) == STRONG
    assert ar.level_for("Hallo", effort="high") == STRONG
    assert ar.level_for("Analysiere bitte die Firewall-Regeln und schlage eine bessere Struktur der Zonen vor") == STRONG
    assert ar.level_for("Bitte prüfen: " + "a " * 800) == STRONG  # lange Nachricht
    code = "```python\n" + "\n".join(f"x{i} = {i}" for i in range(45)) + "\n```\nWarum ist das langsam?"
    assert ar.level_for(code) == STRONG
    docs = [{"name": "a.pdf", "mime": "application/pdf"}, {"name": "b.xlsx", "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}]
    assert ar.level_for("Vergleiche", attachments=docs) == STRONG
    assert ar.level_for("Review", attachments=[]) == NORMAL  # ein einzelnes Wort ist noch keine schwere Aufgabe, aber auch nicht leicht


def test_low_effort_allows_light_for_short_questions():
    assert ar.level_for("Wer war der erste Bundeskanzler der Bundesrepublik?", effort="low") == LIGHT


def test_follow_ups_keep_the_level_of_the_chat():
    assert ar.level_for("Ja, mach das so", in_chat=True, previous=STRONG) == STRONG
    assert ar.level_for("Ja, mach das so", in_chat=True, previous=None) == LIGHT
    assert ar.level_for("Ja", in_chat=True, previous=NORMAL) == NORMAL
    # Lange neue Aufgaben im selben Chat werden neu bewertet
    assert ar.level_for("Schreibe " + "eine längere Beschreibung " * 15, in_chat=True, previous=STRONG) == NORMAL
    # Mit Anhang wird ebenfalls neu bewertet
    assert ar.level_for("Und das hier?", attachments=[{"name": "x.png", "mime": "image/png"}], in_chat=True, previous=STRONG) == NORMAL


def test_memory_is_bounded():
    mem = ar.AutoMemory(limit=2)
    mem.set(("a", "1"), LIGHT)
    mem.set(("a", "2"), NORMAL)
    mem.set(("a", "3"), STRONG)
    assert mem.get(("a", "1")) is None and mem.get(("a", "3")) == (STRONG, "claude")
    mem.forget(("a", "3"))
    assert mem.get(("a", "3")) is None


def test_pasted_text_counts_as_message_and_kinds_count_as_documents():
    pasted = {"name": "Eingefügt", "kind": "text", "pasted": True, "text": "Zeile\n" * 400}
    assert ar.level_for("Schau mal", attachments=[pasted]) == STRONG
    assert ar.level_for("Was steht drin?", attachments=[{"name": "x", "kind": "pdf"}, {"name": "y", "kind": "word"}]) == STRONG
