"""Deterministic scripted provider for tests and the offline demo.

Every reply is labelled provider="fixture" and model="fixture-script". Fixture runs
prove orchestration and persistence mechanics only; they say nothing about Claude,
Codex or any live model.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from .models import Agent, Cancelled, ProviderError, Reply

Respond = Callable[[str, "str | None"], str]


@dataclass
class FixtureCall:
    prompt: str
    session_id: str | None
    started: float
    ended: float | None = None


class FixtureProvider:
    provider = "fixture"

    def __init__(self, name: str = "fixture", *, respond: Respond | None = None, delay: float = 0.0,
                 fail: bool | Callable[[str], bool] = False, gate: threading.Event | None = None,
                 bound_identity: str | None = None, ignore_cancel: bool = False,
                 reply_provider: str | None = None, reply_session: str | None = None) -> None:
        """
        respond: (prompt, session_id) -> text; defaults to a numbered echo.
        delay / gate: wait before answering (cancel is honoured unless ignore_cancel).
        fail: raise a scripted ProviderError (bool, or predicate on the prompt).
        bound_identity: simulate a resident bound to one fixed provider session, so two
            fixtures with the same value are aliases of one identity.
        reply_provider / reply_session: return wrong attribution, for negative tests.
        """
        self.name = name
        self._respond = respond
        self.delay = delay
        self.fail = fail
        self.gate = gate
        self.bound_identity = bound_identity
        self.ignore_cancel = ignore_cancel
        self.reply_provider = reply_provider
        self.reply_session = reply_session
        self.calls: list[FixtureCall] = []
        self._instance = uuid.uuid4().hex
        self._lock = threading.Lock()

    def identity_key(self, session_id: str | None) -> str:
        if self.bound_identity is not None:
            return f"fixture:bound:{self.bound_identity}"
        if session_id is not None:
            return f"fixture:session:{session_id}"
        return f"fixture:fresh:{self._instance}"

    def _wait(self, cancel: threading.Event) -> None:
        if self.gate is not None:
            while not self.gate.wait(0.01):
                if cancel.is_set() and not self.ignore_cancel:
                    raise Cancelled("fixture call cancelled")
        if self.delay:
            if self.ignore_cancel:
                time.sleep(self.delay)
            elif cancel.wait(self.delay):
                raise Cancelled("fixture call cancelled")
        if cancel.is_set() and not self.ignore_cancel:
            raise Cancelled("fixture call cancelled")

    def generate(self, prompt: str, session_id: str | None, cancel: threading.Event) -> Reply:
        call = FixtureCall(prompt, session_id, time.monotonic())
        with self._lock:
            self.calls.append(call)
            number = len(self.calls)
        try:
            self._wait(cancel)
            failing = self.fail(prompt) if callable(self.fail) else self.fail
            if failing:
                raise ProviderError(f"{self.name} (fixture) scripted failure")
            text = self._respond(prompt, session_id) if self._respond else f"[{self.name} fixture reply {number}]"
            session = self.reply_session or session_id or f"fixture-{uuid.uuid4().hex}"
            return Reply(text, self.reply_provider or self.provider, session, "fixture-script")
        finally:
            call.ended = time.monotonic()


def demo_residents() -> tuple[dict[str, Agent], dict[str, FixtureProvider]]:
    """Offline demo residents, visibly labelled as fixtures."""
    agents = {
        "echo": Agent("echo", "Echo (fixture)", "fixture", "scripted demo resident"),
        "quill": Agent("quill", "Quill (fixture)", "fixture", "scripted demo editor"),
    }
    adapters = {key: FixtureProvider(agent.name, delay=0.2) for key, agent in agents.items()}
    return agents, adapters
