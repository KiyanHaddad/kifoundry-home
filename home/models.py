"""Shared data types, limits and errors.

Everything here is small and dependency-free so that store, council, adapters and
HTTP can agree on shapes without importing each other.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

# Budgets are measured in UTF-8 bytes. Inputs over a limit are rejected, never cut.
MAX_OWNER_BYTES = 16 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024
MAX_CONTEXT_BYTES = 48 * 1024
MAX_REPLY_BYTES = 64 * 1024
MAX_TITLE_CHARS = 200
MAX_ARTIFACTS_PER_ROUND = 8
MAX_REQUEST_ID_CHARS = 128
# Registered residents (homes in the town) are distinct from Council participants above.
MAX_RESIDENTS = 64
MAX_RESIDENT_NAME_CHARS = 60
MAX_ROLE_BYTES = 4096
# A Council may include every active resident: at most 2N+1 provider calls per round.
MAX_PARTICIPANTS = MAX_RESIDENTS
# Every assembled provider prompt, in UTF-8 bytes; the native adapter enforces the same 128 KiB.
MAX_PROMPT_BYTES = 128 * 1024


@dataclass(frozen=True)
class Agent:
    """A configured resident. Specialists sharing a provider are separate configured agents."""

    id: str
    name: str
    provider: str
    role: str = ""


@dataclass(frozen=True)
class Reply:
    """What a provider actually returned, including the session and model it reported."""

    text: str
    provider: str
    session_id: str | None = None
    model: str | None = None


class Provider(Protocol):
    """Adapter contract. Implementations live in home/adapters (and home/fixture.py).

    generate() must observe `cancel` and must raise ProviderError (with a safe,
    human-readable message) or Cancelled instead of returning partial text.
    identity_key() names the actual provider identity a call would use, so aliases of
    one bound session serialize, while app-owned fresh sessions do not collide.
    """

    provider: str

    def generate(self, prompt: str, session_id: str | None, cancel: threading.Event) -> Reply: ...

    def identity_key(self, session_id: str | None) -> str: ...


def utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


class HomeError(Exception):
    """Base error. `status` is a suggested HTTP code; messages are safe to show the owner."""

    status = 400


class ValidationError(HomeError):
    status = 400


class NotFoundError(HomeError):
    status = 404


class ConflictError(HomeError):
    status = 409


class ProviderError(HomeError):
    """Raised by adapters. The message must not contain raw stderr, credentials or paths."""

    status = 502


class Cancelled(HomeError):
    """Raised by adapters when the cancel event stopped the call before a final reply."""

    status = 409


class StoreError(HomeError):
    status = 500


class UnsupportedSchemaError(StoreError):
    """The database was written by a newer or unknown version; it is left untouched."""


class StoreLockedError(StoreError):
    """Another process already serves this data root."""
