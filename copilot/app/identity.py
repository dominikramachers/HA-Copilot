"""Auflösung einer Anmelde-Identität auf ein internes Profil.

Jeder Zugangsweg (Ingress heute, Entra-Login auf der Domain in Etappe 4) endet
bei genau einem ``Profile``. Unbekannte Identitäten erhalten keinen Zugriff und
werden nie automatisch angelegt.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from .config import Profile
from .oidc import EntraIdentity


class AccessDenied(Exception):
    """Kein Zugriff. ``reason`` ist nur für das Log gedacht, nie für den Client."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


AUTO_PREFIX = "ha-"
_CLEAN = re.compile(r"[<>\x00-\x1f]")


def _label(*names: str) -> str:
    for name in names:
        text = re.sub(r"\s+", " ", _CLEAN.sub("", name or "")).strip()[:40]
        if text:
            return text
    return "Benutzer"


class Registry:
    """Alle zugangsberechtigten Profile.

    * Profile aus der Add-on-Konfiguration. Ein Profil kann seinen Home-Assistant-Benutzer über die ID
      (``ha_user_id``) oder den Benutzernamen (``ha_user``) angeben; Namen löst das Add-on im Hintergrund zur ID
      auf (``apply_ha_users``).
    * Optional (``all_ha_users``): jeder andere Home-Assistant-Benutzer, der nicht ausgeschlossen ist, bekommt beim
      ersten Zugriff automatisch ein eigenes Profil (``ha-`` + Anfang seiner HA-Benutzer-ID, damit die Chats stabil
      am Benutzer hängen).
    """

    def __init__(self, profiles: tuple[Profile, ...], auto: bool = False, excluded=(), store=None) -> None:
        self._profiles = tuple(profiles)
        self._resolved: dict[str, str] = {}  # Profil-ID -> aufgelöste HA-Benutzer-ID
        self._auto = auto
        self._excluded = frozenset(x.lower() for x in excluded)
        self._store = store
        self._auto_by_ha: dict[str, Profile] = {}
        self._index()

    @classmethod
    def from_settings(cls, settings, store=None) -> "Registry":
        return cls(settings.profiles, settings.all_ha_users, settings.ha_users_excluded, store)

    def _index(self) -> None:
        self._by_ha_user_id = {}
        for p in self._profiles:
            ha_id = p.ha_user_id or self._resolved.get(p.id, "")
            if ha_id:
                self._by_ha_user_id[ha_id] = p
        self._by_upn = {p.entra_upn: p for p in self._profiles if p.entra_upn}
        self._by_id = {p.id: p for p in self._profiles}

    def all(self) -> tuple[Profile, ...]:
        return self._profiles

    def by_id(self, value: str) -> Profile | None:
        found = self._by_id.get(value)
        if found is not None or not (self._auto and value.startswith(AUTO_PREFIX)):
            return found
        # Automatisches Profil nach einem Neustart: aus der Datenbank wiederherstellen (für laufende Domain-Sitzungen)
        for p in self._auto_by_ha.values():
            if p.id == value:
                return p if p.ha_user_id not in self._excluded else None
        remembered = self._store.recall_ha_profile(value) if self._store is not None else None
        if remembered is None or remembered[1] in self._excluded:
            return None
        profile = Profile(value, remembered[0] or "Benutzer", remembered[1], "")
        self._auto_by_ha[remembered[1]] = profile
        return profile

    def by_ha_user_id(self, value: str) -> Profile | None:
        return self._by_ha_user_id.get(value.strip().lower())

    def by_upn(self, value: str) -> Profile | None:
        return self._by_upn.get(value.strip().lower())

    def admit_ha(self, user_id: str, names: tuple[str, ...] = (), display_name: str = "") -> Profile | None:
        """Profil für einen angemeldeten Home-Assistant-Benutzer (Ingress oder Anmeldung mit Home Assistant).

        Erst die Einträge der Konfiguration; sonst, falls ``all_ha_users`` an ist und der Benutzer nicht ausgeschlossen
        wurde, ein automatisch angelegtes Profil.
        """
        user_id = user_id.strip().lower()
        if not user_id:
            return None
        found = self._by_ha_user_id.get(user_id)
        if found is not None or not self._auto:
            return found
        keys = {user_id} | {n.strip().lower() for n in (*names, display_name) if n and n.strip()}
        if keys & self._excluded:
            return None
        label = _label(display_name, *names)
        profile = self._auto_by_ha.get(user_id)
        if profile is None or profile.label != label:
            profile = Profile(AUTO_PREFIX + user_id[:12], label, user_id, "")
            self._auto_by_ha[user_id] = profile
            if self._store is not None:
                self._store.remember_ha_profile(profile.id, profile.label, user_id)
        return profile

    @property
    def auto_admit(self) -> bool:
        """Alle Home-Assistant-Benutzer werden automatisch zugelassen (``all_ha_users``)."""
        return self._auto

    def taken_ids(self) -> set[str]:
        return set(self._by_id)

    def pending(self) -> list[Profile]:
        """Profile mit Benutzername, dessen ID noch nicht aufgelöst ist."""
        return [p for p in self._profiles if p.ha_user and not p.ha_user_id and p.id not in self._resolved]

    def apply_ha_users(self, users: list[dict[str, str]]) -> list[str]:
        """Benutzernamen den Home-Assistant-Benutzern zuordnen. Liefert Meldungen für das Protokoll."""
        notes: list[str] = []
        explicit = {p.ha_user_id for p in self._profiles if p.ha_user_id}
        for profile in self.pending():
            wanted = profile.ha_user.strip().lower()
            matches = {
                u["id"]
                for u in users
                if wanted in {u.get("username", "").lower(), u.get("person", "").lower()}
            }
            if not matches:
                notes.append(f"Profil {profile.id!r}: Es gibt keinen Home-Assistant-Benutzer „{profile.ha_user}“ (Anmeldename oder Person)")
            elif len(matches) > 1:
                notes.append(f"Profil {profile.id!r}: „{profile.ha_user}“ passt auf mehrere Home-Assistant-Benutzer, bitte den Anmeldenamen oder die ID verwenden")
            else:
                ha_id = matches.pop()
                taken = explicit | set(self._resolved.values())
                if ha_id in taken:
                    notes.append(f"Profil {profile.id!r}: Der Home-Assistant-Benutzer „{profile.ha_user}“ gehört schon zu einem anderen Profil")
                else:
                    self._resolved[profile.id] = ha_id
                    notes.append(f"Profil {profile.id!r}: Home-Assistant-Benutzer „{profile.ha_user}“ zugeordnet")
        self._index()
        return notes


