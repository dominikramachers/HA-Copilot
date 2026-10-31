from conftest import ADM01, DORA, SAM, as_user


def test_each_profile_sees_only_own_chats(client):
    created = client.post("/api/chats", json={"title": "Admin-Chat"}, headers=as_user(ADM01, True))
    assert created.status_code == 201
    chat_id = created.json()["id"]

    own = client.get("/api/chats", headers=as_user(ADM01)).json()
    other = client.get("/api/chats", headers=as_user(DORA)).json()
    assert [c["title"] for c in own] == ["Admin-Chat"]
    assert other == []

    # Die Chat-ID zu erraten oder zu kennen reicht nicht.
    assert client.get(f"/api/chats/{chat_id}/messages", headers=as_user(DORA)).status_code == 404
    assert (
        client.patch(
            f"/api/chats/{chat_id}", json={"title": "x"}, headers=as_user(DORA, True)
        ).status_code
        == 404
    )
    assert client.delete(f"/api/chats/{chat_id}", headers=as_user(DORA, True)).status_code == 404
    assert client.get(f"/api/chats/{chat_id}/messages", headers=as_user(ADM01)).status_code == 200


def test_rename_and_delete_flow(client):
    headers = as_user(DORA, True)
    chat_id = client.post("/api/chats", json={}, headers=headers).json()["id"]
    renamed = client.patch(f"/api/chats/{chat_id}", json={"title": "Heizung"}, headers=headers)
    assert renamed.status_code == 200 and renamed.json()["title"] == "Heizung"
    assert client.delete(f"/api/chats/{chat_id}", headers=headers).status_code == 204
    assert client.get("/api/chats", headers=as_user(DORA)).json() == []


def test_me_returns_profile_label(client):
    me = client.get("/api/me", headers=as_user(ADM01)).json()
    assert me["id"] == "adm01" and me["label"] == "Admin"
    assert me["default_effort"] == "medium" and me["test_mode"] is True
    assert client.get("/api/me", headers=as_user(DORA.upper())).json()["id"] == "dora"


def test_unknown_ha_user_is_denied(client):
    assert client.get("/api/chats", headers=as_user(SAM)).status_code == 403
    assert client.get("/api/me", headers=as_user(SAM)).status_code == 403
    page = client.get("/", headers=as_user(SAM))
    assert page.status_code == 403 and "Kein Zugriff" in page.text


def test_missing_or_empty_user_header_is_denied(client):
    assert client.get("/api/chats").status_code == 403
    assert client.get("/api/chats", headers={"X-Remote-User-Id": ""}).status_code == 403


def test_headers_from_untrusted_peer_are_ignored(client_untrusted_peer):
    # Gegenstelle ist nicht der Ingress-Proxy: ein gefälschter Header darf nichts bewirken.
    response = client_untrusted_peer.get("/api/chats", headers=as_user(ADM01))
    assert response.status_code == 403
    assert client_untrusted_peer.get("/", headers=as_user(ADM01)).status_code == 403


def test_forwarded_for_does_not_grant_trust(client_untrusted_peer):
    headers = {**as_user(ADM01), "X-Forwarded-For": "172.30.32.2"}
    assert client_untrusted_peer.get("/api/chats", headers=headers).status_code == 403


def test_writes_require_custom_header(client):
    assert client.post("/api/chats", json={}, headers=as_user(ADM01)).status_code == 403
    chat_id = client.post("/api/chats", json={}, headers=as_user(ADM01, True)).json()["id"]
    assert client.delete(f"/api/chats/{chat_id}", headers=as_user(ADM01)).status_code == 403
    assert client.get("/api/chats", headers=as_user(ADM01)).json()[0]["id"] == chat_id


def test_title_validation(client):
    headers = as_user(ADM01, True)
    chat_id = client.post("/api/chats", json={}, headers=headers).json()["id"]
    assert client.patch(f"/api/chats/{chat_id}", json={"title": ""}, headers=headers).status_code == 422
    assert (
        client.patch(f"/api/chats/{chat_id}", json={"title": "x" * 500}, headers=headers).status_code
        == 422
    )


