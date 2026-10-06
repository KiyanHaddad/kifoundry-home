"""Prompt byte budget and direct-conversation continuity, with fixture providers only."""

import tempfile
import time
import unittest
from pathlib import Path

from home.council import (
    EXCERPT_MARK,
    Council,
    check_council_fits,
    critique_prompt,
    direct_prompt,
    fit_outcomes,
    synthesis_prompt,
)
from home.fixture import FixtureProvider
from home.models import (
    MAX_CONTEXT_BYTES,
    MAX_PROMPT_BYTES,
    MAX_REPLY_BYTES,
    MAX_RESIDENT_NAME_CHARS,
    MAX_ROLE_BYTES,
    Agent,
    ValidationError,
)
from home.residents import ResidentBinding, Seed, fixture_binding
from home.store import Store

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
LIMIT = 131072


def size(text):
    return len(text.encode("utf-8"))


def reply_of(unit, label):
    """A reply of at most MAX_REPLY_BYTES built from `unit`, starting with a unique label."""
    head = f"<{label}> "
    count = (MAX_REPLY_BYTES - size(head)) // size(unit)
    return head + unit * count


UNITS = ["a", "é", "中", "😀", "👩‍👩‍👧"]  # 1, 2, 3, 4-byte and a multi-codepoint emoji sequence


def make_agents(n):
    role = "r" * MAX_ROLE_BYTES
    return [Agent(f"a{i:02d}", f"Resident {i:02d} " + "n" * (MAX_RESIDENT_NAME_CHARS - 12), "fixture", role)
            for i in range(n)]


def near_full_context():
    return "## Owner's message\n" + "c" * (MAX_CONTEXT_BYTES - 300)


def turns_for(agents, phase, failing=()):
    turns = []
    for i, agent in enumerate(agents):
        if agent.id in failing:
            turns.append({"agent_id": agent.id, "phase": phase, "status": "failed", "content": None})
        else:
            turns.append({"agent_id": agent.id, "phase": phase, "status": "completed",
                          "content": reply_of(UNITS[i % len(UNITS)], f"{phase}-{agent.id}")})
    return turns


class FitOutcomes(unittest.TestCase):
    def check_prompt(self, prompt, agents, sections):
        self.assertLessEqual(size(prompt), LIMIT)
        prompt.encode("utf-8", "strict")  # strictly valid Unicode, no split code points
        for agent in agents:
            self.assertEqual(prompt.count(f"### {agent.name} (fixture)"), sections, agent.id)
        self.assertEqual(prompt.count("\n### "), sections * len(agents))  # no phantom participants

    def test_two_participants_max_role_near_full_context_and_max_replies(self):
        agents = make_agents(2)
        by_id = {a.id: a for a in agents}
        order = [a.id for a in agents]
        context = near_full_context()
        proposals, critiques = turns_for(agents, "proposal"), turns_for(agents, "critique")
        saved_copy = [dict(t) for t in proposals + critiques]
        prompt = synthesis_prompt(agents[0], context, proposals, critiques, order, by_id)
        self.check_prompt(prompt, agents, 2)
        self.assertEqual(prompt.count(EXCERPT_MARK), 4)
        self.assertIn(context, prompt)  # the frozen context is never cut
        self.assertIn("cannot establish agreement", prompt)
        for turn in proposals + critiques:  # each excerpt is a real prefix of the saved reply
            label = turn["content"].split(" ", 1)[0]
            start = prompt.index(label)
            excerpt = prompt[start:prompt.index(EXCERPT_MARK, start)]
            self.assertTrue(turn["content"].startswith(excerpt))
            self.assertGreater(size(excerpt), 1000)
        self.assertEqual(saved_copy, proposals + critiques)  # inputs untouched
        self.assertEqual(prompt, synthesis_prompt(agents[0], context, proposals, critiques, order, by_id))
        critique = critique_prompt(agents[1], context, proposals, order, by_id)
        self.check_prompt(critique, agents, 1)
        self.assertIn(f"### {agents[1].name} (fixture) - you", critique)

    def test_sixty_four_participants_every_status_and_attribution_kept(self):
        agents = make_agents(64)
        by_id = {a.id: a for a in agents}
        order = [a.id for a in agents]
        context = near_full_context()
        check_council_fits(agents, context)
        failing = {"a03", "a40"}
        proposals = turns_for(agents, "proposal", failing)
        critiques = turns_for(agents, "critique", failing | {"a10"})
        critiques[10]["status"] = "interrupted"
        short = "Short and exact: keep both options open."
        proposals[5]["content"] = short
        for agent in (agents[0], agents[63]):
            prompt = synthesis_prompt(agent, context, proposals, critiques, order, by_id)
            self.check_prompt(prompt, agents, 2)
            self.assertEqual(prompt.count("[no reply: failed]"), 4)
            self.assertEqual(prompt.count("[no reply: interrupted]"), 1)
            self.assertIn(f"{short}\n\n###", prompt)  # small reply unchanged, no marker
            self.assertEqual(prompt.count(EXCERPT_MARK), 128 - 5 - 1)
            self.assertEqual(prompt, synthesis_prompt(agent, context, proposals, critiques, order, by_id))
        prompt = critique_prompt(agents[7], context, proposals, order, by_id)
        self.check_prompt(prompt, agents, 1)

    def test_unused_shares_of_short_replies_go_to_long_ones(self):
        agents = make_agents(3)
        by_id = {a.id: a for a in agents}
        order = [a.id for a in agents]
        proposals = turns_for(agents, "proposal")
        proposals[0]["content"] = "tiny"
        prompt = critique_prompt(agents[0], near_full_context(), proposals, order, by_id)
        self.assertLessEqual(size(prompt), LIMIT)
        self.assertGreater(size(prompt), LIMIT - 64)  # the freed share was used, not wasted
        self.assertIn("\ntiny\n\n###", prompt)
        self.assertEqual(prompt.count(EXCERPT_MARK), 2)

    def test_small_replies_stay_exact(self):
        agents = make_agents(5)
        by_id = {a.id: a for a in agents}
        proposals = [{"agent_id": a.id, "status": "completed", "content": f"idea {a.id} ✓"} for a in agents]
        prompt = synthesis_prompt(agents[2], "## Owner's message\nhi", proposals, proposals,
                                  [a.id for a in agents], by_id)
        self.assertNotIn(EXCERPT_MARK, prompt)
        for a in agents:
            self.assertEqual(prompt.count(f"\nidea {a.id} ✓"), 2)

    def test_scaffolding_over_the_limit_fails_safely(self):
        with self.assertRaises(ValidationError):
            fit_outcomes("p" * (LIMIT + 1), [])
        with self.assertRaises(ValidationError):
            direct_prompt(make_agents(1)[0], "x" * LIMIT)  # plus persona
        with self.assertRaises(ValidationError):
            check_council_fits(make_agents(64), "x" * (LIMIT - 20000))
        self.assertEqual(MAX_PROMPT_BYTES, LIMIT)


class CouncilCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "home.sqlite3")
        self.council = None
        self.addCleanup(self.shutdown)
        self.room = self.store.create_room("Commons")["id"]

    def shutdown(self):
        if self.council is not None:
            self.council.close()
        self.store.close()

    def settle(self, round_id, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            saved = self.store.round(round_id)
            if saved["status"] in TERMINAL and not any(t["status"] in ("queued", "running") for t in saved["turns"]):
                return saved
            time.sleep(0.01)
        self.fail(f"round did not settle: {self.store.round(round_id)['status']}")


class LargeRepliesInARealRound(CouncilCase):
    def test_max_replies_are_saved_whole_and_prompts_stay_within_limit(self):
        def big(unit):
            return lambda prompt, _session: reply_of(unit, f"{unit}-{size(prompt)}")

        bindings = [ResidentBinding(f"b{i}", f"Big {i}", "fixture",
                                    lambda name, u=unit: FixtureProvider(name, respond=big(u)))
                    for i, unit in enumerate(["a", "中", "😀"])]
        seeds = [Seed(Agent(f"big{i}", f"Big {i} (fixture)", "fixture", "r" * MAX_ROLE_BYTES), f"b{i}")
                 for i in range(3)]
        self.council = Council(self.store, bindings=bindings, seeds=seeds)
        work = self.store.save_artifact(self.room, "Brief", "w" * (30 * 1024))
        saved = self.settle(self.council.start(self.room, "m" * (16 * 1024), ["big0", "big1", "big2"], "r1",
                                               artifact_ids=[work["id"]])["id"])
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(len(saved["turns"]), 7)
        for turn in saved["turns"]:
            self.assertLessEqual(size(turn["content"]), MAX_REPLY_BYTES)
            self.assertGreater(size(turn["content"]), MAX_REPLY_BYTES - 8)  # saved whole, not the excerpt
        prompts = [c.prompt for key in ("big0", "big1", "big2") for c in self.council.adapters[key].calls]
        self.assertEqual(len(prompts), 7)
        for prompt in prompts:
            self.assertLessEqual(size(prompt), LIMIT)
            self.assertIn("w" * (30 * 1024), prompt)  # selected work is never cut
        self.assertTrue(any(EXCERPT_MARK in p for p in prompts))


class DirectContinuity(CouncilCase):
    def test_direct_then_council_then_direct_sees_council_replies_and_keeps_session(self):
        self.council = Council(self.store, bindings=[fixture_binding(delay=0)],
                               seeds=[Seed(Agent("ana", "Ana (fixture)", "fixture", "plans"), "fixture"),
                                      Seed(Agent("bo", "Bo (fixture)", "fixture", "checks"), "fixture")])
        first = self.settle(self.council.start(self.room, "Start the plan", ["ana"], "d1", mode="direct")["id"])
        self.assertEqual(first["status"], "completed")
        session = self.store.session(self.room, "ana")
        self.assertTrue(session)

        council = self.settle(self.council.start(self.room, "Decide the launch order", ["ana", "bo"], "c1")["id"])
        self.assertEqual(council["status"], "completed")
        self.assertEqual(self.store.session(self.room, "ana"), session)  # fresh Council sessions not saved
        decided = [t["content"] for t in council["turns"] if t["status"] == "completed"]
        self.assertEqual(len(decided), 5)
        bo_said = [t["content"] for t in council["turns"] if t["agent_id"] == "bo"]
        self.assertTrue(bo_said)

        again = self.settle(self.council.start(self.room, "What did we decide?", ["ana"], "d2",
                                               mode="direct")["id"])
        self.assertEqual(again["status"], "completed")
        last = self.council.adapters["ana"].calls[-1]
        self.assertEqual(last.session_id, session)
        names = {"ana": "Ana (fixture)", "bo": "Bo (fixture)"}
        for turn in council["turns"]:  # the actual intervening Council replies, attributed
            self.assertIn(f"[{names[turn['agent_id']]} ({turn['phase']})] {turn['content']}", last.prompt)
        self.assertIn("Decide the launch order", last.prompt)
        self.assertEqual(self.store.session(self.room, "ana"), session)


if __name__ == "__main__":
    unittest.main()
