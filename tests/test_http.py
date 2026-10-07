"""Live loopback HTTP boundary tests with inert Store/Council stubs."""
import http.cookiejar
import json
import socket
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection, RemoteDisconnected
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from home.server import HomeServer


class StubStore:
    def __init__(self):
        self.calls = []
        self.rooms = {"room-1": {"id": "room-1", "title": "Commons", "messages": [],
                                  "rounds": [], "artifacts": []}}

    def list_rooms(self):
        return [{"id": key, "title": value["title"]} for key, value in self.rooms.items()]

    def list_rooms_page(self, before=None):
        self.calls.append(("list_rooms_page", before))
        return {"rooms": self.list_rooms(), "next_room_cursor": None}

    def room_for_browser(self, room_id):
        return self.room(room_id)

    def artifact_page(self, room_id, before=None):
        self.calls.append(("artifact_page", room_id, before))
        return {"artifacts": [], "next_artifact_cursor": None}

    def artifact_version(self, room_id, artifact_id, version):
        self.calls.append(("artifact_version", room_id, artifact_id, version))
        return {"id": artifact_id, "version": version, "content": "Synthetic draft"}

    def round_for_browser(self, round_id):
        return {"id": round_id, "status": "queued", "participants": ["claude", "codex"]}

    def room(self, room_id):
        self.calls.append(("room", room_id))
        if room_id == "explode":
            raise RuntimeError("private-database-path sk-secret")
        return self.rooms[room_id]

    def create_room(self, title="Commons"):
        self.calls.append(("create_room", title))
        if not isinstance(title, str):
            # Match safe parsed-request validation rather than Python caller typing.
            raise ValueError("Room title must contain text")  # noqa: TRY004
        return {"id": "new-room", "title": title}

    def save_artifact(self, room_id, title, content, artifact_id=None, expected_version=None):
        self.calls.append(("save_artifact", room_id, title, content, artifact_id, expected_version))
        return {"id": artifact_id or "new-artifact", "version": (expected_version or 0) + 1,
                "title": title, "content": content}


class StubCouncil:
    def __init__(self):
        self.calls = []

    def agents_info(self):
        return [{"id": "claude", "name": "Claude", "provider": "fixture"}]

    def start(self, room_id, text, participants, request_id, mode="council", artifact_ids=None):
        self.calls.append(("start", room_id, text, participants, request_id, mode, artifact_ids))
        if text == "explode":
            raise RuntimeError("private-config sk-secret")
        return {"id": "round-1", "status": "queued", "participants": participants}

    def cancel(self, round_id):
        self.calls.append(("cancel", round_id))
        return {"id": round_id, "status": "cancelled"}


class HTTPBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.web = Path(self.directory.name)
        (self.web / "index.html").write_text('<!doctype html><script src="app.js"></script>', encoding="utf-8")
        (self.web / "app.js").write_text('export const fixture = "inert";', encoding="utf-8")
        (self.web / "private.py").write_text("private", encoding="utf-8")
        self.static_patch = patch("home.server.WEB", self.web)
        self.static_patch.start()
        self.store, self.council = StubStore(), StubCouncil()
        self.server = HomeServer(0, self.store, self.council, fixture=True)
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.launch_token = urlsplit(self.server.launch_url).fragment.removeprefix("launch=")
        self.cookie = None
        self.csrf = None
        self.worker = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.05}, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)
        self.static_patch.stop()
        self.directory.cleanup()

    def request(self, method, path, body=None, headers=None, authenticated=False):
        request_headers = dict(headers or {})
        if authenticated:
            request_headers.setdefault("Cookie", self.cookie)
            request_headers.setdefault("X-CSRF-Token", self.csrf)
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            value = response.read()
            content_type = response.getheader("Content-Type", "")
            if content_type.startswith("application/json"):
                value = json.loads(value)
            return response.status, dict(response.getheaders()), value
        finally:
            connection.close()

    def bootstrap(self):
        status, headers, body = self.request("GET", "/api/session", headers={
            "X-Home-Launch": self.launch_token, "Origin": self.origin})
        self.assertEqual(status, 200)
        cookie = SimpleCookie(headers["Set-Cookie"])
        self.cookie = f"{self.server.cookie_name}={cookie[self.server.cookie_name].value}"
        self.csrf = body["csrf"]
        return headers

    def test_fragment_header_bootstrap_and_cookie_csrf(self):
        self.assertEqual(urlsplit(self.server.launch_url).path, "/")
        headers = self.bootstrap()
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertTrue(self.csrf)
        status, _, body = self.request("GET", "/api/session", authenticated=True)
        self.assertEqual((status, body["csrf"]), (200, self.csrf))
        status, _, body = self.request("GET", "/api/state", authenticated=True)
        self.assertEqual(status, 200)
        self.assertTrue(body["fixture"])
        self.assertEqual(body["room"]["id"], "room-1")

    def test_launch_token_is_one_use_and_not_accepted_as_query(self):
        status, _, _ = self.request("GET", f"/api/session?launch={self.launch_token}")
        self.assertEqual(status, 401)
        self.bootstrap()
        status, _, _ = self.request("GET", "/api/session", headers={"X-Home-Launch": self.launch_token})
        self.assertEqual(status, 401)

    def test_simultaneous_bootstrap_consumes_token_once(self):
        def attempt(_):
            return self.request("GET", "/api/session",
                                headers={"X-Home-Launch": self.launch_token})[0]
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(attempt, range(2)))
        self.assertEqual(sorted(statuses), [200, 401])

    def test_unauthorized_state_and_mutation_are_rejected_before_dispatch(self):
        for method, path, body in (("GET", "/api/state", None),
                                   ("POST", "/api/rooms", {"title": "Oops"}),
                                   ("GET", "/api/rooms/room-1", None)):
            with self.subTest(path=path):
                status, _, value = self.request(method, path, body)
                self.assertEqual(status, 401)
                self.assertIn("error", value)
        self.assertEqual(self.store.calls, [])
        self.assertEqual(self.council.calls, [])

    def test_invalid_cookie_does_not_authorize(self):
        self.bootstrap()
        status, _, _ = self.request("GET", "/api/state", headers={
            "Cookie": f"{self.server.cookie_name}=wrong"})
        self.assertEqual(status, 401)

    def test_two_servers_keep_sessions_in_one_browser_cookie_jar(self):
        second = HomeServer(0, StubStore(), StubCouncil(), fixture=False)
        worker = threading.Thread(target=second.serve_forever,
                                  kwargs={"poll_interval": 0.05}, daemon=True)
        worker.start()
        try:
            jar = http.cookiejar.CookieJar()
            browser = build_opener(HTTPCookieProcessor(jar))
            proofs = {}
            for server in (self.server, second):
                origin = f"http://127.0.0.1:{server.server_address[1]}"
                request = Request(origin + "/api/session", headers={
                    "Origin": origin, "X-Home-Launch": server.launch_token})
                with browser.open(request, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                    proofs[origin] = json.load(response)["csrf"]
                    self.assertTrue(proofs[origin])
                    for attribute in ("HttpOnly", "SameSite=Strict", "Path=/"):
                        self.assertIn(attribute, response.headers["Set-Cookie"])

            # Browser cookies are shared across localhost ports. Both must remain valid
            # after the second launch rather than silently replacing the first login.
            for server, fixture in ((self.server, True), (second, False)):
                origin = f"http://127.0.0.1:{server.server_address[1]}"
                with browser.open(Request(origin + "/api/state", headers={
                        "Origin": origin, "X-CSRF-Token": proofs[origin]}),
                                  timeout=3) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.load(response)["fixture"], fixture)

            self.assertNotEqual(self.server.cookie_name, second.cookie_name)
            self.assertEqual({cookie.name: cookie.value for cookie in jar}, {
                self.server.cookie_name: self.server.cookie_token,
                second.cookie_name: second.cookie_token,
            })
            # A sibling port's cookie or token must not authenticate this app.
            for cookie in (f"{second.cookie_name}={second.cookie_token}",
                           f"{self.server.cookie_name}={second.cookie_token}"):
                status, _, _ = self.request("GET", "/api/state", headers={"Cookie": cookie})
                self.assertEqual(status, 401)
        finally:
            second.shutdown()
            second.server_close()
            worker.join(timeout=2)

    def test_cookie_captured_by_sibling_http_service_cannot_read_or_mutate(self):
        captured = []

        class SiblingHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                captured.append(self.headers.get("Cookie", ""))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_):
                return

        sibling = ThreadingHTTPServer(("127.0.0.1", 0), SiblingHandler)
        worker = threading.Thread(target=sibling.serve_forever,
                                  kwargs={"poll_interval": 0.05}, daemon=True)
        worker.start()
        try:
            browser = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
            with browser.open(Request(self.origin + "/api/session", headers={
                    "X-Home-Launch": self.launch_token}), timeout=3) as response:
                csrf = json.load(response)["csrf"]
            with browser.open(f"http://127.0.0.1:{sibling.server_address[1]}/", timeout=3) as response:
                response.read()
            self.assertIn(self.server.cookie_name, captured[0])
            # The other service can forge Host/Origin but does not receive the
            # browser's origin-scoped proof in a request to its own port.
            headers = {"Cookie": captured[0], "Origin": self.origin}
            for method, path, body, status in (
                    ("GET", "/api/session", None, 401),
                    ("GET", "/api/state", None, 403),
                    ("GET", "/api/rooms/room-1", None, 403),
                    ("POST", "/api/rooms", {"title": "Unauthorized"}, 403)):
                with self.subTest(path=path):
                    actual, _, result = self.request(method, path, body, headers)
                    self.assertEqual(actual, status)
                    self.assertNotIn("csrf", result)
            for path in ("/api/session", "/api/state"):
                status, _, _ = self.request("GET", path, headers={
                    **headers, "X-CSRF-Token": csrf})
                self.assertEqual(status, 200)
            self.assertFalse(any(call[0] == "create_room" for call in self.store.calls))
        finally:
            sibling.shutdown()
            sibling.server_close()
            worker.join(timeout=2)

    def test_http_admission_is_bounded_before_headers_and_reuses_slots(self):
        entered = threading.Event()
        guard = threading.Lock()

        class BoundedServer(HomeServer):
            max_request_threads = 2
            active = 0
            maximum = 0

            def process_request_thread(self, request, client_address):
                with guard:
                    self.active += 1
                    self.maximum = max(self.maximum, self.active)
                    if self.active == 2:
                        entered.set()
                try:
                    super().process_request_thread(request, client_address)
                finally:
                    with guard:
                        self.active -= 1

        server = BoundedServer(0, StubStore(), StubCouncil(), fixture=True)
        worker = threading.Thread(target=server.serve_forever,
                                  kwargs={"poll_interval": 0.05}, daemon=True)
        worker.start()
        sockets = []
        try:
            port = server.server_address[1]
            for _ in range(2):
                connection = socket.create_connection(("127.0.0.1", port), timeout=3)
                sockets.append(connection)
                connection.sendall(b"GET / HTTP/1.1\r\n")
            self.assertTrue(entered.wait(timeout=2))
            overflow = HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                with self.assertRaises((RemoteDisconnected, ConnectionResetError, ConnectionAbortedError)):
                    overflow.request("GET", "/")
                    overflow.getresponse()
            finally:
                overflow.close()
            self.assertEqual(server.maximum, 2)
            for connection in sockets:
                connection.sendall(f"Host: 127.0.0.1:{port}\r\n\r\n".encode())
                while connection.recv(4096):
                    pass
                connection.close()
            sockets.clear()
            # A completed request must release its slot for ordinary town loads.
            connection = HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                connection.request("GET", "/")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
            finally:
                connection.close()
            self.assertLessEqual(server.maximum, 2)
        finally:
            for connection in sockets:
                connection.close()
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_bad_host_and_origin_are_rejected_even_with_auth(self):
        self.bootstrap()
        for header in ({"Host": "evil.example"}, {"Origin": "https://evil.example"}, {"Origin": "null"}):
            with self.subTest(header=header):
                status, _, _ = self.request("GET", "/api/state", headers=header, authenticated=True)
                self.assertEqual(status, 403)
                status, _, _ = self.request("POST", "/api/rooms", {"title": "Oops"},
                                            headers=header, authenticated=True)
                self.assertEqual(status, 403)
        self.assertEqual(self.store.calls, [])

    def test_missing_and_mismatched_csrf_reject_before_dispatch(self):
        self.bootstrap()
        for token in ("", "wrong"):
            with self.subTest(token=token):
                status, _, _ = self.request("POST", "/api/rooms", {"title": "Oops"},
                                            headers={"X-CSRF-Token": token}, authenticated=True)
                self.assertEqual(status, 403)
        self.assertEqual(self.store.calls, [])

    def test_nonascii_launch_rejects_without_connection_failure(self):
        status, _, _ = self.request("GET", "/api/session", headers={"X-Home-Launch": "é"})
        self.assertEqual(status, 401)

    def test_nonascii_csrf_rejects_without_connection_failure(self):
        self.bootstrap()
        status, _, _ = self.request("POST", "/api/rooms", {"title": "Oops"},
                                    headers={"X-CSRF-Token": "é"}, authenticated=True)
        self.assertEqual(status, 403)

    def test_unsupported_content_type_oversized_and_chunked_body(self):
        self.bootstrap()
        cases = (
            ({"Content-Type": "text/plain"}, b"{}"),
            ({"Content-Type": "application/json"}, b"x" * (96 * 1024 + 1)),
            ({"Content-Type": "application/json", "Transfer-Encoding": "chunked"}, b"{}"),
            ({"Content-Type": "application/json", "Content-Length": "-1"}, b""),
        )
        for headers, body in cases:
            with self.subTest(headers=headers):
                try:
                    status, _, value = self.request("POST", "/api/rooms", body, headers, authenticated=True)
                except (RemoteDisconnected, ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                    if len(body) <= 96 * 1024:
                        raise
                    # Oversized bodies are rejected before reading. Closing while
                    # inbound bytes remain can reset the connection on Windows.
                else:
                    self.assertEqual(status, 400)
                    self.assertIn("error", value)
                self.assertEqual(self.store.calls, [])
                self.assertEqual(self.council.calls, [])
                status, _, _ = self.request("GET", "/")
                self.assertEqual(status, 200)  # early rejection does not stop the server
        self.assertEqual(self.store.calls, [])

    def test_invalid_json_and_nonobject_body(self):
        self.bootstrap()
        for body in (b"not JSON", b"[]", b"null"):
            status, _, _ = self.request("POST", "/api/rooms", body,
                                        {"Content-Type": "application/json"}, authenticated=True)
            self.assertEqual(status, 400)
        self.assertEqual(self.store.calls, [])

    def test_missing_content_length_is_rejected_without_reading_body(self):
        self.bootstrap()
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.putrequest("POST", "/api/rooms")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Cookie", self.cookie)
            connection.putheader("X-CSRF-Token", self.csrf)
            connection.endheaders(b"{}")
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            self.assertIn("error", json.loads(response.read()))
        finally:
            connection.close()
        self.assertEqual(self.store.calls, [])

    def test_truncated_body_does_not_dispatch_even_when_prefix_is_valid_json(self):
        self.bootstrap()
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.putrequest("POST", "/api/rooms")
            for key, value in {"Content-Type": "application/json", "Content-Length": "20",
                               "Cookie": self.cookie, "X-CSRF-Token": self.csrf}.items():
                connection.putheader(key, value)
            connection.endheaders(b"{}")
            connection.sock.shutdown(socket.SHUT_WR)
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
        finally:
            connection.close()
        self.assertEqual(self.store.calls, [])

    def test_browser_executable_session_and_unknown_fields_never_dispatch(self):
        self.bootstrap()
        cases = (
            ("/api/rooms", {"title": "X", "executable": "untrusted"}),
            ("/api/rooms/room-1/rounds", {"text": "X", "participants": ["claude"],
                                            "request_id": "r", "workspace": "/untrusted"}),
            ("/api/rooms/room-1/rounds", {"text": "X", "participants": ["claude"],
                                            "request_id": "r", "session_id": "untrusted"}),
            ("/api/rooms/room-1/artifacts", {"title": "X", "content": "X", "path": "/untrusted"}),
            ("/api/rounds/round-1/cancel", {"unknown": True}),
        )
        for path, body in cases:
            with self.subTest(path=path, fields=list(body)):
                status, _, _ = self.request("POST", path, body, authenticated=True)
                self.assertEqual(status, 400)
        self.assertEqual(self.store.calls, [])
        self.assertEqual(self.council.calls, [])

    def test_room_round_cancel_and_artifact_routing(self):
        self.bootstrap()
        status, _, value = self.request("POST", "/api/rooms", {"title": "Studio"}, authenticated=True)
        self.assertEqual((status, value["title"]), (200, "Studio"))
        self.assertEqual(self.store.calls[-1], ("create_room", "Studio"))
        status, _, value = self.request("GET", "/api/rooms/room-1", authenticated=True)
        self.assertEqual((status, value["id"]), (200, "room-1"))
        body = {"text": "Discuss", "participants": ["claude", "codex"], "request_id": "request-1",
                "mode": "council", "artifact_ids": ["script"]}
        status, _, value = self.request("POST", "/api/rooms/room-1/rounds", body, authenticated=True)
        self.assertEqual((status, value["status"]), (200, "queued"))
        self.assertEqual(self.council.calls[-1], ("start", "room-1", "Discuss", ["claude", "codex"],
                                                 "request-1", "council", ["script"]))
        status, _, _ = self.request("POST", "/api/rounds/round-1/cancel", {}, authenticated=True)
        self.assertEqual(status, 200)
        self.assertEqual(self.council.calls[-1], ("cancel", "round-1"))
        body = {"title": "Opening", "content": "<script>alert('inert')</script>",
                "artifact_id": "script", "expected_version": 2}
        status, _, value = self.request("POST", "/api/rooms/room-1/artifacts", body, authenticated=True)
        self.assertEqual((status, value["version"], value["content"]), (200, 3, body["content"]))
        self.assertEqual(self.store.calls[-1], ("save_artifact", "room-1", "Opening", body["content"], "script", 2))

    def test_unknown_endpoints_and_missing_records(self):
        self.bootstrap()
        for method, path, body in (("GET", "/api/unknown", None),
                                   ("GET", "/api/rooms/missing", None),
                                   ("POST", "/api/unknown", {})):
            status, _, _ = self.request(method, path, body, authenticated=True)
            self.assertEqual(status, 404)

    def test_history_routes_use_bounded_pages_and_validate_cursors(self):
        self.bootstrap()
        for path, expected in (
                ("/api/rooms?before=105", ("list_rooms_page", 105)),
                ("/api/rooms/room-1/artifacts?before=205", ("artifact_page", "room-1", 205)),
                ("/api/rooms/room-1/artifacts/draft-1/versions/3", ("artifact_version", "room-1", "draft-1", 3))):
            with self.subTest(path=path):
                status, _, _ = self.request("GET", path, authenticated=True)
                self.assertEqual(status, 200)
                self.assertEqual(expected, self.store.calls[-1])
        calls_before = len(self.store.calls)
        for suffix in ("before=", "before=0", "before=-1", "before=1&before=2", "before=9223372036854775808", "unexpected=1"):
            for base in ("/api/rooms", "/api/rooms/room-1/artifacts"):
                with self.subTest(base=base, suffix=suffix):
                    status, _, _ = self.request("GET", base + "?" + suffix, authenticated=True)
                    self.assertEqual(status, 400)
        for version in ("0", "-1", "invalid", "9223372036854775808"):
            status, _, _ = self.request("GET", "/api/rooms/room-1/artifacts/draft-1/versions/" + version,
                                        authenticated=True)
            self.assertEqual(status, 400)
        self.assertEqual(calls_before, len(self.store.calls))

    def test_internal_errors_are_sanitized(self):
        self.bootstrap()
        for method, path, body in (
            ("GET", "/api/rooms/explode", None),
            ("POST", "/api/rooms/room-1/rounds", {"text": "explode"})):
            status, _, value = self.request(method, path, body, authenticated=True)
            self.assertEqual(status, 500)
            self.assertNotIn("sk-secret", json.dumps(value))
            self.assertNotIn("private", json.dumps(value))

    def test_static_is_inert_and_never_dispatches_or_exposes_arbitrary_files(self):
        for path, content_type in (("/", "text/html"), ("/app.js", "text/javascript")):
            status, headers, body = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertTrue(headers["Content-Type"].startswith(content_type))
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
            self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
            self.assertNotIn("Set-Cookie", headers)
            self.assertNotIn(self.launch_token.encode(), body)
            self.assertNotIn(self.server.cookie_token.encode(), body)
        for path in ("/../private.py", "/%2e%2e/private.py", "/private.py", "/.env", "/app.js/extra"):
            status, _, _ = self.request("GET", path)
            self.assertEqual(status, 404)
        self.assertEqual(self.store.calls, [])
        self.assertEqual(self.council.calls, [])


if __name__ == "__main__":
    unittest.main()