def test_security_headers_and_index(client):
    page = client.get("/", headers=as_user(DORA))
    assert page.status_code == 200 and "HA Copilot" in page.text
    assert page.headers["x-content-type-options"] == "nosniff"
    api = client.get("/api/chats", headers=as_user(DORA))
    assert api.headers["cache-control"] == "no-store"


def test_double_slash_paths_from_ingress_are_served(client):
    # Der HA-Ingress ruft das Add-on real mit "//" statt "/" auf (Log: GET // HTTP/1.1).
    page = client.get("http://testserver//", headers=as_user(DORA))
    assert page.status_code == 200 and "HA Copilot" in page.text
    assert client.get("http://testserver//static/app.js").status_code == 200
    chats = client.get("http://testserver//api/chats", headers=as_user(DORA))
    assert chats.status_code == 200
    assert chats.headers["cache-control"] == "no-store"
    # Die Zugriffsprüfung gilt unverändert auch für diese Pfadform.
    assert client.get("http://testserver//api/chats", headers=as_user(SAM)).status_code == 403
    assert client.get("http://testserver//", headers=as_user(SAM)).status_code == 403


def test_login_page_preview_requires_access(client):
    assert client.get("/login", headers=as_user(SAM)).status_code == 403
    page = client.get("/login", headers=as_user(DORA))
    assert page.status_code == 200 and "E-Mail-Adresse" in page.text and "__V__" not in page.text
    assert client.get("/static/login.css").status_code == 200
    # Animierter Hintergrund: Canvas im Markup, Skript als eigene Datei (die CSP erlaubt nur Skripte der eigenen Herkunft).
    assert '<canvas id="particles"' in page.text and "static/login-bg.js" in page.text
    script = client.get("/static/login-bg.js")
    assert script.status_code == 200 and "prefers-reduced-motion" in script.text and "visibilitychange" in script.text
    font = client.get("/static/fonts/roboto-latin-wght.woff2")
    assert font.status_code == 200 and font.content[:4] == b"wOF2"


def test_page_has_dock_above_input_and_shortcut_hints(client):
    page = client.get("/", headers=as_user(DORA)).text
    # Nutzungslimit und Rückfragen stehen im Dock vor dem Eingabefeld
    assert page.index('id="dock"') < page.index('id="limit-notices"') < page.index('id="dock-asks"') < page.index('class="composer-box"')
    # Kürzel: Neuer Chat, Suchen, Geplant haben je einen Buchstaben (Anzeige nur beim Hover, per CSS)
    for letter in ("O", "F", "G"):
        assert f'class="nav-key" data-key="{letter}"' in page
    script = client.get("/static/app.js").text
    assert "KeyP" in script and "Strg+Umschalt+{0}" in script
    assert ".nav-item:hover .nav-key" in client.get("/static/style.css").text
    # Eingabe wie in Claude: im Feld nur Text und Senden, Anhängen sowie Modell/Aufwand in der Fußzeile darunter
    box = page[page.index('class="composer-box"'):page.index('class="composer-foot"')]
    foot = page[page.index('class="composer-foot"'):]
    assert 'id="send"' in box and 'id="attach"' not in box and 'id="effort"' not in page
    assert 'id="attach"' in foot and 'id="tools"' in foot and 'id="tools-effort"' in foot


def test_page_knows_it_is_embedded_in_ha(client):
    page = client.get("/", headers=as_user(DORA))
    assert 'data-embed="ha"' in page.text and "__EMBED__" not in page.text


def test_logo_and_favicon_are_served(client):
    for url in ("/favicon.ico", "/branding/icon", "/branding/logo", "/branding/logo-full"):
        response = client.get(url)
        assert response.status_code == 200 and response.content[:4] == b"\x89PNG", url
    page = client.get("/", headers=as_user(DORA))
    assert 'href="branding/icon"' in page.text and 'src="branding/logo"' in page.text


def test_assets_are_versioned_and_revalidated(client):
    page = client.get("/", headers=as_user(DORA))
    assert "__V__" not in page.text and "static/style.css?v=" in page.text
    assert page.headers["cache-control"] == "no-store"
    css = client.get("/static/style.css")
    assert css.status_code == 200 and css.headers["cache-control"] == "no-cache"
