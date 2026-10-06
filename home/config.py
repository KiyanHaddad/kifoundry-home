"""Load explicit local resident bindings; the browser cannot change them."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Binding:
    id: str
    name: str
    provider: str
    role: str
    executable: str
    workspace: Path
    timeout: float = 180.0


def default_data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "KiFoundryHome"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "kifoundry-home"


def load_bindings(path: Path) -> list[Binding]:
    """TOML is trusted local setup, never supplied by an HTTP request."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"agents"} or not isinstance(data["agents"], list):
        raise ValueError("Configuration must contain an agents array only")
    bindings: list[Binding] = []
    seen: set[str] = set()
    for item in data["agents"]:
        if not isinstance(item, dict) or set(item) - {
            "id", "name", "provider", "role", "executable", "workspace", "timeout"
        }:
            raise ValueError("Unknown resident configuration fields")
        agent_id = item.get("id")
        name = item.get("name")
        provider = item.get("provider")
        if not isinstance(agent_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", agent_id):
            raise ValueError("Resident ID must be a short lowercase identifier")
        if agent_id in seen or not isinstance(name, str) or not 1 <= len(name) <= 60:
            raise ValueError("Resident IDs must be unique and names nonempty")
        if not isinstance(provider, str) or provider not in {"claude", "codex"}:
            raise ValueError("Configured native provider must be claude or codex")
        role = item.get("role", "")
        executable = item.get("executable", provider)
        if not isinstance(role, str) or len(role.encode("utf-8")) > 4096:
            raise ValueError("Resident role is too large")
        if not isinstance(executable, str) or not executable or len(executable) > 4096:
            raise ValueError("Invalid native executable")
        workspace_value = item.get("workspace", ".")
        if not isinstance(workspace_value, str):
            # Parsed TOML fields share the configuration ValueError contract.
            raise ValueError("Workspace must be a directory")  # noqa: TRY004
        workspace = (path.parent / workspace_value).resolve()
        if not workspace.is_dir():
            raise ValueError("Configured workspace does not exist")
        timeout = item.get("timeout", 180)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 5 <= timeout <= 600:
            raise ValueError("Provider timeout must be between 5 and 600 seconds")
        bindings.append(Binding(agent_id, name, provider, role, executable, workspace, float(timeout)))
        seen.add(agent_id)
    if not 1 <= len(bindings) <= 5:
        raise ValueError("Configure between one and five residents")
    return bindings
