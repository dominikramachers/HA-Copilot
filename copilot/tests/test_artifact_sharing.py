"""Artefakte teilen: nur der Text, nur lesen; in der Instanz mit Link, öffentlich ohne Anmeldung."""
import pytest
from fastapi.testclient import TestClient

from app.main import build_ingress_app, build_public_app
from conftest import ADM01, DORA, FakeBackend, as_user
from test_sharing import BASE, settings_for

H = as_user(DORA, True)
HA = as_user(ADM01, True)
OWNER = "dora"
HTML = "<h1>Hallo</h1><script>alert(1)</script>"


@pytest.fixture()
def apps(store):
    def make(sharing="public"):
        settings = settings_for(sharing)
        backend = FakeBackend(("Antwort ", "eins"))
        return TestClient(build_ingress_app(settings, store, backend)), TestClient(build_public_app(settings, store, backend, None), base_url=BASE)
    return make


@pytest.fixture()
def art(store):
    project = store.create_project(OWNER, "Haus")["id"]
    chat = store.create_chat(OWNER, "Lichtplan", project)["id"]
    made = store.artifact_create(OWNER, chat, "html", "", "Seite", HTML)
    return {"id": made["id"], "chat": chat, "project": project}


def share(client, art, mode="public", headers=H, **body):
    return client.post(f"/api/artifacts/{art['id']}/share", json={"mode": mode, **body}, headers=headers)


def test_instance_share_needs_the_link(apps, art, store):
    inner, _ = apps("instance")
    view = share(inner, art, "instance").json()
    assert len(view["token"]) == 43 and view["viewers"] == [] and view["expires_at"] is None and view["version"] == 1
    # ohne Link sieht niemand etwas
    assert inner.get("/api/shared-artifacts", headers=as_user(ADM01)).json() == []
    sid = inner.get(f"/api/artifacts/{art['id']}/share", headers=H).json()["instance"]  # Kennung der Freigabe steht nicht in der Antwort
    assert "id" not in sid
    first = inner.post("/api/shared/open", json={"token": "A" * 43}, headers=HA)
    assert first.status_code == 404
    known = store.artifact_share_read(token=view["token"])["id"]
    assert inner.get(f"/api/shared-artifacts/{known}", headers=as_user(ADM01)).status_code == 404  # Kennung allein genügt nicht
    opened = inner.post("/api/shared/open", json={"token": view["url"] or view["token"]}, headers=HA)
    assert opened.status_code == 200 and opened.json()["kind"] == "artifact" and opened.json()["mine"] is False
    sid = opened.json()["id"]
    listed = inner.get("/api/shared-artifacts", headers=as_user(ADM01)).json()
    assert [r["id"] for r in listed] == [sid] and listed[0]["title"] == "Seite" and "content" not in listed[0]
    got = inner.get(f"/api/shared-artifacts/{sid}", headers=as_user(ADM01)).json()
    assert got["content"] == HTML and got["kind"] == "html" and got["filename"] == "Seite.html"
    # der Besitzer sieht, wer es geöffnet hat
    me = inner.get(f"/api/artifacts/{art['id']}/share", headers=H).json()["instance"]
    assert len(me["viewers"]) == 1 and me["viewers"][0]["opens"] == 1


def test_opening_my_own_link_does_not_count(apps, art):
    inner, _ = apps("instance")
    view = share(inner, art, "instance").json()
    opened = inner.post("/api/shared/open", json={"token": view["token"]}, headers=H).json()
    assert opened["mine"] is True and opened["kind"] == "artifact"
    assert inner.get("/api/shared-artifacts", headers=H).json() == []


def test_chat_links_still_open_chats(apps):
    inner, _ = apps("instance")
    chat = inner.post("/api/chats", json={}, headers=H).json()
    inner.post(f"/api/chats/{chat['id']}/send", json={"content": "Hi"}, headers=H)
    view = inner.post(f"/api/chats/{chat['id']}/share", json={"mode": "instance"}, headers=H).json()
    opened = inner.post("/api/shared/open", json={"token": view["token"]}, headers=HA).json()
    assert "kind" not in opened and inner.get("/api/shared-artifacts", headers=as_user(ADM01)).json() == []


def test_remove_from_my_list_and_link_brings_it_back(apps, art):
    inner, _ = apps("instance")
    view = share(inner, art, "instance").json()
    sid = inner.post("/api/shared/open", json={"token": view["token"]}, headers=HA).json()["id"]
    assert inner.delete(f"/api/shared-artifacts/{sid}", headers=HA).status_code == 204
    assert inner.get(f"/api/shared-artifacts/{sid}", headers=as_user(ADM01)).status_code == 404
    assert inner.delete(f"/api/shared-artifacts/{sid}", headers=HA).status_code == 404
    inner.post("/api/shared/open", json={"token": view["token"]}, headers=HA)
    assert inner.get(f"/api/shared-artifacts/{sid}", headers=as_user(ADM01)).status_code == 200


def test_snapshot_is_frozen_until_refresh(apps, art, store):
    inner, outer = apps("public")
    token = share(inner, art, "public").json()["url"].rsplit("/", 1)[1]
    store.artifact_update(OWNER, art["id"], "<p>neu</p>")
    assert outer.get(f"/s/{token}/data").json()["artifact"]["content"] == HTML
    r = inner.post(f"/api/artifacts/{art['id']}/share/refresh", json={"mode": "public"}, headers=H)
    assert r.status_code == 200 and r.json()["url"].endswith(token) and r.json()["version"] == 2
    assert outer.get(f"/s/{token}/data").json()["artifact"]["content"] == "<p>neu</p>"


