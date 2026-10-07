"""Resident registry over the live loopback HTTP boundary, with a real Store/Council and fixtures."""
import json
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from home.council import Council
from home.fixture import FixtureProvider
from home.residents import ResidentBinding, demo_registry, fixture_binding
from home.server import HomeServer
from home.store import Store


class ResidentHTTP(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        web = Path(self.directory.name) / "web"
        web.mkdir()
        (web / "index.html").write_text("<!doctype html>", encoding="utf-8")
        self.static_patch = patch("home.server.WEB", web)
        self.static_patch.start()
        self.gate = threading.Event()
        _, seeds = demo_registry()
        gated = ResidentBinding("gated", "Gated fixture (simulated)", "fixture",
                                lambda name: FixtureProvider(name, gate=self.gate))
        self.store = Store(Path(self.directory.name) / "home.sqlite3")
        self.room = self.store.create_room("Commons")["id"]
        self.council = Council(self.store, bindings=[fixture_binding(delay=0), gated], seeds=seeds)
        self.server = HomeServer(0, self.store, self.council, fixture=True)
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.worker.start()
        token = urlsplit(self.server.launch_url).fragment.removeprefix("launch=")
        status, headers, body = self.request("GET", "/api/session",
                                             headers={"X-Home-Launch": token, "Origin": self.origin})
        self.assertEqual(status, 200)
        cookie = SimpleCookie(headers["Set-Cookie"])
        self.cookie = f"{self.server.cookie_name}={cookie[self.server.cookie_name].value}"
        self.csrf = body["csrf"]

    def tearDown(self):
        self.gate.set()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)
        self.council.close()
        self.store.close()
        self.static_patch.stop()

    def request(self, method, path, body=None, headers=None, auth=False):
        request_headers = dict(headers or {})
        if auth:
            request_headers.setdefault("Cookie", self.cookie)
            request_headers.setdefault("Origin", self.origin)
            request_headers.setdefault("X-CSRF-Token", self.csrf)
        if isinstance(body, dict):
            body = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            raw = response.read()
            value = json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw
            return response.status, dict(response.getheaders()), value
        finally:
            connection.close()

    def post(self, path, body, **kw):
        return self.request("POST", path, body, auth=True, **kw)

    def state(self):
        status, _, body = self.request("GET", "/api/state", auth=True)
        self.assertEqual(status, 200)
        return body

    def settle(self, round_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            saved = self.store.round(round_id)
            if saved["status"] in ("completed", "failed", "cancelled", "interrupted") and \
                    not any(t["status"] in ("queued", "running") for t in saved["turns"]):
                return saved
            time.sleep(0.01)
        self.fail("round did not settle")

    def test_state_exposes_bindings_without_secrets_and_archived_homes(self):
        body = self.state()
        self.assertEqual([a["id"] for a in body["agents"]], ["echo", "quill"])
        self.assertEqual(body["archived_agents"], [])
        self.assertEqual({b["id"] for b in body["resident_bindings"]}, {"fixture", "gated"})
        for binding in body["resident_bindings"]:
            self.assertEqual(set(binding), {"id", "label", "provider"})
        for agent in body["agents"]:
            self.assertEqual(set(agent), {"id", "name", "provider", "role", "binding_id", "home_slot",
                                          "archived", "available"})

    def test_http_draft_history_is_metadata_only_and_exact_body_requires_owned_room(self):
        first = self.store.save_artifact(self.room, "Original", "Synthetic original text")
        self.store.save_artifact(self.room, "Revision", "Synthetic revised text", first["id"], 1)
        status, _, room = self.request("GET", f"/api/rooms/{self.room}", auth=True)
        self.assertEqual(status, 200)
        self.assertEqual([2, 1], [item["version"] for item in room["artifacts"]])
        self.assertTrue(all("content" not in item for item in room["artifacts"]))
        status, _, exact = self.request("GET", f"/api/rooms/{self.room}/artifacts/{first['id']}/versions/1", auth=True)
        self.assertEqual((status, exact["content"], exact["sha256"]),
                         (200, first["content"], first["sha256"]))
        other = self.store.create_room("Other synthetic room")["id"]
        status, _, body = self.request("GET", f"/api/rooms/{other}/artifacts/{first['id']}/versions/1", auth=True)
        self.assertEqual(status, 404)
        self.assertNotIn(first["content"], json.dumps(body))
        status, _, _ = self.request("GET", f"/api/rooms/{self.room}/artifacts/{first['id']}/versions/1")
        self.assertEqual(status, 401)

    def test_state_capabilities_match_enforced_limits(self):
        self.assertEqual(self.state()["capabilities"],
                         {"max_residents": 64, "max_participants": 64, "max_provider_calls": 129,
                          "max_workers": 4, "max_active_rounds": 8, "max_prompt_bytes": 131072})
        status, _, _ = self.request("GET", "/api/state")  # still behind the session cookie
        self.assertEqual(status, 401)
        status, _, _ = self.request("GET", "/api/state", auth=True, headers={"Origin": "http://evil.test"})
        self.assertEqual(status, 403)
        status, _, body = self.post(f"/api/rooms/{self.room}/rounds",
                                    {"text": "x", "participants": ["echo", "quill"], "request_id": "cap",
                                     "max_workers": 64})
        self.assertEqual((status, body["error"]), (400, "Unexpected action fields"))
        self.assertEqual(self.store.room(self.room)["rounds"], [])

    def test_council_without_limits_report_gets_a_conservative_estimate(self):
        class Plain:
            def agents_info(self):
                return [{"id": "a"}, {"id": "b"}]

        self.server.council = Plain()
        self.assertEqual(self.state()["capabilities"],
                         {"max_residents": 2, "max_participants": 2, "max_provider_calls": 5,
                          "max_workers": 1, "max_prompt_bytes": 131072})
        self.server.council = self.council

    def test_add_reply_archive_restore_round_trip(self):
        status, _, added = self.post("/api/agents", {"name": "Nova", "role": "writer", "binding_id": "fixture"})
        self.assertEqual(status, 200)
        self.assertTrue(added["id"].startswith("res-"))
        self.assertEqual((added["name"], added["home_slot"]), ("Nova (fixture)", 2))
        status, _, started = self.post(f"/api/rooms/{self.room}/rounds",
                                       {"text": "hi", "participants": [added["id"]], "request_id": "h1",
                                        "mode": "direct"})
        self.assertEqual(status, 200)
        self.assertEqual(self.settle(started["id"])["status"], "completed")
        status, _, archived = self.post(f"/api/agents/{added['id']}/archive", {})
        self.assertEqual((status, archived["archived"]), (200, True))
        body = self.state()
        self.assertNotIn(added["id"], [a["id"] for a in body["agents"]])
        self.assertEqual([a["id"] for a in body["archived_agents"]], [added["id"]])
        self.assertIn("Nova (fixture)", [m["agent_name"] for m in body["room"]["messages"]])
        status, _, error = self.post(f"/api/rooms/{self.room}/rounds",
                                     {"text": "again", "participants": [added["id"]], "request_id": "h2",
                                      "mode": "direct"})
        self.assertEqual(status, 400)
        self.assertIn("archived", error["error"])
        status, _, restored = self.post(f"/api/agents/{added['id']}/restore", {})
        self.assertEqual((status, restored["archived"], restored["home_slot"]), (200, False, 2))
        status, _, _ = self.post(f"/api/agents/{added['id']}/restore", {})
        self.assertEqual(status, 409)
        status, _, _ = self.post("/api/agents/res-unknown/archive", {})
        self.assertEqual(status, 404)

    def test_injected_trusted_fields_are_rejected_without_mutation(self):
        before = self.store.residents()
        for extra in ({"executable": "C:/evil.exe"}, {"workspace": "C:/"}, {"session_id": "stolen"},
                      {"model": "other"}, {"provider": "claude"}, {"id": "echo"}, {"home_slot": 0}):
            status, _, body = self.post("/api/agents", {"name": "X", "role": "", "binding_id": "fixture", **extra})
            self.assertEqual(status, 400, extra)
            self.assertIn("Unexpected", body["error"])
        for path in ("/api/agents/echo/archive", "/api/agents/echo/restore"):
            status, _, _ = self.post(path, {"binding_id": "gated"})
            self.assertEqual(status, 400)
        status, _, _ = self.post("/api/agents", {"name": "X", "role": "", "binding_id": "nope"})
        self.assertEqual(status, 400)
        self.assertEqual(self.store.residents(), before)

    def test_registry_actions_require_cookie_csrf_and_origin(self):
        before = self.store.residents()
        payload = json.dumps({"name": "X", "role": "", "binding_id": "fixture"}).encode("utf-8")
        common = {"Content-Type": "application/json"}
        attempts = [
            {**common, "Origin": self.origin, "X-CSRF-Token": self.csrf},  # no cookie
            {**common, "Origin": self.origin, "Cookie": self.cookie},  # no CSRF
            {**common, "Origin": "http://evil.example", "Cookie": self.cookie, "X-CSRF-Token": self.csrf},
        ]
        for headers in attempts:
            status, _, _ = self.request("POST", "/api/agents", payload, headers=headers)
            self.assertIn(status, (401, 403), headers)
            status, _, _ = self.request("POST", "/api/agents/echo/archive", b"{}", headers=headers)
            self.assertIn(status, (401, 403), headers)
        self.assertEqual(self.store.residents(), before)

    def test_archive_conflicts_during_call_and_resume_route(self):
        status, _, slow = self.post("/api/agents", {"name": "Slow", "role": "", "binding_id": "gated"})
        self.assertEqual(status, 200)
        status, _, started = self.post(f"/api/rooms/{self.room}/rounds",
                                       {"text": "hold", "participants": [slow["id"], "echo"], "request_id": "g1"})
        self.assertEqual(status, 200)
        status, _, _ = self.post(f"/api/agents/{slow['id']}/archive", {})
        self.assertEqual(status, 409)
        status, _, _ = self.post(f"/api/rounds/{started['id']}/cancel", {})
        self.assertEqual(status, 200)
        deadline = time.monotonic() + 5
        while self.council._drivers and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.settle(started["id"])["status"], "cancelled")
        status, _, _ = self.post(f"/api/rounds/{started['id']}/resume", {"retry_interrupted": True})
        self.assertEqual(status, 400)  # no permissive retry flag over HTTP
        self.gate.set()
        status, _, resumed = self.post(f"/api/rounds/{started['id']}/resume", {})
        self.assertEqual(status, 200)
        self.assertEqual(resumed["id"], started["id"])
        outcome = self.settle(started["id"])["status"]
        self.assertIn(outcome, ("completed", "interrupted"))
        calls = sum(len(adapter.calls) for adapter in self.council.adapters.values())
        status, _, result = self.post(f"/api/rounds/{started['id']}/resume", {})
        if outcome == "completed":
            self.assertEqual(status, 409)
        else:
            # Timing can leave a launched call with an unknown outcome. Safe resume remains
            # available, but must never replay that call without the explicit Python flag.
            self.assertEqual(status, 200)
            self.assertEqual(result["id"], started["id"])
            self.assertEqual(self.settle(started["id"])["status"], "interrupted")
            self.assertEqual(sum(len(adapter.calls) for adapter in self.council.adapters.values()), calls)


if __name__ == "__main__":
    unittest.main()
