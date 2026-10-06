"""Native provider adapters and safe, user-readable failure types."""
from .native import ClaudeAdapter, CodexAdapter
from .process import (
    AdapterCancelled,
    AdapterError,
    AdapterTimeout,
    OutputLimitExceeded,
    ProtocolError,
    UnexpectedAction,
)

__all__ = [
    "AdapterCancelled",
    "AdapterError",
    "AdapterTimeout",
    "ClaudeAdapter",
    "CodexAdapter",
    "OutputLimitExceeded",
    "ProtocolError",
    "UnexpectedAction",
]
