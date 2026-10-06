import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from home.models import (
    ConflictError,
    NotFoundError,
    StoreLockedError,
    UnsupportedSchemaError,
    ValidationError,
)
from home.store import SCHEMA_VERSION, Store


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
