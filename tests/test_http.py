"""Live loopback HTTP boundary tests with inert Store/Council stubs."""
import http.cookiejar
import json
import socket
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.cookies import SimpleCookie
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
            if method == "POST":
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
            for server in (self.server, second):
                origin = f"http://127.0.0.1:{server.server_address[1]}"
                request = Request(origin + "/api/session", headers={
                    "Origin": origin, "X-Home-Launch": server.launch_token})
                with browser.open(request, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                    self.assertTrue(json.load(response)["csrf"])
                    for attribute in ("HttpOnly", "SameSite=Strict", "Path=/"):
                        self.assertIn(attribute, response.headers["Set-Cookie"])

            # Browser cookies are shared across localhost ports. Both must remain valid
            # after the second launch rather than silently replacing the first login.
            for server, fixture in ((self.server, True), (second, False)):
                origin = f"http://127.0.0.1:{server.server_address[1]}"
                with browser.open(Request(origin + "/api/state", headers={"Origin": origin}),
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
                status, _, value = self.request("POST", "/api/rooms", body, headers, authenticated=True)
                self.assertEqual(status, 400)
                self.assertIn("error", value)
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
