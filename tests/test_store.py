import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

from home.models import (
    ConflictError,
    NotFoundError,
    Reply,
    StoreLockedError,
    UnsupportedSchemaError,
    ValidationError,
)
from home.store import MIGRATIONS, SCHEMA_VERSION, Store


def plain_context(history, older, artifacts, text):
    return "\n".join([a["content"] for a in artifacts] + [text])


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "home.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self._close)

    def _close(self):
        if self.store is not None:
            self.store.close()
            self.store = None

    def reopen(self):
        self._close()
        self.store = Store(self.path)

    def make_round(self, room_id, request_id="r1", sha="h1", participants=("a", "b"), artifact_ids=()):
        return self.store.create_round(
            room_id=room_id, request_id=request_id, request_sha256=sha, mode="council", text="hello",
            participants=list(participants), artifact_ids=list(artifact_ids), first_phase="proposal",
            build_context=plain_context)


class RoomsAndArtifacts(StoreCase):
    def test_browser_artifact_pages_are_bounded_and_exact_versions_survive(self):
        room = self.store.create_room("Synthetic history")
        content = "x" * 65536
        artifact_id = None
        for version in range(1, 106):
            saved = self.store.save_artifact(room["id"], f"Draft {version}", content, artifact_id,
                                            version - 1 if artifact_id else None)
            artifact_id = saved["id"]
        browser = self.store.room_for_browser(room["id"])
        self.assertEqual(list(range(105, 5, -1)), [item["version"] for item in browser["artifacts"]])
        self.assertLess(len(json.dumps(browser).encode()), 65536)
        self.assertTrue(all("content" not in item and "versions" not in item for item in browser["artifacts"]))
        older = self.store.artifact_page(room["id"], int(browser["next_artifact_cursor"]))
        self.assertEqual([5, 4, 3, 2, 1], [item["version"] for item in older["artifacts"]])
        self.assertIsNone(older["next_artifact_cursor"])
        exact = self.store.artifact_version(room["id"], artifact_id, 1)
        self.assertEqual((1, content, hashlib.sha256(content.encode()).hexdigest()),
                         (exact["version"], exact["content"], exact["sha256"]))
        self.assertEqual(105, exact["latest_version"])
        self.assertTrue(all(item["latest_version"] == 105 for item in browser["artifacts"]))
        self.assertEqual(105, len(self.store.room(room["id"])["artifacts"][0]["versions"]))
        foreign = self.store.create_room("Other room")["id"]
        with self.assertRaises(NotFoundError):
            self.store.artifact_version(foreign, artifact_id, 1)
        for bad in (0, -1, True, "1", 2**63):
            with self.subTest(cursor=bad), self.assertRaises(ValidationError):
                self.store.artifact_page(room["id"], bad)
            with self.subTest(version=bad), self.assertRaises(ValidationError):
                self.store.artifact_version(room["id"], artifact_id, bad)

    def test_restored_old_version_reports_latest_even_outside_newest_page(self):
        room = self.store.create_room("Synthetic revision selection")["id"]
        old = self.store.save_artifact(room, "Older draft", "Version one")
        for version in range(2, 6):
            self.store.save_artifact(room, "Older draft", f"Version {version}", old["id"], version - 1)
        newer = self.store.save_artifact(room, "Newer draft", "Newer version one")
        for version in range(2, 106):
            self.store.save_artifact(room, "Newer draft", f"Newer version {version}", newer["id"], version - 1)
        page = self.store.room_for_browser(room)
        self.assertTrue(all(item["id"] == newer["id"] for item in page["artifacts"]))
        restored = self.store.artifact_version(room, old["id"], 1)
        self.assertEqual((1, 5, "Version one"),
                         (restored["version"], restored["latest_version"], restored["content"]))
        older = self.store.artifact_page(room, int(page["next_artifact_cursor"]))
        old_metadata = [item for item in older["artifacts"] if item["id"] == old["id"]]
        self.assertTrue(old_metadata)
        self.assertTrue(all(item["latest_version"] == 5 for item in old_metadata))

    def test_room_pages_are_bounded_and_older_rooms_remain_addressable(self):
        rooms = [self.store.create_room(f"Room {index}")["id"] for index in range(105)]
        page = self.store.list_rooms_page()
        self.assertEqual(list(reversed(rooms[5:])), [room["id"] for room in page["rooms"]])
        older = self.store.list_rooms_page(int(page["next_room_cursor"]))
        self.assertEqual(list(reversed(rooms[:5])), [room["id"] for room in older["rooms"]])
        self.assertIsNone(older["next_room_cursor"])
        self.assertEqual(rooms[0], self.store.room_for_browser(rooms[0])["id"])
        self.assertEqual(105, len(self.store.list_rooms()))
        for bad in (0, -1, True, "1", 2**63):
            with self.subTest(cursor=bad), self.assertRaises(ValidationError):
                self.store.list_rooms_page(bad)

    def test_room_shapes_are_json_dicts(self):
        room = self.store.create_room("Commons")
        self.assertEqual({"id", "title", "created_at"}, set(room))
        self.assertEqual([room["id"]], [r["id"] for r in self.store.list_rooms()])
        full = self.store.room(room["id"])
        for key in ("messages", "rounds", "artifacts"):
            self.assertEqual([], full[key])
        with self.assertRaises(NotFoundError):
            self.store.room("missing")

    def test_versions_append_and_conflict_never_overwrites(self):
        room = self.store.create_room()
        v1 = self.store.save_artifact(room["id"], "Script", "Opening one")
        self.assertEqual({"id", "title", "version", "content", "sha256", "created_at"}, set(v1))
        self.assertEqual(hashlib.sha256(b"Opening one").hexdigest(), v1["sha256"])
        v2 = self.store.save_artifact(room["id"], "Script", "Opening two", artifact_id=v1["id"], expected_version=1)
        self.assertEqual((v1["id"], 2), (v2["id"], v2["version"]))
        with self.assertRaises(ConflictError):  # a stale editor still thinks version 1 is latest
            self.store.save_artifact(room["id"], "Script", "Stale edit", artifact_id=v1["id"], expected_version=1)
        with self.assertRaises(ValidationError):
            self.store.save_artifact(room["id"], "Script", "No version", artifact_id=v1["id"])
        artifact = self.store.room(room["id"])["artifacts"][0]
        self.assertEqual(["Opening one", "Opening two"], [v["content"] for v in artifact["versions"]])
        self.assertEqual(2, artifact["version"])

    def test_artifact_bounds_and_room_ownership(self):
        a, b = self.store.create_room("A"), self.store.create_room("B")
        with self.assertRaises(ValidationError):
            self.store.save_artifact(a["id"], "Big", "x" * (64 * 1024 + 1))
        saved = self.store.save_artifact(a["id"], "Script", "text")
        with self.assertRaises(NotFoundError):
            self.store.save_artifact(b["id"], "Script", "hijack", artifact_id=saved["id"], expected_version=1)


