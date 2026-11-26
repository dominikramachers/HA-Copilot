"""Modus „Auto“: wählt je Nachricht Anbieter und Modell nach Art und Anspruch der Anfrage.

Drei Stufen: leicht, normal und anspruchsvoll. Bei Claude sind das Haiku, das in der App eingestellte Modell (meist Sonnet)
und Opus; bei OpenAI (nur wenn eingeschaltet) das erste, mittlere und letzte Modell aus ``chat.openai_models``
(Reihenfolge klein → groß). Programmieren, Technik und das Smarthome bleiben bei Claude; Texte schreiben, Fragen und
Alltägliches gehen an OpenAI, wenn es eingeschaltet ist und das Monatslimit nicht erreicht ist. Die Wahl beruht nur auf
Merkmalen der Nachricht (Länge, Code, Anhänge, Schlüsselwörter, Aufwand, Deep Research) und kostet keinen zusätzlichen
Aufruf der KI.

Ein persönliches Standardmodell und eine Wahl im Chat gehen Auto vor (das entscheidet ``main``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LIGHT, NORMAL, STRONG = 0, 1, 2
LEVEL_NAMES = ("leicht", "normal", "anspruchsvoll")

# Kurze Rückfragen im laufenden Chat („ja, mach das“) behalten die Stufe der vorigen Antwort
FOLLOW_UP_CHARS = 300
LIGHT_MAX_CHARS = 160
STRONG_MIN_CHARS = 1500

_DOC_MIMES = ("application/pdf", "officedocument", "msword", "ms-excel", "ms-powerpoint", "opendocument")

_STRONG_WORDS = re.compile(
    r"\b("
    r"analysier\w*|analyse\w*|konzept\w*|architektur\w*|entw[iu]rf\w*|refaktor\w*|refactor\w*|"
    r"debug\w*|fehlersuche|troubleshoot\w*|ursache\w*|root cause|"
    r"strategie\w*|projektplan\w*|migrier\w*|migration\w*|sicherheitspr[üu]f\w*|audit\w*|"
    r"code ?review|review|optimier\w*|bewerte\w*|vergleich\w*|gegen[üu]berstell\w*|"
    r"implementier\w*|programmier\w*|"
    r"analy[sz]e|design|architecture|strategy|implement\w*|compare|evaluate|investigate"
    r")\b",
    re.IGNORECASE,
)
_CODE_WORDS = re.compile(
    r"\b(skript|script|funktion|function|klasse|class|regex|yaml|json|python|javascript|typescript|bash|sql|"
    r"automation\w*|blueprint\w*|template\w*|jinja|dashboard\w*)\b",
    re.IGNORECASE,
)
# Technik und Programmieren: bleibt bei Claude
_TECH_WORDS = re.compile(
    r"\b("
    r"code|coden|programm\w*|entwickl\w*|skript\w*|script\w*|funktion\w*|klasse\w*|regex|yaml|json|python|javascript|typescript|bash|"
    r"powershell|sql|html|css|api|apis|sdk|docker\w*|container\w*|linux|server\w*|firewall\w*|netzwerk\w*|vlan\w*|dns|vpn|"
    r"automation\w*|blueprint\w*|template\w*|jinja|dashboard\w*|entit[äa]t\w*|integration\w*|add-?on\w*|home assistant|zigbee\w*|"
    r"konnektor\w*|mcp|git|github|commit\w*|pull request|deploy\w*|debug\w*|fehlermeldung\w*|log|logs|stacktrace|traceback|"
    r"refaktor\w*|refactor\w*|bug\w*|kompilier\w*|install\w*|konfigur\w*|config\w*|backup\w*|veeam|unifi|zabbix|"
    r"function|class|compile|configure|network|code review"
    r")\b",
    re.IGNORECASE,
)
# Bedienung des Smarthomes: bleibt bei Claude (schnell, im Abo, mit den Werkzeugen für Home Assistant erprobt)
_HOME_WORDS = re.compile(
    r"\b(licht\w*|lampe\w*|heizung\w*|thermostat\w*|rollladen|rollläden|rollo\w*|steckdose\w*|schalte\w*|ventilator\w*|"
    r"temperatur\w*|wie warm|wie kalt|saugroboter|staubsauger|tür|türen|haustür\w*|fenster|alarmanlage|"
    r"light\w*|lamp\w*|heating|thermostat|blind\w*|socket\w*|vacuum|door\w*|scene\w*)\b",
    re.IGNORECASE,
)
_LIGHT_WORDS = re.compile(
    r"^\s*(hallo|hi|hey|moin|servus|guten (morgen|tag|abend)|danke\w*|thx|thanks|ok(ay)?|super|passt|"
    r"schalte?|mach|stell\w*|dimm\w*|öffne|schließe?|starte?|stopp\w*|"
    r"wie spät|wie viel uhr|welcher tag|wie (warm|kalt|ist das wetter)|ist (das|die|der)|sind (die|alle)|"
    r"turn|switch|set|what time|how warm|is the)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Tiers:
    """Die drei Modelle, zwischen denen Auto wählt (fehlt eins, gilt das normale)."""

    light: str
    normal: str
    strong: str

    @classmethod
    def from_choices(cls, normal: str, choices: list[str]) -> Tiers:
        claude = [m for m in choices if m.startswith("claude-")]

        def find(family: str) -> str:
            return next((m for m in claude if f"-{family}-" in m or m.endswith(f"-{family}")), normal)

        return cls(light=find("haiku"), normal=normal, strong=find("opus"))

    def model(self, level: int) -> str:
        return (self.light, self.normal, self.strong)[max(LIGHT, min(STRONG, level))]


def _is_document(meta: dict) -> bool:
    if meta.get("kind") in ("pdf", "word", "excel", "powerpoint"):
        return True
    mime = str(meta.get("mime") or meta.get("type") or "").lower()
    name = str(meta.get("name") or "").lower()
    return any(m in mime for m in _DOC_MIMES) or name.endswith((".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods"))


def level_for(
    text: str,
    *,
    attachments: list[dict] | None = None,
    effort: str = "medium",
    research: bool = False,
    in_chat: bool = False,
    previous: int | None = None,
) -> int:
    """Stufe einer Nachricht (``LIGHT``, ``NORMAL``, ``STRONG``).

    ``in_chat`` = es gibt schon Verlauf; ``previous`` = von Auto zuletzt gewählte Stufe in diesem Chat.
    """
    files = attachments or []
    # Eingefügter Text (als Anhang gezeigt) gehört zur Nachricht selbst und zählt bei der Länge mit
    pasted = [f for f in files if f.get("pasted")]
    text = "\n".join([text or "", *(str(f.get("text") or "") for f in pasted)])
    files = [f for f in files if not f.get("pasted")]
    stripped = text.strip()
    code_blocks = text.count("```") // 2
    code_lines = sum(len(block.splitlines()) for block in text.split("```")[1::2])
    docs = sum(1 for f in files if _is_document(f))

    if research or effort == "high":
        level = STRONG
    elif len(stripped) >= STRONG_MIN_CHARS or code_lines >= 40 or docs >= 2:
        level = STRONG
    elif _STRONG_WORDS.search(stripped) and (len(stripped) > 60 or code_blocks or files):
        level = STRONG
    elif (
        not files
        and not code_blocks
        and len(stripped) <= LIGHT_MAX_CHARS
        and stripped.count("\n") < 2
        and not _CODE_WORDS.search(stripped)
        and not _STRONG_WORDS.search(stripped)
        and (_LIGHT_WORDS.search(stripped) or effort == "low" or len(stripped) <= 40)
    ):
        level = LIGHT
    else:
        level = NORMAL

    # Kurze Antworten im laufenden Chat („ja, so machen“, „und jetzt die Küche“) bleiben auf der Stufe davor
    if in_chat and previous is not None and len(stripped) < FOLLOW_UP_CHARS and not files:
        level = max(level, previous)
    return level


def openai_tiers(models: list[str]) -> Tiers | None:
    """Stufen bei OpenAI aus der eingestellten Liste (klein → groß); ``None`` ohne OpenAI-Modelle."""
    gpt = [m for m in models if m and not m.startswith("claude-")]
    if not gpt:
        return None
    return Tiers(light=gpt[0], normal=gpt[(len(gpt) - 1) // 2] if len(gpt) > 2 else gpt[0], strong=gpt[-1])


def is_technical(text: str, attachments: list[dict] | None = None) -> bool:
    """Programmieren, Technik oder Smarthome: das bleibt bei Claude."""
    text = text or ""
    if "```" in text or _TECH_WORDS.search(text) or _HOME_WORDS.search(text):
        return True
    return any(str(f.get("name") or "").lower().endswith((".py", ".js", ".ts", ".yaml", ".yml", ".json", ".sh", ".ps1", ".sql", ".log", ".conf"))
               for f in attachments or [])


@dataclass(frozen=True)
class Choice:
    model: str
    level: int
    provider: str  # claude oder openai


def route(
    text: str,
    claude: Tiers,
    openai: Tiers | None = None,
    *,
    attachments: list[dict] | None = None,
    effort: str = "medium",
    research: bool = False,
    in_chat: bool = False,
    previous: tuple[int, str] | None = None,
) -> Choice:
    """Anbieter und Modell für eine Nachricht im Modus Auto.

    ``openai`` = Stufen bei OpenAI, nur wenn eingeschaltet und das Monatslimit nicht erreicht ist.
    ``previous`` = (Stufe, Anbieter) der vorigen Auto-Antwort in diesem Chat.
    """
    prev_level, prev_provider = previous if previous else (None, None)
    level = level_for(text, attachments=attachments, effort=effort, research=research, in_chat=in_chat, previous=prev_level)
    pasted = " ".join(str(f.get("text") or "") for f in attachments or [] if f.get("pasted"))
    technical = is_technical(f"{text or ''} {pasted}", attachments)
    provider = "openai" if openai is not None and not technical and not research else "claude"
    # Kurze Folgenachrichten bleiben beim Anbieter davor („ja, mach das so“ nach einer Programmieraufgabe bleibt bei Claude)
    short_follow_up = in_chat and prev_provider and len((text or "").strip()) < FOLLOW_UP_CHARS and not [f for f in attachments or [] if not f.get("pasted")]
    if short_follow_up and not technical:
        provider = prev_provider if (prev_provider == "claude" or openai is not None) else "claude"
    tiers = openai if provider == "openai" and openai is not None else claude
    return Choice(tiers.model(level), level, "openai" if tiers is openai else "claude")


class AutoMemory:
    """Merkt sich je Chat Stufe und Anbieter der letzten Auto-Antwort (nur im Arbeitsspeicher, begrenzt)."""

    def __init__(self, limit: int = 2000) -> None:
        self._levels: dict[tuple[str, str], tuple[int, str]] = {}
        self._limit = limit

    def get(self, key: tuple[str, str]) -> tuple[int, str] | None:
        """(Stufe, Anbieter) der zuletzt von Auto gewählten Antwort in diesem Chat."""
        return self._levels.get(key)

    def set(self, key: tuple[str, str], level: int, provider: str = "claude") -> None:
        self._levels.pop(key, None)
        self._levels[key] = (level, provider)
        while len(self._levels) > self._limit:
            self._levels.pop(next(iter(self._levels)))

    def forget(self, key: tuple[str, str]) -> None:
        self._levels.pop(key, None)
