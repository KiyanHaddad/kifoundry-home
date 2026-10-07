"""Resident registry with controlled fixture bindings. These prove mechanics, not live-provider quality."""

import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from home.council import Council
from home.fixture import FixtureProvider
from home.models import Agent, ConflictError, ProviderError, ValidationError
from home.residents import ResidentBinding, Seed, demo_registry, fixture_binding
from home.store import MIGRATIONS, SCHEMA_VERSION, Store

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def seed(key, name):
    return Seed(Agent(key, name, "fixture", f"{key} role"), "fixture")


class RegistryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "home.sqlite3"
        self.store = None
        self.council = None
        self.gate = threading.Event()
        self.addCleanup(self.gate.set)
        self.addCleanup(self.shutdown)

    def shutdown(self):
        if self.council is not None:
            self.council.close()
            self.council = None
        if self.store is not None:
            self.store.close()
            self.store = None

    def gated(self, ignore_cancel=False):
        return ResidentBinding("gated", "Gated fixture (simulated)", "fixture",
                               lambda name: FixtureProvider(name, gate=self.gate, ignore_cancel=ignore_cancel))

    def build(self, bindings=None, seeds=None):
        self.shutdown()
        self.store = Store(self.path)
        self.council = Council(self.store, bindings=[fixture_binding(delay=0)] if bindings is None else bindings,
                               seeds=[seed("echo", "Echo (fixture)")] if seeds is None else seeds)
        rooms = self.store.list_rooms()
        return rooms[0]["id"] if rooms else self.store.create_room("Commons")["id"]

    def settle(self, round_id, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            saved = self.store.round(round_id)
            if saved["status"] in TERMINAL and not any(t["status"] in ("queued", "running") for t in saved["turns"]):
                return saved
            time.sleep(0.01)
        self.fail(f"round did not settle: {self.store.round(round_id)}")

    def idle(self, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.council._guard:
                if not self.council._drivers:
                    return
            time.sleep(0.01)
        self.fail("drivers did not finish")

    def running(self, round_id, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(t["status"] == "running" for t in self.store.round(round_id)["turns"]):
                return
            time.sleep(0.01)
        self.fail("no call started")

    def slots(self, include_archived=True):
        return {a["id"]: (a["home_slot"], a["archived"]) for a in self.council.agents_info(include_archived)}


class AddAndRestart(RegistryCase):
    def test_full_town_defers_new_seed_until_owner_archives_a_resident(self):
        bindings, initial_seeds = demo_registry()
        self.build(bindings, initial_seeds)
        self.council.archive_resident("quill")
        added = [self.council.add_resident(f"Neighbor {i}", "", "fixture") for i in range(63)]
        before = {row["id"]: row for row in self.store.residents()}
        active_slots = {row["id"]: row["home_slot"] for row in before.values() if not row["archived"]}
        self.assertEqual(len(active_slots), 64)
        self.assertEqual(set(active_slots.values()), set(range(64)))

        new_binding = ResidentBinding("new-link", "New fixture connection", "fixture",
                                      lambda name: FixtureProvider(name, delay=0))
        bindings.append(new_binding)
        newcomer = Seed(Agent("new-seed", "Newcomer (fixture)", "fixture", "new role"), "new-link")
        # Existing active and archived rows must win even if local seed names changed.
        changed_seeds = [newcomer, seed("echo", "Changed echo"), seed("quill", "Changed quill")]
        self.build(bindings, changed_seeds)
        self.assertEqual({row["id"]: row for row in self.store.residents()}, before)
        self.assertEqual({a["id"]: a["home_slot"] for a in self.council.agents_info()}, active_slots)
        self.assertEqual({b["id"] for b in self.council.bindings_info()}, {"fixture", "new-link"})
        self.assertNotIn("new-seed", self.council.agents)
        with self.assertRaisesRegex(ConflictError, "full"):
            self.council.add_resident("Extra", "", "new-link")
        with self.assertRaisesRegex(ConflictError, "full"):
            self.council.restore_resident("quill")
        self.assertEqual({row["id"]: row for row in self.store.residents()}, before)

        victim = added[31]
        archived = self.council.archive_resident(victim["id"])
        self.assertEqual((archived["archived"], archived["home_slot"]), (True, victim["home_slot"]))
        after_archive = {row["id"]: row for row in self.store.residents()}
        self.build(bindings, changed_seeds)
        after_restart = {row["id"]: row for row in self.store.residents()}
        self.assertEqual({key: after_restart[key] for key in after_archive}, after_archive)
        self.assertEqual((after_restart["new-seed"]["home_slot"], after_restart["new-seed"]["archived"],
                          after_restart["new-seed"]["binding_id"]), (victim["home_slot"], False, "new-link"))
        active = self.council.agents_info()
        self.assertEqual(len(active), 64)
        self.assertEqual(len({a["home_slot"] for a in active}), 64)
        self.assertTrue(all(a["available"] for a in active))
        self.assertTrue(all(not adapter.calls for adapter in self.council.adapters.values()))

    def test_added_fixture_resident_replies_and_keeps_id_slot_session_after_restart(self):
        room = self.build()
        nova = self.council.add_resident("  Nova   Writer ", "drafts openings", "fixture")
        self.assertRegex(nova["id"], r"^res-[0-9a-f]{32}$")
        self.assertEqual((nova["name"], nova["provider"], nova["home_slot"], nova["archived"], nova["available"]),
                         ("Nova Writer (fixture)", "fixture", 1, False, True))
        saved = self.settle(self.council.start(room, "hello", [nova["id"]], "r1", mode="direct")["id"])
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["participant_snapshots"][nova["id"]]["name"], "Nova Writer (fixture)")
        reply = next(m for m in self.store.room(room)["messages"] if m["role"] == "agent")
        self.assertEqual((reply["agent_id"], reply["agent_name"], reply["agent_provider"]),
                         (nova["id"], "Nova Writer (fixture)", "fixture"))
        self.assertIn("You are Nova Writer (fixture)", self.council.adapters[nova["id"]].calls[0].prompt)
        session = self.store.session(room, nova["id"])
        self.assertTrue(session)

        room = self.build()
        info = {a["id"]: a for a in self.council.agents_info()}
        self.assertEqual((info[nova["id"]]["home_slot"], info[nova["id"]]["name"]), (1, "Nova Writer (fixture)"))
        self.assertEqual(self.store.session(room, nova["id"]), session)
        self.settle(self.council.start(room, "again", [nova["id"]], "r2", mode="direct")["id"])
        self.assertEqual(self.council.adapters[nova["id"]].calls[0].session_id, session)

    def test_each_resident_gets_its_own_adapter_and_fixture_label(self):
        self.build()
        a = self.council.add_resident("Claude", "", "fixture")
        b = self.council.add_resident("Claude", "", "fixture")
        self.assertEqual(a["name"], "Claude (fixture)")
        self.assertNotEqual(a["id"], b["id"])
        self.assertIsNot(self.council.adapters[a["id"]], self.council.adapters[b["id"]])
        self.assertNotEqual(self.council.adapters[a["id"]].identity_key(None),
                            self.council.adapters[b["id"]].identity_key(None))
        self.assertEqual(self.council.bindings_info(),
                         [{"id": "fixture", "label": "Scripted fixture resident (simulated replies)",
                           "provider": "fixture"}])

    def test_invalid_add_and_factory_failure_change_nothing(self):
        def broken(_name):
            raise RuntimeError("private path C:/secret")

        self.build(bindings=[fixture_binding(delay=0), ResidentBinding("broken", "Broken", "fixture", broken)])
        before = (self.store.residents(), dict(self.council.agents), dict(self.council.adapters))
        for name, role, binding in [("x", "", "nope"), ("", "", "fixture"), ("x" * 80, "", "fixture"),
                                    ("x", 5, "fixture"), ("x", "", None), ("x", "", {"executable": "evil"})]:
            with self.assertRaises(ValidationError):
                self.council.add_resident(name, role, binding)
        with self.assertRaises(ProviderError) as caught, self.assertLogs("home.council", "ERROR"):
            self.council.add_resident("x", "", "broken")
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(before, (self.store.residents(), dict(self.council.agents), dict(self.council.adapters)))


class ArchiveAndRestore(RegistryCase):
    def test_archive_stops_dispatch_but_history_keeps_names(self):
        room = self.build()
        nova = self.council.add_resident("Nova", "", "fixture")["id"]
        self.settle(self.council.start(room, "hi", [nova], "r1", mode="direct")["id"])
        archived = self.council.archive_resident(nova)
        self.assertEqual((archived["archived"], archived["home_slot"], archived["available"]), (True, 1, True))
        self.assertNotIn(nova, [a["id"] for a in self.council.agents_info()])
        self.assertNotIn(nova, self.council.agents)
        with self.assertRaisesRegex(ValidationError, "archived"):
            self.council.start(room, "hi again", [nova], "r2", mode="direct")
        with self.assertRaisesRegex(ValidationError, "archived"):
            self.council.start(room, "both", ["echo", nova], "r3")
        self.assertEqual(len(self.store.room(room)["rounds"]), 1)
        saved = self.settle(self.council.start(room, "who spoke?", ["echo"], "r4", mode="direct")["id"])
        self.assertIn("[Nova (fixture)] ", self.store.round_context(saved["id"]))

        room2 = self.build()  # restart: the archive persists and history still names Nova
        self.assertTrue(self.slots()[nova][1])
        names = {m["agent_name"] for m in self.store.room(room2)["messages"] if m["role"] == "agent"}
        self.assertIn("Nova (fixture)", names)

    def test_restore_retakes_former_slot_or_first_free_and_nobody_moves(self):
        self.build()
        a = self.council.add_resident("A", "", "fixture")["id"]
        b = self.council.add_resident("B", "", "fixture")["id"]
        self.assertEqual((self.slots()[a][0], self.slots()[b][0]), (1, 2))
        self.council.archive_resident(a)
        c = self.council.add_resident("C", "", "fixture")["id"]
        self.assertEqual(self.slots()[c], (1, False))  # first unoccupied active slot is reused
        restored = self.council.restore_resident(a)
        self.assertEqual((restored["home_slot"], restored["archived"]), (3, False))
        self.assertEqual(self.slots()[b], (2, False))
        self.council.archive_resident(b)
        self.assertEqual(self.council.restore_resident(b)["home_slot"], 2)
        self.assertEqual({k: v[0] for k, v in self.slots().items()}, {"echo": 0, c: 1, b: 2, a: 3})
        with self.assertRaises(ConflictError):
            self.council.restore_resident(a)
        self.council.archive_resident(a)
        with self.assertRaises(ConflictError):
            self.council.archive_resident(a)
        with self.assertRaises(Exception) as missing:
            self.council.archive_resident("res-" + "0" * 32)
        self.assertEqual(missing.exception.status, 404)

    def test_archived_seed_is_not_resurrected_at_restart(self):
        bindings, seeds = demo_registry()
        self.build(bindings, seeds)
        self.council.archive_resident("quill")
        self.build(bindings, seeds)
        self.assertEqual([a["id"] for a in self.council.agents_info()], ["echo"])
        self.assertTrue(self.slots()["quill"][1])
        self.assertEqual(len(self.store.residents()), 2)

    def test_registry_edits_do_not_overwrite_or_duplicate_on_reseed(self):
        self.build()
        added = self.council.add_resident("Browser added", "", "fixture")["id"]
        self.build(seeds=[seed("echo", "Renamed in config")])
        info = {a["id"]: a for a in self.council.agents_info()}
        self.assertEqual(info["echo"]["name"], "Echo (fixture)")  # registry row wins
        self.assertIn(added, info)

    def test_missing_binding_keeps_home_as_unavailable_and_rejects_dispatch(self):
        spare = ResidentBinding("spare", "Spare fixture", "fixture", lambda name: FixtureProvider(name))
        room = self.build(bindings=[fixture_binding(delay=0), spare])
        kept = self.council.add_resident("Kept", "", "spare")["id"]
        parked = self.council.add_resident("Parked", "", "spare")["id"]
        self.settle(self.council.start(room, "hi", [kept], "r1", mode="direct")["id"])
        self.council.archive_resident(parked)
        room = self.build()  # restart without the spare binding
        info = {a["id"]: a for a in self.council.agents_info(include_archived=True)}
        self.assertEqual((info[kept]["available"], info[kept]["archived"], info[kept]["home_slot"]), (False, False, 1))
        self.assertFalse(info[parked]["available"])
        with self.assertRaisesRegex(ValidationError, "unavailable"):
            self.council.start(room, "hi", [kept], "r2", mode="direct")
        with self.assertRaisesRegex(ConflictError, "binding"):
            self.council.restore_resident(parked)
        self.assertEqual(len(self.store.residents()), 3)
        self.assertIn("Kept (fixture)", [m["agent_name"] for m in self.store.room(room)["messages"]])


class Concurrency(RegistryCase):
    def test_registry_edits_wait_for_in_flight_calls_even_after_stop(self):
        room = self.build(bindings=[fixture_binding(delay=0), self.gated(ignore_cancel=True)])
        slow = self.council.add_resident("Slow", "", "gated")["id"]
        round_id = self.council.start(room, "hold", [slow], "r1", mode="direct")["id"]
        self.running(round_id)
        with self.assertRaises(ConflictError):
            self.council.archive_resident(slow)
        self.assertEqual(self.council.cancel(round_id)["status"], "cancelled")
        for edit in (lambda: self.council.archive_resident(slow), lambda: self.council.archive_resident("echo"),
                     lambda: self.council.add_resident("Late", "", "fixture")):
            with self.assertRaises(ConflictError):
                edit()  # the round is stopped but its call is still in flight
        self.assertEqual(len(self.store.residents()), 2)
        self.gate.set()
        self.idle()
        saved = self.settle(round_id)
        self.assertEqual(saved["status"], "cancelled")
        self.assertTrue(self.council.archive_resident(slow)["archived"])

    def test_start_archive_race_has_exactly_one_valid_winner(self):
        room = self.build(bindings=[fixture_binding(delay=0), self.gated()])
        target = self.council.add_resident("Target", "", "gated")["id"]
        for attempt in range(12):
            rounds_before = len(self.store.room(room)["rounds"])
            barrier = threading.Barrier(2)
            results = {}

            def start(barrier=barrier, results=results, attempt=attempt):
                barrier.wait()
                try:
                    results["start"] = self.council.start(room, "race", [target], f"race-{attempt}", mode="direct")
                except ValidationError as error:
                    results["start"] = error

            def archive(barrier=barrier, results=results):
                barrier.wait()
                try:
                    results["archive"] = self.council.archive_resident(target)
                except ConflictError as error:
                    results["archive"] = error

            threads = [threading.Thread(target=start), threading.Thread(target=archive)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
            started = isinstance(results["start"], dict)
            archived = isinstance(results["archive"], dict)
            self.assertNotEqual(started, archived, results)
            if started:
                self.gate.set()
                self.assertEqual(self.settle(results["start"]["id"])["status"], "completed")
                self.idle()
                self.gate.clear()
            else:
                self.assertTrue(self.slots()[target][1])
                self.assertEqual(len(self.store.room(room)["rounds"]), rounds_before)
                self.council.restore_resident(target)

    def assert_whole_council(self, saved, ids):
        """Every selected resident proposed and critiqued; exactly one synthesis; 2N+1 calls."""
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["max_calls"], 2 * len(ids) + 1)
        for phase in ("proposal", "critique"):
            turns = [t for t in saved["turns"] if t["phase"] == phase]
            self.assertEqual(sorted(t["agent_id"] for t in turns), sorted(ids), phase)
            self.assertTrue(all(t["status"] == "completed" for t in turns), phase)
        synthesis = [t for t in saved["turns"] if t["phase"] == "synthesis"]
        self.assertEqual((len(synthesis), synthesis[0]["status"]), (1, "completed"))
        calls = [c for key in ids for c in self.council.adapters[key].calls]
        self.assertEqual(len(calls), 2 * len(ids) + 1)
        names = {key: self.council.agents[key].name for key in ids}
        last = self.council.adapters[synthesis[0]["agent_id"]].calls[-1].prompt
        for key in ids:  # every participant is attributed in both sections, and nobody else is
            self.assertEqual(last.count(f"### {names[key]} (fixture)\n"), 2, key)
        self.assertEqual(last.count("\n### "), 2 * len(ids))

    def test_six_member_council_completes_thirteen_calls(self):
        room = self.build()
        ids = ["echo"] + [self.council.add_resident(f"R{i}", "", "fixture")["id"] for i in range(6)]
        self.assertEqual(len(self.council.agents_info()), 7)
        saved = self.settle(self.council.start(room, "six of seven", ids[:6], "r6")["id"])
        self.assertEqual(len(saved["turns"]), 13)
        self.assert_whole_council(saved, ids[:6])
        self.assertEqual(self.council.adapters[ids[6]].calls, [])  # not selected: never called

    def test_all_sixty_four_residents_council_and_sixty_five_rejected_before_save(self):
        room = self.build()
        ids = ["echo"] + [self.council.add_resident(f"Resident {i:02d}", "", "fixture")["id"] for i in range(63)]
        self.assertEqual(self.council.capabilities_info()["max_participants"], 64)
        too_many = ids + ["res-" + "f" * 32]
        with self.assertRaisesRegex(ValidationError, "2 to 64"):
            self.council.start(room, "everyone and one more", too_many, "r65")
        self.assertEqual((self.store.room(room)["rounds"], self.store.room(room)["messages"]), ([], []))
        self.assertEqual(sum(len(self.council.adapters[k].calls) for k in ids), 0)
        saved = self.settle(self.council.start(room, "everyone", ids, "r64")["id"], timeout=30)
        self.assertEqual(len(saved["turns"]), 129)
        self.assert_whole_council(saved, ids)

    def test_resume_validates_participants_before_reactivation_and_keeps_snapshots(self):
        room = self.build(bindings=[fixture_binding(delay=0), self.gated()])
        a = self.council.add_resident("Ana", "plans", "gated")["id"]
        b = self.council.add_resident("Bo", "checks", "gated")["id"]
        round_id = self.council.start(room, "plan it", [a, b], "r1")["id"]
        self.running(round_id)
        self.council.cancel(round_id)
        self.idle()
        self.assertEqual(self.settle(round_id)["status"], "cancelled")
        self.council.archive_resident(b)
        with self.assertRaisesRegex(ValidationError, "archived"):
            self.council.resume(round_id)
        self.assertEqual(self.store.round(round_id)["status"], "cancelled")
        self.council.restore_resident(b)
        self.gate.set()
        # Both stopped calls have unknown outcomes; the owner explicitly accepts repeating them.
        resumed = self.council.resume(round_id, retry_interrupted=True)
        self.assertIn(resumed["status"], ("queued", "running", "completed"))
        saved = self.settle(round_id)
        self.assertEqual(set(saved["participant_snapshots"]), {a, b})
        names = {m["agent_name"] for m in self.store.room(room)["messages"] if m["role"] == "agent"}
        self.assertEqual(names, {"Ana (fixture)", "Bo (fixture)"})
        self.assertEqual(saved["status"], "completed")
        with self.assertRaises(ConflictError):
            self.council.resume(round_id)

    def test_idempotent_repeat_returns_saved_round_after_archive(self):
        room = self.build()
        nova = self.council.add_resident("Nova", "", "fixture")["id"]
        first = self.settle(self.council.start(room, "hi", [nova], "same", mode="direct")["id"])
        self.council.archive_resident(nova)
        again = self.council.start(room, "hi", [nova], "same", mode="direct")
        self.assertEqual(again["id"], first["id"])
        with self.assertRaises(ConflictError):
            self.council.start(room, "different", [nova], "same", mode="direct")


class SchemaUpgrade(unittest.TestCase):
    def test_schema_1_database_upgrades_preserving_rounds_artifacts_and_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "home.sqlite3"
            db = sqlite3.connect(path)
            db.executescript(f"BEGIN;\n{MIGRATIONS[1]}\nPRAGMA user_version = 1;\nCOMMIT;")
            now = "2026-10-01T00:00:00.000+00:00"
            db.execute("INSERT INTO rooms VALUES ('room1', 'Commons', ?)", (now,))
            db.execute("INSERT INTO messages (id, room_id, round_id, role, agent_id, phase, content, created_at) "
                       "VALUES ('m1', 'room1', 'rd1', 'owner', NULL, NULL, 'old question', ?)", (now,))
            db.execute("INSERT INTO messages (id, room_id, round_id, role, agent_id, phase, content, created_at) "
                       "VALUES ('m2', 'room1', 'rd1', 'agent', 'ghost', 'reply', 'old answer', ?)", (now,))
            db.execute("INSERT INTO artifacts VALUES ('a1', 'room1', ?)", (now,))
            db.execute("INSERT INTO artifact_versions VALUES ('a1', 1, 'Plan', 'body', 'ab', ?)", (now,))
            db.execute("INSERT INTO rounds (id, room_id, request_id, request_sha256, mode, status, active_room, "
                       "participants, artifacts, context, context_sha256, owner_message_id, created_at, updated_at) "
                       "VALUES ('rd1', 'room1', 'req1', 'sha', 'direct', 'completed', NULL, '[\"ghost\"]', '[]', "
                       "'ctx', 'csha', 'm1', ?, ?)", (now, now))
            db.execute("INSERT INTO turns (id, round_id, agent_id, phase, status, launched, content, provider, "
                       "session_id, model, created_at, updated_at) VALUES ('t1', 'rd1', 'ghost', 'reply', "
                       "'completed', 1, 'old answer', 'fixture', 'sess-old', 'fixture-script', ?, ?)", (now, now))
            db.execute("INSERT INTO sessions VALUES ('room1', 'ghost', 'fixture', 'sess-old', ?)", (now,))
            db.commit()
            db.close()

            store = Store(path)
            council = Council(store, bindings=[fixture_binding(delay=0)], seeds=[seed("echo", "Echo (fixture)")])
            try:
                saved = store.round("rd1")
                self.assertEqual((saved["status"], saved["participant_snapshots"]), ("completed", {}))
                self.assertEqual(saved["turns"][0]["content"], "old answer")
                self.assertEqual(store.session("room1", "ghost"), "sess-old")
                room = store.room("room1")
                self.assertEqual([a["id"] for a in room["artifacts"]], ["a1"])
                legacy = next(m for m in room["messages"] if m["id"] == "m2")
                self.assertEqual((legacy["agent_name"], legacy["agent_provider"]), (None, None))
                new = council.start("room1", "who answered?", ["echo"], "req2", mode="direct")
                deadline = time.monotonic() + 5
                while store.round(new["id"])["status"] not in TERMINAL and time.monotonic() < deadline:
                    time.sleep(0.01)
                # A legacy speaker with no saved name and no registry row stays unknown, not invented.
                self.assertIn("[Unknown resident] old answer", store.round_context(new["id"]))
                version = store._db.execute("PRAGMA user_version").fetchone()[0]
                self.assertEqual(version, SCHEMA_VERSION)
            finally:
                council.close()
                store.close()


if __name__ == "__main__":
    unittest.main()
