"""Einführung beim ersten Anmelden und „Das ist neu“ nach einem Update: je Person, einmalig, ohne Technik."""
import asyncio
import json
import re
from pathlib import Path

import pytest
import yaml

from app import i18n, news
from test_background_run import asgi, make
from conftest import ADM01, DORA, FakeBackend

APP = Path(__file__).resolve().parent.parent / "app"
CONFIG = yaml.safe_load((APP.parent / "config.yaml").read_text(encoding="utf-8"))


def _get(app, path, user=ADM01):
    out = asyncio.run(asgi(app, "GET", path, user=user))
    return out["status"], json.loads(out["body"] or b"null")


def _post(app, path, body, user=ADM01):
    out = asyncio.run(asgi(app, "POST", path, body, user=user))
    return out["status"]


def _welcome(app, user=ADM01):
    return _get(app, "/api/me", user)[1]["welcome"]


def test_new_person_sees_the_intro_first_and_no_news(store):
    app = make(store, FakeBackend())
    assert _welcome(app) == {"intro": True, "news": []}


def test_okay_on_the_intro_is_remembered_and_only_for_that_person(store):
    app = make(store, FakeBackend())
    assert _post(app, "/api/welcome/seen", {"what": "intro"}) == 204
    assert _welcome(app) == {"intro": False, "news": []}
    assert _welcome(app, DORA)["intro"] is True  # die andere Person hat noch nichts bestätigt


def test_news_appear_once_after_an_update(store):
    app = make(store, FakeBackend())
    store.state_set("intro:adm01", "1")
    store.state_set("news:adm01", "0.31.0")
    shown = _welcome(app)
    assert shown["intro"] is False and [i["title"] for i in shown["news"]][:1] == ["Kurzanleitung zum Start"] and "Auf einen Satz antworten" in [i["title"] for i in shown["news"]]
    assert _post(app, "/api/welcome/seen", {"what": "news"}) == 204
    assert _welcome(app) == {"intro": False, "news": []}


def test_confirming_the_intro_also_marks_current_news_as_seen(store):
    app = make(store, FakeBackend())
    _post(app, "/api/welcome/seen", {"what": "intro"})
    assert store.state_get("news:adm01") == news.latest()


def test_a_later_release_without_user_news_shows_nothing(store):
    store.state_set("intro:adm01", "1")
    store.state_set("news:adm01", news.latest())
    assert news.Welcome(store).state("adm01") == {"intro": False, "news": []}


def test_unknown_answer_and_missing_header_are_refused(store):
    app = make(store, FakeBackend())
    assert _post(app, "/api/welcome/seen", {"what": "alles"}) == 422
    out = asyncio.run(asgi(app, "POST", "/api/welcome/seen", {"what": "intro"}, user="0" * 32))
    assert out["status"] in (401, 403)


def test_history_lists_all_releases_newest_first(store):
    status, history = _get(make(store, FakeBackend()), "/api/news")
    assert status == 200
    versions = [h["version"] for h in history]
    assert versions == sorted(versions, key=news._version_key, reverse=True) and versions[0] == news.latest()
    assert all(h["items"] for h in history)


def test_unseen_is_limited_and_newest_first():
    items = news.unseen("0.0.1")
    assert 0 < len(items) <= news.MAX_ITEMS
    assert items[0] == news.unseen(None)[0]


def test_english_texts_follow_the_language(store):
    i18n.set_language("en")
    assert news.unseen(None)[0]["title"] == news.releases()[0]["items"][0]["en"]["title"]


# ---------------------------------------------------------------- Pflege von news.json

RELEASES = json.loads((APP / "news.json").read_text(encoding="utf-8"))
TECHNICAL = re.compile(r"\b(API|SQL|SQLite|Docker|Endpunkt|Schema|Option|Konfiguration|Add-on|Token|Python|JSON|Parameter|Dockerfile)\b", re.I)


def test_news_file_is_well_formed_and_not_ahead_of_the_add_on():
    current = news._version_key(CONFIG["version"])
    versions = [r["version"] for r in RELEASES]
    assert len(set(versions)) == len(versions)
    assert all(news._version_key(v) <= current for v in versions)
    for release in RELEASES:
        assert release["items"], release["version"]
        for item in release["items"]:
            for lang in ("de", "en"):
                assert item[lang]["title"].strip() and item[lang]["text"].strip(), (release["version"], lang)
                assert len(item[lang]["title"]) <= 40 and len(item[lang]["text"]) <= 220


def test_news_texts_are_free_of_technical_terms_and_german_free_in_english():
    for release in RELEASES:
        for item in release["items"]:
            for lang in ("de", "en"):
                for field in ("title", "text"):
                    assert not TECHNICAL.search(item[lang][field]), item[lang][field]
            assert not re.search(r"[äöüÄÖÜß]", item["en"]["title"] + item["en"]["text"])


@pytest.mark.parametrize("path", ["app.js"])
def test_menu_and_popup_are_wired_in_the_browser_code(path):
    js = (APP / "static" / path).read_text(encoding="utf-8")
    for needle in ("api/welcome/seen", "showWelcome", "openIntro", "openNewsHistory", 'value: "guide"', 'value: "news"'):
        assert needle in js