class Rounds(StoreCase):
    def test_browser_round_preserves_recovery_state_without_duplicate_or_native_content(self):
        room = self.store.create_room()["id"]
        saved, _ = self.store.create_round(
            room_id=room, request_id="synthetic-round", request_sha256="synthetic-hash", mode="direct",
            text="hello", participants=["a"], artifact_ids=[], first_phase="reply", build_context=plain_context,
            participant_snapshots={"a": {"name": "Example", "provider": "fixture", "role": "Synthetic private role"}})
        self.store.mark_round_running(saved["id"])
        self.store.claim_turn(saved["turns"][0]["id"])
        reply = Reply("Synthetic reply body", "fixture", "synthetic-native-session", "synthetic-model")
        self.store.complete_turn(saved["turns"][0]["id"], reply, save_session=True)
        self.store.cancel_round(saved["id"])
        browser = self.store.room_for_browser(room)
        full = self.store.room(room)
        summary_round = browser["rounds"][0]
        full_round = full["rounds"][0]
        for field in ("id", "status", "mode", "participants", "max_calls", "context_bytes", "note"):
            self.assertEqual(full_round[field], summary_round[field])
        self.assertEqual({"a": {"name": "Example", "provider": "fixture"}}, summary_round["participant_snapshots"])
        summary_turn = summary_round["turns"][0]
        for field in ("id", "status", "phase", "launched", "agent_id", "provider", "error"):
            self.assertEqual(full_round["turns"][0][field], summary_turn[field])
        for omitted in ("content", "session_id", "model"):
            self.assertNotIn(omitted, summary_turn)
        encoded = json.dumps(browser)
        self.assertEqual(1, encoded.count(reply.text))  # authoritative message, never duplicated in a turn
        self.assertNotIn("synthetic-native-session", encoded)
        self.assertNotIn("Synthetic private role", encoded)
        self.assertEqual(reply.session_id, full_round["turns"][0]["session_id"])

    def test_request_id_is_idempotent_and_mismatch_is_rejected(self):
        room = self.store.create_room()
        first, created = self.make_round(room["id"])
        again, created_again = self.make_round(room["id"])
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["id"], again["id"])
        with self.assertRaises(ConflictError):
            self.make_round(room["id"], sha="different payload")
        self.assertEqual(1, len(self.store.room(room["id"])["messages"]))

    def test_database_allows_one_active_round_per_room(self):
        room = self.store.create_room()
        self.make_round(room["id"], "r1", "h1")
        with self.assertRaises(ConflictError):
            self.make_round(room["id"], "r2", "h2")
        # Exercise the database constraint itself as well as the domain check above.
        with self.assertRaises(sqlite3.IntegrityError), self.store._tx() as db:
            db.execute("INSERT INTO rounds (id, room_id, request_id, request_sha256, mode, status, "
                       "active_room, participants, artifacts, context, context_sha256, owner_message_id, "
                       "created_at, updated_at) SELECT 'x', room_id, 'r9', 'h', mode, 'queued', room_id, "
                       "participants, artifacts, context, context_sha256, owner_message_id, created_at, "
                       "updated_at FROM rounds")

    def test_recovery_marks_unfinished_work_interrupted_without_relaunch(self):
        room = self.store.create_room()
        saved, _ = self.make_round(room["id"])
        self.assertTrue(self.store.mark_round_running(saved["id"]))
        running = saved["turns"][0]
        self.assertTrue(self.store.claim_turn(running["id"]))
        self.reopen()
        self.assertEqual([saved["id"]], self.store.recover_unfinished())
        after = self.store.round(saved["id"])
        self.assertEqual("interrupted", after["status"])
        states = {t["id"]: (t["status"], t["launched"]) for t in after["turns"]}
        self.assertEqual(("interrupted", True), states[running["id"]])
        self.assertEqual(("interrupted", False), states[saved["turns"][1]["id"]])
        self.assertIsNone(self.store.list_rooms()[0]["active_round_id"])


