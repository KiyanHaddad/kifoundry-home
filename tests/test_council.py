"""Council behaviour with fixture providers. These prove mechanics, not live-provider quality."""

import tempfile
import threading
import time
import unittest
from pathlib import Path

from home.council import Council
from home.fixture import FixtureProvider
from home.models import Agent, ConflictError, Reply, ValidationError
from home.store import Store

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class CouncilCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "home.sqlite3"
        self.store = None
        self.council = None
        self.addCleanup(self.shutdown)

    def shutdown(self):
        if self.council is not None:
            self.council.close()
            self.council = None
        if self.store is not None:
            self.store.close()
            self.store = None

    def build(self, adapters, roles=None, **council_options):
        self.shutdown()
        self.store = Store(self.path)
        agents = {key: Agent(key, key.title(), "fixture", (roles or {}).get(key, "")) for key in adapters}
        self.adapters = adapters
        self.council = Council(self.store, agents, adapters, **council_options)
        return self.store.create_room("Commons")["id"] if not self.store.list_rooms() else \
            self.store.list_rooms()[0]["id"]

    def settle(self, round_id, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            saved = self.store.round(round_id)
            if saved["status"] in TERMINAL and not any(t["status"] in ("queued", "running") for t in saved["turns"]):
                return saved
            time.sleep(0.01)
        self.fail(f"round did not settle: {self.store.round(round_id)}")

    def wait_for(self, predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("condition not reached")

    @staticmethod
    def by_phase(saved, phase):
        return {t["agent_id"]: t for t in saved["turns"] if t["phase"] == phase}

    @staticmethod
    def calls(adapter):
        return [c.prompt for c in adapter.calls]


class CouncilFlow(CouncilCase):
    def test_shared_first_context_peer_critique_and_attributed_synthesis(self):
        adapters = {k: FixtureProvider(k, respond=lambda p, s, k=k: f"{k} says: " + p[:20]) for k in ("ada", "bo", "cy")}
        room = self.build(adapters, roles={"bo": "editor"})
        saved = self.council.start(room, "The opening is weak. Fix it.", ["ada", "bo", "cy"], "req-1")
        self.assertEqual(7, saved["max_calls"])
        done = self.settle(saved["id"])
        self.assertEqual("completed", done["status"])
        self.assertEqual(7, sum(len(a.calls) for a in adapters.values()))

        firsts = [self.calls(a)[0] for a in adapters.values()]
        bodies = {p.split("\n\n", 1)[1] for p in firsts}
        self.assertEqual(1, len(bodies), "first answers must share one frozen context apart from persona")
        self.assertIn("The opening is weak", bodies.pop())
        self.assertTrue(all(a.calls[0].session_id is None for a in adapters.values()))

        proposals = self.by_phase(done, "proposal")
        critique_prompt = self.calls(adapters["ada"])[1]
        for name in ("ada", "bo", "cy"):
            self.assertIn(f"### {name.title()} (fixture)", critique_prompt)
            self.assertIn(proposals[name]["content"], critique_prompt)
        self.assertIn("### Ada (fixture) - you", critique_prompt)

        self.assertEqual("ada", done["synthesizer"])
        synthesis = self.by_phase(done, "synthesis")["ada"]
        self.assertEqual(("completed", "fixture"), (synthesis["status"], synthesis["provider"]))
        self.assertIn("Unresolved", self.calls(adapters["ada"])[2])
        self.assertEqual(2, len(adapters["bo"].calls))  # no hidden extra rounds

        messages = self.store.room(room)["messages"]
        self.assertEqual("owner", messages[0]["role"])
        self.assertEqual(7, sum(m["role"] == "agent" for m in messages))

    def test_partial_failure_keeps_successes_and_marks_the_failure(self):
        adapters = {"ada": FixtureProvider("ada"), "bo": FixtureProvider("bo", fail=True),
                    "cy": FixtureProvider("cy")}
        room = self.build(adapters)
        done = self.settle(self.council.start(room, "Ideas?", ["ada", "bo", "cy"], "req-1")["id"])
        self.assertEqual("completed", done["status"])
        proposals = self.by_phase(done, "proposal")
        self.assertEqual("failed", proposals["bo"]["status"])
        self.assertIn("scripted failure", proposals["bo"]["error"])
        self.assertEqual({"ada", "cy"}, set(self.by_phase(done, "critique")))
        self.assertEqual(1, len(adapters["bo"].calls))  # a failed participant stays failed
        self.assertIn("[no reply: failed]", self.calls(adapters["ada"])[1])
        self.assertIn("Bo", done["note"])

    def test_misattributed_provider_or_session_fails_instead_of_passing(self):
        adapters = {"liar": FixtureProvider("liar", reply_provider="claude"), "ok": FixtureProvider("ok")}
        room = self.build(adapters)
        done = self.settle(self.council.start(room, "hi", ["liar"], "req-1", mode="direct")["id"])
        self.assertEqual("failed", done["status"])
        self.assertIn("attributed to claude", done["turns"][0]["error"])
        self.assertIsNone(self.store.session(room, "liar"))

        first = self.settle(self.council.start(room, "hi", ["ok"], "req-2", mode="direct")["id"])
        saved_session = first["turns"][0]["session_id"]
        self.assertEqual(saved_session, self.store.session(room, "ok"))
        adapters["ok"].reply_session = "someone-elses-session"
        second = self.settle(self.council.start(room, "again", ["ok"], "req-3", mode="direct")["id"])
        self.assertEqual("failed", second["status"])
        self.assertEqual(saved_session, adapters["ok"].calls[1].session_id)
        self.assertEqual(saved_session, self.store.session(room, "ok"))


class Admission(CouncilCase):
    def test_driver_limit_rejects_before_save_but_allows_idempotent_repeat(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        adapter = FixtureProvider("ada", gate=gate, ignore_cancel=True)
        room = self.build({"ada": adapter}, max_active_rounds=2)
        other = self.store.create_room("Other")['id']
        refused = self.store.create_room("Refused")['id']
        first = self.council.start(room, "one", ["ada"], "capacity-one", mode="direct")
        self.wait_for(lambda: len(adapter.calls) == 1)
        second = self.council.start(other, "two", ["ada"], "capacity-two", mode="direct")
        self.assertEqual(first["id"], self.council.start(
            room, "one", ["ada"], "capacity-one", mode="direct")["id"])
        self.council.cancel(first["id"])
        with self.assertRaises(ConflictError):
            self.council.start(refused, "must not be saved", ["ada"], "capacity-three", mode="direct")
        self.assertEqual([], self.store.room(refused)["messages"])
        self.assertEqual([], self.store.room(refused)["rounds"])
        self.assertEqual(2, len(self.council._drivers))
        self.assertEqual(2, self.council.capabilities_info()["max_active_rounds"])
        gate.set()
        self.settle(first["id"])
        self.settle(second["id"])
        self.wait_for(lambda: not self.council._drivers)
        done = self.settle(self.council.start(
            refused, "now accepted", ["ada"], "capacity-four", mode="direct")["id"])
        self.assertEqual("completed", done["status"])

    def test_resume_checks_capacity_before_reactivating_saved_round(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        adapter = FixtureProvider("ada", gate=gate)
        room = self.build({"ada": adapter}, max_active_rounds=1)
        stopped = self.council.start(room, "stopped", ["ada"], "resume-old", mode="direct")
        self.wait_for(lambda: len(adapter.calls) == 1)
        self.council.cancel(stopped["id"])
        self.settle(stopped["id"])
        self.wait_for(lambda: not self.council._drivers)
        other = self.store.create_room("Busy")['id']
        active = self.council.start(other, "busy", ["ada"], "resume-busy", mode="direct")
        with self.assertRaises(ConflictError):
            self.council.resume(stopped["id"])
        self.assertEqual("cancelled", self.store.round(stopped["id"])["status"])
        old_room = next(summary for summary in self.store.list_rooms() if summary["id"] == room)
        self.assertIsNone(old_room["active_round_id"])
        gate.set()
        self.settle(active["id"])
        self.wait_for(lambda: not self.council._drivers)
        self.council.resume(stopped["id"])
        done = self.settle(stopped["id"])
        self.assertEqual("interrupted", done["status"])
        self.assertEqual(2, len(adapter.calls), "An uncertain launched call must not be repeated")

    def test_concurrent_rooms_share_one_finite_admission_limit(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.build({"ada": FixtureProvider("ada", gate=gate)}, max_active_rounds=2)
        rooms = [self.store.create_room(f"Room {i}")["id"] for i in range(8)]
        barrier = threading.Barrier(8)
        accepted, rejected, errors = [], [], []

        def submit(index, room):
            barrier.wait()
            try:
                accepted.append(self.council.start(
                    room, "bounded", ["ada"], f"concurrent-{index}", mode="direct")["id"])
            except ConflictError:
                rejected.append(room)
            except Exception as error:  # noqa: BLE001 - surface unexpected worker errors in the assertion.
                errors.append(error)

        threads = [threading.Thread(target=submit, args=(i, room)) for i, room in enumerate(rooms)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual([], errors)
        self.assertEqual((2, 6), (len(accepted), len(rejected)))
        self.assertTrue(all(not self.store.room(room)["messages"] for room in rejected))
        gate.set()
        for round_id in accepted:
            self.settle(round_id)

    def test_execution_limits_reject_noninteger_or_unbounded_values(self):
        self.store = Store(self.path)
        for option, invalids in (
            ("max_workers", (0, -1, 33, True, 1.5, float("nan"), float("inf"))),
            ("max_active_rounds", (0, -1, 65, False, 1.5, float("nan"), float("inf"))),
        ):
            for invalid in invalids:
                with self.subTest(option=option, value=invalid), self.assertRaises(ValueError):
                    Council(self.store, **{option: invalid})

    def test_duplicate_submit_returns_same_round_and_mismatch_rejects(self):
        adapters = {"ada": FixtureProvider("ada", delay=0.05)}
        room = self.build(adapters)
        results, errors = [], []

        def submit():
            try:
                results.append(self.council.start(room, "hello", ["ada"], "same", mode="direct")["id"])
            # Unexpected worker errors must reach the main thread's assertion.
            except Exception as error:  # noqa: BLE001  # pragma: no cover - surfaced below
                errors.append(error)

        threads = [threading.Thread(target=submit) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual([], errors)
        self.assertEqual(1, len(set(results)))
        self.settle(results[0])
        self.assertEqual(1, len(adapters["ada"].calls))
        with self.assertRaises(ConflictError):
            self.council.start(room, "different text", ["ada"], "same", mode="direct")
        self.assertEqual(1, sum(m["role"] == "owner" for m in self.store.room(room)["messages"]))

    def test_one_active_round_per_room(self):
        gate = threading.Event()
        adapters = {"ada": FixtureProvider("ada", gate=gate), "bo": FixtureProvider("bo")}
        room = self.build(adapters)
        other = self.store.create_room("Studio")["id"]
        first = self.council.start(room, "one", ["ada"], "r1", mode="direct")
        with self.assertRaises(ConflictError):
            self.council.start(room, "two", ["bo"], "r2", mode="direct")
        elsewhere = self.council.start(other, "two", ["bo"], "r3", mode="direct")
        self.assertEqual("completed", self.settle(elsewhere["id"])["status"])
        gate.set()
        self.assertEqual("completed", self.settle(first["id"])["status"])

    def test_invalid_requests_are_rejected_before_anything_is_saved(self):
        adapters = {k: FixtureProvider(k) for k in ("a", "b", "c", "d", "e", "f")}
        room = self.build(adapters)
        other = self.store.create_room("Elsewhere")["id"]
        foreign = self.store.save_artifact(other, "Their script", "not yours")
        attempts = [
            {"text": "x", "participants": ["a", "b"] + [f"p{i}" for i in range(63)]},  # 65 > the 64 cap
            {"text": "x", "participants": ["a"]},
            {"text": "x", "participants": ["a", "a"]},
            {"text": "x", "participants": ["a", "zz"]},
            {"text": "x" * (16 * 1024 + 1), "participants": ["a", "b"]},
            {"text": "x", "participants": ["a", "b"], "artifact_ids": [foreign["id"]]},
        ]
        for i, kwargs in enumerate(attempts):
            with self.subTest(i=i), self.assertRaises(ValidationError):
                self.council.start(room, request_id=f"bad-{i}", **kwargs)
        big = self.store.save_artifact(room, "Long script", "y" * (40 * 1024))
        with self.assertRaises(ValidationError):  # message + work over the 48 KiB context: refused, not cut
            self.council.start(room, "z" * (10 * 1024), ["a", "b"], "too-big", artifact_ids=[big["id"]])
        self.assertEqual([], self.store.room(room)["messages"])
        self.assertEqual([], self.store.room(room)["rounds"])
        self.assertEqual(0, sum(len(a.calls) for a in adapters.values()))


class Exclusivity(CouncilCase):
    def test_waiting_aliases_leave_workers_for_an_unrelated_ready_provider(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        held = FixtureProvider("held", gate=gate, bound_identity="shared-session")
        free = FixtureProvider("free")
        room = self.build({"held": held, "free": free}, max_workers=2)
        first = self.council.start(room, "held", ["held"], "held-one", mode="direct")
        self.wait_for(lambda: len(held.calls) == 1)
        alias_room = self.store.create_room("Alias")['id']
        alias = self.council.start(alias_room, "alias", ["held"], "held-two", mode="direct")
        unrelated_room = self.store.create_room("Unrelated")['id']
        unrelated = self.council.start(
            unrelated_room, "ready", ["free"], "free-one", mode="direct")
        self.assertEqual("completed", self.settle(unrelated["id"])["status"])
        self.assertEqual(1, len(held.calls), "The held identity must remain serialized")
        self.assertFalse(gate.is_set(), "The unrelated reply must arrive while the first call is held")
        self.assertFalse(self.store.round(alias["id"])["turns"][0]["launched"])
        gate.set()
        self.settle(first["id"])
        self.settle(alias["id"])
        self.wait_for(lambda: not self.council._drivers)
        self.assertEqual(set(), self.council._busy_identities, "Idle identity reservations must be retired")

    def test_stop_wakes_an_alias_waiter_without_launching_it_and_resume_is_safe(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        held = FixtureProvider("held", gate=gate, bound_identity="shared-session")
        room = self.build({"held": held}, max_workers=1)
        first = self.council.start(room, "held", ["held"], "stop-held", mode="direct")
        self.wait_for(lambda: len(held.calls) == 1)
        alias_room = self.store.create_room("Alias")['id']
        alias = self.council.start(alias_room, "alias", ["held"], "stop-waiting", mode="direct")
        self.wait_for(lambda: self.store.round(alias["id"])["status"] == "running")
        self.council.cancel(alias["id"])
        done = self.settle(alias["id"])
        self.wait_for(lambda: alias["id"] not in self.council._drivers)
        self.assertEqual("cancelled", done["turns"][0]["status"])
        self.assertFalse(done["turns"][0]["launched"])
        self.assertEqual(1, len(held.calls))
        gate.set()
        self.settle(first["id"])
        self.wait_for(lambda: not self.council._drivers)
        self.council.resume(alias["id"])
        self.assertEqual("completed", self.settle(alias["id"])["status"])
        self.assertEqual(2, len(held.calls))

    def test_close_wakes_identity_waiters_and_releases_reservations(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        held = FixtureProvider("held", gate=gate, bound_identity="shared-session")
        room = self.build({"held": held}, max_workers=1)
        first = self.council.start(room, "held", ["held"], "close-held", mode="direct")
        self.wait_for(lambda: len(held.calls) == 1)
        other = self.store.create_room("Alias")['id']
        second = self.council.start(other, "alias", ["held"], "close-waiting", mode="direct")
        self.council.close(timeout=2)
        self.assertEqual({}, self.council._drivers)
        self.assertEqual(set(), self.council._busy_identities)
        self.assertEqual(1, len(held.calls))
        self.assertEqual("interrupted", self.store.round(first["id"])["status"])
        self.assertEqual("interrupted", self.store.round(second["id"])["status"])
        self.assertFalse(self.store.round(second["id"])["turns"][0]["launched"])

    def test_aliases_of_one_bound_session_never_overlap_across_rooms(self):
        adapters = {"resident": FixtureProvider("resident", delay=0.1, bound_identity="one-session"),
                    "alias": FixtureProvider("alias", delay=0.1, bound_identity="one-session")}
        room = self.build(adapters)
        other = self.store.create_room("Studio")["id"]
        a = self.council.start(room, "first", ["resident"], "r1", mode="direct")
        b = self.council.start(other, "second", ["alias"], "r2", mode="direct")
        self.settle(a["id"])
        self.settle(b["id"])
        spans = sorted((c.started, c.ended) for ad in adapters.values() for c in ad.calls)
        self.assertEqual(2, len(spans))
        self.assertLessEqual(spans[0][1], spans[1][0], "aliased identity calls overlapped")


class StopAndRestart(CouncilCase):
    def test_stop_keeps_input_and_completed_replies_and_blocks_later_phases(self):
        gate = threading.Event()
        adapters = {"ada": FixtureProvider("ada"), "bo": FixtureProvider("bo", gate=gate)}
        room = self.build(adapters)
        saved = self.council.start(room, "Fix the opening", ["ada", "bo"], "r1")
        self.wait_for(lambda: self.by_phase(self.store.round(saved["id"]), "proposal")["ada"]["status"] == "completed")
        self.council.cancel(saved["id"])
        done = self.settle(saved["id"])
        self.assertEqual("cancelled", done["status"])
        proposals = self.by_phase(done, "proposal")
        self.assertEqual("completed", proposals["ada"]["status"])
        self.assertEqual("cancelled", proposals["bo"]["status"])
        self.assertEqual({"proposal"}, {t["phase"] for t in done["turns"]})
        messages = self.store.room(room)["messages"]
        self.assertEqual("Fix the opening", messages[0]["content"])
        self.assertEqual(1, len(adapters["ada"].calls))

    def test_reply_that_arrives_despite_stop_is_kept_truthfully(self):
        gate = threading.Event()
        adapters = {"ada": FixtureProvider("ada", gate=gate, ignore_cancel=True)}
        room = self.build(adapters)
        saved = self.council.start(room, "hi", ["ada"], "r1", mode="direct")
        self.wait_for(lambda: len(adapters["ada"].calls) == 1)
        self.assertEqual("cancelled", self.council.cancel(saved["id"])["status"])
        gate.set()
        done = self.settle(saved["id"])
        self.assertEqual("cancelled", done["status"])
        self.assertEqual("completed", done["turns"][0]["status"])
        self.assertEqual(1, sum(m["role"] == "agent" for m in self.store.room(room)["messages"]))

    def test_restart_interrupts_without_calls_and_resume_reuses_saved_outputs(self):
        self.store = Store(self.path)
        room = self.store.create_room()["id"]
        # Simulate a crash mid-proposals: ada answered, bo was running, cy never launched.
        saved, _ = self.store.create_round(
            room_id=room, request_id="r1", request_sha256="h", mode="council", text="Fix it",
            participants=["ada", "bo", "cy"], artifact_ids=[], first_phase="proposal",
            build_context=lambda h, o, a, t: t)
        self.store.mark_round_running(saved["id"])
        turns = {t["agent_id"]: t["id"] for t in saved["turns"]}
        self.store.claim_turn(turns["ada"])
        self.store.complete_turn(turns["ada"], Reply("ada's saved idea", "fixture", "s-ada"), save_session=False)
        self.store.claim_turn(turns["bo"])
        self.store.close()
        self.store = None

        adapters = {k: FixtureProvider(k) for k in ("ada", "bo", "cy")}
        self.build(adapters)
        self.assertEqual([saved["id"]], self.council.recovered)
        after = self.store.round(saved["id"])
        self.assertEqual("interrupted", after["status"])
        self.assertEqual(0, sum(len(a.calls) for a in adapters.values()))

        self.council.resume(saved["id"])
        done = self.settle(saved["id"])
        self.assertEqual("completed", done["status"])
        self.assertEqual(0, len(adapters["bo"].calls), "an unknown-outcome call must not be repeated")
        self.assertEqual(2, len(adapters["cy"].calls))  # cy: proposal + critique
        self.assertEqual(2, len(adapters["ada"].calls))  # ada: critique + synthesis, proposal reused
        self.assertIn("ada's saved idea", self.calls(adapters["cy"])[1])
        self.assertEqual("interrupted", self.by_phase(done, "proposal")["bo"]["status"])
        with self.assertRaises(ConflictError):
            self.council.resume(saved["id"])  # completed rounds do not resume


class Artifacts(CouncilCase):
    def test_round_freezes_the_selected_exact_version(self):
        adapters = {"ada": FixtureProvider("ada"), "bo": FixtureProvider("bo")}
        room = self.build(adapters)
        v1 = self.store.save_artifact(room, "Script", "Version one opening")
        v2 = self.store.save_artifact(room, "Script", "Version two opening", artifact_id=v1["id"], expected_version=1)
        saved = self.council.start(room, "Review", ["ada", "bo"], "r1", artifact_ids=[v1["id"]])
        self.store.save_artifact(room, "Script", "Version three, saved later", artifact_id=v1["id"],
                                 expected_version=2)
        done = self.settle(saved["id"])
        self.assertEqual([{"id": v1["id"], "title": "Script", "version": 2, "sha256": v2["sha256"]}],
                         done["artifacts"])
        prompt = self.calls(adapters["ada"])[0]
        self.assertIn("Version two opening", prompt)
        self.assertNotIn("Version three", prompt)
        self.assertEqual(3, len(self.store.room(room)["artifacts"][0]["versions"]))


if __name__ == "__main__":
    unittest.main()
