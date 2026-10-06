"""Trusted resident bindings: how a registered resident gets a real adapter instance.

A binding is local, server-side setup (native TOML or the explicit fixture demo). The
browser only names an existing binding_id; it never supplies an executable, workspace,
session or model. Every resident built from a binding receives its own adapter
instance, so fresh provider sessions of two residents never share an identity key.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .config import Binding
from .fixture import FixtureProvider
from .models import (
    MAX_RESIDENT_NAME_CHARS,
    MAX_ROLE_BYTES,
    Agent,
    Provider,
    ValidationError,
    utf8_len,
)

# Resident IDs created by the server; configured IDs follow the TOML rule instead.
RESIDENT_ID = re.compile(r"[a-z][a-z0-9_-]{0,39}|res-[0-9a-f]{32}")
FIXTURE_MARK = "(fixture)"

Factory = Callable[[str], Provider]


@dataclass(frozen=True)
class ResidentBinding:
    """id/label/provider are shown to the browser; factory(resident_name) stays server-side."""

    id: str
    label: str
    provider: str
    factory: Factory
    addable: bool = True

    def info(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "provider": self.provider}


@dataclass(frozen=True)
class Seed:
    """A configured resident registered once under its own ID."""

    agent: Agent
    binding_id: str


def check_name(name: object, provider: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("Resident name must be non-empty text")
    name = " ".join(name.split())
    if provider == "fixture" and FIXTURE_MARK not in name:
        name = f"{name} {FIXTURE_MARK}"  # scripted residents never pass for live providers
    if len(name) > MAX_RESIDENT_NAME_CHARS:
        raise ValidationError(f"Resident name is over {MAX_RESIDENT_NAME_CHARS} characters")
    return name


def check_role(role: object) -> str:
    if role is None:
        return ""
    if not isinstance(role, str):
        raise ValidationError("Resident role must be text")
    if utf8_len(role) > MAX_ROLE_BYTES:
        raise ValidationError("Resident role is too long")
    return role.strip()


def fixture_binding(delay: float = 0.2) -> ResidentBinding:
    return ResidentBinding("fixture", "Scripted fixture resident (simulated replies)", "fixture",
                           lambda name: FixtureProvider(name, delay=delay))


def demo_registry() -> tuple[list[ResidentBinding], list[Seed]]:
    """Offline demo: one fixture binding, two seeded fixture residents, all labelled."""
    seeds = [Seed(Agent("echo", "Echo (fixture)", "fixture", "scripted demo resident"), "fixture"),
             Seed(Agent("quill", "Quill (fixture)", "fixture", "scripted demo editor"), "fixture")]
    return [fixture_binding()], seeds


def native_registry(bindings: Iterable[Binding]) -> tuple[list[ResidentBinding], list[Seed]]:
    """Each configured binding seeds its own resident and can build further residents."""
    from .adapters import ClaudeAdapter, CodexAdapter

    result: list[ResidentBinding] = []
    seeds: list[Seed] = []
    for item in bindings:
        adapter_type = ClaudeAdapter if item.provider == "claude" else CodexAdapter

        def factory(_name: str, item: Binding = item,
                    adapter_type: type[ClaudeAdapter | CodexAdapter] = adapter_type) -> Provider:
            return adapter_type(item.executable, item.workspace, timeout=item.timeout)

        result.append(ResidentBinding(item.id, f"{item.name} ({item.provider})", item.provider, factory))
        seeds.append(Seed(Agent(item.id, item.name, item.provider, item.role), item.id))
    return result, seeds


def static_registry(agents: dict[str, Agent], adapters: dict[str, Provider]
                    ) -> tuple[list[ResidentBinding], list[Seed]]:
    """Backward-compatible Council(store, agents, adapters): each given adapter is bound only
    to its own resident and is not offered for adding new residents."""
    def bound_factory(adapter: Provider) -> Factory:
        def factory(_name: str) -> Provider:
            return adapter
        return factory

    result = [ResidentBinding(key, agent.name, agent.provider, bound_factory(adapters[key]), addable=False)
              for key, agent in agents.items()]
    return result, [Seed(agent, key) for key, agent in agents.items()]