def resolve_ingress(
    registry: Registry,
    peer_host: str,
    headers: Mapping[str, str],
    trusted_peers: frozenset[str],
) -> Profile:
    """Profil für eine Anfrage über HA-Ingress bestimmen.

    Die Header werden nur akzeptiert, wenn die TCP-Verbindung direkt vom
    Ingress-Proxy kommt. X-Forwarded-For o. Ä. wird bewusst nie ausgewertet.
    """
    if peer_host not in trusted_peers:
        raise AccessDenied("untrusted_peer")

    user_id = headers.get("x-remote-user-id", "").strip().lower()
    if not user_id:
        raise AccessDenied("no_user_header")

    profile = registry.admit_ha(
        user_id,
        (headers.get("x-remote-user-name", ""),),
        headers.get("x-remote-user-display-name", ""),
    )
    if profile is None:
        raise AccessDenied(f"unknown_user:{user_id[:8]}")
    return profile


def resolve_entra(registry: Registry, store, identity: EntraIdentity) -> Profile:
    """Profil für eine Entra-Anmeldung bestimmen.

    Maßgeblich ist die unveränderliche Objekt-ID (``oid``). Beim ersten Login wird sie über die
    in der Konfiguration hinterlegte UPN dem Profil zugeordnet und danach fest daran gebunden.
    Unbekannte Konten erhalten keinen Zugriff und werden nie angelegt.
    """
    bound = store.profile_id_for_oid(identity.oid)
    if bound is not None:
        profile = registry.by_id(bound)
        if profile is None:
            raise AccessDenied("oid_bound_to_removed_profile")
        return profile

    for name in identity.names:
        profile = registry.by_upn(name)
        if profile is not None:
            if not store.bind_oid(profile.id, identity.oid):
                raise AccessDenied(f"oid_mismatch:{profile.id}")
            return profile
    raise AccessDenied("unknown_upn:" + ",".join(identity.names)[:80])
