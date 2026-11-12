"""Chats teilen: Schnappschuss, in der Instanz lesen und kopieren, öffentlicher Link ohne Anmeldung."""
import dataclasses
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import parse_settings
from app.main import build_ingress_app, build_public_app
from conftest import ADM01, DORA, RAW, FakeBackend, as_user

BASE = "https://ai.test"
DORA_ID = "dora"  # Profilkennung (DORA ist die Kennung im Anmelde-Header)
H = as_user(DORA, True)
HA = as_user(ADM01, True)


def settings_for(sharing="public", **extra):
    raw = {**RAW, "sharing": sharing, "public_enabled": True, "public_base_url": BASE, **extra}
    return parse_settings(raw, frozenset({"testclient"}))


@pytest.fixture()
def apps(store):
    def make(sharing="public"):
        settings = settings_for(sharing)
        backend = FakeBackend(("Antwort ", "eins"))
        inner = TestClient(build_ingress_app(settings, store, backend))
        outer = TestClient(build_public_app(settings, store, backend, None), base_url=BASE)
        return inner, outer
    return make


def chat_with_text(client, headers=H, text="Frage eins"):
    chat = client.post("/api/chats", json={}, headers=headers).json()
    assert client.post(f"/api/chats/{chat['id']}/send", json={"content": text}, headers=headers).status_code == 200
    return chat


def share(client, chat, mode="public", headers=H, **body):
    return client.post(f"/api/chats/{chat['id']}/share", json={"mode": mode, **body}, headers=headers)


def token_of(url):
    return url.rsplit("/", 1)[1]


def test_instance_share_is_listed_for_others_and_readable(apps):
    inner, _ = apps("instance")
    chat = chat_with_text(inner)
    r = share(inner, chat, "instance")
    assert r.status_code == 200 and "url" not in r.json()
    assert inner.get("/api/shared", headers=as_user(DORA)).json() == []  # die eigene Freigabe steht nicht in der eigenen Liste
    listed = inner.get("/api/shared", headers=as_user(ADM01)).json()
    assert len(listed) == 1 and listed[0]["title"] and "messages" not in listed[0]
    got = inner.get(f"/api/shared/{listed[0]['id']}", headers=as_user(ADM01)).json()
    assert [m["role"] for m in got["messages"]] == ["user", "assistant"] and got["mine"] is False
    assert got["messages"][0]["content"] == "Frage eins"


def test_copy_makes_own_imported_chat(apps, store):
    inner, _ = apps("instance")
    chat = chat_with_text(inner)
    share(inner, chat, "instance")
    sid = inner.get("/api/shared", headers=as_user(ADM01)).json()[0]["id"]
    copy = inner.post(f"/api/shared/{sid}/copy", headers=HA)
    assert copy.status_code == 201
    new = copy.json()
    assert new["id"] != chat["id"] and new["imported"] is True
    msgs = inner.get(f"/api/chats/{new['id']}/messages", headers=as_user(ADM01)).json()
    assert [m["content"] for m in msgs][0] == "Frage eins"
    assert inner.get(f"/api/chats/{new['id']}/messages", headers=as_user(DORA)).status_code == 404  # gehört nur der kopierenden Person
    assert not any(c["id"] == new["id"] for c in inner.get("/api/chats", headers=as_user(DORA)).json())


def test_matrix_off_instance_public(apps):
    inner, outer = apps("off")
    chat = chat_with_text(inner)
    assert share(inner, chat, "instance").status_code == 404
    assert inner.get("/api/shared", headers=as_user(ADM01)).status_code == 404
    inner, outer = apps("instance")
    chat = chat_with_text(inner)
    assert share(inner, chat, "public").status_code == 403
    assert share(inner, chat, "instance").status_code == 200
    inner, outer = apps("public")
    chat = chat_with_text(inner)
    r = share(inner, chat, "public")
    assert r.status_code == 200 and r.json()["url"].startswith(f"{BASE}/s/")


def test_public_link_serves_without_login_and_hardened(apps):
    inner, outer = apps("public")
    chat = chat_with_text(inner)
    url = share(inner, chat, "public").json()["url"]
    token = token_of(url)
    assert len(token) == 43
    page = outer.get(f"/s/{token}")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    for resp in (page, outer.get(f"/s/{token}/data")):
        assert "noindex" in resp.headers["x-robots-tag"]
        assert resp.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in page.headers["content-security-policy"]
    data = outer.get(f"/s/{token}/data").json()
    assert set(data) == {"title", "taken_at", "expires_at", "messages"}
    assert [m["content"] for m in data["messages"]] == ["Frage eins", "Antwort eins"]
    assert data["expires_at"]  # Standard: 30 Tage
    assert "chat_id" not in str(data) and chat["id"] not in str(data)


@pytest.mark.parametrize("bad", ["kurz", "A" * 42, "A" * 44, "../" + "A" * 40, "A" * 43])
def test_public_link_wrong_token_404(apps, bad):
    _, outer = apps("public")
    assert outer.get(f"/s/{bad}").status_code == 404
    assert outer.get(f"/s/{bad}/data").status_code == 404


