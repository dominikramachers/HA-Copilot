"""Verteiler zwischen den KI-Anbietern.

Die Oberfläche kennt weiter nur ``ChatBackend``. Der Anbieter ergibt sich aus der Modellkennung (``gpt-…`` = OpenAI, sonst Claude).
Titel und Zusammenfassungen übernimmt immer der Anbieter des Chats: Was in einem ChatGPT-Chat steht, geht nie an Claude,
und was in einem Claude-Chat steht, nie an OpenAI.
"""
from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from .backend import BackendError, ChatBackend
from .config import provider_of
from .i18n import tr


class RouterBackend:
    def __init__(self, claude: ChatBackend, openai: Any | None = None) -> None:
        self.claude = claude
        self.openai = openai

    def _pick(self, model: str | None) -> Any:
        if provider_of(model or "") == "openai":
            if self.openai is None:
                raise BackendError(tr("ChatGPT ist nicht eingerichtet (Add-on-Option „openai_enabled“ und ein OpenAI-Schlüssel in der Gruppe Chat)."))
            return self.openai
        return self.claude

    async def stream(self, history: list[dict], message: str, effort: str, *args: Any, **options: Any) -> AsyncIterator[str]:
        inner = self._pick(options.get("model")).stream(history, message, effort, *args, **options)
        async with contextlib.aclosing(inner) as pieces:
            async for piece in pieces:
                yield piece

    async def title(self, user_text: str, answer: str, model: str | None = None, **options: Any) -> str | None:
        backend = self._pick(model)
        if backend is self.openai:
            return await backend.title(user_text, answer, model=model, **options)
        return await backend.title(user_text, answer)

    async def summarize(self, previous: str | None, messages: list[dict], model: str | None = None, **options: Any) -> str | None:
        backend = self._pick(model)
        if backend is self.openai:
            return await backend.summarize(previous, messages, model=model, **options)
        return await backend.summarize(previous, messages)

    def sweep(self) -> int:
        sweep = getattr(self.claude, "sweep", None)
        return sweep() if sweep else 0

    @property
    def subscription(self) -> bool:
        return bool(getattr(self.claude, "subscription", False))

    async def probe_limits(self, on_limit: Any) -> bool:
        probe = getattr(self.claude, "probe_limits", None)
        return await probe(on_limit) if probe else False
