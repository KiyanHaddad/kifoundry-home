"""Loopback HTTP transport. Conversation behavior lives in Council and Store."""

from __future__ import annotations

import hmac
import json
import secrets
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .models import MAX_PROMPT_BYTES, HomeError

WEB = Path(__file__).with_name("web")
STATIC_TYPES = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".ttf": "font/ttf",
}


def same_secret(value: object, secret: str) -> bool:
    if not isinstance(value, str) or len(value) > 512:
        return False
    return hmac.compare_digest(value.encode("utf-8"), secret.encode("utf-8"))


class HomeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, store: Any, council: Any, fixture: bool = False) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.store = store
        self.council = council
        self.fixture = fixture
        self.launch_token = secrets.token_urlsafe(32)
        self.cookie_token = secrets.token_urlsafe(32)
        self.csrf = secrets.token_urlsafe(32)
        self.auth_lock = threading.Lock()
        actual_port = self.server_address[1]
        # Cookies ignore ports, so simultaneous local Home instances need distinct names.
        self.cookie_name = f"home_session_{actual_port}"
        self.hosts = {f"127.0.0.1:{actual_port}", f"localhost:{actual_port}"}
        self.origins = {f"http://{host}" for host in self.hosts}

    @property
    def launch_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/#launch={self.launch_token}"