def test_public_link_serves_only_text_and_hardened(apps, art):
    inner, outer = apps("public")
    view = share(inner, art, "public").json()
    token = view["url"].rsplit("/", 1)[1]
    assert view["url"] == f"{BASE}/s/{token}" and view["expires_at"]  # Standard: 30 Tage
    page = outer.get(f"/s/{token}")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"] and page.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in page.headers["content-security-policy"] and "<script>alert" not in page.text
    data = outer.get(f"/s/{token}/data")
    assert "noindex" in data.headers["x-robots-tag"] and data.headers["cache-control"] == "no-store" and data.headers["content-type"].startswith("application/json")
    body = data.json()
    assert set(body) == {"title", "taken_at", "expires_at", "artifact"}
    assert body["artifact"] == {"kind": "html", "language": "", "content": HTML, "version": 1}
    assert art["id"] not in str(body) and art["chat"] not in str(body)
    assert inner.get(f"/api/artifacts/{art['id']}/share", headers=H).json()["public"]["opens"] == 1


def test_public_link_ends_on_revoke_expiry_and_deleting(apps, art, store):
    inner, outer = apps("public")
    token = share(inner, art, "public").json()["url"].rsplit("/", 1)[1]
    assert inner.delete(f"/api/artifacts/{art['id']}/share/public", headers=H).status_code == 204
    assert outer.get(f"/s/{token}/data").status_code == 404
    assert inner.delete(f"/api/artifacts/{art['id']}/share/public", headers=H).status_code == 404
    token = share(inner, art, "public").json()["url"].rsplit("/", 1)[1]
    with store._conn:
        store._conn.execute("UPDATE artifact_shares SET expires_at = '2000-01-01T00:00:00+00:00'")
    assert outer.get(f"/s/{token}/data").status_code == 404
    token = share(inner, art, "public", expires_days=0).json()["url"].rsplit("/", 1)[1]
    assert inner.delete(f"/api/artifacts/{art['id']}", headers=H).status_code == 204  # Artefakt gelöscht: Link tot
    assert outer.get(f"/s/{token}/data").status_code == 404
    assert store._conn.execute("SELECT COUNT(*) FROM artifact_shares").fetchone()[0] == 0


def test_deleting_the_chat_removes_the_share(apps, art, store):
    inner, outer = apps("public")
    token = share(inner, art, "public").json()["url"].rsplit("/", 1)[1]
    assert inner.delete(f"/api/chats/{art['chat']}", headers=H).status_code in (200, 204)
    assert outer.get(f"/s/{token}/data").status_code == 404


def test_instance_link_is_not_public_and_setting_off_stops_it(apps, art):
    inner, outer = apps("public")
    share(inner, art, "instance")
    inst = inner.get(f"/api/artifacts/{art['id']}/share", headers=H).json()["instance"]
    assert outer.get(f"/s/{inst['token']}/data").status_code == 404
    token = share(inner, art, "public").json()["url"].rsplit("/", 1)[1]
    _, outer_off = apps("off")
    assert outer_off.get(f"/s/{token}").status_code == 404
    assert outer_off.get(f"/s/{token}/data").status_code == 404


def test_matrix_and_rights(apps, art):
    inner, _ = apps("instance")
    assert share(inner, art, "public").status_code == 403  # nicht freigeschaltet
    assert share(inner, art, "instance", headers=as_user(ADM01, True)).status_code == 404  # fremdes Artefakt
    assert inner.post(f"/api/artifacts/{art['id']}/share", json={"mode": "instance"}, headers=as_user(DORA)).status_code == 403  # ohne Schreibkopf
    assert inner.get(f"/api/artifacts/{art['id']}/share", headers=as_user(ADM01)).status_code == 404
    off, _ = apps("off")
    assert share(off, art, "instance").status_code == 404
    assert off.get(f"/api/artifacts/{art['id']}/share", headers=H).status_code == 404


def test_expiry_choice_survives_refresh(apps, art):
    inner, _ = apps("public")
    assert share(inner, art, "public", expires_days=7).json()["expires_at"]
    kept = inner.post(f"/api/artifacts/{art['id']}/share/refresh", json={"mode": "public"}, headers=H).json()
    assert kept["expires_at"]
    assert share(inner, art, "public", expires_days=0).json()["expires_at"] is None


def test_list_marks_shared_artifacts_with_project_hint(apps, art, store):
    inner, _ = apps("public")
    other = store.create_chat(OWNER, "Anderes", None)["id"]
    store.artifact_create(OWNER, other, "markdown", "", "Notiz", "x")
    assert [a["shared"] for a in inner.get("/api/artifacts", headers=H).json()] == [[], []]
    share(inner, art, "instance")
    share(inner, art, "public")
    only = inner.get("/api/artifacts?shared=true", headers=H).json()
    assert len(only) == 1 and only[0]["id"] == art["id"] and only[0]["shared"] == ["instance", "public"]
    assert only[0]["project_id"] == art["project"] and only[0]["chat_title"] == "Lichtplan" and "content" not in only[0]
    assert inner.get("/api/artifacts", headers=as_user(ADM01)).json() == []


def test_sweep_removes_expired_artifact_shares(apps, art, store):
    inner, _ = apps("public")
    share(inner, art, "public", expires_days=7)
    with store._conn:
        store._conn.execute("UPDATE artifact_shares SET expires_at = '2000-01-01T00:00:00+00:00'")
    assert store.share_sweep() == 1
    assert store.artifact_share_get(OWNER, art["id"], "public") is None
