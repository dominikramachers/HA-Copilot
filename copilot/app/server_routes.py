"""Schnittstelle der Seite „Server“ (Übersicht, Aktivität, Hinzufügen).

Zugriff hat, wer ``server_access: on`` hat, ein Administrator der App ist (ohne ausdrückliches ``off``) oder den Standard
``servers.access_default: on`` geerbt hat. Es gibt nur ganz oder gar nicht: wer Zugriff hat, sieht und verwaltet alle Server,
wer ihn nicht hat, sieht die Seite gar nicht (403). Die Prüfung steckt in der Abhängigkeit ``server_profile`` (``main.py``).
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import _HUB_ADDRESS_RE, Profile, Settings
from .i18n import tr
from .server_script import hub_with_port, render_script
from .servers import HUB_PORT, KEY_MAX_HOURS, KEY_MAX_USES, ServerError, ServerHub


class ScriptBody(BaseModel):
    hub: str = Field(default="", max_length=260)
    name: str = Field(default="", max_length=60)
    hours: int = Field(default=24, ge=1, le=KEY_MAX_HOURS)
    max_uses: int = Field(default=1, ge=1, le=KEY_MAX_USES)
    changes: bool = True  # lokale Richtlinie des neuen Servers: Änderungen nach Freigabe erlauben (sonst nur lesen)


class RenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)


def register_server_routes(
    app: FastAPI, settings: Settings, hub: ServerHub, current_profile: Callable[..., Profile], write_guard: Callable[..., None],
) -> None:
    # current_profile ist hier die Abhängigkeit, die zusätzlich den Zugriff auf Server prüft (403 ohne Freigabe)
    def fail(exc: ServerError) -> HTTPException:
        return HTTPException(status_code=exc.status, detail=str(exc))

    def actor(profile: Profile) -> str:
        return profile.label or profile.id

    @app.get("/api/servers")
    def servers_overview(profile: Profile = Depends(current_profile)) -> dict:
        return {
            "servers": hub.listing(),
            "summary": hub.summary(),
            "hub": {
                "port": HUB_PORT, "address": settings.server_hub_address, "fingerprint": hub.pki.ca_fingerprint if hub.pki.dir.exists() else "",
                "agents": sorted(hub.agent_binaries()),
            },
            "keys": hub.repo.key_list(),
        }

    @app.patch("/api/servers/{server_id}", dependencies=[Depends(write_guard)])
    def servers_rename(server_id: str, body: RenameBody, profile: Profile = Depends(current_profile)) -> dict:
        try:
            hub.rename(server_id, body.name)
        except ServerError as exc:
            raise fail(exc) from None
        return {"ok": True}

    @app.post("/api/servers/{server_id}/confirm", dependencies=[Depends(write_guard)])
    def servers_confirm(server_id: str, profile: Profile = Depends(current_profile)) -> dict:
        try:
            return hub.view(hub.confirm(server_id, actor(profile)))
        except ServerError as exc:
            raise fail(exc) from None

    @app.post("/api/servers/{server_id}/block", dependencies=[Depends(write_guard)])
    def servers_block(server_id: str, profile: Profile = Depends(current_profile)) -> dict:
        try:
            hub.block(server_id, actor(profile))
        except ServerError as exc:
            raise fail(exc) from None
        return {"ok": True}

    @app.post("/api/servers/{server_id}/unblock", dependencies=[Depends(write_guard)])
    def servers_unblock(server_id: str, profile: Profile = Depends(current_profile)) -> dict:
        try:
            hub.unblock(server_id, actor(profile))
        except ServerError as exc:
            raise fail(exc) from None
        return {"ok": True}

    @app.delete("/api/servers/{server_id}", dependencies=[Depends(write_guard)])
    def servers_delete(server_id: str, profile: Profile = Depends(current_profile)) -> dict:
        try:
            hub.remove(server_id, actor(profile))
        except ServerError as exc:
            raise fail(exc) from None
        return {"ok": True}

    @app.get("/api/servers/activity")
    def servers_activity(
        server: str = Query("", max_length=40), kind: str = Query("", pattern="^(read|change|event)?$"),
        days: int = Query(1, ge=1, le=90), profile: Profile = Depends(current_profile),
    ) -> dict:
        return {"items": hub.repo.audit_list(server_id=server, kind=kind, days=days)}

    @app.delete("/api/servers/keys/{key_id}", dependencies=[Depends(write_guard)])
    def servers_key_revoke(key_id: str, profile: Profile = Depends(current_profile)) -> dict:
        if not hub.repo.key_revoke(key_id):
            raise HTTPException(status_code=404, detail=tr("Dieser Schlüssel ist nicht bekannt oder schon widerrufen."))
        hub.repo.audit_add("event", tr("Registrierungsschlüssel widerrufen"), actor=actor(profile), result="ok")
        return {"ok": True}

    @app.post("/api/servers/install-script", dependencies=[Depends(write_guard)])
    def servers_install_script(body: ScriptBody, profile: Profile = Depends(current_profile)) -> JSONResponse:
        """Erzeugt einen neuen Registrierungsschlüssel und das fertige Installationsskript mit allen Angaben."""
        address = (body.hub or settings.server_hub_address).strip().lower()
        if not address or not _HUB_ADDRESS_RE.match(address):
            raise HTTPException(status_code=422, detail=tr("Die Adresse des Hubs fehlt oder ist ungültig (z. B. ha.example.lan oder 10.20.0.5:8101)."))
        hashes = hub.agent_hashes()
        if not hashes:
            raise HTTPException(status_code=409, detail=tr("In diesem Add-on ist keine Programmdatei des Agenten enthalten."))
        try:
            pin = hub.pki.hub_pin(hub.hosts())  # das Zertifikat, das der laufende Hub verwendet (die Adresse im Skript ändert es nicht)
        except OSError:
            raise HTTPException(status_code=500, detail=tr("Das Zertifikat des Hubs konnte nicht angelegt werden.")) from None
        label = (body.name or "").strip() or "Installationsskript"
        key_id, key, expires = hub.repo.key_create(actor(profile), label[:60], body.hours, body.max_uses)
        hub.repo.audit_add("event", tr("Registrierungsschlüssel erzeugt"), actor=actor(profile), result="ok", detail=f"{label[:60]} · {body.max_uses}×")
        script = render_script(
            hub=hub_with_port(address), key=key, ca_fingerprint=hub.pki.ca_fingerprint, hub_pin=pin, hashes=hashes,
            expires=expires.replace("T", " ").replace("+00:00", " UTC"), max_uses=body.max_uses, name=(body.name or "").strip(), changes=body.changes,
        )
        return JSONResponse(
            {"script": script, "filename": "install-copilot-agent.sh", "key_id": key_id, "expires": expires},
            headers={"Cache-Control": "no-store"},
        )