class SchemaAndLocking(StoreCase):
    @unittest.skipUnless(os.name == "posix", "POSIX mode checks do not establish Windows ACL permissions")
    def test_new_data_root_and_database_are_private_under_permissive_umask(self):
        path = Path(self.tmp.name) / "new-private-root" / "home.sqlite"
        previous_umask = os.umask(0o022)
        private = None
        try:
            private = Store(path)
            private.create_room("Synthetic permission fixture")
            self.assertEqual(0o700, stat.S_IMODE(path.parent.stat().st_mode))
            for file in (path, path.with_name(path.name + ".lock"),
                         path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
                if file.exists():
                    self.assertEqual(0o600, stat.S_IMODE(file.stat().st_mode), file.name)
        finally:
            if private is not None:
                private.close()
            os.umask(previous_umask)

    def test_schema_two_upgrade_adds_indexes_without_rewriting_saved_content(self):
        older_path = Path(self.tmp.name) / "schema-two.sqlite"
        db = sqlite3.connect(older_path)
        db.executescript(f"BEGIN;\n{MIGRATIONS[1]}\n{MIGRATIONS[2]}\nPRAGMA user_version = 2;\nCOMMIT;")
        db.execute("INSERT INTO rooms VALUES ('synthetic-old-room', 'Original room', 'synthetic-date')")
        db.execute("INSERT INTO artifacts VALUES ('synthetic-old-draft', 'synthetic-old-room', 'synthetic-date')")
        digest = hashlib.sha256(b"Original draft").hexdigest()
        db.execute("INSERT INTO artifact_versions VALUES (?, ?, ?, ?, ?, ?)",
                   ("synthetic-old-draft", 1, "Original title", "Original draft", digest, "synthetic-date"))
        db.commit()
        db.close()
        upgraded = Store(older_path)
        try:
            exact = upgraded.artifact_version("synthetic-old-room", "synthetic-old-draft", 1)
            self.assertEqual(("Original draft", digest), (exact["content"], exact["sha256"]))
            self.assertEqual(SCHEMA_VERSION, upgraded._db.execute("PRAGMA user_version").fetchone()[0])
            indexes = {row[0] for row in upgraded._db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
            self.assertTrue({"rounds_by_room", "artifacts_by_room"} <= indexes)
            plan = [row[3] for row in upgraded._db.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM rounds WHERE room_id = ? ORDER BY seq DESC LIMIT 50",
                ("synthetic-old-room",))]
            self.assertTrue(any("rounds_by_room" in item for item in plan))
        finally:
            upgraded.close()

    def test_future_schema_is_refused_and_left_untouched(self):
        self._close()
        db = sqlite3.connect(self.path)
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        db.close()
        before = self.path.read_bytes()
        with self.assertRaises(UnsupportedSchemaError):
            Store(self.path)
        self.assertEqual(before, self.path.read_bytes())
        db = sqlite3.connect(self.path)
        self.assertEqual(SCHEMA_VERSION + 1, db.execute("PRAGMA user_version").fetchone()[0])
        db.close()

    def test_unversioned_foreign_database_is_refused(self):
        other = Path(self.tmp.name) / "other.sqlite3"
        db = sqlite3.connect(other)
        db.execute("CREATE TABLE notes (x)")
        db.commit()
        db.close()
        with self.assertRaises(UnsupportedSchemaError):
            Store(other)

    def test_one_server_per_data_root(self):
        with self.assertRaises(StoreLockedError):
            Store(self.path)
        self.reopen()  # released on close, reusable afterwards
        self.assertEqual([], self.store.list_rooms())


if __name__ == "__main__":
    unittest.main()
