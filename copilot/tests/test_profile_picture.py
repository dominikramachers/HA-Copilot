"""Profilbild aus Home Assistant: nur der Bilderpfad von HA wird geholt, ohne Bild 404."""
import asyncio

import httpx
from fastapi.testclient import TestClient

import app.ha_client as hac
from app.ha_client import HaApi
from app.main import build_ingress_app
from conftest import ADM01, DORA, FakeBackend, as_user
from test_schedules import RecordingHa, SETTINGS

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20


class PictureHa(RecordingHa):
    def __init__(self, picture):
        super().__init__()
        self.picture = picture

    async def person_picture(self, user_id):
        return (PNG, "image/png") if self.picture and user_id == ADM01 else None


def client(store, picture=True):
    return TestClient(build_ingress_app(SETTINGS, store, FakeBackend(("a",)), ha=PictureHa(picture)))


def test_picture_is_served_to_its_own_person(store):
    c = client(store)
    assert c.get("/api/me", headers=as_user(ADM01)).json()["picture"] is True
    r = c.get("/api/me/picture", headers=as_user(ADM01))
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"


def test_no_picture_gives_404_so_the_letter_stays(store):
    c = client(store)
    assert c.get("/api/me/picture", headers=as_user(DORA)).status_code == 404
    assert client(store, picture=False).get("/api/me/picture", headers=as_user(ADM01)).status_code == 404


class FakeApi(HaApi):
    def __init__(self, picture):
        super().__init__("tok", "ws://x", rest_url="http://core/api")
        self._picture = picture

    async def call(self, command, timeout=None):
        return {"storage": [{"user_id": ADM01.upper(), "picture": self._picture}], "config": []}


def fetch(picture, monkeypatch, status=200, media="image/png"):
    seen = []

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            seen.append((url, headers))
            return httpx.Response(status, content=PNG, headers={"content-type": media})

    monkeypatch.setattr(hac.httpx, "AsyncClient", Client)
    return asyncio.run(FakeApi(picture).person_picture(ADM01)), seen


def test_only_the_image_path_of_home_assistant_is_fetched(monkeypatch):
    got, seen = fetch("/api/image/serve/abc/512x512", monkeypatch)
    assert got == (PNG, "image/png")
    assert seen[0][0] == "http://core/api/image/serve/abc/512x512" and seen[0][1]["Authorization"] == "Bearer tok"
    for bad in ("http://evil.example/x.png", "/api/config", "/api/image/serve/../states", "/api/image/serve/a?b=1", ""):
        assert fetch(bad, monkeypatch)[0] is None and fetch(bad, monkeypatch)[1] == []


def test_non_image_answers_are_ignored(monkeypatch):
    assert fetch("/api/image/serve/abc/512x512", monkeypatch, media="text/html")[0] is None
    assert fetch("/api/image/serve/abc/512x512", monkeypatch, status=404)[0] is None