def test_public_link_revoke_expiry_and_switch_off(apps, store):
    inner, outer = apps("public")
    chat = chat_with_text(inner)
    token = token_of(share(inner, chat, "public").json()["url"])
    assert outer.get(f"/s/{token}/data").status_code == 200
    # abgelaufen
    with store._conn:
        store._conn.execute("UPDATE chat_shares SET expires_at = '2000-01-01T00:00:00+00:00'")
    assert outer.get(f"/s/{token}/data").status_code == 404
    assert store.share_get(DORA_ID, chat["id"], "public") is None  # beim Lesen aufgeräumt
    # neu anlegen, widerrufen
    token = token_of(share(inner, chat, "public").json()["url"])
    assert inner.delete(f"/api/chats/{chat['id']}/share/public", headers=H).status_code == 204
    assert outer.get(f"/s/{token}/data").status_code == 404
    assert inner.delete(f"/api/chats/{chat['id']}/share/public", headers=H).status_code == 404
    # Einstellung zurückgenommen: vorhandene Links wirken nicht mehr
    token = token_of(share(inner, chat, "public").json()["url"])
    _, outer_inst = apps("instance")
    assert outer_inst.get(f"/s/{token}/data").status_code == 404
    _, outer_off = apps("off")
    assert outer_off.get(f"/s/{token}").status_code == 404


def test_instance_share_is_not_reachable_through_public_link(apps, store):
    inner, outer = apps("public")
    chat = chat_with_text(inner)
    share(inner, chat, "instance")
    row = store.share_get(DORA_ID, chat["id"], "instance")
    assert outer.get(f"/s/{row['token']}/data").status_code == 404


def test_public_rate_limit(apps):
    _, outer = apps("public")
    codes = [outer.get("/s/" + "B" * 43 + "/data").status_code for _ in range(70)]
    assert codes[0] == 404 and 429 in codes


def test_snapshot_is_frozen_until_refresh(apps):
    inner, outer = apps("public")
    chat = chat_with_text(inner)
    token = token_of(share(inner, chat, "public").json()["url"])
    inner.post(f"/api/chats/{chat['id']}/send", json={"content": "Spätere Frage"}, headers=H)
    assert len(outer.get(f"/s/{token}/data").json()["messages"]) == 2
    r = inner.post(f"/api/chats/{chat['id']}/share/refresh", json={"mode": "public"}, headers=H)
    assert r.status_code == 200 and r.json()["url"].endswith(token)  # gleicher Link
    assert len(outer.get(f"/s/{token}/data").json()["messages"]) == 4


def test_expiry_choice_and_keep_on_refresh(apps, store):
    inner, _ = apps("public")
    chat = chat_with_text(inner)
    assert share(inner, chat, "public", expires_days=0).json()["expires_at"] is None
    inner.post(f"/api/chats/{chat['id']}/share/refresh", json={"mode": "public"}, headers=H)
    assert store.share_get(DORA_ID, chat["id"], "public")["expires_at"] is None
    assert share(inner, chat, "public", expires_days=7).json()["expires_at"]
    assert share(inner, chat, "public", expires_days=5).status_code == 422


def test_not_shareable_incognito_voice_empty_foreign(apps):
    inner, _ = apps("public")
    incog = inner.post("/api/chats", json={"incognito": True}, headers=H).json()
    inner.post(f"/api/chats/{incog['id']}/send", json={"content": "geheim"}, headers=H)
    assert share(inner, incog, "instance").status_code == 409
    empty = inner.post("/api/chats", json={}, headers=H).json()
    assert share(inner, empty, "instance").status_code == 422
    chat = chat_with_text(inner)
    assert share(inner, chat, "instance", headers=HA).status_code == 404  # fremder Chat
    assert inner.delete(f"/api/chats/{chat['id']}/share/instance", headers=HA).status_code == 404


def test_without_write_header_refused(apps):
    inner, _ = apps("public")
    chat = chat_with_text(inner)
    assert inner.post(f"/api/chats/{chat['id']}/share", json={"mode": "public"}, headers=as_user(DORA)).status_code in (400, 403)


def test_snapshot_has_no_tools_or_attachments(store):
    chat = store.create_chat(DORA_ID, "T")
    store.add_message(DORA_ID, chat["id"], "user", "Hallo")
    msg = store.add_message(DORA_ID, chat["id"], "assistant", "Hi", tools=[{"label": "Gedächtnis: Geheim", "kind": "memory", "action": "x"}])
    title, messages = store.share_snapshot(DORA_ID, chat["id"])
    assert title == "T" and all(set(m) == {"role", "content", "at"} for m in messages)
    assert "Geheim" not in str(messages)


def test_deleting_chat_removes_shares(apps, store):
    inner, outer = apps("public")
    chat = chat_with_text(inner)
    token = token_of(share(inner, chat, "public").json()["url"])
    assert inner.delete(f"/api/chats/{chat['id']}", headers=H).status_code in (200, 204)
    assert outer.get(f"/s/{token}/data").status_code == 404
    assert store._conn.execute("SELECT COUNT(*) FROM chat_shares").fetchone()[0] == 0


def test_sweep_removes_expired_only(apps, store):
    inner, _ = apps("public")
    a, b = chat_with_text(inner), chat_with_text(inner, text="zwei")
    share(inner, a, "public", expires_days=7)
    share(inner, b, "public", expires_days=0)
    with store._conn:
        store._conn.execute("UPDATE chat_shares SET expires_at = '2000-01-01T00:00:00+00:00' WHERE chat_id = ?", (a["id"],))
    assert store.share_sweep() == 1
    assert store.share_get(DORA_ID, b["id"], "public") is not None


def test_me_reports_sharing(apps):
    inner, _ = apps("public")
    me = inner.get("/api/me", headers=as_user(DORA)).json()
    assert me["sharing"] == "public" and me["sharing_public"] is True
    inner, _ = apps("off")
    assert inner.get("/api/me", headers=as_user(DORA)).json()["sharing"] == "off"
