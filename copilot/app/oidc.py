"""Anmeldung über Microsoft Entra ID (OpenID Connect, Code-Flow mit PKCE).

Der Add-on ist eine vertrauliche Web-App (Client-Secret) in einem einzelnen Mandanten.
Geprüft werden Signatur, Aussteller, Zielgruppe (Client-ID), Ablauf, Nonce und Mandant des
ID-Tokens. Die E-Mail-Adresse aus dem Anmeldeformular ist nur ein Hinweis für Microsoft
(``login_hint``) und wird nie zur Zugriffsentscheidung verwendet.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

log = logging.getLogger("ki_chat.oidc")

AUTHORITY = "https://login.microsoftonline.com"
SCOPES = "openid profile email"
PENDING_TTL = 600  # Sekunden, so lange darf die Anmeldung bei Microsoft dauern


class OidcError(Exception):
    """Anmeldung fehlgeschlagen. Die Meldung ist nur fürs Log bestimmt."""


@dataclass(frozen=True)
class EntraIdentity:
    tenant_id: str
    oid: str
    names: tuple[str, ...]  # kleingeschriebene Anmeldenamen aus dem Token (preferred_username, upn)
    display_name: str = ""


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class EntraClient:
    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        http: httpx.AsyncClient | None = None,
        authority: str = AUTHORITY,
    ) -> None:
        self.tenant_id = tenant_id.lower()
        self.client_id = client_id
        self._secret = client_secret
        self.redirect_uri = redirect_uri
        self._http = http or httpx.AsyncClient(timeout=10.0)
        self._authority = authority.rstrip("/")
        self._discovery: dict | None = None
        self._discovery_at = 0.0
        self._jwks: dict | None = None

    # ------------------------------------------------------------ Metadaten

    @property
    def issuer(self) -> str:
        return f"{self._authority}/{self.tenant_id}/v2.0"

    async def _meta(self) -> dict:
        if self._discovery and time.monotonic() - self._discovery_at < 3600:
            return self._discovery
        url = f"{self.issuer}/.well-known/openid-configuration"
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            meta = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcError(f"Discovery fehlgeschlagen: {exc}") from exc
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer"):
            if not isinstance(meta.get(key), str):
                raise OidcError(f"Discovery ohne {key}")
        if meta["issuer"].lower() != self.issuer.lower():
            raise OidcError("Discovery: unerwarteter Aussteller")
        self._discovery, self._discovery_at = meta, time.monotonic()
        return meta

    async def _signing_key(self, kid: str | None, refresh: bool = False):
        meta = await self._meta()
        if self._jwks is None or refresh:
            try:
                response = await self._http.get(meta["jwks_uri"])
                response.raise_for_status()
                self._jwks = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise OidcError(f"JWKS nicht ladbar: {exc}") from exc
        for key in self._jwks.get("keys", []):
            if key.get("kid") == kid:
                return jwt.PyJWK.from_dict(key).key
        if not refresh:
            return await self._signing_key(kid, refresh=True)
        raise OidcError("Signaturschlüssel unbekannt")

    # --------------------------------------------------------------- Ablauf

    async def authorize_url(self, state: str, nonce: str, challenge: str, login_hint: str = "") -> str:
        meta = await self._meta()
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "response_mode": "query",
            "scope": SCOPES,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{meta['authorization_endpoint']}?{urlencode(params)}"

    async def complete(self, code: str, verifier: str, nonce: str) -> EntraIdentity:
        meta = await self._meta()
        try:
            response = await self._http.post(
                meta["token_endpoint"],
                data={
                    "client_id": self.client_id,
                    "client_secret": self._secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "code_verifier": verifier,
                    "scope": SCOPES,
                },
            )
        except httpx.HTTPError as exc:
            raise OidcError(f"Token-Endpunkt nicht erreichbar: {exc}") from exc
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code != 200 or "id_token" not in body:
            raise OidcError(
                f"Code-Einlösung abgelehnt ({response.status_code}): "
                f"{body.get('error')} {str(body.get('error_description', ''))[:200]}"
            )
        return await self._validate(body["id_token"], nonce)

    async def _validate(self, id_token: str, nonce: str) -> EntraIdentity:
        try:
            header = jwt.get_unverified_header(id_token)
            if header.get("alg") != "RS256":
                raise OidcError("Unerwarteter Signaturalgorithmus")
            key = await self._signing_key(header.get("kid"))
            claims = jwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=self.issuer,
                leeway=60,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise OidcError(f"ID-Token ungültig: {exc}") from exc
        if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            raise OidcError("Nonce stimmt nicht")
        if str(claims.get("tid", "")).lower() != self.tenant_id:
            raise OidcError("Falscher Mandant")
        oid = str(claims.get("oid") or "").lower()
        if not oid:
            raise OidcError("Token ohne oid")
        names = []
        for claim in ("preferred_username", "upn"):
            value = claims.get(claim)
            if isinstance(value, str) and value.strip() and "#ext#" not in value.lower():
                names.append(value.strip().lower())
        return EntraIdentity(self.tenant_id, oid, tuple(dict.fromkeys(names)), str(claims.get("name") or ""))


class PendingLogins:
    """Laufende Anmeldungen (state → Nonce, PKCE-Verifier, Bindung an den Browser)."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._items: dict[str, tuple[float, str, str, str]] = {}

    @staticmethod
    def _bind(browser_token: str) -> str:
        return hashlib.sha256(browser_token.encode()).hexdigest()

    def add(self, state: str, nonce: str, verifier: str, browser_token: str) -> None:
        now = self._clock()
        self._items = {k: v for k, v in self._items.items() if now - v[0] < PENDING_TTL}
        if len(self._items) >= 500:
            raise OidcError("Zu viele offene Anmeldungen")
        self._items[state] = (now, nonce, verifier, self._bind(browser_token))

    def take(self, state: str, browser_token: str) -> tuple[str, str] | None:
        """(nonce, verifier) einmalig herausgeben, wenn state und Browser passen."""
        item = self._items.pop(state, None)
        if item is None or self._clock() - item[0] >= PENDING_TTL:
            return None
        if not hmac.compare_digest(item[3], self._bind(browser_token)):
            return None
        return item[1], item[2]
