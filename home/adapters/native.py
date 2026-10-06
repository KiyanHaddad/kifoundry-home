"""Conversation-only native adapters. Native authentication remains in the CLIs."""
from __future__ import annotations

import json
import math
import threading
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict, Unpack

from home.models import MAX_PROMPT_BYTES, Reply

from .process import AdapterError, ProtocolError, UnexpectedAction, run_owned


def _session(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProtocolError("Native session must be an exact UUID.")
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise ProtocolError("Native session must be an exact UUID.") from None


def _event(line: bytes) -> dict[str, Any]:
    try:
        value = json.loads(line.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise ProtocolError("Native CLI returned invalid JSON.") from None
    if not isinstance(value, dict):
        raise ProtocolError("Native CLI returned an invalid event.")
    return value


def _model(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise ProtocolError("Native CLI returned invalid model metadata.")
    return value


class _Limits(TypedDict, total=False):
    timeout: float
    max_output_bytes: int
    max_reply_bytes: int


class _ClaudeState(TypedDict):
    session: str | None
    model: object
    result: object


class _CodexState(TypedDict):
    session: str | None
    model: object
    reply: object
    completed: bool


class _NativeAdapter(ABC):
    provider: str

    def __init__(self, executable: str, workspace: Path | str, timeout: float = 180,
                 max_output_bytes: int = 2 * 1024 * 1024,
                 max_reply_bytes: int = 64 * 1024) -> None:
        self.executable = str(executable)
        self.workspace = Path(workspace).resolve()
        if not self.workspace.is_dir():
            raise ValueError("Provider workspace must be an existing directory.")
        if not math.isfinite(timeout) or timeout <= 0 or timeout > 3600:
            raise ValueError("Provider timeout must be finite and between 0 and 3600 seconds.")
        if not 1024 <= max_output_bytes <= 16 * 1024 * 1024:
            raise ValueError("Native output limit is out of range.")
        if not 1 <= max_reply_bytes <= 256 * 1024:
            raise ValueError("Reply limit is out of range.")
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes
        self.max_reply_bytes = max_reply_bytes
        self._fresh_key = f"{self.provider}:fresh:{uuid.uuid4()}"

    def identity_key(self, session_id: str | None) -> str:
        actual = _session(session_id)
        return f"{self.provider}:session:{actual}" if actual else self._fresh_key

    @abstractmethod
    def _command(self, session_id: str | None) -> list[str]:
        raise NotImplementedError

    def _run(self, prompt: str, session_id: str | None, cancel: threading.Event,
             parser: Callable[[bytes], None]) -> None:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Provider prompt must contain text.")
        try:
            encoded = prompt.encode("utf-8")
        except UnicodeError:
            raise ValueError("Provider prompt must be valid Unicode text.") from None
        if len(encoded) > MAX_PROMPT_BYTES:
            raise ValueError("Provider prompt exceeds the input limit.")
        run_owned(self._command(_session(session_id)), self.workspace, encoded, cancel,
                  self.timeout, self.max_output_bytes, parser)

    def _reply(self, text: object, session: object, model: object,
               requested: str | None) -> Reply:
        if not isinstance(text, str) or not text.strip():
            raise ProtocolError("Native CLI did not return a final reply.")
        try:
            reply_bytes = text.encode("utf-8")
        except UnicodeError:
            raise ProtocolError("Native CLI returned invalid reply text.") from None
        if len(reply_bytes) > self.max_reply_bytes:
            raise ProtocolError("Native reply exceeded the configured limit.")
        actual = _session(session)
        if actual is None:
            raise ProtocolError("Native CLI did not report a resumable session.")
        if requested and actual != _session(requested):
            raise ProtocolError("Native CLI returned a different session than requested.")
        return Reply(text=text, provider=self.provider, session_id=actual, model=_model(model))


class ClaudeAdapter(_NativeAdapter):
    provider = "claude"

    def __init__(self, executable: str = "claude", workspace: Path | str = ".",
                 **limits: Unpack[_Limits]) -> None:
        super().__init__(executable, workspace, **limits)

    def _command(self, session_id: str | None) -> list[str]:
        command = [self.executable, "--print", "--verbose", "--output-format", "stream-json",
                   "--input-format", "text", "--tools", "", "--disable-slash-commands",
                   "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                   "--permission-prompts", "none"]
        if session_id:
            command.extend(["--resume", session_id])
        return command

    def generate(self, prompt: str, session_id: str | None, cancel: threading.Event) -> Reply:
        state: _ClaudeState = {"session": None, "model": None, "result": None}

        def parse(line: bytes) -> None:
            event = _event(line)
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "init":
                actual = _session(event.get("session_id"))
                if state["session"] and actual != state["session"]:
                    raise ProtocolError("Claude returned inconsistent session metadata.")
                state["session"] = actual
                state["model"] = event.get("model")
            elif kind == "assistant":
                content = event.get("message", {}).get("content", [])
                if any(isinstance(item, dict) and item.get("type") in {
                        "tool_use", "server_tool_use"} for item in content):
                    raise UnexpectedAction("Claude attempted a tool action in conversation mode.")
            elif kind in {"tool_use", "tool_result", "tool_progress"}:
                raise UnexpectedAction("Claude attempted a tool action in conversation mode.")
            elif kind == "result":
                if event.get("is_error") or event.get("subtype") not in {None, "success"}:
                    raise AdapterError("Claude did not complete the reply. Check its native CLI status.")
                state["result"] = event.get("result")
                reported = event.get("session_id")
                if state["session"] and reported and _session(reported) != _session(state["session"]):
                    raise ProtocolError("Claude returned inconsistent session metadata.")
                state["session"] = reported or state["session"]
                state["model"] = event.get("model") or state["model"]

        self._run(prompt, session_id, cancel, parse)
        return self._reply(state["result"], state["session"], state["model"], session_id)


class CodexAdapter(_NativeAdapter):
    provider = "codex"

    def __init__(self, executable: str = "codex", workspace: Path | str = ".",
                 **limits: Unpack[_Limits]) -> None:
        super().__init__(executable, workspace, **limits)

    def _command(self, session_id: str | None) -> list[str]:
        # Resume help supports config overrides but not the exec --sandbox flag.
        command = [self.executable, "exec"]
        if session_id:
            command.extend(["resume", session_id])
        else:
            command.extend(["--sandbox", "read-only"])
        command.extend(["-c", 'sandbox_mode="read-only"', "-c", 'approval_policy="never"',
                        "--skip-git-repo-check", "--json", "-"])
        return command

    def generate(self, prompt: str, session_id: str | None, cancel: threading.Event) -> Reply:
        state: _CodexState = {"session": None, "model": None, "reply": None, "completed": False}

        def parse(line: bytes) -> None:
            event = _event(line)
            kind = event.get("type")
            if kind == "thread.started":
                actual = _session(event.get("thread_id"))
                if state["session"] and actual != state["session"]:
                    raise ProtocolError("Codex returned inconsistent session metadata.")
                state["session"] = actual
                state["model"] = event.get("model")
            elif kind in {"item.started", "item.updated", "item.completed"}:
                item = event.get("item", {})
                item_type = item.get("type")
                if item_type not in {"agent_message", "reasoning"}:
                    raise UnexpectedAction("Codex attempted an unexpected action in conversation mode.")
                if kind == "item.completed" and item_type == "agent_message":
                    state["reply"] = item.get("text")
            elif kind == "turn.completed":
                state["completed"] = True
            elif kind in {"turn.failed", "error"}:
                raise AdapterError("Codex did not complete the reply. Check its native CLI status.")

        self._run(prompt, session_id, cancel, parse)
        if not state["completed"]:
            raise ProtocolError("Codex did not report a completed turn.")
        return self._reply(state["reply"], state["session"], state["model"], session_id)