class Handler(BaseHTTPRequestHandler):
    server: HomeServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_: object) -> None:
        # Requests may contain private data; record application receipts separately.
        return

    def _headers(self, content_type: str, length: int, cookie: bool = False) -> None:
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", f"{self.server.cookie_name}={self.server.cookie_token}; HttpOnly; SameSite=Strict; Path=/")
        self.end_headers()

    def _json(self, value: object, status: int = 200, cookie: bool = False) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._headers("application/json", len(body), cookie)
        self.wfile.write(body)

    def _origin_ok(self) -> bool:
        if self.headers.get("Host") not in self.server.hosts:
            self._json({"error": "Unexpected local host"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self.server.origins:
            self._json({"error": "Unexpected request origin"}, 403)
            return False
        return True

    def _authenticated(self) -> bool:
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            value = cookie.get(self.server.cookie_name)
            return value is not None and same_secret(value.value, self.server.cookie_token)
        except Exception:  # noqa: BLE001 - malformed cookies must fail authentication closed.
            return False

    def _require_auth(self) -> bool:
        if not self._authenticated():
            self._json({"error": "Reopen Home using its launcher"}, 401)
            return False
        return True

    def do_GET(self) -> None:
        if not self._origin_ok():
            return
        path = urlsplit(self.path).path
        if path == "/api/session":
            if self._authenticated():
                self._json({"csrf": self.server.csrf})
                return
            token = self.headers.get("X-Home-Launch", "")
            with self.server.auth_lock:
                valid = bool(self.server.launch_token) and same_secret(token, self.server.launch_token)
                if valid:
                    self.server.launch_token = ""
            if valid:
                self._json({"csrf": self.server.csrf}, cookie=True)
            else:
                self._json({"error": "Reopen Home using its launcher"}, 401)
            return
        if path.startswith("/api/"):
            if not self._require_auth():
                return
            try:
                if path == "/api/state":
                    rooms = self.server.store.list_rooms()
                    room = self.server.store.room(rooms[0]["id"]) if rooms else None
                    self._json({"agents": self.server.council.agents_info(), "rooms": rooms, "room": room,
                                "fixture": self.server.fixture, **self._registry_state()})
                elif path.startswith("/api/rooms/") and len(path.split("/")) == 4:
                    self._json(self.server.store.room(path.split("/")[3]))
                else:
                    self._json({"error": "Unknown endpoint"}, 404)
            except HomeError as error:
                self._json({"error": str(error)[:200]}, error.status)
            except (ValueError, KeyError):
                self._json({"error": "That room is unavailable"}, 404)
            except Exception:  # noqa: BLE001 - keep internal exception details out of HTTP responses.
                self._json({"error": "Home could not read that record"}, 500)
            return
        filename = "index.html" if path == "/" else path.removeprefix("/")
        # Static assets are single package files, not arbitrary user paths.
        if "/" in filename or "\\" in filename or filename.startswith("."):
            self._json({"error": "Unknown page"}, 404)
            return
        target = WEB / filename
        content_type = STATIC_TYPES.get(target.suffix)
        if content_type is None or not target.is_file():
            self._json({"error": "Unknown page"}, 404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self._headers(content_type, len(body))
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise ValueError("Use JSON for this action")
        if self.headers.get("Transfer-Encoding") is not None:
            raise ValueError("Chunked requests are unsupported")
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError as error:
            raise ValueError("Invalid request length") from error
        if not 0 <= length <= 96 * 1024:
            raise ValueError("Request is too large or has no length")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("Request body ended before its declared length")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Expected an action object")  # noqa: TRY004 - preserve JSON validation's ValueError contract.
        return value

    def _registry_state(self) -> dict[str, Any]:
        """Bindings the owner may add from (id/label/provider only) and archived homes.
        A council without registry management reports neither."""
        council = self.server.council
        bindings = getattr(council, "bindings_info", None)
        archived: list[dict[str, Any]] = []
        if hasattr(council, "bindings_info"):
            archived = [a for a in council.agents_info(include_archived=True) if a.get("archived")]
        return {"resident_bindings": bindings() if bindings else [], "archived_agents": archived,
                "capabilities": self._capabilities()}

    def _capabilities(self) -> dict[str, int]:
        """Limits the Council actually enforces. A Council that cannot report them gets a
        conservative estimate from its visible residents rather than the 64-resident claim."""
        report = getattr(self.server.council, "capabilities_info", None)
        if report is not None:
            return dict(report())
        count = len(self.server.council.agents_info())
        return {"max_residents": count, "max_participants": count,
                "max_provider_calls": 2 * count + 1 if count >= 2 else min(count, 1),
                "max_workers": 1, "max_prompt_bytes": MAX_PROMPT_BYTES}

    @staticmethod
    def _fields(body: dict[str, Any], allowed: set[str]) -> None:
        if set(body) - allowed:
            raise ValueError("Unexpected action fields")

    def do_POST(self) -> None:
        if not self._origin_ok() or not self._require_auth():
            return
        if not same_secret(self.headers.get("X-CSRF-Token", ""), self.server.csrf):
            self._json({"error": "Refresh Home before sending this action"}, 403)
            return
        try:
            body = self._body()
            parts = urlsplit(self.path).path.strip("/").split("/")
            if parts == ["api", "rooms"]:
                self._fields(body, {"title"})
                result = self.server.store.create_room(body.get("title", "Commons"))
            elif len(parts) == 4 and parts[:2] == ["api", "rooms"] and parts[3] == "rounds":
                self._fields(body, {"text", "participants", "request_id", "mode", "artifact_ids"})
                result = self.server.council.start(parts[2], body.get("text"), body.get("participants"), body.get("request_id"), body.get("mode", "council"), body.get("artifact_ids"))
            elif len(parts) == 4 and parts[:2] == ["api", "rounds"] and parts[3] == "cancel":
                self._fields(body, set())
                result = self.server.council.cancel(parts[2])
            elif len(parts) == 4 and parts[:2] == ["api", "rounds"] and parts[3] == "resume":
                self._fields(body, set())
                result = self.server.council.resume(parts[2], retry_interrupted=False)
            elif parts == ["api", "agents"]:
                # Only a configured binding_id is accepted; executable, workspace, session and
                # model stay in local trusted configuration.
                self._fields(body, {"name", "role", "binding_id"})
                result = self.server.council.add_resident(body.get("name"), body.get("role"), body.get("binding_id"))
            elif len(parts) == 4 and parts[:2] == ["api", "agents"] and parts[3] in ("archive", "restore"):
                self._fields(body, set())
                action = self.server.council.archive_resident if parts[3] == "archive" else self.server.council.restore_resident
                result = action(parts[2])
            elif len(parts) == 4 and parts[:2] == ["api", "rooms"] and parts[3] == "artifacts":
                self._fields(body, {"title", "content", "artifact_id", "expected_version"})
                result = self.server.store.save_artifact(parts[2], body.get("title"), body.get("content"), body.get("artifact_id"), body.get("expected_version"))
            else:
                self._json({"error": "Unknown action"}, 404)
                return
            self._json(result)
        except HomeError as error:
            self._json({"error": str(error)[:200]}, error.status)
        except (ValueError, TypeError, KeyError) as error:
            # Store/domain validation messages are intentionally safe for the owner.
            summary = str(error)[:200] or "Invalid action"
            self._json({"error": summary}, 400)
        except Exception:  # noqa: BLE001 - preserve a safe HTTP failure for unexpected boundary errors.
            self._json({"error": "Home could not complete that action; your saved work remains available"}, 500)
